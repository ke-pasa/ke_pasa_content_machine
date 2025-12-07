import uuid
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib

from .news_filter_prompt import get_news_filter_prompt
from workers.tools.openai_client import parse_json_from_text
from workers.tools.constants import MIN_ARTICLE_SCORE

# Firebase client removed — this worker uses Postgres via `workers.tools.pg_client`.


def _get_openai_client():
    try:
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'get_openai_client'):
            return worker_mod.get_openai_client()
    except Exception:
        pass
    from workers.tools.openai_client import get_openai_client as _go
    return _go()


def _chat_completion(client, model, messages, max_tokens=600, temperature=0):
    try:
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'chat_completion'):
            return worker_mod.chat_completion(client, model, messages, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        pass
    from workers.tools.openai_client import chat_completion as _cc
    return _cc(client, model, messages, max_tokens=max_tokens, temperature=temperature)


def _parse_json_from_text(text: str):
    try:
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    except Exception:
        pass
    return parse_json_from_text(text)


from .config import CategorizationConfig


class CategorizationWorker:
    """Categorization worker with paginated reads from Postgres via `workers.tools.pg_client`.

    This worker was migrated away from Firestore and now uses the `PGClient` adapter
    exposed by `workers.tools.pg_client.get_pg_client()`. The code still defensively
    handles Firestore-like objects for backward compatibility, but reads/writes use Postgres.
    """

    def __init__(self, config: CategorizationConfig = None, batch_size: int = None):
        self.config = config or CategorizationConfig.from_env()

        if batch_size is not None:
            try:
                self.config.batch_size = int(batch_size)
            except Exception:
                self.config.batch_size = 10
        else:
            self.config.batch_size = int(getattr(self.config, 'batch_size', 10) or 10)

        from workers.tools.pg_client import get_pg_client
        self.pg = get_pg_client()
        self.instance_id = str(uuid.uuid4())[:8]

    def categorize_new_articles(self) -> Dict:
        results = {'processed': 0, 'errors': []}

        score_buckets = {
            '90+': 0,
            '80-90': 0,
            '70-80': 0,
            '60-70': 0,
            '<60': 0
        }

        try:
            requested_total = int(self.config.batch_size)
            if requested_total <= 0:
                return {'status': 'success', 'processed': 0}

            chunk_size = 30
            processed_total = 0
            last_snapshot = None

            while processed_total < requested_total:
                limit_for_query = min(chunk_size, requested_total - processed_total)

                try:
                    # last_snapshot is a cursor dict with 'created_at' and 'id'
                    docs = self.pg.fetch_articles_new(limit=limit_for_query, last_cursor=last_snapshot, status='NEW')
                except Exception as e:
                    return {'status': 'error', 'message': str(e)}

                if not docs:
                    break

                model = 'gpt-5-mini'
                client = _get_openai_client()

                try:
                    max_workers = int(getattr(self.config, 'parallelism', None) or 0) or int(__import__('os').environ.get('CATEGORIZATION_PARALLELISM', '4'))
                except Exception:
                    max_workers = 4

                chunk_results = {'processed': 0, 'errors': []}
                lock = threading.Lock()

                def _process_doc(doc):
                    try:
                        # Expect normalized row dicts from Postgres
                        if isinstance(doc, dict):
                            doc_id = doc.get('id')
                            data = doc
                        else:
                            # Defensive fallback: try to handle Firestore-like objects
                            try:
                                doc_id = getattr(doc, 'id', None)
                                data = doc.to_dict() or {}
                            except Exception:
                                doc_id = None
                                data = {}

                        title = data.get('title', '')
                        description = data.get('description', '') or ''
                        content = data.get('content', '') or ''
                        tags = data.get('tags', []) or data.get('categories', []) or []
                        source = data.get('source', '') or data.get('link', '') or ''
                        pub_date = data.get('pub_date', '') or ''

                        feed_name = data.get('feed_name', '') or data.get('feed', '') or ''
                        region_hint = data.get('region_hint', '') or ''
                        system_prompt, user_prompt = get_news_filter_prompt(title, description, tags, content, source, pub_date, feed_name=feed_name, region_hint=region_hint)

                        interest_result = None
                        record_start = time.perf_counter()

                        if client:
                            try:
                                messages = [
                                    {"role": "system", "content": system_prompt},
                                    {"role": "user", "content": user_prompt}
                                ]

                                text = _chat_completion(client, model, messages, max_tokens=6000, temperature=0)
                                parsed = _parse_json_from_text(text or '')

                                if parsed:
                                    interest_result = parsed
                                else:
                                    interest_result = None
                                    logging.getLogger('workers.categorization').warning(
                                        'LLM returned invalid JSON for article %s; skipping local heuristic', doc_id)

                            except Exception:
                                interest_result = None
                                logging.getLogger('workers.categorization').exception(
                                    'Error while calling LLM for article %s; skipping local heuristic', doc_id)
                        else:
                            interest_result = None
                            logging.getLogger('workers.categorization').warning(
                                'No LLM client available for article %s; skipping local heuristic', doc_id)

                        total_score = None
                        rating = None
                        short_note = None
                        category_field = None
                        comment_field = None
                        publish_on_site = None
                        publish_on_social = None
                        newsletter_field = None

                        if isinstance(interest_result, dict):
                            total_score = interest_result.get('total_score') or interest_result.get('total')
                            rating = interest_result.get('rating') or interest_result.get('recommendation')
                            short_note = interest_result.get('short_analysis') or interest_result.get('short_note')
                            category_field = interest_result.get('category')
                            comment_field = interest_result.get('comment') or interest_result.get('commentary')

                            publish_on_site = interest_result.get('publish_on_site')
                            publish_on_social = interest_result.get('publish_on_social')
                            newsletter_field = interest_result.get('newsletter')

                        record_end = time.perf_counter()
                        processing_time_ms = int((record_end - record_start) * 1000)

                        status_field = 'CATEGORIZED'
                        try:
                            if total_score is not None:
                                try:
                                    ts_val = float(total_score)
                                except Exception:
                                    ts_val = None
                                if ts_val is not None and ts_val < MIN_ARTICLE_SCORE:
                                    status_field = 'SKIPPED'

                        except Exception:
                            pass

                        update_payload = {
                            'interest': interest_result,
                            'status': status_field,
                            'total_score': total_score,
                            'rating': rating,
                            'short_note': short_note,
                            'category': category_field,
                            'comment': comment_field,
                            'publish_on_site': publish_on_site,
                            'publish_on_social': publish_on_social,
                            'newsletter': newsletter_field,
                            'categorized_at': datetime.now(timezone.utc).isoformat(),
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                        }

                        try:
                            ok = self.pg.save_article_categorization(doc_id, update_payload)
                            if ok:
                                save_status = 'ok'
                                result_line = f"[categorization] ✅ Article {doc_id} categorized"
                                with lock:
                                    chunk_results['processed'] += 1
                            else:
                                err = f"Postgres save returned no rows updated for {doc_id}"
                                save_status = {'error': err}
                                result_line = f"[categorization] ❌ {err}"
                                with lock:
                                    chunk_results['errors'].append(err)
                        except Exception as e:
                            err = f"Save error for {doc_id}: {e}"
                            save_status = {'error': str(e)}
                            result_line = f"[categorization] ❌ {err}"
                            with lock:
                                chunk_results['errors'].append(err)

                        # logging
                        try:
                            log_dir = Path(__file__).parent.parent.parent / 'logs'
                            log_dir.mkdir(parents=True, exist_ok=True)
                            log_file = log_dir / 'categorization.jsonl'
                            log_entry = {
                                'doc_id': doc_id,
                                'input': {
                                    'title': title,
                                    'description': description,
                                    'tags': tags,
                                    'source': source,
                                    'pub_date': pub_date
                                },
                                'interest': interest_result,
                                'save_status': save_status,
                                'processing_time_ms': processing_time_ms,
                                'model': model,
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }
                            with log_file.open('a', encoding='utf-8') as f:
                                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                            try:
                                # Emit a concise machine-readable summary to the logger (console)
                                summary = {
                                    'doc_id': doc_id,
                                    'total_score': total_score,
                                    'rating': rating,
                                    'short_note': short_note,
                                    'processing_time_ms': processing_time_ms,
                                    'save_status': save_status,
                                    'timestamp': datetime.now(timezone.utc).isoformat()
                                }
                                try:
                                    _log = logging.getLogger('workers.categorization')
                                    _log.info(json.dumps(summary, ensure_ascii=False))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        except Exception:
                            pass

                        # Update per-run score buckets (thread-safe)
                        try:
                            ts = None
                            if isinstance(interest_result, dict):
                                ts = interest_result.get('total_score') or interest_result.get('total')
                            # Fall back to update_payload total_score
                            if ts is None:
                                ts = update_payload.get('total_score')
                            if ts is not None:
                                try:
                                    val = float(ts)
                                except Exception:
                                    val = None
                                if val is not None:
                                    with lock:
                                        if val >= 90:
                                            score_buckets['90+'] += 1
                                        elif val >= 80:
                                            score_buckets['80-90'] += 1
                                        elif val >= 70:
                                            score_buckets['70-80'] += 1
                                        elif val >= 60:
                                            score_buckets['60-70'] += 1
                                        else:
                                            score_buckets['<60'] += 1
                        except Exception:
                            pass

                    except Exception as e:
                        err = f"Processing error for doc {getattr(doc, 'id', '?')}: {e}"
                        with lock:
                            chunk_results['errors'].append(err)

                # execute in thread pool
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    futures = [ex.submit(_process_doc, d) for d in docs]
                    for f in as_completed(futures):
                        try:
                            f.result()
                        except Exception as e:
                            # Shouldn't occur because _process_doc captures exceptions, but just in case
                            chunk_results['errors'].append(str(e))

                # aggregate chunk results
                results['processed'] += chunk_results['processed']
                results['errors'].extend(chunk_results['errors'])
                processed_total += chunk_results['processed']

                # If we've processed enough, break early
                if processed_total >= requested_total:
                    break

                try:
                    last_row = docs[-1]
                    # pg.fetch_articles_new returns normalized rows with created_at and id
                    if isinstance(last_row, dict):
                        last_snapshot = {'created_at': last_row.get('created_at'), 'id': last_row.get('id')}
                    else:
                        last_snapshot = last_row
                except Exception:
                    last_snapshot = None

                if len(docs) < limit_for_query:
                    break

            # After successful processing, print detailed score buckets summary
            try:
                print('\n📊 Detailed scoring summary for this run:')
                print(f"   Total processed: {results.get('processed', 0)}")
                print(f"   90+: {score_buckets.get('90+', 0)}")
                print(f"   80-90: {score_buckets.get('80-90', 0)}")
                print(f"   70-80: {score_buckets.get('70-80', 0)}")
                print(f"   60-70: {score_buckets.get('60-70', 0)}")
                print(f"   <60: {score_buckets.get('<60', 0)}")
            except Exception:
                pass

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_statistics(self) -> Dict:
        try:
            conn = self.pg._conn
            cur = conn.cursor()

            def column_exists(col_name: str) -> bool:
                cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='articles' AND column_name=%s)", (col_name,))
                return bool(cur.fetchone()[0])

            stats = {
                'total': 0,
                'urgent': 0,
                'by_priority': {'high': 0, 'medium': 0, 'low': 0},
                'by_category': {},
                'score_buckets': {'90+': 0, '80-90': 0, '70-80': 0, '60-70': 0, '<60': 0}
            }

            # Total
            cur.execute('SELECT COUNT(*) FROM public.articles')
            stats['total'] = int(cur.fetchone()[0] or 0)

            # Urgent
            if column_exists('urgent'):
                cur.execute('SELECT COUNT(*) FROM public.articles WHERE urgent = TRUE')
                stats['urgent'] = int(cur.fetchone()[0] or 0)

            # Priority buckets (if priority_score column exists)
            if column_exists('priority_score'):
                cur.execute("SELECT SUM(CASE WHEN COALESCE(priority_score,0) >= 8 THEN 1 ELSE 0 END), SUM(CASE WHEN COALESCE(priority_score,0) >=5 AND COALESCE(priority_score,0) < 8 THEN 1 ELSE 0 END), SUM(CASE WHEN COALESCE(priority_score,0) < 5 THEN 1 ELSE 0 END) FROM public.articles")
                row = cur.fetchone() or (0, 0, 0)
                stats['by_priority']['high'] = int(row[0] or 0)
                stats['by_priority']['medium'] = int(row[1] or 0)
                stats['by_priority']['low'] = int(row[2] or 0)

            # Categories aggregation
            if column_exists('categories'):
                try:
                    cur.execute("SELECT elem, COUNT(*) FROM public.articles, jsonb_array_elements_text(COALESCE(categories, '[]'::jsonb)) AS elem GROUP BY elem")
                    for cat, cnt in cur.fetchall():
                        stats['by_category'][cat] = int(cnt or 0)
                except Exception:
                    pass

            # Score buckets based on total_score column (fallback to 0 when NULL)
            if column_exists('total_score'):
                cur.execute("SELECT SUM(CASE WHEN total_score >= 90 THEN 1 ELSE 0 END), SUM(CASE WHEN total_score >=80 AND total_score < 90 THEN 1 ELSE 0 END), SUM(CASE WHEN total_score >=70 AND total_score < 80 THEN 1 ELSE 0 END), SUM(CASE WHEN total_score >=60 AND total_score < 70 THEN 1 ELSE 0 END), SUM(CASE WHEN total_score < 60 THEN 1 ELSE 0 END) FROM public.articles WHERE total_score IS NOT NULL")
                row = cur.fetchone() or (0, 0, 0, 0, 0)
                stats['score_buckets']['90+'] = int(row[0] or 0)
                stats['score_buckets']['80-90'] = int(row[1] or 0)
                stats['score_buckets']['70-80'] = int(row[2] or 0)
                stats['score_buckets']['60-70'] = int(row[3] or 0)
                stats['score_buckets']['<60'] = int(row[4] or 0)

            try:
                cur.close()
            except Exception:
                pass

            return stats
        except Exception:
            return {}

    def _process_single_doc(self, doc) -> Dict:
        """
        Process a single normalized row or Firestore-like doc and return a dict with result info.
        This reuses the same logic as the threaded _process_doc but in a single-call form.
        """
        try:
            # Expect normalized row dicts from Postgres
            if isinstance(doc, dict):
                doc_id = doc.get('id')
                data = doc
            else:
                try:
                    doc_id = getattr(doc, 'id', None)
                    data = doc.to_dict() or {}
                except Exception:
                    doc_id = None
                    data = {}

            title = data.get('title', '')
            description = data.get('description', '') or ''
            content = data.get('content', '') or ''
            tags = data.get('tags', []) or data.get('categories', []) or []
            source = data.get('source', '') or data.get('link', '') or ''
            pub_date = data.get('pub_date', '') or ''

            feed_name = data.get('feed_name', '') or data.get('feed', '') or ''
            region_hint = data.get('region_hint', '') or ''
            system_prompt, user_prompt = get_news_filter_prompt(title, description, tags, content, source, pub_date, feed_name=feed_name, region_hint=region_hint)

            client = _get_openai_client()
            model = 'gpt-5-mini'

            interest_result = None
            if client:
                try:
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                    text = _chat_completion(client, model, messages, max_tokens=6000, temperature=0)
                    parsed = _parse_json_from_text(text or '')
                    if parsed:
                        interest_result = parsed
                except Exception:
                    interest_result = None

            total_score = None
            rating = None
            short_note = None
            category_field = None
            comment_field = None
            publish_on_site = None
            publish_on_social = None
            newsletter_field = None

            if isinstance(interest_result, dict):
                total_score = interest_result.get('total_score') or interest_result.get('total')
                rating = interest_result.get('rating') or interest_result.get('recommendation')
                short_note = interest_result.get('short_analysis') or interest_result.get('short_note')
                category_field = interest_result.get('category')
                comment_field = interest_result.get('comment') or interest_result.get('commentary')
                publish_on_site = interest_result.get('publish_on_site')
                publish_on_social = interest_result.get('publish_on_social')
                newsletter_field = interest_result.get('newsletter')

            status_field = 'CATEGORIZED'
            try:
                if total_score is not None:
                    try:
                        ts_val = float(total_score)
                    except Exception:
                        ts_val = None
                    if ts_val is not None and ts_val < MIN_ARTICLE_SCORE:
                        status_field = 'SKIPPED'
            except Exception:
                pass

            update_payload = {
                'interest': interest_result,
                'status': status_field,
                'total_score': total_score,
                'rating': rating,
                'short_note': short_note,
                'category': category_field,
                'comment': comment_field,
                'publish_on_site': publish_on_site,
                'publish_on_social': publish_on_social,
                'newsletter': newsletter_field,
                'categorized_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }

            ok = self.pg.save_article_categorization(doc_id, update_payload)
            return {'doc_id': doc_id, 'ok': ok, 'payload': update_payload}
        except Exception as e:
            return {'doc_id': getattr(doc, 'id', None), 'ok': False, 'error': str(e)}

    def categorize_article_by_id(self, article_id: str) -> Dict:
        try:
            row = self.pg.fetch_article_by_id(article_id)
            if not row:
                return {'status': 'error', 'message': f'Article {article_id} not found'}
            res = self._process_single_doc(row)
            if res.get('ok'):
                return {'status': 'success', 'processed': 1, 'doc_id': article_id}
            else:
                return {'status': 'error', 'message': res.get('error', 'save_failed')}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
