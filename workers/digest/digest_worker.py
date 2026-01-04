"""
Digest Worker (migrated to workers.digest)
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

# Configuration (local to package)
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
                importlib.reload(module)
                return module.generate_digest()
            else:
                logger.error(f"Module {script_module} has no generate_digest function")
        except Exception as e:
            logger.error(f"Error executing script {script_module}: {e}")
        return None

    def _markdown_to_telegram_html(self, text: str) -> str:
        if not text:
            return ""
        import re
        text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        text = re.sub(r'^#+\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
        text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
        text = re.sub(r'^\s*\*\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        return text

    def publish_content(self, content: str, channels: list):
        if not content:
            logger.warning("No content generated to publish")
            return

        html_content = self._markdown_to_telegram_html(content)

        for channel in channels:
            try:
                logger.info(f"Sending digest to {channel}...")
                send_message(channel, html_content, token=self.telegram_token, parse_mode='HTML')
                logger.info(f"✅ Sent to {channel}")
            except Exception as e:
                logger.error(f"❌ Failed to send to {channel}: {e}")

    def run_immediate(self, job_id, target_channel=None):
        logger.info(f"🚀 Manual run for job: {job_id}")
        config = self.load_config()
        job = next((j for j in config.get('jobs', []) if j['id'] == job_id), None)
        
        if not job:
            logger.error(f"Job {job_id} not found in config")
            return

        content = self.execute_digest(job['script_module'])
        if content:
            channels = [target_channel] if target_channel else job.get('channels', [])
            self.publish_content(content, channels)
        else:
            logger.error("Failed to generate content")

    def run_daemon(self):
        logger.info("🕒 Starting Digest Worker Daemon")
        
        while True:
            try:
                config = self.load_config()
                state = self.load_state()
                now_utc = datetime.now(timezone.utc)
                logger.info(f"✓ Checking schedules at {now_utc.strftime('%Y-%m-%d %H:%M:%S UTC')}")
                
                for job in config.get('jobs', []):
                    if not job.get('enabled'):
                        logger.debug(f"  - Job '{job.get('id', 'unknown')}' is disabled, skipping")
                        continue
                    
                    job_id = job['id']
                    cron_expr = job['cron_schedule']
                    
                    if croniter.match(cron_expr, now_utc):
                        logger.info(f"  ⏰ Schedule matched for '{job_id}' ({cron_expr})")
                        last_run_iso = state.get(job_id, {}).get('last_run_iso')
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
                                if job_id not in state: state[job_id] = {}
                                state[job_id]['last_run_iso'] = now_utc.isoformat()
                                self.save_state(state)
                                logger.info(f"  ✅ Completed '{job_id}'")
                    else:
                        iter_cron = croniter(cron_expr, now_utc)
                        next_run = iter_cron.get_next(datetime)
                        logger.info(f"  - Job '{job_id}' ({cron_expr}): next run at {next_run.strftime('%Y-%m-%d %H:%M UTC')}")

            except Exception as e:
                logger.error(f"Daemon loop error: {e}")
            
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
