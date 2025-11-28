"""
Publisher Worker - handles article publication to Telegram
"""

import sys
import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()

from workers.tools.firebase_client import get_firebase_client
import html
from workers.tools.telegram_helper import send_message, send_photo
from .config import PublisherConfig
from workers.tools import openai_client

class PublisherWorker:
    """Worker for publishing articles to Telegram channels"""
    
    def __init__(self, config: PublisherConfig = None):
        """
        Initialize publisher worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or PublisherConfig.from_env()
        self.db = get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        # Telegram bot token (we'll use HTTP requests for sync sends)
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or None
        if not bot_token:
            print("[publisher] ⚠️ TELEGRAM_BOT_TOKEN not set in environment; publishing will fail until configured")
        # Keep token for helper usage
        self.telegram_token = bot_token
        # Chat id may come from env or from Firebase settings
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID') or None
        
        print(f"[publisher] Starting worker id={self.instance_id}")
        print(f"[publisher] Max articles per run: {self.config.max_articles_per_run}")
        print(f"[publisher] Publication delay: {self.config.publication_delay}s")

    # Locking disabled: run without acquiring Firestore locks

    def publish_articles(self) -> Dict:
        """
        Publishes ready articles to Telegram
        
        Returns:
            Dictionary with publication results
        """
        try:
            print(f"[publisher] 🚀 Starting publication run (articles_ru)...")

            results = self.publish_oldest_translated_high_score()

            target = int(self.config.max_articles_per_run or 1)
            published_so_far = results.get('published', 0)
            if published_so_far < target:
                remaining = target - published_so_far
                batch_results = self.publish_articles_from_articles_ru(max_to_publish=remaining)
                # Merge results
                results['checked'] = (results.get('checked', 0) or 0) + (batch_results.get('checked', 0) or 0)
                results['published'] = (results.get('published', 0) or 0) + (batch_results.get('published', 0) or 0)
                results['errors'] = (results.get('errors', []) or []) + (batch_results.get('errors', []) or [])

            published = results.get('published', 0)
            total_checked = results.get('checked', 0)
            errors = results.get('errors', [])
            
            print(f"[publisher] ✅ Publication completed")
            print(f"[publisher] Published: {published}/{total_checked}")
            
            if errors:
                print(f"[publisher] ⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    print(f"  • {error}")
            
            return {
                'status': 'success',
                'published': published,
                'total_checked': total_checked,
                'errors': errors,
                'message': f'Published {published} out of {total_checked} articles',
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            print(f"[publisher] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            pass

    def _get_chat_id(self) -> str:
        """Resolve telegram chat id from env or Firebase settings"""
        try:
            if self.telegram_chat_id:
                return self.telegram_chat_id
            # Try to get from settings in Firebase
            from workers.tools.firebase_client import get_firebase_client
            client = get_firebase_client()
            settings = client.get_settings()
            return settings.get('telegram_chat_id')
        except Exception:
            return None

    # --- Embedding + dedup helpers ---
    def _compute_embedding(self, text: str):
        """Return embedding vector for text or None on failure/unsupported."""
        try:
            client = openai_client.get_openai_client()
            if client is None or not text:
                return None
            resp = client.embeddings.create(model='text-embedding-3-small', input=[text])
            if getattr(resp, 'data', None) and len(resp.data) > 0:
                return resp.data[0].embedding
        except Exception:
            print(f"[publisher] ⚠️ Embedding compute failed: {text[:60]}")
        return None
    
    def _compute_and_save_embedding_for_doc(self, coll, doc):
        """Compute embedding for candidate article and save it to the document. Returns embedding or None."""
        try:
            data = doc.to_dict() or {}
            # Use only data['telegram_final']['telegram_preview'] as the canonical preview
            final_preview = None
            try:
                final_preview = (data.get('telegram_final') or {}).get('telegram_preview')
            except Exception:
                final_preview = None
            if not final_preview:
                return None

            emb = self._compute_embedding(final_preview)
            if not emb:
                return None

            try:
                coll.document(doc.id).set({'telegram_emb': emb, 'telegram_emb_computed_at': datetime.utcnow().isoformat()}, merge=True)
            except Exception:
                pass
            return emb
        except Exception:
            return None

    def _fetch_recent_published_embeddings(self, coll, days: int):
        """Return list of (doc_id, embedding) for articles published in the last `days` days."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            # Support different casing used in the DB: 'PUBLISHED' and 'published'
            docs = list(coll.where('telegram_emb', '!=', None).stream())
            # Filter locally by status to avoid complex OR queries
            docs = [d for d in docs if ((d.to_dict() or {}).get('status') or '').lower() == 'published']
            out = []
            for d in docs:
                try:
                    data = d.to_dict() or {}
                    ts = data.get('telegram_emb_computed_at')
                    # If timestamp is a string, attempt simple parse; otherwise include
                    include = True
                    if ts:
                        try:
                            # Accept string ISO format
                            if isinstance(ts, str):
                                t = datetime.fromisoformat(ts)
                            else:
                                t = ts
                            if hasattr(t, 'tzinfo') and t.tzinfo is None:
                                # naive -> assume UTC
                                t = t
                            include = (t >= cutoff)
                        except Exception:
                            include = True
                    if include:
                        emb = data.get('telegram_emb')
                        if emb:
                            out.append((d.id, emb))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def _cosine_similarity(self, a, b):
        try:
            import math
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += (float(x) * float(y))
                na += float(x) * float(x)
                nb += float(y) * float(y)
            if na == 0 or nb == 0:
                return 0.0
            return float(dot) / (math.sqrt(na) * math.sqrt(nb))
        except Exception:
            return 0.0

    def _check_duplicate_and_mark(self, coll, doc, candidate_emb) -> bool:
        """Check candidate embedding against recent published embeddings.

        If a duplicate is detected (similarity >= threshold), mark the article
        with status 'DUBLICATED' and return True. Otherwise return False.
        """
        try:
            if not candidate_emb:
                return False
            cfg_days = int(getattr(self.config, 'duplicate_check_days', 3) or 3)
            threshold = float(getattr(self.config, 'similarity_threshold', 0.8))
            recent = self._fetch_recent_published_embeddings(self.db.collection('articles_ru'), cfg_days)
            for rid, emb in recent:
                sim = self._cosine_similarity(candidate_emb, emb)
                if sim >= threshold:
                    # Mark as duplicated
                    try:
                        coll.document(doc.id).set({'status': 'DUBLICATED', 'duplicate_of': rid, 'duplicate_similarity': float(sim)}, merge=True)
                        print(f"[publisher] 🔁 Article {doc.id} marked DUBLICATED (sim={sim:.3f}) against {rid}")
                    except Exception as e:
                        print(f"[publisher] ⚠️ Failed to mark duplicate for {doc.id}: {e}")
                    return True
            return False
        except Exception as e:
            print(f"[publisher] ⚠️ Duplicate check failed for {getattr(doc,'id', '?')}: {e}")
            return False

    def _http_send_message(self, chat_id: str, text: str) -> dict:
        """Send a text message via Telegram (helper). Returns parsed result or raises."""
        return send_message(chat_id, text, token=self.telegram_token)

    def _http_send_photo(self, chat_id: str, photo_url: str, caption: str = None) -> dict:
        """Send a photo by URL using Telegram (helper). Returns parsed result or raises."""
        return send_photo(chat_id, photo_url, caption=caption, token=self.telegram_token)

    # --- Helpers to deduplicate publishing logic ---
    def _build_message(self, data: dict, include_source: bool = True) -> str:
        title = data.get('title_ru') or data.get('title') or ''
        text = data.get('content_ru') or data.get('description_ru') or ''
        source = data.get('source_name') or data.get('source') or data.get('source_link') or data.get('source_url') or ''
        parts = []
        if title:
            parts.append(title)
        if text:
            parts.append(text)
        if include_source and source:
            parts.append(f"Источник: {source}")
        return '\n\n'.join([p for p in parts if p]) or title or 'Новость'

    def _prepare_caption(self, message: str, max_caption: int = 1024) -> str:
        if len(message) <= max_caption:
            return message
        # Try to keep the last line (often source) and truncate the rest
        parts = message.split('\n')
        if len(parts) > 1:
            last = parts[-1]
            front = '\n'.join(parts[:-1])
            avail = max_caption - len(last) - 3
            if avail > 0:
                front_trunc = (front[:avail] + '...') if len(front) > avail else front
                return front_trunc + '\n' + last
            else:
                return last[:max_caption-3] + '...'
        return message[:max_caption-3] + '...'

    def _record_post(self, article_id: str, telegram_result, chat_id: str):
        try:
            post_record = {
                'article_id': article_id,
                'telegram_message': telegram_result.to_dict() if hasattr(telegram_result, 'to_dict') else None,
                'chat_id': chat_id,
                'created_at': datetime.utcnow().isoformat(),
            }
            self.db.collection('telegram_posts').add(post_record)
        except Exception as e:
            print(f"[publisher] ⚠️ Failed to record telegram_posts for {article_id}: {e}")

    def _mark_article_published(self, coll, doc_id: str, sent_message, error_str: str | None = None):
        try:
            update_fields = {
                'status': 'PUBLISHED',
                'published_to_telegram': True if sent_message else False,
                'published_to_telegram_at': datetime.utcnow().isoformat(),
                'telegram_publish_error': error_str,
            }
            coll.document(doc_id).set(update_fields, merge=True)
        except Exception as e:
            print(f"[publisher] ⚠️ Failed to update article doc {doc_id}: {e}")

    def _send_with_fallback(self, chat_id: str, image: str | None, message: str, data: dict) -> tuple:
        """Try to send a photo with caption, fall back to sending text. Returns (result, error_str)."""
        sent_message = None
        doc_error = None
        if image:
            try:
                caption = message
                max_caption = 1024
                if len(caption) > max_caption:
                    caption = self._prepare_caption(caption, max_caption=max_caption)
                sent_message = self._http_send_photo(chat_id, image, caption)
            except Exception as e:
                print(f"[publisher] ⚠️ Failed to send photo: {e}")
                doc_error = str(e)
                try:
                    sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
                except Exception as e2:
                    print(f"[publisher] ⚠️ Fallback text send failed: {e2}")
                    doc_error = f"{doc_error}; fallback_send_error: {e2}" if doc_error else str(e2)
        else:
            try:
                sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
            except Exception as e:
                print(f"[publisher] ⚠️ sendMessage failed: {e}")
                doc_error = str(e)
        return sent_message, doc_error

    def publish_articles_from_articles_ru(self, max_to_publish: int | None = None) -> Dict:
        """Publishes up to `max_to_publish` (or config.max_articles_per_run) articles from `articles_ru` collection.

        When duplicates are encountered, the method continues to try other candidates
        until the desired number of publications is reached or the candidate pool is exhausted.
        """
        if max_to_publish is None:
            max_to_publish = self.config.max_articles_per_run

        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_token:
            err = 'Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        chat_id = self._get_chat_id()
        if not chat_id:
            err = 'Telegram chat id not configured (TELEGRAM_CHAT_ID missing and not in Firebase settings)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        try:
            coll = self.db.collection('articles_ru')
            # Expand initial candidate pool so that if some items are skipped as duplicates
            # we still have extra candidates to try during the same run.
            pool_limit = max(self.config.max_articles_per_run * 10, 50)
            query = coll.where('status', '==', 'TRANSLATED').where('total_score', '>', 80).order_by('created_at').limit(pool_limit)
            docs = list(query.stream())

            filtered = [d for d in docs if not (d.to_dict() or {}).get('published_to_telegram') and (d.to_dict() or {}).get('status') == 'TRANSLATED']

            def _created_key(doc):
                try:
                    v = (doc.to_dict() or {}).get('created_at')
                    if v is None:
                        return ''
                    if hasattr(v, 'isoformat'):
                        return v.isoformat()
                    if hasattr(v, 'seconds'):
                        return str(v.seconds)
                    return str(v)
                except Exception:
                    return ''

            # Sort candidates by creation and keep an expanded candidate list
            docs = sorted(filtered, key=_created_key)[: pool_limit]
        except Exception as e:
            err = f'Firestore query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            # stop if we've already published the requested maximum in this run
            if results['published'] >= max_to_publish:
                break
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                image = data.get('image_url') or data.get('image') or None

                # Use only data['telegram_final']['telegram_preview'] as canonical preview
                final_preview = None
                try:
                    final_preview = (data.get('telegram_final') or {}).get('telegram_preview')
                except Exception:
                    final_preview = None
                if not final_preview:
                    print(f"[publisher] ⚠️ Skipping article {article_id}: missing telegram_final.telegram_preview")
                    continue
                # Before sending, compute embedding and save it to the article document
                try:
                    emb = self._compute_and_save_embedding_for_doc(coll, doc)
                    # If embedding computed, perform deduplication check against recent published
                    try:
                        if emb and self._check_duplicate_and_mark(coll, doc, emb):
                            # Already marked as DUBLICATED in the DB; skip sending and try next candidate
                            continue
                    except Exception:
                        pass
                except Exception:
                    pass

                message = final_preview
                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(coll, doc.id, sent_message, doc_error)

                if sent_message:
                    results['published'] += 1
                    print(f"[publisher] ✅ Published article {article_id} to Telegram")
                    # If we've reached the requested maximum, stop attempting more
                    if results['published'] >= max_to_publish:
                        break
                else:
                    print(f"[publisher] ⚠️ Article {article_id} marked published but Telegram send failed. See 'telegram_publish_error' in doc.")
            except Exception as e:
                err = f"Error publishing doc {getattr(doc, 'id', '?')}: {e}"
                print(f"[publisher] ❌ {err}")
                results['errors'].append(err)

        return results

    def publish_oldest_translated_high_score(self) -> Dict:
        """Find the oldest article in `articles_ru` with status == 'TRANSLATED' and total_score > 80

        Publishes a single article (image first, then text+source) and marks it published.
        """
        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_token:
            err = 'Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        chat_id = self._get_chat_id()
        if not chat_id:
            err = 'Telegram chat id not configured (TELEGRAM_CHAT_ID missing and not in Firebase settings)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        try:
            coll = self.db.collection('articles_ru')
            pool_limit = 200
            query = coll.where('status', '==', 'TRANSLATED').where('total_score', '>', 80).order_by('created_at').limit(pool_limit)
            docs = list(query.stream())

            candidates = [d for d in docs if not (d.to_dict() or {}).get('published_to_telegram') and (d.to_dict() or {}).get('status') == 'TRANSLATED']
            candidates = sorted(candidates, key=lambda d: ((d.to_dict() or {}).get('created_at') and str((d.to_dict() or {}).get('created_at'))) or '')
            # Keep expanded candidate list; we'll try until we publish one or exhaust the list
            docs = candidates
        except Exception as e:
            err = f'Firestore query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            # stop if we've published one (this method intends to publish a single top candidate)
            if results['published'] >= 1:
                break
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                image = data.get('image_url') or data.get('image') or None
                # Use only data['telegram_final']['telegram_preview'] as canonical preview
                final_preview = None
                try:
                    final_preview = (data.get('telegram_final') or {}).get('telegram_preview')
                except Exception:
                    final_preview = None
                if not final_preview:
                    print(f"[publisher] ⚠️ Skipping article {article_id}: missing telegram_final.telegram_preview")
                    continue
                # compute embedding and save it to the article document
                try:
                    emb = self._compute_and_save_embedding_for_doc(coll, doc)
                    try:
                        if emb and self._check_duplicate_and_mark(coll, doc, emb):
                            # marked as duplicate, try next candidate
                            continue
                    except Exception:
                        pass
                except Exception:
                    pass

                message = final_preview
                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(coll, doc.id, sent_message, doc_error)

                if sent_message:
                    results['published'] += 1
                    print(f"[publisher] ✅ Published article {article_id} to Telegram (TRANSLATED/high-score)")
                else:
                    print(f"[publisher] ⚠️ Article {article_id} marked published but Telegram send failed. See 'telegram_publish_error' in doc.")
            except Exception as e:
                err = f"Error publishing doc {getattr(doc, 'id', '?')}: {e}"
                print(f"[publisher] ❌ {err}")
                results['errors'].append(err)

        return results


def main():
    """Entry point for worker execution"""
    print("=" * 60)
    print("📢 Publisher Worker - Telegram Publication Handler")
    print("=" * 60)
    
    try:
        config = PublisherConfig.from_env()

        # Use configuration from environment (no CLI or new env overrides)
        worker = PublisherWorker(config)
        result = worker.publish_articles()
        
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Published: {result.get('published', 0)}")
        print(f"Total checked: {result.get('total_checked', 0)}")
        
        if result.get('errors'):
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors'][:5]:
                print(f"  • {error}")
        
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
