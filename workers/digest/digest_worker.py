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
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat
from datetime import datetime, timezone
from pathlib import Path
from croniter import croniter
import uuid

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

# Publishing is handled by individual digest scripts

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
        self.dry_run = False
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

    def execute_job(self, job: dict):
        """Import digest module and delegate full execution to it.

        Prefers calling `run_job(job)` or `run(job)`. Falls back to `generate_digest()` for legacy scripts.
        """
        script_module = job.get('script_module')
        try:
            logger.debug(f"Importing digest module {script_module}")
            module = importlib.import_module(script_module)
            importlib.reload(module)
            if hasattr(module, 'run_job'):
                logger.info("Delegating to module.run_job(job)")
                return module.run_job(job)
            if hasattr(module, 'run'):
                logger.info("Delegating to module.run(job)")
                return module.run(job)
            if hasattr(module, 'generate_digest'):
                logger.info("Legacy module: calling generate_digest(); module must handle publishing itself.")
                return module.generate_digest()
            logger.error(f"Module {script_module} has no run_job/run/generate_digest entrypoints")
        except Exception:
            import traceback
            traceback.print_exc()
            logger.exception(f"Error executing module {script_module}")
        return None

    def run_immediate(self, job_id, target_channel=None):
        logger.info(f"🚀 Manual run for job: {job_id}")
        config = self.load_config()
        job = next((j for j in config.get('jobs', []) if j['id'] == job_id), None)
        
        if not job:
            logger.error(f"Job {job_id} not found in config")
            return
        # Inject dry-run flag and delegate to the digest module
        try:
            job['dry_run'] = bool(self.dry_run)
        except Exception:
            pass
        self.execute_job(job)

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
                            # Inject dry-run flag and delegate full job execution to the digest module
                            try:
                                job['dry_run'] = bool(self.dry_run)
                            except Exception:
                                pass
                            self.execute_job(job)
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
    parser.add_argument("--dry-run", action="store_true", help="Generate content only; skip publish/republish")
    
    args = parser.parse_args()
    
    worker = DigestWorker()
    worker.dry_run = bool(args.dry_run)
    
    if args.run_now:
        worker.run_immediate(args.run_now, args.target_channel)
    else:
        worker.run_daemon()
