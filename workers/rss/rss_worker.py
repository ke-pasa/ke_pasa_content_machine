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

# Project imports
from firebase_client import get_firebase_client
from .rss_parser import RSSParser
from .config import RSSConfig


class RSSWorker:
    """Worker for parsing RSS feeds with validation and auto-cleanup"""
    
    def __init__(self, config: RSSConfig = None):
        """
        Initialize RSS worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or RSSConfig.from_env()
        self.db = get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        
        print(f"[rss-worker] Starting worker id={self.instance_id}")
        print(f"[rss-worker] Feeds file: {self.config.feeds_file}")
        print(f"[rss-worker] Lock lease: {self.config.lock_lease_sec}s")

    def _acquire_lock(self) -> bool:
        """
        Acquire lock for RSS parsing
        
        Returns:
            True if lock acquired, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('rss_worker')
            lock_doc = locks.get()
            
            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                exp = lock_data.get('expires_at')
                
                if exp:
                    exp_dt = datetime.fromisoformat(exp)
                    if exp_dt.tzinfo is None:
                        exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                    
                    if exp_dt > now:
                        holder = lock_data.get('holder_id', 'unknown')
                        print(f"[rss-worker] Another instance is active (holder: {holder})")
                        return False
                    else:
                        print(f"[rss-worker] Found stale lock, releasing...")
            
            # Set new lock
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self.config.lock_lease_sec)).isoformat(),
                'worker_type': 'rss'
            })
            print(f"[rss-worker] ✅ Lock acquired")
            return True
            
        except Exception as e:
            print(f"[rss-worker] ❌ Lock acquisition error: {e}")
            return False

    def _release_lock(self):
        """Release the lock"""
        try:
            self.db.collection('locks').document('rss_worker').delete()
            print(f"[rss-worker] ✅ Lock released")
        except Exception as e:
            print(f"[rss-worker] ⚠️  Lock release error: {e}")

    def process_feeds(self) -> dict:
        """
        Process RSS feeds from file with automatic validation
        
        Returns:
            Dictionary with processing results
        """
        if not self._acquire_lock():
            return {
                'status': 'skipped',
                'reason': 'locked',
                'message': 'Another instance is already running'
            }
        
        try:
            # Check if file exists
            if not os.path.exists(self.config.feeds_file):
                print(f"[rss-worker] ❌ File not found: {self.config.feeds_file}")
                return {
                    'status': 'error',
                    'reason': 'file_not_found',
                    'message': f'File {self.config.feeds_file} not found'
                }
            
            print(f"[rss-worker] 🚀 Processing feeds from: {self.config.feeds_file}")
            
            # Read feeds from file
            valid_feeds = []
            not_working_feeds = []
            outdated_feeds = []
            
            with open(self.config.feeds_file, 'r', encoding='utf-8') as f:
                feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
            print(f"[rss-worker] 📋 Found {len(feeds)} feeds to check")
            
            # Process each feed with validation
            for i, feed_url in enumerate(feeds, 1):
                print(f"[rss-worker] 🔍 [{i}/{len(feeds)}] Checking: {feed_url}")
                
                try:
                    # Try parsing the feed
                    parser = RSSParser()
                    feed_data = parser.parse_feed(feed_url)
                    
                    if not feed_data or not feed_data.get('entries'):
                        # Feed is not working
                        print(f"[rss-worker] ❌ Feed not working: {feed_url}")
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
                        print(f"[rss-worker] 📅 Feed outdated (no articles < 30 days): {feed_url}")
                        outdated_feeds.append(feed_url)
                        continue
                    
                    # Feed is valid
                    print(f"[rss-worker] ✅ Feed valid: {len(feed_data['entries'])} articles")
                    valid_feeds.append(feed_url)
                    
                except Exception as e:
                    print(f"[rss-worker] ❌ Feed check error: {e}")
                    not_working_feeds.append(feed_url)
                    continue
            
            # Update feeds.txt with valid feeds only
            if len(valid_feeds) < len(feeds):
                print(f"[rss-worker] 📝 Updating feeds.txt: {len(valid_feeds)}/{len(feeds)} valid")
                self._update_feeds_file(self.config.feeds_file, valid_feeds)
                
                # Save not working feeds
                if not_working_feeds:
                    self._save_problematic_feeds('feeds_not_working.txt', not_working_feeds)
                    print(f"[rss-worker] 💾 Saved {len(not_working_feeds)} not working feeds")
                
                # Save outdated feeds
                if outdated_feeds:
                    self._save_problematic_feeds('feeds_outdated.txt', outdated_feeds)
                    print(f"[rss-worker] 💾 Saved {len(outdated_feeds)} outdated feeds")
            
            # Now process valid feeds
            if valid_feeds:
                print(f"[rss-worker] 🚀 Processing {len(valid_feeds)} valid feeds...")
                parser = RSSParser()
                
                # Temporarily save valid feeds to temp file
                temp_feeds_file = self.config.feeds_file + '.tmp'
                with open(temp_feeds_file, 'w', encoding='utf-8') as f:
                    for feed in valid_feeds:
                        f.write(feed + '\n')
                
                # Process temp file
                result = parser.process_multiple_feeds(temp_feeds_file)
                
                # Delete temp file
                if os.path.exists(temp_feeds_file):
                    os.remove(temp_feeds_file)
            
            print(f"[rss-worker] ✅ Processing completed successfully")
            
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
            print(f"[rss-worker] ❌ Processing error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            self._release_lock()
    
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
            print(f"[rss-worker] ❌ Feed file update error: {e}")
    
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
            print(f"[rss-worker] ❌ Problematic feeds save error: {e}")

    def get_status(self) -> dict:
        """
        Get current worker status
        
        Returns:
            Dictionary with worker status
        """
        try:
            lock_doc = self.db.collection('locks').document('rss_worker').get()
            
            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                return {
                    'locked': True,
                    'holder_id': lock_data.get('holder_id'),
                    'acquired_at': lock_data.get('acquired_at'),
                    'expires_at': lock_data.get('expires_at')
                }
            else:
                return {
                    'locked': False,
                    'message': 'Worker is free'
                }
        except Exception as e:
            return {
                'error': str(e)
            }
