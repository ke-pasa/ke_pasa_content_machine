"""
RSS Worker - RSS feed processing with automatic validation
"""

# Standard library imports
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Add root directory to path for importing shared modules
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

# Load environment variables (optional, can be set by system)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv is optional, variables can be set by system

from .config import RSSConfig
import traceback
import logging

logger = logging.getLogger(__name__)


class RSSWorker:
    """Worker for parsing RSS feeds with validation and auto-cleanup"""
    
    def __init__(self, config: RSSConfig = None):
        """
        Initialize RSS worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or RSSConfig.from_env()
        self.instance_id = str(uuid.uuid4())[:8]

        self.db = None
        self.pg = None

        try:
            from workers.tools.pg_client import get_pg_client
            self.pg = get_pg_client()
            logger.info("✅ Postgres client initialized for RSS worker (lazy)")
        except Exception:
            self.pg = None

        logger.info(f"Starting worker id={self.instance_id}")
        logger.info(f"Feeds file: {self.config.feeds_file}")
        logger.info(f"Locking disabled (running without Firebase locks)")

    def process_feeds(self) -> dict:
        """
        Process RSS feeds from file with automatic validation
        
        Returns:
            Dictionary with processing results
        """
        try:
            # Check if file exists
            if not os.path.exists(self.config.feeds_file):
                logger.error(f"❌ File not found: {self.config.feeds_file}")
                return {
                    'status': 'error',
                    'reason': 'file_not_found',
                    'message': f'File {self.config.feeds_file} not found'
                }
            
            logger.info(f"🚀 Processing feeds from: {self.config.feeds_file}")
            
            # Read feeds from file
            valid_feeds = []
            not_working_feeds = []
            outdated_feeds = []
            
            with open(self.config.feeds_file, 'r', encoding='utf-8') as f:
                feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
            logger.info(f"📋 Found {len(feeds)} feeds to check")
            
            # Ensure conditional GET caches are cleared before initial validation
            try:
                etag_path = Path('rss_etag_cache.json')
                lm_path = Path('rss_lastmod_cache.json')
                if etag_path.exists():
                    etag_path.unlink()
                    logger.info(f"Cleared ETag cache: {etag_path}")
                if lm_path.exists():
                    lm_path.unlink()
                    logger.info(f"Cleared Last-Modified cache: {lm_path}")
            except Exception as e:
                logger.warning(f"⚠️ Could not clear RSS caches before validation: {e}")

            # Process each feed with validation
            for i, feed_url in enumerate(feeds, 1):
                logger.info(f"🔍 [{i}/{len(feeds)}] Checking: {feed_url}")
                
                try:
                    from .rss_parser import RSSParser
                    parser = RSSParser()
                    feed_data = parser.parse_feed(feed_url)
                    
                    if not feed_data or not feed_data.get('entries'):
                        # Feed is not working
                        logger.error(f"❌ Feed not working: {feed_url}")
                        not_working_feeds.append(feed_url)
                        continue
                    
                    # Check for recent articles (less than 30 days old)
                    has_recent = False
                    for article in feed_data['entries']:
                        published = article.get('published', '')
                        if published:
                            try:
                                from dateutil import parser as date_parser
                                article_date = date_parser.parse(published)
                                days_old = (datetime.now() - article_date).days
                                
                                if days_old <= 30:
                                    has_recent = True
                                    break
                            except:
                                continue
                    
                    if not has_recent:
                        # Feed is outdated
                        logger.warning(f"📅 Feed outdated (no articles < 30 days): {feed_url}")
                        outdated_feeds.append(feed_url)
                        continue
                    
                    # Feed is valid
                    logger.info(f"✅ Feed valid: {len(feed_data['entries'])} articles")
                    valid_feeds.append(feed_url)
                    
                except Exception as e:
                    logger.error(f"❌ Feed check error: {e}")
                    traceback.print_exc()
                    not_working_feeds.append(feed_url)
                    continue
            
            # Update feeds.txt with valid feeds only
            if len(valid_feeds) < len(feeds):
                logger.info(f"📝 Updating feeds.txt: {len(valid_feeds)}/{len(feeds)} valid")
                self._update_feeds_file(self.config.feeds_file, valid_feeds)
                
                # Save not working feeds
                if not_working_feeds:
                    self._save_problematic_feeds('feeds_not_working.txt', not_working_feeds)
                    logger.info(f"💾 Saved {len(not_working_feeds)} not working feeds")
                
                # Save outdated feeds
                if outdated_feeds:
                    self._save_problematic_feeds('feeds_outdated.txt', outdated_feeds)
                    logger.info(f"💾 Saved {len(outdated_feeds)} outdated feeds")
            
            # Now process valid feeds
            if valid_feeds:
                logger.info(f"🚀 Processing {len(valid_feeds)} valid feeds...")
                from .rss_parser import RSSParser
                parser = RSSParser()
                
                # Clearing conditional GET caches to avoid immediate 304 responses
                # caused by the earlier validation step which already populated ETag/Last-Modified.
                try:
                    etag_path = Path(parser._etag_cache_path)
                    lm_path = Path(parser._lm_cache_path)
                    if etag_path.exists():
                        etag_path.unlink()
                        logger.info(f"Cleared ETag cache: {etag_path}")
                    if lm_path.exists():
                        lm_path.unlink()
                        logger.info(f"Cleared Last-Modified cache: {lm_path}")
                except Exception as e:
                    logger.warning(f"⚠️ Could not clear RSS conditional GET caches: {e}")

                # Temporarily save valid feeds to temp file
                temp_feeds_file = self.config.feeds_file + '.tmp'
                with open(temp_feeds_file, 'w', encoding='utf-8') as f:
                    for feed in valid_feeds:
                        f.write(feed + '\n')
                
                # Prefetch uploaded links once and pass to parser to avoid repeated DB calls
                shared_uploaded_links = set()
                try:
                    if self.pg and hasattr(self.pg, 'get_recent_article_links'):
                        shared_uploaded_links = set(self.pg.get_recent_article_links(24) or set())
                        if shared_uploaded_links:
                            logger.info(f"ℹ️ Prefetched {len(shared_uploaded_links)} recent links from Postgres")
                except Exception as e:
                    logger.warning(f"⚠️ Could not prefetch recent links: {e}")
                    traceback.print_exc()

                # Process temp file with shared uploaded-links cache
                result = parser.process_multiple_feeds(temp_feeds_file, shared_uploaded_links=shared_uploaded_links)
                
                # Delete temp file
                if os.path.exists(temp_feeds_file):
                    os.remove(temp_feeds_file)
            
            logger.info(f"✅ Processing completed successfully")
            
            return {
                'status': 'success',
                'message': 'RSS feeds processed successfully',
                'instance_id': self.instance_id,
                'feeds_file': self.config.feeds_file,
                'valid_feeds': len(valid_feeds),
                'not_working_feeds': len(not_working_feeds),
                'outdated_feeds': len(outdated_feeds),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Processing error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            logger.info(f"Locking disabled — no lock to release")
    
    def _update_feeds_file(self, filepath: str, valid_feeds: list):
        """Update feeds file with valid feeds only"""
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write("# RSS feeds - Automatically cleaned\n")
                f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("#\n\n")
                for feed in valid_feeds:
                    f.write(feed + '\n')
        except Exception as e:
            logger.error(f"❌ Feed file update error: {e}")
    
    def _save_problematic_feeds(self, filepath: str, feeds: list):
        """Save problematic feeds to separate file"""
        try:
            # Read existing problematic feeds if file exists
            existing_feeds = set()
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    existing_feeds = set(line.strip() for line in f if line.strip() and not line.startswith('#'))
            
            # Merge with new problematic feeds
            all_problematic = existing_feeds.union(set(feeds))
            
            # Write to file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(f"# Problematic RSS feeds\n")
                f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"# Total: {len(all_problematic)}\n")
                f.write("#\n\n")
                for feed in sorted(all_problematic):
                    f.write(feed + '\n')
        except Exception as e:
            logger.error(f"❌ Problematic feeds save error: {e}")

    def get_status(self) -> dict:
        """
        Get current worker status
        
        Returns:
            Dictionary with worker status
        """
        # Locking is disabled in this build; always report unlocked.
        return {
            'locked': False,
            'message': 'Locking disabled'
        }
