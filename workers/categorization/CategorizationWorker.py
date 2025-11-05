import uuid
import os
import json
from datetime import datetime, timezone
from typing import Dict
import time
from pathlib import Path

from .news_filter_prompt import get_news_filter_prompt, validate_news_interest
from workers.tools.openai_client import parse_json_from_text

# Dynamic resolution helpers: these attempt to use the test-friendly symbols
# exported on workers.categorization.worker (so tests can monkeypatch them).
def _get_firebase_client():
    try:
        import importlib
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'get_firebase_client') and worker_mod.get_firebase_client:
            return worker_mod.get_firebase_client()
    except Exception:
        pass
    # Fallback to canonical tools implementation
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

from daily_prioritization import DailyPrioritization
from .config import CategorizationConfig


class CategorizationWorker:
    """Worker for article prioritization and categorization"""

    def __init__(self, config: CategorizationConfig = None, batch_size: int = None):
        """
        Initialize categorization worker

        Args:
            config: Worker configuration
        """
        self.config = config or CategorizationConfig.from_env()

        if batch_size is not None:
            try:
                self.config.batch_size = int(batch_size)
            except Exception:
                self.config.batch_size = 10
        else:
            self.config.batch_size = 10

        self.db = _get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]

        print(f"[categorization] Starting worker id={self.instance_id}")
        print(f"[categorization] Batch size: {self.config.batch_size}")
        print(f"[categorization] Urgent detection: {self.config.detect_urgent}")
        print(f"[categorization] Urgent threshold: {self.config.urgent_threshold}")

    def update_priorities(self) -> Dict:
        """
        Updates article priorities and categories

        Returns:
            Dictionary with update results
        """

        try:
            print(f"[categorization] 🔄 Updating article priorities...")

            # Create prioritization instance
            prioritization = DailyPrioritization()
            results = prioritization.update_all_article_priorities()

            updated = results.get('updated', 0)
            urgent = results.get('urgent', 0)
            errors = results.get('errors', [])

            print(f"[categorization] ✅ Prioritization completed")
            print(f"[categorization] Updated: {updated} articles")
            print(f"[categorization] Urgent: {urgent} articles")

            if errors:
                print(f"[categorization] ⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    print(f"  • {error}")

            return {
                'status': 'success',
                'updated': updated,
                'urgent': urgent,
                'errors': errors,
                'message': f'Updated {updated} articles, marked {urgent} as urgent',
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

        except Exception as e:
            print(f"[categorization] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }

    def categorize_new_articles(self) -> Dict:
        """
        Process a batch of NEW articles: call OpenAI to evaluate interest and
        update each article's status to CATEGORIZED with interest metadata.

        Returns a summary dict with counts and errors.
        """

        results = {'processed': 0, 'errors': []}

        try:
            # Determine batch size (limit to a sensible default 20)
            batch = min(int(self.config.batch_size), 20)

            # Query oldest articles with status == 'NEW'
            try:
                query = self.db.collection('articles').where('status', '==', 'NEW').order_by('created_at').limit(batch)
                docs = list(query.stream())
            except Exception as e:
                print(f"[categorization] ❌ Firebase query error: {e}")
                return {'status': 'error', 'message': str(e)}

            if not docs:
                print("[categorization] ℹ️ No NEW articles found to categorize")
                return {'status': 'success', 'processed': 0}

            # Always use the canonical model for classification
            model = 'gpt-4o-mini'

            # Initialize shared OpenAI client wrapper
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

                    # Build prompt
                    user_prompt = get_news_filter_prompt(title, description, tags, content, source, pub_date)

                    interest_result = None

                    # start per-record timer
                    record_start = time.perf_counter()

                    # If OpenAI client available, call it via wrapper
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

                            text = _chat_completion(client, model or 'gpt-4o-mini', messages, max_tokens=600, temperature=0)
                            parsed = _parse_json_from_text(text or '')

                            if parsed:
                                interest_result = parsed
                            else:
                                print(f"[categorization] ⚠️ OpenAI returned non-JSON for {doc_id}, using heuristic fallback")
                                interest_result = validate_news_interest({
                                    'title': title,
                                    'description': description,
                                    'content': content,
                                    'tags': tags,
                                    'source': source,
                                    'pub_date': pub_date
                                })

                        except Exception as e:
                            print(f"[categorization] ⚠️ OpenAI request error for {doc_id}: {e}")
                            interest_result = validate_news_interest({
                                'title': title,
                                'description': description,
                                'content': content,
                                'tags': tags,
                                'source': source,
                                'pub_date': pub_date
                            })
                    else:
                        # No OpenAI -> use local heuristic
                        interest_result = validate_news_interest({
                            'title': title,
                            'description': description,
                            'content': content,
                            'tags': tags,
                            'source': source,
                            'pub_date': pub_date
                        })

                    # Prepare update payload
                    # Extract top-level fields from the interest object (safe fallbacks)
                    total_score = None
                    rating = None
                    short_note = None
                    category_field = None
                    comment_field = None

                    if isinstance(interest_result, dict):
                        total_score = interest_result.get('total_score') or interest_result.get('total')
                        rating = interest_result.get('rating') or interest_result.get('recommendation')
                        # short_analysis / short_note are common names in prompts
                        short_note = interest_result.get('short_analysis') or interest_result.get('short_note')
                        category_field = interest_result.get('category')
                        comment_field = interest_result.get('comment') or interest_result.get('commentary')

                    # Compute processing time (ms)
                    record_end = time.perf_counter()
                    processing_time_ms = int((record_end - record_start) * 1000)

                    # Print processing time to console (do not persist in DB)
                    print(f"[categorization] ⏱ Article {doc_id} processing_time_ms={processing_time_ms}")

                    # Prepare update payload (processing_time_ms intentionally NOT included)
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

                    # Save to Firestore (merge)
                    try:
                        self.db.collection('articles').document(doc_id).set(update_payload, merge=True)
                        results['processed'] += 1
                        save_status = 'ok'
                        print(f"[categorization] ✅ Article {doc_id} categorized (score={interest_result.get('total_score')})")
                    except Exception as e:
                        err = f"Firebase save error for {doc_id}: {e}"
                        save_status = {'error': str(e)}
                        print(f"[categorization] ❌ {err}")
                        results['errors'].append(err)

                    # Append verbose JSONL log (input, interest, save result, processing time)
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
                    except Exception as e:
                        print(f"[categorization] ⚠️ Failed to write log for {doc_id}: {e}")

                except Exception as e:
                    err = f"Processing error for doc {getattr(doc, 'id', '?')}: {e}"
                    print(f"[categorization] ❌ {err}")
                    results['errors'].append(err)

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_statistics(self) -> Dict:
        """
        Gets categorization statistics from Firebase
        
        Returns:
            Dictionary with statistics
        """
        try:
            articles = list(self.db.collection('articles').stream())
            
            stats = {
                'total': len(articles),
                'urgent': 0,
                'by_priority': {
                    'high': 0,  # 8-10
                    'medium': 0,  # 5-7
                    'low': 0  # 0-4
                },
                'by_category': {}
            }
            
            for doc in articles:
                data = doc.to_dict() or {}
                
                # Count urgent
                if data.get('urgent', False):
                    stats['urgent'] += 1
                
                # Count by priority
                priority = data.get('priority_score', 0)
                if priority >= 8:
                    stats['by_priority']['high'] += 1
                elif priority >= 5:
                    stats['by_priority']['medium'] += 1
                else:
                    stats['by_priority']['low'] += 1
                
                # Count by categories
                categories = data.get('categories', [])
                for category in categories:
                    stats['by_category'][category] = stats['by_category'].get(category, 0) + 1
            
            return stats
            
        except Exception as e:
            print(f"[categorization] ⚠️  Statistics error: {e}")
            return {}
