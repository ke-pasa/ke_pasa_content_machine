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
import requests
from telegram import Bot
from .config import PublisherConfig

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
        # Keep token for direct HTTP calls; also create Bot for compatibility if needed
        self.telegram_token = bot_token
        self.telegram_bot = Bot(token=bot_token) if bot_token else None
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

            # Prefer publishing oldest translated high-score article first
            results = self.publish_oldest_translated_high_score()

            # Fallback to batch publishing if nothing found
            if results.get('checked', 0) == 0 and results.get('published', 0) == 0:
                results = self.publish_articles_from_articles_ru()

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

    def _http_send_message(self, chat_id: str, text: str) -> dict:
        """Send a text message via Telegram HTTP API (synchronous). Returns parsed JSON result or raises."""
        if not self.telegram_token:
            raise RuntimeError('No telegram token configured')
        url = f'https://api.telegram.org/bot{self.telegram_token}/sendMessage'
        resp = requests.post(url, json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'})
        j = resp.json()
        if not (resp.status_code == 200 and j.get('ok')):
            raise RuntimeError(f'Telegram sendMessage failed: {j}')
        return j.get('result')

    def _http_send_photo(self, chat_id: str, photo_url: str, caption: str = None) -> dict:
        """Send a photo by URL using Telegram HTTP API. Returns parsed JSON result or raises."""
        if not self.telegram_token:
            raise RuntimeError('No telegram token configured')
        url = f'https://api.telegram.org/bot{self.telegram_token}/sendPhoto'
        payload = {'chat_id': chat_id, 'photo': photo_url}
        if caption:
            payload['caption'] = caption
            payload['parse_mode'] = 'HTML'
        resp = requests.post(url, json=payload)
        j = resp.json()
        if not (resp.status_code == 200 and j.get('ok')):
            raise RuntimeError(f'Telegram sendPhoto failed: {j}')
        return j.get('result')

    def publish_articles_from_articles_ru(self) -> Dict:
        """Publishes up to configured max articles from `articles_ru` collection.

        For each article:
        - If image_url present: send_photo with caption containing text + source
        - Otherwise: sendMessage with text + source
        - Record publication in `telegram_posts` and update article doc with published=True
        """
        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_bot:
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
            # Read a window of recent articles ordered by creation date and filter in Python
            coll = self.db.collection('articles_ru')
            query = coll.order_by('created_at').limit(self.config.max_articles_per_run * 10)
            docs = list(query.stream())

            filtered = []
            for d in docs:
                data = d.to_dict() or {}
                # must be TRANSLATED
                if data.get('status') != 'TRANSLATED':
                    continue
                # skip already published
                if data.get('published_to_telegram'):
                    continue
                # require total_score > 80
                if data.get('total_score', 0) <= 80:
                    continue
                filtered.append(d)
            docs = filtered[: self.config.max_articles_per_run]
        except Exception as e:
            err = f'Firestore query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                title = data.get('title_ru') or data.get('title') or ''
                text = data.get('content_ru') or data.get('description_ru') or ''
                source = data.get('source_name') or data.get('source') or data.get('source_link') or data.get('source_url') or ''
                image = data.get('image_url') or data.get('image') or None

                # Build message: title, text, then source (each separated by blank line)
                msg_lines = []
                if title:
                    msg_lines.append(f"{title}")
                if text:
                    msg_lines.append(text)
                if source:
                    msg_lines.append(f"Источник: {source}")
                message = '\n\n'.join([l for l in msg_lines if l]) or title or 'Новость'

                # Send image first if exists: prefer a single photo message with caption (max ~1024 chars)
                sent_message = None
                if image:
                    try:
                        max_caption = 1024
                        caption = message
                        if len(caption) <= max_caption:
                            # caption fits — send photo with caption
                            sent_message = self._http_send_photo(chat_id, image, caption)
                        else:
                            # caption too long — per request: do NOT send the image; instead send a truncated text message keeping the source link
                            # Determine URL and display text for source
                            data_source_url = data.get('source_url') or data.get('source_link') or (data.get('source') if isinstance(data.get('source'), str) and data.get('source').startswith('http') else None)
                            source_name = data.get('source_name') or (data.get('source') if data.get('source') and not data_source_url else '')

                            # Build HTML-safe content
                            title_html = html.escape(title)
                            text_html = html.escape(text)

                            content_parts = []
                            if title_html:
                                content_parts.append(title_html)
                            if text_html:
                                content_parts.append(text_html)
                            content = '\n\n'.join(content_parts)

                            # Build clickable source HTML if URL available, otherwise plain source text
                            if data_source_url:
                                link_html = f'<a href="{html.escape(data_source_url)}">Источник</a>'
                            elif source_name:
                                link_html = f'Источник: {html.escape(source_name)}'
                            else:
                                link_html = ''

                            # Truncate content so total message <= 2000 chars (safe limit)
                            max_total = 2000
                            total_reserved = len(link_html) + 2 if link_html else 0
                            allowed = max_total - total_reserved
                            if allowed <= 0:
                                truncated = ''
                            else:
                                if len(content) > allowed:
                                    truncated = content[: allowed - 3] + '...'
                                else:
                                    truncated = content

                            message_html = (truncated + '\n\n' + link_html) if link_html else truncated
                            # Send text-only message (HTML)
                            sent_result = self._http_send_message(chat_id, message_html)
                            sent_message = sent_result
                    except Exception as e:
                        print(f"[publisher] ⚠️ Failed to send photo for {article_id}: {e}")
                        # fallback to sending text only (best-effort)
                        try:
                            sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
                        except Exception as e2:
                            print(f"[publisher] ⚠️ Fallback text send failed for {article_id}: {e2}")
                else:
                    sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)

                # Record publication in telegram_posts
                try:
                    post_record = {
                        'article_id': article_id,
                        'telegram_message': sent_message.to_dict() if hasattr(sent_message, 'to_dict') else None,
                        'chat_id': chat_id,
                        'created_at': datetime.utcnow().isoformat(),
                    }
                    self.db.collection('telegram_posts').add(post_record)
                except Exception as e:
                    print(f"[publisher] ⚠️ Failed to record telegram_posts for {article_id}: {e}")

                # Update article doc: mark published_to_telegram True and add published_at
                try:
                    coll.document(doc.id).set({'published_to_telegram': True, 'published_to_telegram_at': datetime.utcnow().isoformat()}, merge=True)
                except Exception as e:
                    print(f"[publisher] ⚠️ Failed to update article doc {doc.id}: {e}")

                results['published'] += 1
                print(f"[publisher] ✅ Published article {article_id} to Telegram")
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

        if not self.telegram_bot:
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
            # Query: status == 'TRANSLATED', order by created_at ascending; filter total_score in Python
            # Pull a window ordered by created_at and filter in Python to avoid index requirements
            query = coll.order_by('created_at').limit(200)
            docs = list(query.stream())
            # Filter: status == TRANSLATED, not published_to_telegram, total_score > 80
            docs = [d for d in docs if (d.to_dict() or {}).get('status') == 'TRANSLATED' and not (d.to_dict() or {}).get('published_to_telegram') and (d.to_dict() or {}).get('total_score', 0) > 80]
            # Keep only the oldest matching doc
            docs = docs[:1]
        except Exception as e:
            err = f'Firestore query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                title = data.get('title_ru') or data.get('title') or ''
                text = data.get('content_ru') or data.get('description_ru') or ''
                source = data.get('source_name') or data.get('source') or data.get('source_link') or data.get('source_url') or ''
                image = data.get('image_url') or data.get('image') or None

                msg_lines = []
                if title:
                    msg_lines.append(f"{title}")
                if text:
                    msg_lines.append(text)
                if source:
                    msg_lines.append(f"Источник: {source}")
                message = '\n\n'.join([l for l in msg_lines if l]) or title or 'Новость'

                sent_message = None
                if image:
                    try:
                        max_caption = 1024
                        caption = message
                        if len(caption) > max_caption:
                            parts = caption.split('\n')
                            if len(parts) > 1:
                                last = parts[-1]
                                front = '\n'.join(parts[:-1])
                                avail = max_caption - len(last) - 3
                                if avail > 0:
                                    front_trunc = (front[:avail] + '...') if len(front) > avail else front
                                    caption = front_trunc + '\n' + last
                                else:
                                    caption = (last[:max_caption-3] + '...')
                            else:
                                caption = caption[:max_caption-3] + '...'

                        sent_message = self._http_send_photo(chat_id, image, caption)
                    except Exception as e:
                        print(f"[publisher] ⚠️ Failed to send photo for {article_id}: {e}")
                        sent_message = self._http_send_message(chat_id, message)
                else:
                    sent_message = self._http_send_message(chat_id, message)

                try:
                    post_record = {
                        'article_id': article_id,
                        'telegram_message': sent_message.to_dict() if hasattr(sent_message, 'to_dict') else None,
                        'chat_id': chat_id,
                        'created_at': datetime.utcnow().isoformat(),
                    }
                    self.db.collection('telegram_posts').add(post_record)
                except Exception as e:
                    print(f"[publisher] ⚠️ Failed to record telegram_posts for {article_id}: {e}")

                try:
                    coll.document(doc.id).set({'published_to_telegram': True, 'published_to_telegram_at': datetime.utcnow().isoformat()}, merge=True)
                except Exception as e:
                    print(f"[publisher] ⚠️ Failed to update article doc {doc.id}: {e}")

                results['published'] += 1
                print(f"[publisher] ✅ Published article {article_id} to Telegram (TRANSLATED/high-score)")
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
