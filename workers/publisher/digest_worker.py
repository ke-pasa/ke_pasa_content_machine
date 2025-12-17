"""
Digest Worker
Handles scheduled execution of digest scripts and publishing to Telegram.
"""
import sys
import os
import time
import json
import logging
import argparse
import importlib
from datetime import datetime, timezone
from pathlib import Path
from croniter import croniter

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

from workers.tools.telegram_helper import send_message

# Configuration
CONFIG_FILE = Path(__file__).parent / "digest_config.json"
STATE_FILE = Path(__file__).parent / "digest_state.json"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("workers.digest")

class DigestWorker:
    def __init__(self):
        self.telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
        if not self.telegram_token:
            logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set")
            
    def load_config(self):
        try:
            if CONFIG_FILE.exists():
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load config: {e}")
        return {"jobs": []}

    def load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def save_state(self, state):
        try:
            with open(STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def execute_digest(self, script_module: str) -> str:
        """Dynamically imports module and calls generate_digest()"""
        try:
            module = importlib.import_module(script_module)
            if hasattr(module, 'generate_digest'):
                # Reload module to ensure fresh code if running long-term
                importlib.reload(module)
                return module.generate_digest()
            else:
                logger.error(f"Module {script_module} has no generate_digest function")
        except Exception as e:
            logger.error(f"Error executing script {script_module}: {e}")
        return None

    def _markdown_to_telegram_html(self, text: str) -> str:
        """
        Converts standard Markdown to Telegram-supported HTML.
        Supported:
        - # Header -> <b>Header</b>
        - **bold** -> <b>bold</b>
        - *italic* -> <i>italic</i>
        - [link](url) -> <a href="url">link</a>
        - * Bullet -> • Bullet
        """
        if not text:
            return ""
            
        import re
        
        # Escape HTML special characters first to avoid conflict with tags we create
        # But wait, python-telegram-bot or the helper might not expect escaped entities if we add tags?
        # Actually standard HTML needs & < > escaped.
        # Let's do a simple pass.
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        
        # Headers: # text -> <b>text</b>
        text = re.sub(r'^#+\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        
        # Bold: **text** -> <b>text</b>
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        
        # Italic: *text* -> <i>text</i>
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        
        # Links: [text](url) -> <a href="url">text</a>
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        
        # Lists: * text -> • text
        text = re.sub(r'^\s*\*\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        
        return text

    def publish_content(self, content: str, channels: list):
        if not content:
            logger.warning("No content generated to publish")
            return

        # Convert Markdown to Telegram HTML
        html_content = self._markdown_to_telegram_html(content)

        for channel in channels:
            try:
                logger.info(f"Sending digest to {channel}...")
                send_message(channel, html_content, token=self.telegram_token, parse_mode='HTML')
                logger.info(f"✅ Sent to {channel}")
            except Exception as e:
                logger.error(f"❌ Failed to send to {channel}: {e}")

    def run_immediate(self, job_id, target_channel=None):
        """Run a specific digest job immediately"""
        logger.info(f"🚀 Manual run for job: {job_id}")
        config = self.load_config()
        job = next((j for j in config.get('jobs', []) if j['id'] == job_id), None)
        
        if not job:
            logger.error(f"Job {job_id} not found in config")
            return

        content = self.execute_digest(job['script_module'])
        if content:
            # Use provided override channel or configured channels
            channels = [target_channel] if target_channel else job.get('channels', [])
            self.publish_content(content, channels)
        else:
            logger.error("Failed to generate content")

    def run_daemon(self):
        """Continuous monitoring loop"""
        logger.info("🕒 Starting Digest Worker Daemon")
        
        while True:
            try:
                config = self.load_config()
                state = self.load_state()
                now_utc = datetime.now(timezone.utc)
                
                # Log every check
                logger.info(f"✓ Checking schedules at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                
                for job in config.get('jobs', []):
                    if not job.get('enabled', True):
                        continue
                        
                    job_id = job['id']
                    cron_expr = job['cron_schedule']
                    last_run_str = state.get(job_id, {}).get('last_run_iso')
                    
                    # Logic: 
                    # 1. Calculate previous scheduled run time relative to NOW
                    # 2. If we haven't run it since that time -> Run it.
                    
                    iter_cron = croniter(cron_expr, now_utc)
                    prev_run_time = iter_cron.get_prev(datetime)
                    
                    should_run = False
                    if not last_run_str:
                        # Never run before, but we probably shouldn't run immediately on startup 
                        # unless the schedule *just* matched. 
                        # Safe bet: assume we missed it if it was very recent, otherwise wait for next.
                        # For now, let's just mark it as 'handled' to wait for next, OR
                        # strictly: if prev_run_time is very close to now (e.g. within 5 mins), run it.
                        # BUT, simplified logic: just track execution.
                        # Let's simply handle the "last run" logic:
                        should_run = False # Don't auto-fire old jobs on fresh start to avoid spam
                        # Initialize state to avoid undefined behavior? 
                        # Actually, let's just wait for the NEXT occurrence in the loop?
                        # No, the loop sleeps. We need to catch the moment.
                        
                        # Better approach for daemon: 
                        # Check if now matches cron (approx).
                        # Or compare timestamps.
                        
                        # Let's use standard logic:
                        # If (now - prev_run_time) < threshold AND prev_run_time > recorded_last_run
                        pass
                    else:
                        last_run_dt = datetime.fromisoformat(last_run_str)
                        if prev_run_time > last_run_dt:
                             # We have a scheduled run that is newer than our last actual run
                             # Check if it's "fresh" (e.g. we didn't miss it by hours due to crash)
                             # If we want to catch up: run it.
                             # If we want to only run current: check diff.
                             
                             # Rule: If the scheduled time was within the last 5 minutes, run it.
                             diff = now_utc - prev_run_time
                             if diff.total_seconds() < 300: # 5 minutes window
                                 should_run = True

                    # Handle first run case separately if needed, or manual trigger.
                    # For a simple robust loop:
                    # just check if Current Minute matches Cron Minute (and hasn't run yet this minute).
                    # But croniter is better.
                    
                    # Let's try "Has a scheduled event occurred since we last checked?"
                    # We can store "last_check_time" in memory.
                    pass

                # Revised Simple Loop Logic with Memory State for Daemon lifetime
                # But we need persistence.
                
                # Let's go with:
                # 1. Get current time.
                # 2. Check if current time matches cron (minute resolution).
                # 3. If match AND not already executed this minute/instance -> Execute.
                
                for job in config.get('jobs', []):
                    if not job.get('enabled'):
                        logger.debug(f"  - Job '{job.get('id', 'unknown')}' is disabled, skipping")
                        continue
                    
                    job_id = job['id']
                    cron_expr = job['cron_schedule']
                    
                    if croniter.match(cron_expr, now_utc):
                        # It matches THIS minute.
                        logger.info(f"  ⏰ Schedule matched for '{job_id}' ({cron_expr})")
                        
                        # Check state to ensure we didn't already run it for this specific time.
                        last_run_iso = state.get(job_id, {}).get('last_run_iso')
                        # If last run was less than 60 seconds ago, skip
                        already_run = False
                        if last_run_iso:
                            last_dt = datetime.fromisoformat(last_run_iso)
                            if (now_utc - last_dt).total_seconds() < 65:
                                already_run = True
                                logger.info(f"  ⏭️  Skipping '{job_id}' - already ran recently")
                                
                        if not already_run:
                            logger.info(f"  ▶️  Executing '{job_id}'...")
                            content = self.execute_digest(job['script_module'])
                            if content:
                                self.publish_content(content, job['channels'])
                                
                                # Update State
                                if job_id not in state: state[job_id] = {}
                                state[job_id]['last_run_iso'] = now_utc.isoformat()
                                self.save_state(state)
                                logger.info(f"  ✅ Completed '{job_id}'")
                    else:
                        # Calculate next run time for this job
                        iter_cron = croniter(cron_expr, now_utc)
                        next_run = iter_cron.get_next(datetime)
                        logger.info(f"  - Job '{job_id}' ({cron_expr}): next run at {next_run.strftime('%Y-%m-%d %H:%M UTC')}")

            except Exception as e:
                logger.error(f"Daemon loop error: {e}")
            
            # Sleep to align with next minute
            # Simple sleep 60 is okay, but aligning to :00 seconds is better
            sleep_time = 60 - time.time() % 60
            time.sleep(sleep_time)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Digest Worker")
    parser.add_argument("--run-now", help="ID of job to run immediately")
    parser.add_argument("--target-channel", help="Override target channel for immediate run")
    
    args = parser.parse_args()
    
    worker = DigestWorker()
    
    if args.run_now:
        worker.run_immediate(args.run_now, args.target_channel)
    else:
        worker.run_daemon()
