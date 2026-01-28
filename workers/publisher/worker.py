"""
Publisher Worker - handles article publication to Telegram
"""
import sys
import os
import uuid
import json
import logging
import re

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))


import html
from workers.tools.telegram_helper import send_message, send_photo
from workers.tools.x_helper import post_tweet
from workers.tools.instagram_helper import post_instagram
from workers.tools.facebook_helper import post_facebook
from workers.tools.threads_helper import post_threads
from workers.tools.pg_client import get_pg_client
from .config import PublisherConfig
from workers.tools.audio_generator import generate_audio_for_article
from workers.tools.video_generator import generate_video_for_article, cleanup_temp_video
from workers.tools.azure_storage_helper import AzureStorageUploader, cleanup_local_video
from workers.tools.pexels_helper import PexelsHelper
from workers.tools.video_generator import VideoGenerator
from workers.tools.audio_generator import AudioGenerator
from workers.tools.constants import MIN_PUBLISH_SCORE
from workers.tools.x_helper import _get_valid_access_token

logger = logging.getLogger(__name__)

class PublisherWorker:
    """Worker for publishing articles to Telegram channels"""
    
    def __init__(self, config: PublisherConfig = None, video_only_mode: bool = False):
        """
        Initialize publisher worker
        
        Args:
            config: Worker configuration
            video_only_mode: If True, only generate videos without publishing
        """
        self.config = config or PublisherConfig.from_env()
        self.video_only_mode = video_only_mode
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
            now = datetime.now(madrid_tz)
        except (ImportError, Exception):
            # Fallback for Python < 3.9 or missing timezone data
            from datetime import timezone as tz
            madrid_tz = tz(timedelta(hours=1))  # CET approximation
            now = datetime.now(madrid_tz)
        
        hour = now.hour
        # Block posting between 23:00 (inclusive) and 09:00 (exclusive)
        return hour >= 23 or hour < 9

    def _html_to_plain_text(self, html_text: str, keep_links: bool = False) -> str:
        """Convert HTML tags to plain text for Facebook/Instagram.
        
        Telegram uses HTML tags like <b>, <i>, <a href="">, etc.
        Facebook and Instagram only support plain text without formatting.
        
        Args:
            html_text: HTML text to convert
            keep_links: Not used - kept for compatibility
        """
        if not html_text:
            return html_text
        
        text = html_text
        
        # Remove link tags completely (we'll add article link separately)
        text = re.sub(r'<a[^>]*>([^<]+)</a>', r'\1', text)
        
        # Remove bold tags - just keep the text (Facebook doesn't support bold in posts)
        text = re.sub(r'<b>([^<]+)</b>', r'\1', text)
        text = re.sub(r'<strong>([^<]+)</strong>', r'\1', text)
        
        # Remove italic tags - just keep the text
        text = re.sub(r'<i>([^<]+)</i>', r'\1', text)
        text = re.sub(r'<em>([^<]+)</em>', r'\1', text)
        
        # Remove any remaining HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Decode HTML entities
        text = html.unescape(text)
        
        return text

    def check_integrations_health(self) -> Dict:
        """
        Check health of all social media integrations
        
        Returns:
            Dictionary with health status for each platform
        """
        logger.info("=" * 60)
        logger.info("🏥 Starting Integrations Health Check")
        logger.info("=" * 60)
        
        health_status = {
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'overall_status': 'healthy',
            'platforms': {}
        }
        
        # Check Telegram
        logger.info("\n📱 Checking Telegram...")
        try:
            if not self.telegram_token:
                raise ValueError("TELEGRAM_BOT_TOKEN not configured")
            
            chat_id = self._get_chat_id()
            if not chat_id:
                raise ValueError("TELEGRAM_CHAT_ID not configured")
            
            # Test API call
            import requests
            url = f"https://api.telegram.org/bot{self.telegram_token}/getMe"
            response = requests.get(url, timeout=10)
            
            if response.status_code == 200:
                bot_info = response.json().get('result', {})
                health_status['platforms']['telegram'] = {
                    'status': 'healthy',
                    'bot_username': bot_info.get('username'),
                    'bot_id': bot_info.get('id'),
                    'chat_id': chat_id
                }
                logger.info(f"✅ Telegram: OK (bot: @{bot_info.get('username')})")
            else:
                raise Exception(f"API returned {response.status_code}")
                
        except Exception as e:
            health_status['platforms']['telegram'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ Telegram: FAILED - {e}")
        
        # Check X (Twitter)
        logger.info("\n𝕏 Checking X (Twitter)...")
        try:
            if post_tweet is None:
                raise ValueError("X helper not installed")
            
            # Try to get valid access token - this will attempt refresh if needed
            try:
                token = _get_valid_access_token()
            except Exception as token_error:
                # If token refresh failed, it's unhealthy
                raise Exception(f"Token validation/refresh failed: {token_error}")
            
            if not token:
                raise Exception("No valid access token available")
            
            # Actually test the token by making a real API call
            import requests
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            # Use /users/me endpoint to verify token works
            response = requests.get('https://api.twitter.com/2/users/me', headers=headers, timeout=10)
            
            if response.status_code == 200:
                user_data = response.json().get('data', {})
                health_status['platforms']['x'] = {
                    'status': 'healthy',
                    'has_token': True,
                    'username': user_data.get('username'),
                    'user_id': user_data.get('id')
                }
                logger.info(f"✅ X (Twitter): OK (user: @{user_data.get('username')})")
            else:
                raise Exception(f"API test failed: {response.status_code} - {response.text[:200]}")
                
        except Exception as e:
            health_status['platforms']['x'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ X (Twitter): FAILED - {e}")
        
        # Check Instagram
        logger.info("\n🟣 Checking Instagram...")
        try:
            if post_instagram is None:
                raise ValueError("Instagram helper not installed")
            
            access_token = os.getenv('INSTAGRAM_ACCESS_TOKEN')
            user_id = os.getenv('INSTAGRAM_USER_ID')
            
            if not access_token or not user_id:
                raise ValueError("INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_USER_ID not configured")
            
            # Test API call
            import requests
            url = f"https://graph.facebook.com/v18.0/{user_id}"
            params = {'fields': 'username', 'access_token': access_token}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                user_info = response.json()
                health_status['platforms']['instagram'] = {
                    'status': 'healthy',
                    'username': user_info.get('username'),
                    'user_id': user_id
                }
                logger.info(f"✅ Instagram: OK (user: @{user_info.get('username')})")
            else:
                raise Exception(f"API returned {response.status_code}: {response.text}")
                
        except Exception as e:
            health_status['platforms']['instagram'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ Instagram: FAILED - {e}")
        
        # Check Facebook
        logger.info("\n🔵 Checking Facebook...")
        try:
            if post_facebook is None:
                raise ValueError("Facebook helper not installed")
            
            access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
            page_id = os.getenv('FACEBOOK_PAGE_ID')
            
            if not access_token or not page_id:
                raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN or FACEBOOK_PAGE_ID not configured")
            
            # Test API call
            import requests
            url = f"https://graph.facebook.com/v18.0/{page_id}"
            params = {'fields': 'name,access_token', 'access_token': access_token}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                page_info = response.json()
                health_status['platforms']['facebook'] = {
                    'status': 'healthy',
                    'page_name': page_info.get('name'),
                    'page_id': page_id
                }
                logger.info(f"✅ Facebook: OK (page: {page_info.get('name')})")
            else:
                raise Exception(f"API returned {response.status_code}: {response.text}")
                
        except Exception as e:
            health_status['platforms']['facebook'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ Facebook: FAILED - {e}")
        
        # Check Threads
        logger.info("\n🧵 Checking Threads...")
        try:
            if post_threads is None:
                raise ValueError("Threads helper not installed")
            
            # Threads uses Facebook credentials
            app_id = os.getenv('FACEBOOK_APP_ID')
            user_id = os.getenv('INSTAGRAM_USER_ID')
            access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
            
            if not app_id:
                raise ValueError("FACEBOOK_APP_ID not configured (required for Threads)")
            if not user_id:
                raise ValueError("INSTAGRAM_USER_ID not configured (required for Threads)")
            if not access_token:
                raise ValueError("FACEBOOK_PAGE_ACCESS_TOKEN not configured (required for Threads)")
            
            # Test API call - get user profile
            import requests
            url = f"https://graph.threads.net/v1.0/{user_id}"
            params = {'fields': 'username,threads_profile_picture_url', 'access_token': access_token}
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                user_info = response.json()
                health_status['platforms']['threads'] = {
                    'status': 'healthy',
                    'username': user_info.get('username'),
                    'user_id': user_id,
                    'note': 'Uses Facebook credentials'
                }
                logger.info(f"✅ Threads: OK (user: @{user_info.get('username')}, using Facebook credentials)")
            else:
                raise Exception(f"API returned {response.status_code}: {response.text}")
                
        except Exception as e:
            health_status['platforms']['threads'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ Threads: FAILED - {e}")
        
        # Check Database
        logger.info("\n🗄️ Checking Database (PostgreSQL)...")
        try:
            pg = getattr(self, 'pg', None)
            if not pg:
                raise ValueError("Postgres client not available")
            
            # Test query
            conn, pooled = pg._get_conn()
            cur = conn.cursor()
            try:
                cur.execute("SELECT COUNT(*) FROM public.articles_ru WHERE status = 'TRANSLATED'")
                count = cur.fetchone()[0]
                health_status['platforms']['database'] = {
                    'status': 'healthy',
                    'translated_articles': count
                }
                logger.info(f"✅ Database: OK ({count} articles ready to publish)")
            finally:
                cur.close()
                pg._put_conn(conn, pooled)
                
        except Exception as e:
            health_status['platforms']['database'] = {
                'status': 'unhealthy',
                'error': str(e)
            }
            health_status['overall_status'] = 'degraded'
            logger.error(f"❌ Database: FAILED - {e}")
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.info("📊 HEALTH CHECK SUMMARY")
        logger.info("=" * 60)
        
        healthy = sum(1 for p in health_status['platforms'].values() if p['status'] == 'healthy')
        total = len(health_status['platforms'])
        
        logger.info(f"Overall Status: {health_status['overall_status'].upper()}")
        logger.info(f"Healthy Platforms: {healthy}/{total}")
        
        for platform, status in health_status['platforms'].items():
            status_icon = "✅" if status['status'] == 'healthy' else "❌"
            logger.info(f"  {status_icon} {platform.capitalize()}: {status['status']}")
        
        return health_status

    def publish_articles(self, force: bool = False) -> Dict:
        """
        Publishes ready articles to Telegram
        
        Args:
            force: If True, skip night hours check and publish anyway
        
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
            if not force and self._is_night_hours():
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
            
            if force and self._is_night_hours():
                logger.info("⚠️ FORCE mode: Publishing during night hours")

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

    def _generate_social_video(self, article_id: str, script_text: str, title: str) -> tuple:
        """Generate video for social media posting (shared logic for Instagram and Facebook)
        
        Returns: (success: bool, video_path: str, public_url: str, error_msg: str)
        """
        try:
            video_generator = VideoGenerator()
            audio_generator = AudioGenerator()
            pexels_helper = PexelsHelper()
            
            # Get 3 videos from Pexels
            video_urls = pexels_helper.get_videos_for_script(script_text, count=3)
            if len(video_urls) < 3:
                return False, None, None, f"Only found {len(video_urls)} videos"
            
            # Generate audio
            import tempfile
            with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as audio_temp:
                success, error_msg = audio_generator.generate_audio(script_text, audio_temp.name)
                if not success:
                    return False, None, None, f"Audio generation failed: {error_msg}"
                
                audio_duration = audio_generator.get_audio_duration_estimate(script_text)
                
                # Generate video with title overlay
                videos_dir = os.path.join(os.getcwd(), "generated_videos")
                os.makedirs(videos_dir, exist_ok=True)
                video_output_path = os.path.join(videos_dir, f"{article_id}_social.mp4")
                
                try:
                    success, error_msg = video_generator.generate_video_with_multiple_videos(
                        video_urls=video_urls,
                        audio_path=audio_temp.name,
                        output_path=video_output_path,
                        audio_duration=audio_duration,
                        title=title
                    )
                    
                    if not success:
                        return False, None, None, f"Video generation failed: {error_msg}"
                    
                    logger.info(f"🎬 Video generated: {video_output_path}")
                    
                    # Upload video to Azure Storage for public access
                    uploader = AzureStorageUploader()
                    public_video_url = uploader.upload_video(video_output_path, f"{article_id}_social.mp4")
                    
                    if not public_video_url:
                        return False, video_output_path, None, "Azure Storage upload failed"
                    
                    return True, video_output_path, public_video_url, None
                    
                finally:
                    # Cleanup temporary audio file
                    try:
                        audio_temp.close()
                        os.unlink(audio_temp.name)
                    except:
                        pass
                        
        except Exception as e:
            return False, None, None, str(e)
    
    def _post_to_instagram(self, message: str, data: dict) -> tuple:
        """Attempt to post to Instagram if configured. Returns (result, error_str).
        
        For high-score articles (>95), generates and posts video instead of image.
        For regular articles, posts image with caption to Instagram Business/Creator account.
        """
        if post_instagram is None:
            return None, 'instagram_helper_not_installed'

        try:
            # Check if this is a high-score article for video generation
            total_score = data.get('total_score', 0)
            script_text = data.get('script', '').strip()
            
            if total_score > 95 and script_text:
                logger.info(f"🎬 High-score article ({total_score}) - generating video for Instagram")
                article_id = data.get('id')
                title = data.get('title_ru', '')
                
                success, video_path, public_url, error_msg = self._generate_social_video(article_id, script_text, title)
                
                if success:
                    caption = self._html_to_plain_text(message)
                    caption = f"🎬 {caption}\n\nПодробности по ссылке в профиле @kepasa.es"
                    
                    try:
                        res = post_instagram(public_url, caption, media_type='VIDEO')
                        logger.info(f"🎬🟣 Instagram video post successful: {res.get('id')}")
                        
                        # Auto-cleanup: Delete video from Azure Storage after successful posting
                        self._cleanup_azure_video(public_url, article_id)
                        
                        return res, None
                    except Exception as e:
                        logger.warning(f"⚠️ Video posting failed: {e}, falling back to image")
                        return self._fallback_to_image_instagram(message, data, video_generated=True)
                else:
                    logger.warning(f"⚠️ {error_msg}, falling back to image")
                    return self._fallback_to_image_instagram(message, data)
            
            # Standard image posting for regular articles
            image_url = data.get('image_url') or data.get('image')
            if not image_url:
                logger.warning(f"⚠️ No image_url for Instagram post")
                return None, 'no_image_url'

            # Convert HTML to plain text for Instagram
            caption = self._html_to_plain_text(message)
            
            # Instagram doesn't support clickable links in posts
            caption = f"{caption}\n\nПодробности по ссылке в профиле @kepasa.es"

            # Post to Instagram
            res = post_instagram(image_url, caption)
            logger.info(f"🟣 Instagram post successful: {res.get('id')}")
            return res, None
        except Exception as e:
            logger.warning(f"⚠️ Failed to post to Instagram: {e}")
            return None, str(e)

    def _cleanup_azure_video(self, public_url: str, article_id: str) -> None:
        """Delete video from Azure Storage after successful posting.
        
        Args:
            public_url: The public Azure Storage URL of the video
            article_id: Article ID for logging purposes
        """
        try:
            # Extract blob name from public URL
            # Format: https://{account}.blob.core.windows.net/{container}/{blob_name}
            if not public_url or 'blob.core.windows.net' not in public_url:
                return
            
            blob_name = public_url.split('/')[-1]
            
            # Delete from Azure Storage
            uploader = AzureStorageUploader()
            if uploader.delete_video(blob_name):
                logger.info(f"🧹 Cleaned up Azure video for article {article_id}: {blob_name}")
            else:
                logger.warning(f"⚠️ Failed to cleanup Azure video: {blob_name}")
                
        except Exception as e:
            logger.warning(f"⚠️ Error during Azure cleanup for {article_id}: {e}")
    
    def _fallback_to_image_instagram(self, message: str, data: dict, video_generated: bool = False) -> tuple:
        """Fallback to regular image posting for Instagram"""
        try:
            image_url = data.get('image_url') or data.get('image')
            if not image_url:
                return None, 'no_image_url'

            # Convert HTML to plain text for Instagram
            caption = self._html_to_plain_text(message)
            
            # Add video indicator if video was generated
            if video_generated:
                caption = f"🎬 {caption}\n\nВидео доступно на нашем канале!"
            
            caption = f"{caption}\n\nПодробности по ссылке в профиле @kepasa.es"

            # Post to Instagram
            res = post_instagram(image_url, caption)
            logger.info(f"🟣 Instagram image post successful: {res.get('id')}")
            return res, None
        except Exception as e:
            return None, str(e)

    def _post_to_facebook(self, message: str, data: dict) -> tuple:
        """Attempt to post to Facebook Page if configured. Returns (result, error_str).
        
        For high-score articles (>95), generates and posts video instead of image.
        For regular articles, posts image with message to Facebook Page.
        """
        if post_facebook is None:
            return None, 'facebook_helper_not_installed'

        try:
            # Check if this is a high-score article for video generation
            total_score = data.get('total_score', 0)
            script_text = data.get('script', '').strip()
            
            if total_score > 95 and script_text:
                logger.info(f"🎬 High-score article ({total_score}) - generating video for Facebook")
                article_id = data.get('id')
                title = data.get('title_ru', '')
                
                # Check if video already exists from Instagram posting
                videos_dir = os.path.join(os.getcwd(), "generated_videos")
                video_output_path = os.path.join(videos_dir, f"{article_id}_social.mp4")
                
                if os.path.exists(video_output_path):
                    logger.info(f"🔄 Reusing existing video for Facebook: {video_output_path}")
                    success, video_path, public_url = True, video_output_path, None
                else:
                    success, video_path, public_url, error_msg = self._generate_social_video(article_id, script_text, title)
                    
                    if not success:
                        logger.warning(f"⚠️ {error_msg}, falling back to image")
                        return self._fallback_to_image_facebook(message, data)
                
                # Post video to Facebook using local file path
                post_message = self._html_to_plain_text(message)
                post_message = f"🎬 {post_message}\n\nНаш тг канал: https://t.me/spain_kepasa"
                
                try:
                    res = post_facebook(video_path, post_message, media_type='VIDEO')
                    logger.info(f"🎬🔵 Facebook video post successful: {res.get('post_id')}")
                    
                    # Cleanup local video after both platforms posted
                    cleanup_local_video(video_path)
                    
                    return res, None
                except Exception as e:
                    logger.warning(f"⚠️ Video posting failed: {e}, falling back to image")
                    return self._fallback_to_image_facebook(message, data, video_generated=True)
            
            # Standard image posting for regular articles
            image_url = data.get('image_url') or data.get('image')
            if not image_url:
                logger.warning(f"⚠️ No image_url for Facebook post")
                return None, 'no_image_url'

            # Convert HTML to Facebook-friendly text
            post_message = self._html_to_plain_text(message)
            
            # Add social media links
            post_message = f"{post_message}\n\nНаш тг канал: https://t.me/spain_kepasa"

            # Post to Facebook
            res = post_facebook(image_url, post_message)
            logger.info(f"🔵 Facebook post successful: {res.get('post_id')}")
            return res, None
        except Exception as e:
            logger.warning(f"⚠️ Failed to post to Facebook: {e}")
            return None, str(e)

    def _fallback_to_image_facebook(self, message: str, data: dict, video_generated: bool = False) -> tuple:
        """Fallback to regular image posting for Facebook"""
        try:
            image_url = data.get('image_url') or data.get('image')
            if not image_url:
                return None, 'no_image_url'

            # Convert HTML to Facebook-friendly text
            post_message = self._html_to_plain_text(message)
            
            # Add video indicator if video was generated (same as Instagram)
            if video_generated:
                post_message = f"🎬 {post_message}\n\nВидео доступно на нашем канале!"
            
            post_message = f"{post_message}\n\nНаш тг канал: https://t.me/spain_kepasa"

            # Post to Facebook
            res = post_facebook(image_url, post_message)
            logger.info(f"🔵 Facebook image post successful: {res.get('post_id')}")
            return res, None
        except Exception as e:
            return None, str(e)

    def _post_to_threads(self, message: str, data: dict) -> tuple:
        """Attempt to post to Threads if configured. Returns (result, error_str).
        
        Posts image with text to Threads (Instagram's text-based app).
        Uses the same format as X (Twitter): description_ru + article link.
        Simple and clean format without HTML.
        """
        if post_threads is None:
            return None, 'threads_helper_not_installed'

        try:
            # Extract data
            image_url = data.get('image_url') or data.get('image')
            if not image_url:
                logger.warning(f"⚠️ No image_url for Threads post")
                return None, 'no_image_url'

            # Use same format as X (Twitter): description + link
            description = data.get('description_ru') or data.get('content_ru') or ''
            slug = data.get('slug') or data.get('id') or data.get('article_id') or ''
            
            # Build URL
            article_url = f"https://ke-pasa.es/news/{slug}/" if slug else ""
            
            # Format: Description\n\n<URL> (same as X)
            parts = []
            if description:
                parts.append(description)
            if article_url:
                parts.append(article_url)
            
            post_text = '\n\n'.join([p for p in parts if p])

            # Post to Threads
            res = post_threads(image_url, post_text)
            logger.info(f"🧵 Threads post successful: {res.get('id')}")
            return res, None
        except Exception as e:
            logger.warning(f"⚠️ Failed to post to Threads: {e}")
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
                
                # Generate video for script if available
                video_file_path = None
                script_text = data.get('script')
                if script_text and script_text.strip() and image:
                    logger.info(f"🎬 Generating video for article {article_id}")
                    try:
                        if self.video_only_mode:
                            # In video-only mode, save videos permanently
                            videos_dir = os.path.join(os.getcwd(), "videos")
                            success, video_path, error_msg = generate_video_for_article(
                                article_id, script_text, image, 
                                output_dir=videos_dir, keep_video=True
                            )
                        else:
                            # In normal mode, create temporary videos
                            success, video_path, error_msg = generate_video_for_article(
                                article_id, script_text, image
                            )
                            
                        if success:
                            video_file_path = video_path
                            logger.info(f"✅ Video generated for {article_id}: {video_path}")
                            
                            # In video-only mode, just generate video and skip publication
                            if self.video_only_mode:
                                logger.info(f"📹 Video-only mode: Skipping publication for {article_id}")
                                results['published'] += 1
                                continue
                                
                        else:
                            logger.warning(f"⚠️ Video generation failed for {article_id}: {error_msg}")
                    except Exception as e:
                        logger.warning(f"⚠️ Video generation exception for {article_id}: {e}")
                
                # In video-only mode, skip publication
                if self.video_only_mode:
                    if video_file_path:
                        logger.info(f"📹 Video-only mode: Video generated for {article_id}")
                        results['published'] += 1
                    else:
                        logger.info(f"📹 Video-only mode: No video generated for {article_id}, skipping")
                        results['skipped'] += 1
                    continue

                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                # Clean up temporary video file (only in normal mode)
                if video_file_path and not self.video_only_mode:
                    try:
                        cleanup_temp_video(video_file_path)
                    except Exception as e:
                        logger.warning(f"⚠️ Failed to cleanup video file for {article_id}: {e}")

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(article_id, sent_message, doc_error)

                # Skip social media posting in video-only mode
                if not self.video_only_mode:
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

                    # Attempt to post to Instagram if enabled
                    try:
                        ig_res, ig_err = self._post_to_instagram(message, data)
                        logger.debug(f"Instagram post attempt result: res={ig_res} err={ig_err}")
                        if ig_err:
                            logger.info(f"ℹ️ Instagram post skipped/failed for {article_id}: {ig_err}")
                    except Exception as e:
                        logger.warning(f"⚠️ Unexpected error while posting to Instagram: {e}")

                    # Attempt to post to Facebook if enabled
                    try:
                        fb_res, fb_err = self._post_to_facebook(message, data)
                        logger.debug(f"Facebook post attempt result: res={fb_res} err={fb_err}")
                        if fb_err:
                            logger.info(f"ℹ️ Facebook post skipped/failed for {article_id}: {fb_err}")
                    except Exception as e:
                        logger.warning(f"⚠️ Unexpected error while posting to Facebook: {e}")

                    # Attempt to post to Threads if enabled
                    try:
                        threads_res, threads_err = self._post_to_threads(message, data)
                        logger.debug(f"Threads post attempt result: res={threads_res} err={threads_err}")
                        if threads_err:
                            if '500' in str(threads_err) or 'not connected' in str(threads_err):
                                logger.warning(f"⚠️ Threads not configured properly for {article_id}. Skipping Threads (Instagram needs to be connected to Threads and have proper permissions)")
                            else:
                                logger.info(f"ℹ️ Threads post skipped/failed for {article_id}: {threads_err}")
                    except Exception as e:
                        logger.warning(f"⚠️ Unexpected error while posting to Threads: {e}")

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
    import argparse
    
    # Configure logging (verbose for debugging X posts)
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger('workers.publisher')

    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Publisher Worker - Telegram Publication Handler')
    parser.add_argument('--health-check', action='store_true', 
                       help='Run health check on all integrations instead of publishing')
    parser.add_argument('--force', action='store_true',
                       help='Force publication even during night hours (23:00-09:00)')
    parser.add_argument('--article_id', type=str,
                       help='Publish specific article by ID')
    args = parser.parse_args()

    logger.info("=" * 60)
    if args.health_check:
        logger.info("🏥 Publisher Worker - Health Check Mode")
    else:
        logger.info("📢 Publisher Worker - Telegram Publication Handler")
    logger.info("=" * 60)
    
    try:
        config = PublisherConfig.from_env()
        worker = PublisherWorker(config)
        
        if args.health_check:
            # Run health check instead of publishing
            result = worker.check_integrations_health()
            
            # Exit with error code if any platform is unhealthy
            exit_code = 0 if result['overall_status'] == 'healthy' else 1
            sys.exit(exit_code)
        else:
            # Normal publication flow
            if args.article_id:
                # Publish specific article
                logger.info(f"🎯 Publishing specific article: {args.article_id}")
                result = worker.publish_specific_article(args.article_id, force=args.force)
            else:
                # Normal batch publication
                result = worker.publish_articles(force=args.force)
            
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
