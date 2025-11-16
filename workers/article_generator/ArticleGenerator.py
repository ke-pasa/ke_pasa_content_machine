import uuid
import json
from datetime import datetime, timezone, timedelta
import time
import math
from pathlib import Path
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from .translator import ArticleTranslator


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
        title_ru = tr.get('title_ru') or (tr.get('editorial_result') or {}).get('title_ru') or None
        description_ru = tr.get('description_ru') or (tr.get('editorial_result') or {}).get('description_ru') or None
        content_ru = tr.get('content_ru') or (tr.get('editorial_result') or {}).get('content_ru') or tr.get('translation_ru') or None

        # Stage outputs
        stage2 = tr.get('editorial_result') or None
        stage3 = {'publish_md': tr.get('publish_md'), 'flags': tr.get('publish_flags') or []}
        stage4 = {'tg_preview': tr.get('tg_preview'), 'flags': tr.get('tg_flags') or []}

        # Combine flags from various sources
        combined_flags = []
        for f in (tr.get('flags') or [], stage3.get('flags') or [], stage4.get('flags') or []):
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
                'editorial': stage2,
                'publish': stage3,
                'telegram': stage4,
            },
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
                else:
                    self.logger.warning('Write appeared to succeed but articles_ru doc %s does not exist after write', doc_id)
            except Exception:
                self.logger.exception('Failed to verify write for articles_ru %s', doc_id)
        except Exception:
            logging.exception("Failed to write generated article %s to articles_ru", doc_id)

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
            try:
                # Page through CATEGORIZED docs in chunks to avoid long-running Firestore queries
                low_score_count = 0
                skipped_ids = []
                db = self.db
                page_size = 500
                last_snapshot = None
                page_index = 0
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
                            
                            # Check if article is older than 5 days
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

                if low_score_count:
                    results['skipped'] += low_score_count
                    results['processed'] += low_score_count
                
                self.logger.info('Pre-scan complete: marked %d SKIPPED', low_score_count)
            except Exception:
                # If pre-scan fails, continue to translation pass without blocking
                logging.exception('Pre-scan for low-score articles failed')

            # ===== PHASE 2: TRANSLATION =====
            # Fetch high-quality CATEGORIZED articles in batches and translate them to Russian
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
                            # fake DBs used in tests may not support start_after
                            pass

                    docs = list(query.stream())
                    self.logger.info('Translation batch %d: fetched %d docs', batch_index, len(docs))
                except Exception as e:
                    return {'status': 'error', 'message': str(e)}

                if not docs:
                    break

                try:
                    max_workers = int(__import__('os').environ.get('ARTICLE_GENERATOR_PARALLELISM', '4'))
                except Exception:
                    max_workers = 4

                chunk_results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': []}
                lock = threading.Lock()

                def _process_doc(doc):
                    try:
                        proc_start = time.perf_counter()
                        doc_id = doc.id
                        data = doc.to_dict() or {}
                        title = data.get('title', '') or ''
                        description = data.get('description', '') or ''
                        content = data.get('content', '') or ''

                        # Get total_score for metadata
                        total_score = self._get_total_score(data)

                        article_metadata = {
                            'url': data.get('link') or data.get('url'),
                            'source': data.get('source') or data.get('source_name'),
                            'published_at': data.get('published_at') or data.get('published') or data.get('pub_date'),
                            'total_score': total_score,
                            'doc_id': doc_id,
                        }

                        # call translator and measure time
                        trans_start = time.perf_counter()
                        translation_result = self.translator.translate(title, description, content, metadata=article_metadata)
                        trans_duration = time.perf_counter() - trans_start

                        # Report concise JSON-structured stage completion log
                        tr = translation_result or {}
                        translation_ru = tr.get('translation_ru') or tr.get('content_ru') or ''
                        translation_len = len(translation_ru) if isinstance(translation_ru, str) else 0

                        stage_log = {
                            'doc_id': doc_id,
                            'editorial': bool(tr.get('editorial_result')),
                            'publish': bool(tr.get('publish_md')),
                            'telegram': bool(tr.get('tg_preview')),
                            'translation_len': translation_len,
                            'flags': [str(x) for x in (tr.get('flags') or [])][:20],
                            'translator_seconds': round(trans_duration, 3),
                        }
                        self.logger.info(json.dumps(stage_log, ensure_ascii=False, separators=(',', ':')))

                        # Detect both falsy returns and sentinel dicts from translator indicating parse errors
                        is_parse_error = isinstance(translation_result, dict) and bool(translation_result.get('_parse_error') or translation_result.get('parse_error'))
                        if (not translation_result) or is_parse_error:
                            # translation_result may contain direct raw filename info
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

                            return

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
                                'status': 'TRANSLATED',
                                'translated_at': datetime.now(timezone.utc).isoformat(),
                                'updated_at': datetime.now(timezone.utc).isoformat(),
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
                        except Exception as save_err:
                            with lock:
                                chunk_results['errors'].append(f"Save error for {doc_id}: {save_err}")

                        proc_duration = time.perf_counter() - proc_start
                        self.logger.info('finished doc %s: trans=%.3fs total=%.3fs', doc_id, trans_duration, proc_duration)

                    except Exception as proc_err:
                        with lock:
                            chunk_results['errors'].append(f"Processing error for doc {getattr(doc, 'id', '?')}: {proc_err}")

                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = [ex.submit(_process_doc, d) for d in docs]
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

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}
