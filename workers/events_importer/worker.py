"""
Events Importer Worker

Monitors a folder for new JSON event files and processes RSS feeds daily.
Saves events to public.events table in PostgreSQL via pg_client.
"""
import sys
import os
import time
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional
from croniter import croniter

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

# Configuration
DEFAULT_EVENTS_FOLDER = Path(__file__).parent.parent.parent / "data" / "events"
RSS_CONFIG_FILE = Path(__file__).parent / "event_rss.json"
STATE_FILE = Path(__file__).parent / "events_importer_state.json"

# Daily RSS schedule: 3:00 AM UTC
RSS_CRON_SCHEDULE = "0 3 * * *"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("workers.events_importer")


class EventsImporterWorker:
    """Worker for importing events from JSON files and RSS feeds"""
    
    def __init__(self, events_folder: Path = None):
        """
        Initialize the Events Importer Worker
        
        Args:
            events_folder: Path to folder to monitor for JSON files
        """
        self.events_folder = Path(events_folder) if events_folder else DEFAULT_EVENTS_FOLDER
        self.processed_files = set()
        self.last_rss_run = None
        self.pg = None
        
        self._ensure_events_folder()
        self._load_state()
        self._init_db()
        
        logger.info(f"🚀 Events Importer Worker initialized")
        logger.info(f"📁 Watching folder: {self.events_folder}")
        logger.info(f"📰 RSS config: {RSS_CONFIG_FILE}")
        logger.info(f"⏰ RSS schedule: {RSS_CRON_SCHEDULE}")
    
    def _init_db(self):
        """Initialize PostgreSQL connection"""
        try:
            from workers.tools.pg_client import get_pg_client
            self.pg = get_pg_client()
            logger.info("✅ PostgreSQL client initialized")
        except Exception as e:
            logger.warning(f"⚠️ Could not initialize PostgreSQL: {e}")
            self.pg = None
    
    def _ensure_events_folder(self):
        """Create events folder if it doesn't exist"""
        if not self.events_folder.exists():
            self.events_folder.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 Created events folder: {self.events_folder}")
        else:
            logger.info(f"📁 Events folder exists: {self.events_folder}")
    
    def _load_state(self):
        """Load processed files state from disk"""
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.processed_files = set(state.get('processed_files', []))
                    self.last_rss_run = state.get('last_rss_run')
                    logger.info(f"📋 Loaded state: {len(self.processed_files)} processed files")
        except Exception as e:
            logger.warning(f"⚠️ Could not load state: {e}")
            self.processed_files = set()
            self.last_rss_run = None
    
    def _save_state(self):
        """Save processed files state to disk"""
        try:
            state = {
                'processed_files': list(self.processed_files),
                'last_rss_run': self.last_rss_run
            }
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"❌ Could not save state: {e}")
    
    def check_folder_for_new_files(self) -> list:
        """
        Check events folder for new JSON files
        
        Returns:
            List of new file paths found
        """
        new_files = []
        
        try:
            if not self.events_folder.exists():
                self._ensure_events_folder()
                return []
            
            # Find all JSON files in the folder
            json_files = list(self.events_folder.glob("*.json"))
            
            for file_path in json_files:
                file_key = str(file_path.absolute())
                
                if file_key not in self.processed_files:
                    logger.info(f"📄 New file detected: {file_path.name}")
                    new_files.append(file_path)
                    self.processed_files.add(file_key)
            
            if new_files:
                self._save_state()
                
        except Exception as e:
            logger.error(f"❌ Error checking folder: {e}")
        
        return new_files
    
    def process_new_file(self, file_path: Path) -> int:
        """
        Process a new JSON file - parse and save events to database
        
        Args:
            file_path: Path to the JSON file
            
        Returns:
            Number of events saved
        """
        logger.info(f"✨ Processing file: {file_path.name}")
        saved_count = 0
        
        if not self.pg:
            logger.error("❌ No database connection, cannot save events")
            return 0
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Handle both single event and array of events
            events = data if isinstance(data, list) else [data]
            
            logger.info(f"📋 Found {len(events)} event(s) in file")
            
            for i, event in enumerate(events, 1):
                # Validate required fields
                if not event.get('title'):
                    logger.warning(f"⚠️ Event {i}: Missing required field 'title', skipping")
                    continue
                if not event.get('start_at'):
                    logger.warning(f"⚠️ Event {i}: Missing required field 'start_at', skipping")
                    continue
                if not event.get('city'):
                    logger.warning(f"⚠️ Event {i}: Missing required field 'city', skipping")
                    continue
                
                # Use pg_client.save_event() method
                event_id = self.pg.save_event(event)
                if event_id:
                    saved_count += 1
                    title_preview = event.get('title', '')[:50]
                    logger.info(f"✅ Event {i}: '{title_preview}...' saved with ID {event_id}")
                else:
                    title_preview = event.get('title', '')[:50]
                    logger.error(f"❌ Event {i}: Failed to save '{title_preview}...'")
            
            logger.info(f"📊 Processed {file_path.name}: {saved_count}/{len(events)} events saved")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in {file_path.name}: {e}")
        except Exception as e:
            logger.error(f"❌ Error processing {file_path.name}: {e}")
        
        return saved_count
    
    def check_and_run_rss(self):
        """Check if RSS should run and execute if due"""
        now_utc = datetime.now(timezone.utc)
        
        # Check if schedule matches current minute
        if croniter.match(RSS_CRON_SCHEDULE, now_utc):
            # Check if we already ran recently (within 65 seconds)
            if self.last_rss_run:
                last_run_dt = datetime.fromisoformat(self.last_rss_run)
                if (now_utc - last_run_dt).total_seconds() < 65:
                    logger.debug("⏭️ RSS already ran recently, skipping")
                    return
            
            logger.info("⏰ RSS schedule matched, running RSS import...")
            self.process_rss_feeds()
            self.last_rss_run = now_utc.isoformat()
            self._save_state()
    
    def process_rss_feeds(self):
        """Read and process RSS feeds from event_rss.json using configured handlers"""
        logger.info("📰 Processing RSS feeds...")
        
        if not RSS_CONFIG_FILE.exists():
            logger.warning(f"⚠️ RSS config file not found: {RSS_CONFIG_FILE}")
            return
        
        try:
            with open(RSS_CONFIG_FILE, 'r', encoding='utf-8') as f:
                config = json.load(f)
            
            feeds = config.get('feeds', [])
            if not feeds:
                logger.info("📭 No RSS feeds configured")
                return
            
            # Import handlers
            from workers.events_importer.handlers import get_handler
            
            logger.info(f"📋 Found {len(feeds)} RSS feed(s) to process")
            total_events_saved = 0
            
            for feed_config in feeds:
                if not feed_config.get('enabled', True):
                    logger.info(f"⏭️ Feed disabled: {feed_config.get('url', 'unknown')}")
                    continue
                
                feed_url = feed_config.get('url')
                handler_name = feed_config.get('handler', 'default_handler')
                
                if not feed_url:
                    logger.warning("⚠️ Feed config missing 'url', skipping")
                    continue
                
                logger.info(f"🔗 Processing feed: {feed_url}")
                logger.info(f"   Handler: {handler_name}")
                
                try:
                    # Fetch and parse RSS feed
                    feed_data = self._fetch_rss_feed(feed_url)
                    if not feed_data:
                        logger.warning(f"⚠️ Could not fetch feed: {feed_url}")
                        continue
                    
                    # Get handler and process
                    handler = get_handler(handler_name)
                    events = handler(feed_data)
                    
                    logger.info(f"   📌 Extracted {len(events)} event(s)")
                    
                    # Save events to database
                    for event in events:
                        if self.pg:
                            event_id = self.pg.save_event(event)
                            if event_id:
                                total_events_saved += 1
                        else:
                            logger.warning("⚠️ No database connection")
                    
                except Exception as e:
                    logger.error(f"❌ Error processing feed {feed_url}: {e}")
            
            logger.info(f"✅ RSS processing completed: {total_events_saved} events saved")
            
        except json.JSONDecodeError as e:
            logger.error(f"❌ Invalid JSON in RSS config: {e}")
        except Exception as e:
            logger.error(f"❌ Error processing RSS feeds: {e}")
    
    def _fetch_rss_feed(self, feed_url: str) -> Optional[Dict[str, Any]]:
        """Fetch and parse an RSS feed"""
        try:
            import feedparser
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                logger.warning(f"⚠️ Feed parsing error: {feed.bozo_exception}")
                return None
            return {'entries': feed.entries, 'feed': feed.feed}
        except ImportError:
            logger.error("❌ feedparser not installed. Add to requirements.txt")
            return None
        except Exception as e:
            logger.error(f"❌ Error fetching feed: {e}")
            return None
    
    def run_continuous(self):
        """Run worker in continuous mode, checking folder every minute"""
        logger.info("🕒 Starting Events Importer Worker in continuous mode")
        logger.info("⏱️ Checking folder every 60 seconds")
        
        while True:
            try:
                now_utc = datetime.now(timezone.utc)
                logger.info(f"✓ Checking at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                
                # Check for new files
                new_files = self.check_folder_for_new_files()
                total_saved = 0
                for file_path in new_files:
                    saved = self.process_new_file(file_path)
                    total_saved += saved
                
                if new_files:
                    logger.info(f"📊 Total: {total_saved} events saved from {len(new_files)} file(s)")
                else:
                    logger.info("📭 No new files found")
                
                # Check if RSS should run
                self.check_and_run_rss()
                
            except Exception as e:
                logger.error(f"❌ Loop error: {e}")
            
            # Sleep until next minute
            sleep_time = 60 - time.time() % 60
            time.sleep(sleep_time)
    
    def run_once(self):
        """Run single check (for testing)"""
        logger.info("🔍 Running single check...")
        
        # Check for new files
        new_files = self.check_folder_for_new_files()
        total_saved = 0
        for file_path in new_files:
            saved = self.process_new_file(file_path)
            total_saved += saved
        
        if new_files:
            logger.info(f"📊 Total: {total_saved} events saved from {len(new_files)} file(s)")
        else:
            logger.info("📭 No new files found")
        
        return new_files
    
    def run_rss_now(self):
        """Run RSS processing immediately (for testing)"""
        logger.info("🚀 Manual RSS run triggered")
        self.process_rss_feeds()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Events Importer Worker")
    parser.add_argument("--run-once", action="store_true", help="Run single check and exit")
    parser.add_argument("--run-rss", action="store_true", help="Run RSS import immediately")
    parser.add_argument("--folder", help="Override events folder path")
    
    args = parser.parse_args()
    
    folder = Path(args.folder) if args.folder else None
    worker = EventsImporterWorker(events_folder=folder)
    
    if args.run_once:
        worker.run_once()
    elif args.run_rss:
        worker.run_rss_now()
    else:
        worker.run_continuous()
