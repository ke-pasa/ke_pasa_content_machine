import uuid
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict

from .news_filter_prompt import get_news_filter_prompt, validate_news_interest
from workers.tools.openai_client import parse_json_from_text


# Helpers that prefer test-time monkeypatching via the thin worker module.
def _get_firebase_client():
    try:
        import importlib
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'get_firebase_client') and worker_mod.get_firebase_client:
            return worker_mod.get_firebase_client()
    except Exception:
        pass
    from workers.tools.firebase_client import get_firebase_client as _gf
    return _gf()


def _get_openai_client():
    try:
        import importlib
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'get_openai_client'):
            return worker_mod.get_openai_client()
    except Exception:
        pass
    from workers.tools.openai_client import get_openai_client as _go
    return _go()


def _chat_completion(client, model, messages, max_tokens=600, temperature=0):
    try:
        import importlib
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'chat_completion'):
            return worker_mod.chat_completion(client, model, messages, max_tokens=max_tokens, temperature=temperature)
    except Exception:
        pass
    from workers.tools.openai_client import chat_completion as _cc
    return _cc(client, model, messages, max_tokens=max_tokens, temperature=temperature)


def _parse_json_from_text(text: str):
    try:
        import importlib
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    except Exception:
        pass
    return parse_json_from_text(text)


from .config import CategorizationConfig


class CategorizationWorker:
    """Categorization worker with paginated reads from Firestore."""

    def __init__(self, config: CategorizationConfig = None, batch_size: int = None):
        self.config = config or CategorizationConfig.from_env()

        if batch_size is not None:
            try:
                self.config.batch_size = int(batch_size)
            except Exception:
                self.config.batch_size = 10
        else:
            self.config.batch_size = int(getattr(self.config, 'batch_size', 10) or 10)

        self.db = _get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]

    def categorize_new_articles(self) -> Dict:
        results = {'processed': 0, 'errors': []}

        try:
            requested_total = int(self.config.batch_size)
            if requested_total <= 0:
                return {'status': 'success', 'processed': 0}

            chunk_size = 20
            processed_total = 0
            last_snapshot = None

            while processed_total < requested_total:
                limit_for_query = min(chunk_size, requested_total - processed_total)

                try:
                    query = self.db.collection('articles').where('status', '==', 'NEW').order_by('created_at').limit(limit_for_query)
                    if last_snapshot is not None:
                        try:
                            query = query.start_after(last_snapshot)
                        except Exception:
                            # fake DBs used in tests may not support start_after
                            pass

                    docs = list(query.stream())
                except Exception as e:
                    return {'status': 'error', 'message': str(e)}

                if not docs:
                    break

                model = 'gpt-4o-mini'
                client = _get_openai_client()

                for doc in docs:
                    try:
                        doc_id = doc.id
                        data = doc.to_dict() or {}
                        title = data.get('title', '')
                        description = data.get('description', '') or ''
                        content = data.get('content', '') or ''
                        tags = data.get('tags', []) or []
                        source = data.get('source', '') or ''
                        pub_date = data.get('pub_date', '') or ''

                        user_prompt = get_news_filter_prompt(title, description, tags, content, source, pub_date)

                        interest_result = None
                        record_start = time.perf_counter()

                        if client:
                            try:
                                system_msg = (
                                    "Ты эксперт. Верни JSON с полями: total_score (0-100), "
                                    "recommendation (ПУБЛИКОВАТЬ/КРАТКАЯ ЗАМЕТКА/НЕ ПУБЛИКОВАТЬ), "
                                    "short_analysis (короткое обоснование). Только JSON, без лишних комментариев."
                                )
                                messages = [
                                    {"role": "system", "content": system_msg},
                                    {"role": "user", "content": user_prompt}
                                ]

                                text = _chat_completion(client, model, messages, max_tokens=600, temperature=0)
                                parsed = _parse_json_from_text(text or '')

                                if parsed:
                                    interest_result = parsed
                                else:
                                    interest_result = validate_news_interest({
                                        'title': title,
                                        'description': description,
                                        'content': content,
                                        'tags': tags,
                                        'source': source,
                                        'pub_date': pub_date
                                    })

                            except Exception:
                                interest_result = validate_news_interest({
                                    'title': title,
                                    'description': description,
                                    'content': content,
                                    'tags': tags,
                                    'source': source,
                                    'pub_date': pub_date
                                })
                        else:
                            interest_result = validate_news_interest({
                                'title': title,
                                'description': description,
                                'content': content,
                                'tags': tags,
                                'source': source,
                                'pub_date': pub_date
                            })

                        # extract fields
                        total_score = None
                        rating = None
                        short_note = None
                        category_field = None
                        comment_field = None

                        if isinstance(interest_result, dict):
                            total_score = interest_result.get('total_score') or interest_result.get('total')
                            rating = interest_result.get('rating') or interest_result.get('recommendation')
                            short_note = interest_result.get('short_analysis') or interest_result.get('short_note')
                            category_field = interest_result.get('category')
                            comment_field = interest_result.get('comment') or interest_result.get('commentary')

                        record_end = time.perf_counter()
                        processing_time_ms = int((record_end - record_start) * 1000)

                        update_payload = {
                            'interest': interest_result,
                            'status': 'CATEGORIZED',
                            'total_score': total_score,
                            'rating': rating,
                            'short_note': short_note,
                            'category': category_field,
                            'comment': comment_field,
                            'categorized_at': datetime.now(timezone.utc).isoformat(),
                            'updated_at': datetime.now(timezone.utc).isoformat()
                        }

                        try:
                            self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
                            results['processed'] += 1
                            processed_total += 1
                            save_status = 'ok'
                            result_line = f"[categorization] ✅ Article {doc_id} categorized"
                        except Exception as e:
                            err = f"Firebase save error for {doc_id}: {e}"
                            save_status = {'error': str(e)}
                            result_line = f"[categorization] ❌ {err}"
                            results['errors'].append(err)

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
                                result_log = log_dir / 'categorization_results.log'
                                with result_log.open('a', encoding='utf-8') as rf:
                                    rf.write(result_line + '\n')
                            except Exception:
                                pass
                        except Exception:
                            pass

                    except Exception as e:
                        err = f"Processing error for doc {getattr(doc, 'id', '?')}: {e}"
                        results['errors'].append(err)

                try:
                    last_snapshot = docs[-1]
                except Exception:
                    last_snapshot = None

                if len(docs) < limit_for_query:
                    break

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_statistics(self) -> Dict:
        try:
            articles = list(self.db.collection('articles').stream())

            stats = {
                'total': len(articles),
                'urgent': 0,
                'by_priority': {'high': 0, 'medium': 0, 'low': 0},
                'by_category': {}
            }

            for doc in articles:
                data = doc.to_dict() or {}
                if data.get('urgent', False):
                    stats['urgent'] += 1
                priority = data.get('priority_score', 0)
                if priority >= 8:
                    stats['by_priority']['high'] += 1
                elif priority >= 5:
                    stats['by_priority']['medium'] += 1
                else:
                    stats['by_priority']['low'] += 1
                for category in data.get('categories', []):
                    stats['by_category'][category] = stats['by_category'].get(category, 0) + 1

            return stats

        except Exception:
            return {}
