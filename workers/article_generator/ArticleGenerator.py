import uuid
import json
from datetime import datetime, timezone
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
        self.translator = translator or ArticleTranslator()
        self.logger = logging.getLogger('workers.article_generator')

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
            'source_name': source.get('source') or source.get('source_name'),
            'source_published_at': source.get('published_at') or source.get('pub_date') or None,
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
            'model': getattr(getattr(self, 'translator', None), 'model', None) or 'gpt-5-mini',
            'worker': metadata.get('worker_name'),
            'translation_metadata': tr,
            'created_at': now,
            'updated_at': now,
        }

        try:
            self.db.collection('articles_ru').document(doc_id).set(payload, merge=True)
        except Exception:
            logging.exception("Failed to write generated article %s to articles_ru", doc_id)

    def translated(self) -> dict:
        """Read articles with status CATEGORIZED. If total_score < 60 -> set SKIPPED. Else -> translate to Russian."""

        results = {'processed': 0, 'skipped': 0, 'translated': 0, 'errors': []}

        try:
            # startup log for CI visibility
            self.logger.info('ArticleGenerator starting; instance=%s batch_size=%s', self.instance_id, self.batch_size)

            # Respect configured batch_size when provided, otherwise process all available documents
            requested_total = float(self.batch_size) if (self.batch_size is not None) else math.inf
            self.logger.info('Requested total to process: %s', requested_total)

            # First pass: mark all currently CATEGORIZED articles with total_score < 60 as SKIPPED
            try:
                # Page through CATEGORIZED docs in chunks to avoid long-running Firestore queries
                low_score_count = 0
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

                            if total_score < 60:
                                try:
                                    db.collection('articles').document(d.id).set({
                                        'status': 'SKIPPED',
                                        'skipped_reason': 'low_score',
                                        'total_score': total_score,
                                        'skipped_at': datetime.now(timezone.utc).isoformat(),
                                        'updated_at': datetime.now(timezone.utc).isoformat(),
                                    }, merge=True)
                                    # Log the skip so CI shows the action
                                    self.logger.info('pre-scan: marked %s SKIPPED (low_score=%.1f)', d.id, float(total_score))
                                    low_score_count += 1
                                except Exception:
                                    self.logger.exception('Failed to mark low-score article %s as SKIPPED', d.id)
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
            except Exception:
                # If pre-pass fails, continue to translation pass without blocking
                logging.exception('Pre-scan for low-score articles failed')

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
                        self.logger.info('start processing doc %s', getattr(doc, 'id', '?'))

                        doc_id = doc.id
                        data = doc.to_dict() or {}
                        title = data.get('title', '') or ''
                        description = data.get('description', '') or ''
                        content = data.get('content', '') or ''

                        # Determine total_score using helper
                        total_score = self._get_total_score(data)

                        if total_score < 60:
                            update_payload = {
                                'status': 'SKIPPED',
                                'skipped_reason': 'low_score',
                                'total_score': total_score,
                                'skipped_at': datetime.now(timezone.utc).isoformat(),
                                'updated_at': datetime.now(timezone.utc).isoformat(),
                            }
                            try:
                                self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
                                self.logger.info('translation-pass: marked %s SKIPPED (low_score=%.1f)', doc_id, float(total_score))
                                with lock:
                                    chunk_results['skipped'] += 1
                                    chunk_results['processed'] += 1
                            except Exception as save_err:
                                err = f"Firebase save error for {doc_id}: {save_err}"
                                with lock:
                                    chunk_results['errors'].append(err)
                            return

                        article_metadata = {
                            'url': data.get('link') or data.get('url'),
                            'link': data.get('link'),
                            'source': data.get('source') or data.get('source_name'),
                            'source_name': data.get('source_name') or data.get('source'),
                            'published_at': data.get('published_at') or data.get('published') or data.get('pub_date'),
                            'pub_date': data.get('pub_date'),
                            'total_score': total_score,
                        }

                        # call translator and measure time
                        trans_start = time.perf_counter()
                        translation_result = self.translator.translate(title, description, content, metadata=article_metadata)
                        trans_duration = time.perf_counter() - trans_start
                        self.logger.debug('translator finished for %s in %.3fs', doc_id, trans_duration)

                        # Report concise JSON-structured stage completion log for CI and parsing
                        try:
                            tr = translation_result or {}
                            editorial = bool(tr.get('editorial_result'))
                            publish_md = bool(tr.get('publish_md'))
                            tg_preview = bool(tr.get('tg_preview'))
                            translation_ru = tr.get('translation_ru') or tr.get('content_ru') or ''
                            if not isinstance(translation_ru, str):
                                try:
                                    translation_ru = str(translation_ru)
                                except Exception:
                                    translation_ru = ''
                            translation_snippet = (translation_ru[:200] + '...') if len(translation_ru) > 200 else translation_ru
                            translation_len = len(translation_ru)
                            flags = [str(x) for x in (tr.get('flags') or [])][:20]

                            stage_log = {
                                'doc_id': doc_id,
                                'editorial': editorial,
                                'publish': publish_md,
                                'telegram': tg_preview,
                                'translation_len': translation_len,
                                'translation_snippet': translation_snippet,
                                'flags': flags,
                                'translator_seconds': round(trans_duration, 3),
                                'worker_instance': self.instance_id,
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                            }

                            # Emit structured JSON so CI logs are easier to parse/search
                            try:
                                self.logger.info(json.dumps(stage_log, ensure_ascii=False, separators=(',', ':')))
                            except Exception:
                                # fallback to plain info if JSON encoding fails
                                self.logger.info('doc %s stages: editorial=%s publish=%s telegram=%s translation_len=%d',
                                                 doc_id, editorial, publish_md, tg_preview, translation_len)
                        except Exception:
                            # don't let logging interfere with processing
                            self.logger.exception('Failed to log translation stages for %s', doc_id)

                        if not translation_result:
                            update_payload = {
                                'status': 'TRANSLATION_FAILED',
                                'total_score': total_score,
                                'translated_at': None,
                                'updated_at': datetime.now(timezone.utc).isoformat(),
                            }
                            try:
                                self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
                                with lock:
                                    chunk_results['processed'] += 1
                                    chunk_results['errors'].append(f"Translation failed for {doc_id}")
                            except Exception as save_err:
                                err = f"Firebase save error for {doc_id}: {save_err}"
                                with lock:
                                    chunk_results['errors'].append(err)
                            return

                        title_ru = translation_result.get('title_ru') or None
                        description_ru = translation_result.get('description_ru') or None
                        content_ru = translation_result.get('content_ru') or translation_result.get('translation_ru') or None
                        notes = translation_result.get('notes') or []
                        flags = translation_result.get('flags') or []

                        # Instead of updating the original `articles` doc and setting status=TRANSLATED,
                        # persist the generated result into `articles_ru` only. Do not modify the
                        # original article's status (user requested to keep original untouched).
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
                                'total_score': total_score,
                                'translated_at': datetime.now(timezone.utc).isoformat(),
                                'updated_at': datetime.now(timezone.utc).isoformat(),
                            }

                            try:
                                self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
                            except Exception as save_err:
                                # If updating original fails, record error but do not roll back articles_ru
                                err = f"Firebase save error for {doc_id}: {save_err}"
                                with lock:
                                    chunk_results['errors'].append(err)

                            with lock:
                                chunk_results['translated'] += 1
                                chunk_results['processed'] += 1
                        except Exception as save_err:
                            err = f"Generated-article save error for {doc_id}: {save_err}"
                            with lock:
                                chunk_results['errors'].append(err)

                        try:
                            proc_duration = time.perf_counter() - proc_start
                            log_dir = Path(__file__).parent.parent.parent / 'logs'
                            log_dir.mkdir(parents=True, exist_ok=True)
                            log_file = log_dir / 'article_generation.jsonl'

                            # build rich log entry
                            entry = {
                                'doc_id': doc_id,
                                'source_url': article_metadata.get('url'),
                                'source_name': article_metadata.get('source_name') or article_metadata.get('source'),
                                'total_score': total_score,
                                'model': getattr(self.translator, 'model', None) or 'gpt-5-mini',
                                'translation_result_summary': {
                                    'has_translation': bool(translation_result.get('translation_ru')) if isinstance(translation_result, dict) else False,
                                    'title_ru_len': len((translation_result.get('title_ru') or '') if isinstance(translation_result, dict) else ''),
                                    'content_ru_len': len((translation_result.get('content_ru') or translation_result.get('translation_ru') or '') if isinstance(translation_result, dict) else ''),
                                    'flags': translation_result.get('flags') if isinstance(translation_result, dict) else [],
                                    'publish_md_len': len((translation_result.get('publish_md') or '') if isinstance(translation_result, dict) else ''),
                                    'tg_preview_len': len((translation_result.get('tg_preview') or '') if isinstance(translation_result, dict) else ''),
                                },
                                'timings': {
                                    'translator_seconds': round(trans_duration, 3),
                                    'processing_seconds': round(proc_duration, 3),
                                },
                                'worker_instance': self.instance_id,
                                'timestamp': datetime.now(timezone.utc).isoformat(),
                            }

                            # include full translation_result for deeper debugging
                            try:
                                entry['translation_full'] = translation_result
                            except Exception:
                                entry['translation_full'] = str(translation_result)

                            with log_file.open('a', encoding='utf-8') as f:
                                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

                            self.logger.info('finished processing doc %s: trans=%.3fs total=%.3fs', doc_id, trans_duration, proc_duration)
                        except Exception:
                            self.logger.exception('failed to write log for %s', doc_id)

                    except Exception as proc_err:
                        err = f"Processing error for doc {getattr(doc, 'id', '?')}: {proc_err}"
                        with lock:
                            chunk_results['errors'].append(err)

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
