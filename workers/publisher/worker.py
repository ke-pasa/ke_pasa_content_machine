"""
Publisher Worker - handles article publication to Telegram
"""
import sys
import os
import uuid
import json
import logging

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


import html
from workers.tools.telegram_helper import send_message, send_photo
from workers.tools.x_helper import post_tweet
from workers.tools.pg_client import get_pg_client
from .config import PublisherConfig
from workers.tools.constants import MIN_PUBLISH_SCORE
from workers.tools.x_helper import _get_valid_access_token

logger = logging.getLogger(__name__)

class PublisherWorker:
    """Worker for publishing articles to Telegram channels"""
    
    def __init__(self, config: PublisherConfig = None):
        """
        Initialize publisher worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or PublisherConfig.from_env()
        try:
            self.pg = get_pg_client()
        except Exception:
            raise RuntimeError('Postgres client is required for PublisherWorker')

        self.instance_id = str(uuid.uuid4())[:8]
        # Telegram bot token (we'll use HTTP requests for sync sends)
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or None
        if not bot_token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set in environment; publishing will fail until configured")
        # Keep token for helper usage
        self.telegram_token = bot_token
        # Chat id may come from env or from Firebase settings
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID') or None
        
        logger.info(f"Starting worker id={self.instance_id}")
        logger.info(f"Max articles per run: {self.config.max_articles_per_run}")
        logger.info(f"Publication delay: {self.config.publication_delay}s")

    def _is_night_hours(self) -> bool:
        """Check if current time is in night hours (23:00 - 09:00 Madrid time)"""
        try:
            import zoneinfo
            madrid_tz = zoneinfo.ZoneInfo('Europe/Madrid')
        except ImportError:
            # Fallback for Python < 3.9
            from datetime import timezone as tz
            madrid_tz = tz(timedelta(hours=1))  # CET/CEST approximation
        
        now = datetime.now(madrid_tz)
        hour = now.hour
        # Block posting between 23:00 (inclusive) and 09:00 (exclusive)
        return hour >= 23 or hour < 9

    def publish_articles(self) -> Dict:
        """
        Publishes ready articles to Telegram
        
        Returns:
            Dictionary with publication results
        """
        try:
            logger.info(f"🚀 Starting publication run (articles_ru)...")

            # Proactively refresh X token even if no articles to publish (keeps token fresh)
            try:
                _get_valid_access_token()
                logger.info("✓ X token check passed")
            except Exception as e:
                logger.warning(f"⚠️ X token refresh failed: {e} (will retry on actual post)")

            # Check if we're in night hours (23:00 - 09:00 Madrid time)
            if self._is_night_hours():
                logger.info("🌙 Night hours (23:00-09:00) - skipping publication")
                return {
                    'status': 'skipped',
                    'reason': 'night_hours',
                    'published': 0,
                    'total_checked': 0,
                    'errors': [],
                    'message': 'Publication skipped during night hours (23:00-09:00)',
                    'instance_id': self.instance_id,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                }

            target = int(self.config.max_articles_per_run or 1)
            results = self.publish_articles_from_articles_ru(max_to_publish=target)

            published = results.get('published', 0)
            total_checked = results.get('checked', 0)
            errors = results.get('errors', [])
            
            logger.info(f"✅ Publication completed")
            logger.info(f"Published: {published}/{total_checked}")
            
            if errors:
                logger.warning(f"⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    logger.warning(f"  • {error}")
            
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
            logger.critical(f"❌ Critical error: {e}")
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
            # Try to get from settings via PG client helper
            settings = {}
            try:
                settings = self.pg.get_settings() if hasattr(self.pg, 'get_settings') else {}
            except Exception:
                settings = {}
            return settings.get('telegram_chat_id')
        except Exception:
            return None

    # Helper utilities

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

    def _normalize_telegram_preview(self, raw) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            txt = raw.get('tg_preview') or raw.get('text') or raw.get('preview')
        elif isinstance(raw, (bytes, str)):
            txt = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        else:
            txt = str(raw)
        if not txt:
            return None
        txt = txt.replace('\\n', '\n').strip()
        if txt.startswith('(') and txt.endswith(')'):
            inner = txt[1:-1].strip()
            if inner and not inner.endswith('.'):
                txt = inner
        return txt

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
        post_record = {
            'article_id': article_id,
            'telegram_message': telegram_result.to_dict() if hasattr(telegram_result, 'to_dict') else None,
            'chat_id': chat_id,
            'created_at': datetime.now(timezone.utc).isoformat(),
        }

        pg = getattr(self, 'pg', None)
        if not pg:
            raise RuntimeError('Postgres client not available to record telegram post')

        # Record publication flag in articles_ru (no telegram_posts table used)
        conn, pooled = pg._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE id = %s",
                ('PUBLISHED', datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), article_id),
            )
            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                pg._put_conn(conn, pooled)
            except Exception:
                pass

    def _mark_article_published(self, doc_id: str, sent_message, error_str: str | None = None):
        try:
            update_fields = {
                'status': 'PUBLISHED',
                'published_at': datetime.now(timezone.utc).isoformat(),
                'telegram_publish_error': error_str,
            }
            pg = getattr(self, 'pg', None)
            if pg:
                try:
                    conn, pooled = pg._get_conn()
                    cur = conn.cursor()
                    try:
                        # Update basic published fields; x_publish_error is stored in telegram_publish_error column
                        cur.execute("UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE id = %s",
                                    (update_fields['status'], update_fields['published_at'], update_fields['published_at'], doc_id))
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    finally:
                        try:
                            cur.close()
                        except Exception:
                            pass
                        pg._put_conn(conn, pooled)
                except Exception:
                    logger.warning(f"⚠️ Failed to update articles_ru for {doc_id} via Postgres")
        except Exception as e:
            logger.warning(f"⚠️ Failed to update article doc {doc_id}: {e}")

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
                logger.warning(f"⚠️ Failed to send photo: {e}")
                doc_error = str(e)
                try:
                    sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
                except Exception as e2:
                    logger.warning(f"⚠️ Fallback text send failed: {e2}")
                    doc_error = f"{doc_error}; fallback_send_error: {e2}" if doc_error else str(e2)
        else:
            try:
                sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
            except Exception as e:
                logger.warning(f"⚠️ sendMessage failed: {e}")
                doc_error = str(e)
        return sent_message, doc_error

    def _post_to_x(self, message: str, data: dict) -> tuple:
        """Attempt to post to X (twitter) if configured. Returns (result, error_str).

        Always attempts to post to X when the helper is installed. Uses
        credentials from environment or the helper's arguments.
        
        Constructs X post from title_ru and description_ru with link to ke-pasa.es.
        """
        if post_tweet is None:
            return None, 'x_helper_not_installed'

        try:
            # Ensure access token is valid (refresh if needed) before posting
            try:
                _get_valid_access_token()
            except Exception as e:
                logger.warning(f"⚠️ X token refresh failed before publish: {e}")
                return None, f"x_token_refresh_failed:{e}"

            # Build X post: Description\n<URL>
            description = data.get('description_ru') or data.get('content_ru') or ''
            slug = data.get('slug') or data.get('id') or data.get('article_id') or ''

            # Build URL
            article_url = f"https://ke-pasa.es/news/{slug}/" if slug else ""

            # Format: Description\n\n<URL> (one blank line between)
            parts = []
            if description:
                parts.append(description)
            if article_url:
                parts.append(article_url)

            x_text = '\n\n'.join([p for p in parts if p])
            
            # Truncate to 280 chars will happen in post_tweet
            res = post_tweet(x_text)
            return res, None
        except Exception as e:
            logger.warning(f"⚠️ Failed to post to X: {e}")
            return None, str(e)

    def publish_articles_from_articles_ru(self, max_to_publish: int | None = None) -> Dict:
        """Publishes up to `max_to_publish` (or config.max_articles_per_run) articles from `articles_ru` collection."""
        if max_to_publish is None:
            max_to_publish = self.config.max_articles_per_run

        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_token:
            err = 'Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)'
            logger.error(f"❌ {err}")
            results['errors'].append(err)
            return results

        chat_id = self._get_chat_id()
        if not chat_id:
            err = 'Telegram chat id not configured (TELEGRAM_CHAT_ID missing and not in Firebase settings)'
            logger.error(f"❌ {err}")
            results['errors'].append(err)
            return results

        try:
            # Prefer Postgres for articles_ru queries

            pg = get_pg_client()

            pool_limit = max(self.config.max_articles_per_run * 10, 50)

            # Fetch candidates: high score first
            rows = pg.fetch_translated_for_publish(limit=pool_limit, min_score=MIN_PUBLISH_SCORE)
            
            docs = []
            for r in rows:
                # Ensure we have an ID
                if not r.get('id') and r.get('article_id'):
                    r['id'] = r['article_id']
                docs.append(r)

            # Safety filter (DB query should have covered this, but good to double check)
            filtered = [d for d in docs if d.get('status') == 'TRANSLATED']

            # Sort by creation date (oldest first) to avoid starving older high-quality news
            def _get_created_at(d):
                v = d.get('created_at')
                if v is None:
                    return datetime.max.replace(tzinfo=timezone.utc)
                if isinstance(v, str):
                    try:
                        return datetime.fromisoformat(v)
                    except ValueError:
                        pass
                if isinstance(v, datetime):
                    return v
                return datetime.max.replace(tzinfo=timezone.utc)

            candidates = sorted(filtered, key=_get_created_at)[:pool_limit]
            
        except Exception as e:
            err = f'Database query error: {e}'
            logger.error(f"❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(candidates)

        for data in candidates:
            # stop if we've already published the requested maximum in this run
            if results['published'] >= max_to_publish:
                break
            
            article_id = data.get('id')
            doc_id = article_id # Use same ID for logging
            
            try:
                image = data.get('image_url') or data.get('image') or None

                # Use raw data['telegram_final'] as the message source
                raw_preview = data.get('telegram_final')
                final_preview = self._normalize_telegram_preview(raw_preview)
                
                if not final_preview or not final_preview.strip():
                    logger.error(f"❌ Article {article_id} has empty telegram_final")
                    results['errors'].append(f"empty_telegram_final:{article_id}")
                    continue

                class DocShim:
                    def __init__(self, d): self.d = d; self.id = d.get('id')
                    def to_dict(self): return self.d

                doc_obj = DocShim(data)

                message = final_preview
                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(article_id, sent_message, doc_error)

                # Attempt to post to X (twitter) if enabled
                try:
                    x_res, x_err = self._post_to_x(message, data)
                    logger.debug(f"X post attempt result: res={x_res} err={x_err}")
                    if x_err:
                        # Append X error to telegram_publish_error field via direct DB update
                        try:
                            conn, pooled = pg._get_conn()
                            cur = conn.cursor()
                            try:
                                cur.execute("UPDATE public.articles_ru SET telegram_publish_error = %s, updated_at = %s WHERE id = %s",
                                            (x_err, datetime.now(timezone.utc).isoformat(), article_id))
                                conn.commit()
                            finally:
                                try:
                                    cur.close()
                                except Exception:
                                    pass
                                pg._put_conn(conn, pooled)
                        except Exception:
                            logger.warning(f"⚠️ Failed to record X error for {article_id}")

                except Exception as e:
                    logger.warning(f"⚠️ Unexpected error while posting to X: {e}")

                if sent_message:
                    results['published'] += 1
                    logger.info(f"✅ Published article {article_id} to Telegram")
                else:
                    logger.warning(f"⚠️ Article {article_id} marked published but Telegram send failed. See 'telegram_publish_error' in doc.")
            except Exception as e:
                err = f"Error publishing doc {doc_id}: {e}"
                logger.error(f"❌ {err}")
                results['errors'].append(err)

        return results


def main():
    """Entry point for worker execution"""
    # Configure logging (verbose for debugging X posts)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger('workers.publisher')

    logger.info("=" * 60)
    logger.info("📢 Publisher Worker - Telegram Publication Handler")
    logger.info("=" * 60)
    
    try:
        config = PublisherConfig.from_env()

        # Use configuration from environment (no CLI or new env overrides)
        worker = PublisherWorker(config)
        result = worker.publish_articles()
        

        logger.info("\n" + "=" * 60)
        logger.info("📊 RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {result['status']}")
        logger.info(f"Published: {result.get('published', 0)}")
        logger.info(f"Total checked: {result.get('total_checked', 0)}")
        
        if result.get('errors'):
            logger.info(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors'][:5]:
                logger.info(f"  • {error}")
        
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
