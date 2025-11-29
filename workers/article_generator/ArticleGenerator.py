import uuid
import json
from datetime import datetime, timezone, timedelta
import time
import math
from pathlib import Path
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import re
from typing import Optional

import requests
from bs4 import BeautifulSoup
from readability import Document

from .translator import ArticleTranslator
# embedding/publishing handled in publisher worker; no OpenAI client here


# Helpers that prefer test-time monkeypatching via the thin worker module.
def _get_firebase_client():
    try:
        import importlib
        worker_mod = importlib.import_module('workers.article_generator.worker')
        if hasattr(worker_mod, 'get_firebase_client') and worker_mod.get_firebase_client:
            return worker_mod.get_firebase_client()
    except Exception:
        pass
    from workers.tools.firebase_client import get_firebase_client as _gf
    return _gf()


class ArticleGenerator:

    def __init__(self, translator: ArticleTranslator | None = None, batch_size: int | None = None):
        # This worker processes all matching articles by default (no batching)
        try:
            self.batch_size = int(batch_size) if batch_size is not None else None
            if self.batch_size is not None and self.batch_size < 0:
                self.batch_size = None
        except Exception:
            self.batch_size = None

        self.db = _get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        self.translator = translator or ArticleTranslator(
            stage1_max_tokens=2000,
            stage2_max_tokens=2000,
            stage3_max_tokens=2000
        )
        self.logger = logging.getLogger('workers.article_generator')
        # Ensure console output for the worker during local runs / CI
        try:
            if not any(isinstance(h, logging.StreamHandler) for h in self.logger.handlers):
                ch = logging.StreamHandler()
                ch.setLevel(logging.DEBUG)
                fmt = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
                ch.setFormatter(fmt)
                self.logger.addHandler(ch)
        except Exception:
            pass

    def _get_total_score(self, data: dict) -> float:
        """Extract a float total_score from article data.

        Tries top-level 'total_score', then nested interest.total_score or interest.total.
        Returns 0.0 on missing/unparseable values.
        """
        try:
            maybe = data.get('total_score')
            if maybe is None:
                interest = data.get('interest') or {}
                maybe = interest.get('total_score') or interest.get('total')
            if maybe is None:
                return 0.0
            return float(maybe)
        except Exception:
            return 0.0

    def _save_generated_article(self, doc_id: str, source: dict, total_score: float = 0.0,
                                translation_result: dict | None = None, status: str = 'UNKNOWN', metadata: dict | None = None) -> None:
        """Persist generated article and metadata into `articles_ru` collection.

        Uses the original doc id so it's easy to join with `articles` collection.
        Stores stage outputs, combined flags, model and worker info.
        """
        now = datetime.now(timezone.utc).isoformat()
        metadata = metadata or {}
        tr = translation_result or {}

        # Best-effort RU fields
        title_ru = tr.get('title_ru') or None
        description_ru = tr.get('description_ru') or None
        content_ru = tr.get('content_ru') or tr.get('translation_ru') or None

        # Stage outputs from editorial_result
        editorial_result = tr.get('editorial_result') or {}
        stage1 = editorial_result.get('stage1') or {}
        stage2 = editorial_result.get('stage2') or {}
        stage3 = editorial_result.get('stage3') or {}
        stage4 = editorial_result.get('stage4') or {}
        
        # Stage5 (markdown) and Stage6 (telegram) from top level
        publish_md = tr.get('publish_md')
        tg_preview = tr.get('tg_preview')
        stage6_telegram = tr.get('stage6_telegram') or {}

        # Combine flags from various sources
        combined_flags = []
        for f in (tr.get('flags') or [], tr.get('publish_flags') or [], tr.get('tg_flags') or []):
            combined_flags.extend([x for x in (f or []) if isinstance(x, str)])

        payload = {
            'article_id': doc_id,
            'source_url': source.get('link') or source.get('url'),
            'source_link': source.get('link') or source.get('url'),  # alias for compatibility
            'source_name': source.get('source') or source.get('source_name'),
            'source_published_at': source.get('published_at') or source.get('pub_date') or None,
            'image_url': source.get('image') or source.get('image_url') or None,
            'status': status,
            'total_score': total_score,
            'title_ru': title_ru,
            'description_ru': description_ru,
            'content_ru': content_ru,
            'stages': {
                'stage1': stage1,
                'stage2': stage2,
                'stage3': stage3,
                'stage4': stage4,
            },
            'publish_md': publish_md,
            'publish_flags': tr.get('publish_flags') or [],
            'telegram_preview': tg_preview,
            'telegram_flags': tr.get('tg_flags') or [],
            'telegram_final': stage6_telegram,
            'flags': sorted(set(combined_flags)),
            'created_at': now,
            'updated_at': now,
        }

        try:
            doc_ref = self.db.collection('articles_ru').document(doc_id)
            doc_ref.set(payload, merge=True)
            # verify write by reading back a small snapshot
            try:
                read_back = doc_ref.get()
                if getattr(read_back, 'exists', False):
                    try:
                        rb = read_back.to_dict() or {}
                        # log a concise confirmation with key fields
                        self.logger.info('Saved articles_ru %s (title_ru_len=%d content_ru_len=%d)',
                                         doc_id,
                                         len((rb.get('title_ru') or '') if isinstance(rb.get('title_ru', ''), str) else str(rb.get('title_ru'))),
                                         len((rb.get('content_ru') or '') if isinstance(rb.get('content_ru', ''), str) else str(rb.get('content_ru'))))
                    except Exception:
                        self.logger.info('Saved articles_ru %s (read-back succeeded)', doc_id)
                    # Also save publish markdown locally when available
                    try:
                        if tr.get('publish_md'):
                            try:
                                self._save_publish_markdown(doc_id, source, tr.get('editorial_result') or {}, tr)
                            except Exception:
                                self.logger.exception('Failed to save publish markdown after articles_ru write for %s', doc_id)
                    except Exception:
                        pass
                else:
                    self.logger.warning('Write appeared to succeed but articles_ru doc %s does not exist after write', doc_id)
            except Exception:
                self.logger.exception('Failed to verify write for articles_ru %s', doc_id)
        except Exception:
            logging.exception("Failed to write generated article %s to articles_ru", doc_id)

    def _fetch_article_content(self, url: str) -> Optional[str]:
        """
        Fetch full article text from URL.
        
        Uses BeautifulSoup and readability-lxml to extract main content from web pages.
        
        Args:
            url: Article URL
            
        Returns:
            Full article text or None if extraction failed
        """
        if not url:
            return None
            
        try:
            # Download page
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Fix encoding if needed
            if response.encoding == 'ISO-8859-1':
                response.encoding = response.apparent_encoding
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Remove unwanted elements
            for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
                element.decompose()
            
            # Remove ad blocks
            ad_selectors = [
                '[class*="ad"]', '[class*="advertisement"]', '[class*="banner"]',
                '[id*="ad"]', '[id*="advertisement"]', '[id*="banner"]',
                '[class*="social"]', '[class*="share"]', '[class*="comment"]'
            ]
            for selector in ad_selectors:
                for element in soup.select(selector):
                    element.decompose()
            
            # Try to find main content using BeautifulSoup
            content_selectors = [
                'article',
                '[class*="content"]',
                '[class*="article"]',
                '[class*="post"]',
                '[class*="entry"]',
                '.main-content',
                '.article-content',
                '.post-content',
                '.entry-content',
                '#content',
                '#article',
                '#post'
            ]
            
            content = None
            for selector in content_selectors:
                elements = soup.select(selector)
                if elements:
                    # Select the largest element
                    largest_element = max(elements, key=lambda x: len(x.get_text()))
                    if len(largest_element.get_text().strip()) > 100:
                        content = largest_element
                        break
            
            # If BeautifulSoup didn't find content, use readability-lxml
            if not content:
                try:
                    doc = Document(response.text)
                    content_html = doc.summary()
                    content_soup = BeautifulSoup(content_html, 'html.parser')
                    content = content_soup
                except Exception as e:
                    self.logger.debug('readability-lxml failed to extract text from %s: %s', url, e)
                    return None
            
            if not content:
                return None
            
            # Extract text
            text = content.get_text(separator=' ', strip=True)
            
            # Clean text
            text = re.sub(r'\s+', ' ', text)  # Remove extra spaces
            text = re.sub(r'\n\s*\n', '\n', text)  # Remove empty lines
            text = text.strip()
            
            # Check if text is long enough
            if len(text) < 50:
                self.logger.debug('Extracted text too short from %s: %d chars', url, len(text))
                return None
            
            self.logger.info('Successfully fetched article content from %s: %d chars', url, len(text))
            return text
            
        except Exception as e:
            self.logger.warning('Failed to fetch article content from %s: %s', url, e)
            return None

    def _phase1_prescan_and_skip(self) -> int:
        """
        Phase 1: Pre-scan and skip low-quality articles.
        
        Mark all currently CATEGORIZED articles with total_score < 60 or older than 5 days as SKIPPED.
        This filtering step runs BEFORE translation to avoid wasting resources on low-quality content.
        
        Returns:
            int: Number of articles marked as SKIPPED
        """
        low_score_count = 0
        skipped_ids = []
        db = self.db
        page_size = 500
        last_snapshot = None
        page_index = 0
        
        try:
            while True:
                try:
                    query = db.collection('articles').where('status', '==', 'CATEGORIZED').order_by('created_at').limit(page_size)
                    if last_snapshot is not None:
                        try:
                            query = query.start_after(last_snapshot)
                        except Exception:
                            # some test fakes may not support start_after
                            pass

                    self.logger.info('Pre-scan page %d: querying articles (after=%s)', page_index, getattr(last_snapshot, 'id', None))
                    docs = list(query.stream())
                    self.logger.info('Pre-scan page %d: fetched %d docs', page_index, len(docs))
                except Exception as exc:
                    # retry once after a short backoff for transient issues
                    self.logger.exception('Pre-scan query failed, retrying once: %s', exc)
                    try:
                        time.sleep(1)
                        docs = list(query.stream())
                    except Exception as exc2:
                        self.logger.exception('Pre-scan retry failed: %s', exc2)
                        break

                if not docs:
                    break

                for d in docs:
                    try:
                        data = d.to_dict() or {}
                        total_score = self._get_total_score(data)
                        

                        skip_reason = None
                        age_days = None
                        
                        if total_score < 60:
                            skip_reason = 'low_score'
                        else:
                            # Check article age - use published_at or fallback to created_at
                            date_field = data.get('published_at') or data.get('published') or data.get('pub_date') or data.get('created_at')
                            if date_field:
                                try:
                                    # Parse ISO format timestamp or Firestore timestamp
                                    if isinstance(date_field, str):
                                        pub_dt = datetime.fromisoformat(date_field.replace('Z', '+00:00'))
                                    else:
                                        # Firestore timestamp object
                                        pub_dt = date_field
                                    
                                    now_utc = datetime.now(timezone.utc)
                                    age_days = (now_utc - pub_dt).total_seconds() / 86400
                                    
                                    if age_days > 5:
                                        skip_reason = 'too_old'
                                except Exception as parse_err:
                                    self.logger.debug('Failed to parse date for %s: %s', d.id, parse_err)

                        if skip_reason:
                            try:
                                db.collection('articles').document(d.id).set({
                                    'status': 'SKIPPED',
                                    'skipped_reason': skip_reason,
                                    'total_score': total_score,
                                    'skipped_at': datetime.now(timezone.utc).isoformat(),
                                    'updated_at': datetime.now(timezone.utc).isoformat(),
                                }, merge=True)
                                
                                if skip_reason == 'low_score':
                                    self.logger.info('pre-scan: marked %s SKIPPED (low_score=%.1f)', d.id, float(total_score))
                                else:
                                    self.logger.info('pre-scan: marked %s SKIPPED (too_old, age=%.1f days)', d.id, age_days)
                                
                                skipped_ids.append(d.id)
                                low_score_count += 1
                            except Exception:
                                self.logger.exception('Failed to mark article %s as SKIPPED', d.id)
                    except Exception:
                        # protect the sweep from single-doc failures
                        self.logger.exception('Error while evaluating score for document %s', getattr(d, 'id', '?'))

                last_snapshot = docs[-1]
                page_index += 1
                # if we received fewer docs than page_size, we've reached the end
                if len(docs) < page_size:
                    break
            
            self.logger.info('Pre-scan complete: marked %d SKIPPED', low_score_count)
            return low_score_count
            
        except Exception:
            # If pre-scan fails, log and return 0
            logging.exception('Pre-scan for low-score articles failed')
            return 0

    def _prepare_article_content(self, doc_id: str, data: dict) -> tuple[str, str, str, str, str, float]:
        """
        Extract and prepare article content for translation.
        
        Returns:
            tuple: (title, description, content, article_url, content_source, total_score)
        """
        title = data.get('title', '') or ''
        description = data.get('description', '') or ''
        content = data.get('content', '') or ''
        article_url = data.get('link') or data.get('url')
        content_source = 'stored'
        
        # Try to fetch full article content from URL
        if article_url:
            fetched_content = self._fetch_article_content(article_url)
            # If full fetched content available, persist a copy to logs for auditing
            try:
                if fetched_content:
                    logs_dir = Path(__file__).resolve().parent.parent.parent / 'logs' / 'fetched_articles'
                    logs_dir.mkdir(parents=True, exist_ok=True)
                    fetched_file = logs_dir / f"{doc_id}_fetched.txt"
                    with open(fetched_file, 'w', encoding='utf-8') as fh:
                        fh.write(fetched_content)
                    self.logger.info('Wrote fetched content to %s', fetched_file)
            except Exception as wf_err:
                self.logger.exception('Failed to write fetched content for %s: %s', doc_id, wf_err)
            
            if fetched_content and len(fetched_content) > len(content):
                self.logger.info('Using fetched content for %s (fetched: %d chars, stored: %d chars)', 
                               doc_id, len(fetched_content), len(content))
                content = fetched_content
                content_source = 'fetched'
            elif fetched_content:
                self.logger.debug('Fetched content shorter than stored for %s, using stored content', doc_id)
            else:
                self.logger.debug('Failed to fetch content for %s, using stored content', doc_id)
        else:
            self.logger.debug('No URL available for %s, using stored content', doc_id)
        
        total_score = self._get_total_score(data)
        return title, description, content, article_url, content_source, total_score

    def _build_article_metadata(self, doc_id: str, data: dict, article_url: str, fetched_content: str, 
                                content_source: str, total_score: float) -> dict:
        """Build metadata dictionary for translation."""
        return {
            'url': article_url,
            'image_url': data.get('image') or data.get('image_url') or None,
            'source': data.get('source') or data.get('source_name'),
            'published_at': data.get('published_at') or data.get('published') or data.get('pub_date'),
            'total_score': total_score,
            'doc_id': doc_id,
            'fetched_content': fetched_content,
            'content_source': content_source,
        }

    def _log_translation_stages(self, doc_id: str, translation_result: dict, trans_duration: float) -> None:
        """Log concise JSON-structured stage completion information."""
        tr = translation_result or {}
        translation_ru = tr.get('translation_ru') or tr.get('content_ru') or ''
        translation_len = len(translation_ru) if isinstance(translation_ru, str) else 0

        stage_log = {
            'doc_id': doc_id,
            'stage1': bool(tr.get('editorial_result', {}).get('stage1')),
            'stage2': bool(tr.get('editorial_result', {}).get('stage2')),
            'stage3': bool(tr.get('editorial_result', {}).get('stage3')),
            'stage4': bool(tr.get('editorial_result', {}).get('stage4')),
            'publish_md': bool(tr.get('publish_md')),
            'telegram': bool(tr.get('tg_preview')),
            'translation_len': translation_len,
            'flags': [str(x) for x in (tr.get('flags') or [])][:20],
            'translator_seconds': round(trans_duration, 3),
        }
        self.logger.info(json.dumps(stage_log, ensure_ascii=False, separators=(',', ':')))

    def _handle_translation_failure(self, doc_id: str, translation_result: dict, total_score: float, 
                                    chunk_results: dict, lock: threading.Lock, proc_start: float) -> None:
        """Handle translation failure by updating status and logging errors."""
        raw_files = []
        try:
            if isinstance(translation_result, dict):
                rf = translation_result.get('_raw_file') or translation_result.get('raw_file')
                if rf:
                    raw_files = [rf]
            # Fallback: discover any files in logs matching doc_id
            if not raw_files:
                log_dir = Path(__file__).parent.parent.parent / 'logs' / 'openai_raw'
                if log_dir.exists():
                    raw_files = [p.name for p in log_dir.glob(f"{doc_id}_*.txt")]
        except Exception:
            raw_files = []

        update_payload = {
            'status': 'TRANSLATION_FAILED',
            'total_score': total_score,
            'translated_at': None,
            'updated_at': datetime.now(timezone.utc).isoformat(),
            'translation_failure_raw_files': raw_files,
        }
        
        try:
            self.db.collection('articles').document(doc_id).set(update_payload, merge=True)

            try:
                raw_text = None
                if isinstance(translation_result, dict):
                    raw_text = translation_result.get('_raw_text') or translation_result.get('raw_text')
                if raw_text:
                    snippet = (raw_text[:4000] + '...') if len(raw_text) > 4000 else raw_text
                    self.logger.warning('Translation failed for %s; raw_output_snippet:\n%s', doc_id, snippet)
                elif raw_files:
                    self.logger.warning('Translation failed for %s; raw_files=%s', doc_id, raw_files)
                else:
                    self.logger.warning('Translation failed for %s', doc_id)
            except Exception:
                pass
            
            with lock:
                chunk_results['processed'] += 1
                if raw_files:
                    chunk_results['errors'].append(f"Translation failed for {doc_id} (raw_files={raw_files})")
                else:
                    chunk_results['errors'].append(f"Translation failed for {doc_id}")
        except Exception as save_err:
            err = f"Firebase save error for {doc_id}: {save_err}"
            with lock:
                chunk_results['errors'].append(err)

        # Per-article summary for failures
        try:
            summary = {
                'doc_id': doc_id,
                'status': 'TRANSLATION_FAILED',
                'total_score': total_score,
                'translation_len': 0,
                'flags': [],
                'processing_time_s': round(time.perf_counter() - proc_start, 3),
                'error': 'translation_failed'
            }
            try:
                self.logger.info(json.dumps(summary, ensure_ascii=False))
            except Exception:
                pass
        except Exception:
            pass

    def _save_translation_success(self, doc_id: str, data: dict, total_score: float, 
                                  translation_result: dict, article_metadata: dict, 
                                  chunk_results: dict, lock: threading.Lock, proc_start: float, 
                                  trans_duration: float) -> None:
        """Save successful translation to both articles_ru and articles collections."""
        title_ru = translation_result.get('title_ru') or None
        description_ru = translation_result.get('description_ru') or None
        content_ru = translation_result.get('content_ru') or translation_result.get('translation_ru') or None
        notes = translation_result.get('notes') or []
        flags = translation_result.get('flags') or []

        try:
            # persist full generated article to articles_ru
            self._save_generated_article(
                doc_id=doc_id,
                source=data,
                total_score=total_score,
                translation_result=translation_result,
                status='TRANSLATED',
                metadata={'worker_name': 'article_generator', 'model': getattr(self.translator, 'model', None)},
            )

            # Also update original article record to reflect translation status
            update_payload = {
                'title_ru': title_ru,
                'description_ru': description_ru,
                'content_ru': content_ru,
                'translation_ru': translation_result.get('translation_ru'),
                'translation_notes': notes,
                'translation_flags': flags,
                'translation_metadata': translation_result,
                'publish_md': translation_result.get('publish_md'),
                'publish_flags': translation_result.get('publish_flags'),
                'telegram_preview': translation_result.get('tg_preview'),
                'telegram_flags': translation_result.get('tg_flags'),
                'telegram_final': translation_result.get('stage6_telegram'),
                'status': 'TRANSLATED',
                'translated_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'fetched_content': article_metadata.get('fetched_content'),
                'fetched_full_text': article_metadata.get('fetched_content'),
                'content_source': article_metadata.get('content_source'),
            }

            try:
                self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
            except Exception as save_err:
                err = f"Firebase save error for {doc_id}: {save_err}"
                with lock:
                    chunk_results['errors'].append(err)

            with lock:
                chunk_results['translated'] += 1
                chunk_results['processed'] += 1

            # Per-article success summary
            try:
                proc_duration = time.perf_counter() - proc_start
                tr = translation_result or {}
                translation_ru = tr.get('translation_ru') or tr.get('content_ru') or ''
                translation_len = len(translation_ru) if isinstance(translation_ru, str) else 0
                
                summary = {
                    'doc_id': doc_id,
                    'status': 'TRANSLATED',
                    'total_score': total_score,
                    'translation_len': translation_len,
                    'flags': [str(x) for x in (tr.get('flags') or [])][:20],
                    'processing_time_s': round(proc_duration, 3),
                }
                try:
                    self.logger.info(json.dumps(summary, ensure_ascii=False))
                except Exception:
                    pass
            except Exception:
                pass
            # Additionally, save the generated publish markdown to local `articles/` folder
            try:
                self._save_publish_markdown(doc_id, data, article_metadata, translation_result)
            except Exception:
                try:
                    self.logger.exception('Failed to save publish markdown for %s', doc_id)
                except Exception:
                    pass
        except Exception as save_err:
            with lock:
                chunk_results['errors'].append(f"Save error for {doc_id}: {save_err}")

        proc_duration = time.perf_counter() - proc_start
        self.logger.info('finished doc %s: trans=%.3fs total=%.3fs', doc_id, trans_duration, proc_duration)

    def _process_single_document(self, doc, chunk_results: dict, lock: threading.Lock) -> None:
        """
        Process a single document for translation.
        
        Args:
            doc: Firestore document snapshot
            chunk_results: Dictionary to accumulate results (processed, translated, errors)
            lock: Threading lock for safe updates to chunk_results
        """
        try:
            proc_start = time.perf_counter()
            doc_id = doc.id
            data = doc.to_dict() or {}
            
            # Prepare article content
            title, description, content, article_url, content_source, total_score = self._prepare_article_content(doc_id, data)
            
            # Build metadata for translation
            article_metadata = self._build_article_metadata(
                doc_id, data, article_url, 
                data.get('fetched_content') if content_source == 'fetched' else None,
                content_source, total_score
            )

            # Call translator and measure time
            trans_start = time.perf_counter()
            translation_result = self.translator.translate(title, description, content, metadata=article_metadata)
            trans_duration = time.perf_counter() - trans_start

            # Log translation stages
            if translation_result:
                self._log_translation_stages(doc_id, translation_result, trans_duration)

            # Detect parse errors
            is_parse_error = isinstance(translation_result, dict) and bool(translation_result.get('_parse_error') or translation_result.get('parse_error'))
            if (not translation_result) or is_parse_error:
                self._handle_translation_failure(doc_id, translation_result, total_score, chunk_results, lock, proc_start)
                return

            # Save successful translation
            self._save_translation_success(doc_id, data, total_score, translation_result, article_metadata, 
                                          chunk_results, lock, proc_start, trans_duration)

        except Exception as proc_err:
            with lock:
                chunk_results['errors'].append(f"Processing error for doc {getattr(doc, 'id', '?')}: {proc_err}")

    def _save_publish_markdown(self, doc_id: str, data: dict, article_metadata: dict, translation_result: dict) -> None:
        """Save generated publish_md into articles/<slug>_<doc_id>.md with frontmatter fixes."""
        tr = translation_result if isinstance(translation_result, dict) else None
        publish_md = tr.get('publish_md') if tr else None
        try:
            self.logger.info('_save_publish_markdown called for %s; publish_md present=%s type=%s',
                             doc_id,
                             bool(publish_md),
                             type(publish_md).__name__ if publish_md is not None else 'None')
        except Exception:
            pass
        if not publish_md or not isinstance(publish_md, str):
            try:
                self.logger.info('No publish_md to save for %s (publish_md=%r)', doc_id, publish_md)
            except Exception:
                pass
            return

        import re as _re
        md = publish_md
        # locate YAML frontmatter
        fm_start = md.find('---')
        fm_end = -1
        if fm_start != -1:
            fm_end = md.find('\n---', fm_start+3)
            if fm_end != -1:
                fm_block = md[fm_start:fm_end]
                rest = md[fm_end+1:]
            else:
                fm_block = ''
                rest = md
        else:
            fm_block = ''
            rest = md

        def _fm_get(key, text):
            m = _re.search(rf'^{key}:\s*(.*)$', text, flags=_re.MULTILINE)
            return m.group(1).strip() if m else None

        title_val = _fm_get('title', fm_block) or translation_result.get('title_ru') or ''
        desc_val = _fm_get('description', fm_block) or translation_result.get('description_ru') or ''
        slug_val = _fm_get('slug', fm_block) or ''
        image_val = _fm_get('image', fm_block) or ''

        def _strip_quotes(s):
            if not s:
                return s
            s = s.strip()
            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                return s[1:-1]
            return s

        title_val = _strip_quotes(title_val)
        desc_val = _strip_quotes(desc_val)
        slug_val = _strip_quotes(slug_val)
        image_val = _strip_quotes(image_val)

        if not slug_val:
            base = (title_val or translation_result.get('title_ru') or '')
            slug = _re.sub(r'[^a-z0-9\-]', '-', base.lower())
            slug = _re.sub(r'-{2,}', '-', slug).strip('-')
            if not slug:
                slug = doc_id
        else:
            slug = slug_val

        if not image_val:
            image_val = article_metadata.get('image_url') or data.get('image') or data.get('image_url') or ''

        # rebuild frontmatter
        if fm_block:
            fm_text = fm_block
            fm_text = _re.sub(r'^title:.*$', f'title: "{title_val.replace("\"", "\\\"")}"', fm_text, flags=_re.MULTILINE)
            fm_text = _re.sub(r'^description:.*$', f'description: "{desc_val.replace("\"", "\\\"")}"', fm_text, flags=_re.MULTILINE)
            if _re.search(r'^image:.*$', fm_text, flags=_re.MULTILINE):
                fm_text = _re.sub(r'^image:.*$', f'image: {image_val}', fm_text, flags=_re.MULTILINE)
            else:
                fm_text = fm_text + '\nimage: ' + (image_val or '')
            if _re.search(r'^slug:.*$', fm_text, flags=_re.MULTILINE):
                fm_text = _re.sub(r'^slug:.*$', f'slug: {slug}', fm_text, flags=_re.MULTILINE)
            else:
                fm_text = fm_text + f'\nslug: {slug}'
            new_md = '---' + fm_text + '\n---' + rest
        else:
            new_fm_lines = [f'title: "{title_val.replace("\"", "\\\"")}"', f'description: "{desc_val.replace("\"", "\\\"")}"', f'slug: {slug}', f'image: {image_val or ""}']
            new_md = '---\n' + '\n'.join(new_fm_lines) + '\n---\n\n' + md

        # ensure image markdown after frontmatter
        if image_val and ('![' not in new_md.split('---', 2)[-1]):
            alt = title_val or slug
            closing_idx = new_md.find('\n---', 0)
            if closing_idx != -1:
                pos = new_md.find('\n', closing_idx+1)
                if pos == -1:
                    pos = closing_idx + 4
                img_line = f"![{alt}]({image_val})\n\n"
                new_md = new_md[:pos+1] + img_line + new_md[pos+1:]

        repo_root = Path(__file__).resolve().parent.parent.parent
        articles_dir = repo_root / 'articles'
        articles_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{slug}_{doc_id}.md"
        file_path = articles_dir / filename
        try:
            self.logger.info('Attempting to write publish markdown to %s', str(file_path))
            with open(file_path, 'w', encoding='utf-8') as fw:
                fw.write(new_md)
            self.logger.info('Wrote publish markdown to %s', str(file_path))
        except Exception as wf:
            self.logger.exception('Failed to write publish markdown file %s: %s', str(file_path), wf)

    def _phase2_translate_articles(self, requested_total: float) -> dict:
        """
        Phase 2: Translate high-quality articles.
        
        Fetch high-quality CATEGORIZED articles in batches and translate them to Russian.
        
        Args:
            requested_total: Maximum number of articles to process (math.inf for unlimited)
            
        Returns:
            dict: Results with keys: processed, skipped, translated, errors
        """
        results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': []}
        chunk_size = 20
        processed_total = 0
        last_snapshot = None
        batch_index = 0

        while processed_total < requested_total:
            limit_for_query = int(min(chunk_size, requested_total - processed_total))
            try:
                self.logger.info('Fetching translation batch %d: limit=%d processed_total=%d requested_total=%s', batch_index, limit_for_query, processed_total, requested_total)
                query = self.db.collection('articles').where('status', '==', 'CATEGORIZED').order_by('created_at').limit(limit_for_query)
                if last_snapshot is not None:
                    try:
                        query = query.start_after(last_snapshot)
                    except Exception:
                        pass

                docs = list(query.stream())
                self.logger.info('Translation batch %d: fetched %d docs', batch_index, len(docs))
            except Exception as e:
                results['errors'].append(f'Query error: {str(e)}')
                return results

            if not docs:
                break

            try:
                max_workers = int(__import__('os').environ.get('ARTICLE_GENERATOR_PARALLELISM', '4'))
            except Exception:
                max_workers = 4

            chunk_results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': []}
            lock = threading.Lock()

            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                futures = [ex.submit(self._process_single_document, d, chunk_results, lock) for d in docs]
                for f in as_completed(futures):
                    try:
                        f.result()
                    except Exception as thread_err:
                        chunk_results['errors'].append(str(thread_err))


            # summarize this chunk for CI logs
            self.logger.info('Batch %d complete: processed=%d skipped=%d translated=%d errors=%d',
                             batch_index, chunk_results['processed'], chunk_results['skipped'], chunk_results['translated'], len(chunk_results['errors']))

            results['processed'] += chunk_results['processed']
            results['skipped'] += chunk_results['skipped']
            results['translated'] += chunk_results['translated']
            results['errors'].extend(chunk_results['errors'])
            processed_total += chunk_results['processed']
            batch_index += 1

            if processed_total >= requested_total:
                break

            try:
                last_snapshot = docs[-1]
            except Exception:
                last_snapshot = None

            if len(docs) < limit_for_query:
                break

        return results

    def process_articles(self) -> dict:
        """
        Two-phase article processing pipeline:
        1. Pre-scan: Mark low-quality articles (total_score < 60) as SKIPPED
        2. Translation: Translate high-quality articles to Russian and save to articles_ru
        
        Returns dict with counts: processed, skipped, translated, errors
        """

        results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': []}

        try:
            # startup log for CI visibility
            self.logger.info('ArticleGenerator starting; instance=%s batch_size=%s', self.instance_id, self.batch_size)

            # Respect configured batch_size when provided, otherwise process all available documents
            requested_total = float(self.batch_size) if (self.batch_size is not None) else math.inf
            self.logger.info('Requested total to process: %s', requested_total)

            # ===== PHASE 1: PRE-SCAN =====
            # Mark all currently CATEGORIZED articles with total_score < 60 as SKIPPED
            # This filtering step runs BEFORE translation to avoid wasting resources on low-quality content
            low_score_count = self._phase1_prescan_and_skip()
            if low_score_count:
                results['skipped'] += low_score_count
                results['processed'] += low_score_count

            # ===== PHASE 2: TRANSLATION =====
            # Fetch high-quality CATEGORIZED articles in batches and translate them to Russian
            translation_results = self._phase2_translate_articles(requested_total)
            
            # Merge translation results into overall results
            results['processed'] += translation_results['processed']
            results['skipped'] += translation_results['skipped']
            results['translated'] += translation_results['translated']
            results['errors'].extend(translation_results['errors'])

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}
