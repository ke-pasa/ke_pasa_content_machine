import uuid
import json
import time
import math
import re
import os
import logging
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Note: external HTML fetching/parsing was removed; avoid importing fetching libraries here.

from .translator import ArticleTranslator
from workers.tools.pg_client import get_pg_client
from workers.tools.constants import MIN_ARTICLE_SCORE


class ArticleGenerator:

    def __init__(self, translator: ArticleTranslator | None = None, batch_size: int | None = None):
        try:
            self.batch_size = int(batch_size) if batch_size is not None else None
            if self.batch_size is not None and self.batch_size < 0:
                self.batch_size = None
        except Exception:
            self.batch_size = None

        try:
            self.pg = get_pg_client()
        except Exception:
            raise RuntimeError('Postgres client is required for ArticleGenerator')
        self.instance_id = str(uuid.uuid4())[:8]
        self.translator = translator or ArticleTranslator(
            stage1_max_tokens=1200,
            stage2_max_tokens=1200,
            stage3_max_tokens=1200
        )
        # Whether to request stage saving from translator (passed via metadata)
        self.save_stages = False
        # Use root logger configuration from entrypoint; avoid adding handlers here.
        self.logger = logging.getLogger('workers.article_generator')
        # Allow propagation to root logger so stdout captures these logs
        self.logger.propagate = True

    def _get_total_score(self, data: dict) -> float:
        """Extract float total_score from article data."""
        try:
            score = data.get('total_score')
            if score is None:
                interest = data.get('interest') or {}
                score = interest.get('total_score') or interest.get('total')
            return float(score) if score is not None else 0.0
        except Exception:
            return 0.0

    def _save_generated_article(self, doc_id: str, source: dict, total_score: float = 0.0,
                                translation_result: dict | None = None, status: str = 'UNKNOWN', metadata: dict | None = None) -> None:
        """Persist generated article and metadata into articles_ru collection."""
        now = datetime.now(timezone.utc).isoformat()
        tr = translation_result or {}

        title_ru = tr.get('title_ru')
        description_ru = tr.get('description_ru')
        content_ru = tr.get('content_ru') or tr.get('translation_ru')

        publish_md = tr.get('publish_md')
        # Take stage6 result directly from translator (do not synthesize tg_preview here)
        stage6_telegram = tr.get('stage6_telegram')

        combined_flags = []
        for flag_list in (tr.get('flags') or [], tr.get('publish_flags') or [], tr.get('tg_flags') or []):
            combined_flags.extend(f for f in (flag_list or []) if isinstance(f, str))

        # Use only `link` field from `public.articles` (Postgres fetch aliases link->source)
        # Accept `source` key (PG alias) as the canonical link when present.
        src_url = source.get('link') or source.get('source')
        img_url = source.get('image')

        # Extract telegram text from stage6_telegram (store plain text, not dict).
        telegram_text = None
        try:
            if isinstance(stage6_telegram, dict):
                tg = stage6_telegram.get('tg_preview') or stage6_telegram.get('text')
                telegram_text = tg if isinstance(tg, str) and tg.strip() != '' else None
            elif isinstance(stage6_telegram, str):
                telegram_text = stage6_telegram.strip() or None
        except Exception:
            telegram_text = None

        # Build the database payload directly from source and translation result
        save_payload = {
            # Prefer explicit link from source, but accept PG alias `source` or `link`
            'source_url': src_url or source.get('source') or source.get('link'),
            'source_link': src_url or source.get('source') or source.get('link'),
            'source_name': source.get('source') or source.get('source_name'),
            'source_published_at': source.get('published_at') or source.get('pub_date'),
            'image_url': img_url,
            'status': status,
            'total_score': total_score,
            'title_ru': title_ru,
            'description_ru': description_ru,
            'content_ru': content_ru,
            'publish_md': publish_md,
            # Save telegram_final as plain text (the tg_preview) or NULL.
            'telegram_final': telegram_text,
            'published_at': now,
            'updated_at': now,
        }

        try:
            # Prefer Postgres client when available (migration to Postgres)
            try:
                from workers.tools.pg_client import get_pg_client
                pg = get_pg_client()
            except Exception:
                pg = None

            if pg:
                ok = pg.save_generated_article(doc_id, save_payload)
                if ok:
                    self.logger.info('Saved articles_ru %s (title_ru_len=%d content_ru_len=%d)', doc_id,
                                   len(str(save_payload.get('title_ru') or '')), len(str(save_payload.get('content_ru') or '')))
                    if tr.get('publish_md'):
                        article_metadata = {'image_url': source.get('image')}
                        try:
                            self._save_publish_markdown(doc_id, source, article_metadata, tr)
                        except Exception:
                            self.logger.exception('Failed to save publish markdown for %s after pg save', doc_id)
                else:
                    self.logger.warning('Postgres save returned False for articles_ru %s', doc_id)
            else:
                # No Postgres client: warn and skip writing articles_ru
                self.logger.warning('No Postgres client available; cannot save articles_ru %s', doc_id)
        except Exception:
            self.logger.exception('Failed to write generated article %s to articles_ru', doc_id)


    def _phase1_prescan_and_skip(self) -> int:
        """Mark CATEGORIZED articles with score < MIN_ARTICLE_SCORE or age > 3 days as SKIPPED."""
        low_score_count = 0
        page_size = 500
        last_snapshot = None
        page_index = 0
        
        try:
            while True:
                rows = self.pg.fetch_articles_new(limit=page_size, last_cursor=last_snapshot, status='CATEGORIZED')
                self.logger.info('Pre-scan page %d: fetched %d rows', page_index, len(rows))

                if not rows:
                    break

                for r in rows:
                    try:
                        data = r or {}
                        total_score = self._get_total_score(data)
                        skip_reason = None
                        age_days = None

                        if total_score < MIN_ARTICLE_SCORE:
                            skip_reason = 'low_score'
                        else:
                            date_field = data.get('published_at') or data.get('published') or data.get('pub_date') or data.get('created_at')
                            if date_field:
                                try:
                                    pub_dt = datetime.fromisoformat(date_field.replace('Z', '+00:00')) if isinstance(date_field, str) else date_field
                                    age_days = (datetime.now(timezone.utc) - pub_dt).total_seconds() / 86400
                                    if age_days > 3:
                                        skip_reason = 'too_old'
                                except Exception:
                                    pass

                        if skip_reason:
                            try:
                                conn, pooled = self.pg._get_conn()
                                cur = conn.cursor()
                                try:
                                    cur.execute("""
                                        UPDATE public.articles SET
                                            status = %s,
                                            total_score = %s,
                                            updated_at = %s
                                        WHERE id = %s
                                    """, (
                                        'SKIPPED', total_score, datetime.now(timezone.utc).isoformat(), r.get('id')
                                    ))
                                    try:
                                        conn.commit()
                                    except Exception:
                                        pass
                                finally:
                                    try:
                                        cur.close()
                                    except Exception:
                                        pass
                                    self.pg._put_conn(conn, pooled)
                            except Exception:
                                self.logger.exception('Failed to mark skipped for %s', r.get('id'))

                            log_msg = f'pre-scan: marked {r.get("id")} SKIPPED ({skip_reason}'
                            if skip_reason == 'low_score':
                                self.logger.info(log_msg + f', score={total_score:.1f})')
                            else:
                                self.logger.info(log_msg + f', age={age_days:.1f} days)')
                            low_score_count += 1
                    except Exception:
                        self.logger.exception('Error evaluating row %s', getattr(r, 'id', '?'))

                last_snapshot = rows[-1]
                page_index += 1
                if len(rows) < page_size:
                    break
            
            self.logger.info('Pre-scan complete: marked %d SKIPPED', low_score_count)
            return low_score_count
            
        except Exception:
            self.logger.exception('Pre-scan for low-score articles failed')
            return 0

    def _prepare_article_content(self, doc_id: str, data: dict) -> Tuple[str, str, str, Optional[str], str, float]:
        """Extract and prepare article content for translation."""
        title = data.get('title', '') or ''
        description = data.get('description', '') or ''
        content = data.get('content', '') or ''
        # Only use `link` from the canonical `public.articles` row (Postgres returns it as `source`)
        article_url = data.get('link') or data.get('source')
        content_source = 'stored'
        
        return title, description, content, article_url, content_source, self._get_total_score(data)

    def _build_article_metadata(self, doc_id: str, data: dict, article_url: Optional[str], fetched_content: Optional[str], 
                                content_source: str, total_score: float) -> dict:
        """Build metadata dictionary for translation."""
        return {
            'url': article_url,
            # Only use `image` from `public.articles`
            'image_url': data.get('image'),
            'source': data.get('source') or data.get('source_name'),
            'published_at': data.get('published_at') or data.get('published') or data.get('pub_date'),
            'total_score': total_score,
            'doc_id': doc_id,
            'fetched_content': fetched_content,
            'content_source': content_source,
            # Forward save_stages flag so translator can opt-in to writing logs
            'save_stages': getattr(self, 'save_stages', False),
        }

    def _log_translation_stages(self, doc_id: str, translation_result: Optional[dict], trans_duration: float) -> None:
        """Log stage completion information."""
        tr = translation_result or {}
        translation_ru = tr.get('translation_ru') or tr.get('content_ru') or ''
        editorial = tr.get('editorial_result', {})

        stage_log = {
            'doc_id': doc_id,
            'stage1': bool(editorial.get('stage1')),
            'stage2': bool(editorial.get('stage2')),
            'stage3': bool(editorial.get('stage3')),
            'stage4': bool(editorial.get('stage4')),
            'publish_md': bool(tr.get('publish_md')),
            'telegram': bool(tr.get('tg_preview')),
            'translation_len': len(translation_ru) if isinstance(translation_ru, str) else 0,
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
            try:
                conn, pooled = self.pg._get_conn()
                cur = conn.cursor()
                try:
                    cur.execute("""
                        UPDATE public.articles SET
                            title = COALESCE(%s, title),
                            summary = COALESCE(%s, summary),
                            content = COALESCE(%s, content),
                            updated_at = %s
                        WHERE id = %s
                    """, (
                        update_payload.get('title_ru'),
                        update_payload.get('description_ru'),
                        update_payload.get('content_ru'),
                        update_payload.get('updated_at'),
                        doc_id,
                    ))
                    try:
                        conn.commit()
                    except Exception:
                        pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    self.pg._put_conn(conn, pooled)
            except Exception:
                # best-effort: fall back to no-op if PG update fails
                self.logger.exception('Failed to update articles row %s', doc_id)

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
            # Ensure telegram_final has tg_preview for compatibility with publisher
            # Use stage6 as returned by translator without merging tg_preview
            try:
                stage6 = translation_result.get('stage6_telegram')
            except Exception:
                stage6 = translation_result.get('stage6_telegram') if isinstance(translation_result, dict) else None

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
                'telegram_final': stage6,
                'status': 'TRANSLATED',
                'translated_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'fetched_content': article_metadata.get('fetched_content'),
                'fetched_full_text': article_metadata.get('fetched_content'),
                'content_source': article_metadata.get('content_source'),
            }

            try:
                conn, pooled = self.pg._get_conn()
                cur = conn.cursor()
                try:
                    cur.execute("""
                        UPDATE public.articles SET
                            title = COALESCE(%s, title),
                            summary = COALESCE(%s, summary),
                            content = COALESCE(%s, content),
                            updated_at = %s
                        WHERE id = %s
                    """, (
                        update_payload.get('title_ru'),
                        update_payload.get('description_ru'),
                        update_payload.get('content_ru'),
                        update_payload.get('updated_at'),
                        doc_id,
                    ))
                    conn.commit()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    try:
                        self.pg._put_conn(conn, pooled)
                    except Exception:
                        pass
            except Exception as save_err:
                with lock:
                    chunk_results['errors'].append(f"Postgres save error for {doc_id}: {save_err}")

            with lock:
                chunk_results['translated'] += 1
                chunk_results['processed'] += 1
                chunk_results['translated_ids'].append(doc_id)

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
            # Publish markdown is saved earlier during Postgres save; do not call it again here.
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

            if not isinstance(doc, dict):
                try:
                    # Try to call a to_dict() if present as a best-effort
                    data = doc.to_dict() if hasattr(doc, 'to_dict') else None
                    if not isinstance(data, dict):
                        raise ValueError('doc is not a dict')
                except Exception:
                    self.logger.warning('Received non-dict document in _process_single_document; skipping')
                    with lock:
                        chunk_results['errors'].append(f'Invalid document type for {getattr(doc, "id", "?")}')
                    return
                doc_id = data.get('id')
            else:
                data = doc or {}
                doc_id = data.get('id')
            
            title, description, content, article_url, content_source, total_score = self._prepare_article_content(doc_id, data)
            
            article_metadata = self._build_article_metadata(
                doc_id, data, article_url, 
                data.get('fetched_content') if content_source == 'fetched' else None,
                content_source, total_score
            )

            trans_start = time.perf_counter()
            translation_result = self.translator.translate(title, description, content, metadata=article_metadata)
            trans_duration = time.perf_counter() - trans_start

            # Log translation stages
            if translation_result:
                self._log_translation_stages(doc_id, translation_result, trans_duration)

            is_parse_error = isinstance(translation_result, dict) and bool(translation_result.get('_parse_error') or translation_result.get('parse_error'))
            if (not translation_result) or is_parse_error:
                self.logger.error(f'Translation failed for {doc_id}: result={translation_result}')
                self._handle_translation_failure(doc_id, translation_result, total_score, chunk_results, lock, proc_start)
                return

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

        # Determine whether the original frontmatter contained an explicit image: field
        had_image_in_fm = False
        try:
            if fm_block and _re.search(r'^image:\s*.*$', fm_block, flags=_re.MULTILINE):
                had_image_in_fm = True
        except Exception:
            had_image_in_fm = False


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
            esc_title = title_val.replace('"', '\\"') if isinstance(title_val, str) else ''
            esc_desc = desc_val.replace('"', '\\"') if isinstance(desc_val, str) else ''
            fm_text = _re.sub(r'^title:.*$', f'title: "{esc_title}"', fm_text, flags=_re.MULTILINE)
            fm_text = _re.sub(r'^description:.*$', f'description: "{esc_desc}"', fm_text, flags=_re.MULTILINE)
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
            esc_title2 = title_val.replace('"', '\\"') if isinstance(title_val, str) else ''
            esc_desc2 = desc_val.replace('"', '\\"') if isinstance(desc_val, str) else ''
            new_fm_lines = [f'title: "{esc_title2}"', f'description: "{esc_desc2}"', f'slug: {slug}', f'image: {image_val or ""}']
            new_md = '---\n' + '\n'.join(new_fm_lines) + '\n---\n\n' + md

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
        results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': [], 'translated_ids': []}
        chunk_size = 20
        processed_total = 0
        last_snapshot = None
        batch_index = 0

        while processed_total < requested_total:
            limit_for_query = int(min(chunk_size, requested_total - processed_total))

            self.logger.info('Fetching translation batch %d: limit=%d processed_total=%d requested_total=%s', batch_index, limit_for_query, processed_total, requested_total)
            try:
                rows = self.pg.fetch_articles_new(limit=limit_for_query, last_cursor=last_snapshot, status='CATEGORIZED')
            except Exception as e:
                results['errors'].append(f'PG query error: {e}')
                return results

            docs = rows
            self.logger.info('Translation batch %d: fetched %d rows', batch_index, len(docs))

            if not docs:
                break

            chunk_results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': [], 'translated_ids': []}
            lock = threading.Lock()

            for doc in docs:
                try:
                    self._process_single_document(doc, chunk_results, lock)
                except Exception as thread_err:
                    chunk_results['errors'].append(str(thread_err))

            # summarize this chunk for CI logs
            self.logger.info('Batch %d complete: processed=%d skipped=%d translated=%d errors=%d',
                             batch_index, chunk_results['processed'], chunk_results['skipped'], chunk_results['translated'], len(chunk_results['errors']))

            results['processed'] += chunk_results['processed']
            results['skipped'] += chunk_results['skipped']
            results['translated'] += chunk_results['translated']
            results['errors'].extend(chunk_results['errors'])
            results['translated_ids'].extend(chunk_results['translated_ids'])
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

    def process_articles(self) -> dict[str, any]:
        """Two-phase pipeline: 1) Mark low-quality as SKIPPED, 2) Translate high-quality to Russian."""
        results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': [], 'translated_ids': []}

        try:
            self.logger.info('ArticleGenerator starting; instance=%s batch_size=%s', self.instance_id, self.batch_size)

            # Respect configured batch_size when provided, otherwise process all available documents
            requested_total = float(self.batch_size) if (self.batch_size is not None) else math.inf
            self.logger.info('Requested total to process: %s', requested_total)

            # ===== PHASE 1: PRE-SCAN =====
            # Mark all currently CATEGORIZED articles with total_score < MIN_ARTICLE_SCORE as SKIPPED
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
            results['translated_ids'].extend(translation_results['translated_ids'])

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def process_single_article(self, article_id: str) -> dict:
        """Process a single article by id: run translation and save results.

        Returns same result shape as chunk processing for one document.
        """
        try:
            if not article_id:
                return {'status': 'error', 'message': 'article_id required'}

            # Fetch the article row from Postgres
            try:
                row = self.pg.fetch_article_by_id(article_id)
            except Exception as e:
                return {'status': 'error', 'message': f'failed to fetch article: {e}'}

            if not row:
                return {'status': 'error', 'message': 'article not found'}

            # Process a single document using existing pipeline pieces
            chunk_results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': [], 'translated_ids': []}
            lock = threading.Lock()

            # Use the same flow as _process_single_document
            try:
                self._process_single_document(row, chunk_results, lock)
            except Exception as e:
                chunk_results['errors'].append(str(e))

            return {'status': 'success', **chunk_results}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def process_continuous(self, git_sync_interval_minutes: int = 30) -> None:
        """
        Continuously process articles in an infinite loop.
        
        - Fetches the top CATEGORIZED article from the last 24 hours (by total_score DESC)
        - Processes and saves it to articles/ directory
        - Waits 5 seconds before fetching the next article
        - Performs git sync every git_sync_interval_minutes (default 30 minutes)
        - Runs indefinitely until manually stopped (Ctrl+C)
        
        Args:
            git_sync_interval_minutes: How often to sync to git (default 30 minutes)
        """
        self.logger.info('🔄 Starting continuous article processing mode')
        self.logger.info(f'Git sync interval: {git_sync_interval_minutes} minutes')
        
        processed_ids = []
        processed_in_session = set()  # Track all IDs processed in this session
        article_pause_seconds = 5
        
        # Articles directory path
        articles_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'articles')
        
        cycle_count = 0
        
        while True:
            try:
                cycle_count += 1
                self.logger.info(f'📊 Cycle {cycle_count}: Fetching top CATEGORIZED article from last 24h...')
                
                # Count markdown files in articles directory
                articles_count = 0
                if os.path.exists(articles_dir):
                    articles_count = len([f for f in os.listdir(articles_dir) if f.endswith('.md')])
                                
                # Fetch the top article from last 24 hours
                article = self.pg.fetch_top_categorized_article_24h()
                
                if not article:
                    self.logger.info('⏸️  No CATEGORIZED articles found in last 24h. Waiting 60 seconds...')
                    time.sleep(60)
                    continue
                
                article_id = article.get('id')
                
                # Skip if already processed in this session
                if article_id in processed_in_session:
                    self.logger.info(f'⏭️  Article {article_id} already processed in this session. Waiting 60 seconds...')
                    time.sleep(60)
                    continue
                
                total_score = self._get_total_score(article)
                
                self.logger.info(f'✅ Found article: {article_id} (score: {total_score:.2f})')
                
                # Process the article
                chunk_results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': [], 'translated_ids': []}
                lock = threading.Lock()
                
                try:
                    self._process_single_document(article, chunk_results, lock)
                    
                    # Mark this article as processed in session
                    processed_in_session.add(article_id)
                    
                    if chunk_results['translated'] > 0:
                        processed_ids.append(article_id)
                        self.logger.info(f'✅ Successfully processed article {article_id}')
                    elif chunk_results['skipped'] > 0:
                        self.logger.info(f'⏭️  Skipped article {article_id}')
                    elif chunk_results['errors']:
                        # Translation or processing failed - stop continuous mode
                        self.logger.error(f'❌ Errors during processing: {chunk_results["errors"]}')
                        self.logger.error(f'🛑 Stopping continuous mode due to processing errors')
                        break
                    else:
                        self.logger.warning(f'⚠️  Article {article_id} processed with no clear result')
                        self.logger.warning(f'🛑 Stopping continuous mode due to unclear result')
                        break
                
                except Exception as proc_err:
                    self.logger.exception(f'❌ Failed to process article {article_id}: {proc_err}')
                    self.logger.error(f'🛑 Stopping continuous mode due to processing exception')
                    # Still mark as processed to avoid infinite retries
                    processed_in_session.add(article_id)
                    break
                
                # Wait before fetching next article
                self.logger.info(f'⏸️  Waiting {article_pause_seconds} seconds before next article...')
                time.sleep(article_pause_seconds)
                
            except KeyboardInterrupt:
                self.logger.info('🛑 Received shutdown signal. Requesting final sync via git-sync daemon...')
                try:
                    # Create a simple trigger file the daemon watches for
                    repo_root = Path(__file__).resolve().parent.parent.parent
                    trigger_file = repo_root / 'articles' / 'sync_now.flag'
                    articles_dir = repo_root / 'articles'
                    if articles_dir.exists() and any(articles_dir.glob('*.md')):
                        try:
                            trigger_file.write_text(datetime.now(timezone.utc).isoformat(), encoding='utf-8')
                            self.logger.info('Wrote trigger file %s to request immediate sync', trigger_file)
                        except Exception:
                            self.logger.exception('Failed to write trigger file %s', trigger_file)
                    else:
                        self.logger.info('No markdown files present; no trigger file created')
                except Exception:
                    self.logger.exception('Error while creating trigger file')
                self.logger.info('👋 Shutting down gracefully')
                break
            
            except Exception as loop_err:
                self.logger.exception(f'❌ Unexpected error in continuous loop: {loop_err}')
                self.logger.info('⏸️  Waiting 30 seconds before retry...')
                time.sleep(30)

