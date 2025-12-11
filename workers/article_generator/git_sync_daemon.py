#!/usr/bin/env python3
"""Daemon to sync articles/ to remote git repo periodically.

Usage:
  python scripts/git_sync_daemon.py --interval 30    # run every 30 minutes
  python scripts/git_sync_daemon.py --once            # run once and exit
"""
import argparse
import logging
import signal
import sys
import time
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from datetime import datetime

sys.path.insert(0, '.')


def sync_to_git_repo(article_ids=None) -> dict:
    results = {'synced': 0, 'errors': [], 'article_ids': article_ids or []}
    pat = os.getenv('GIT_KE_PASA_PAT')
    if not pat:
        logging.warning("GIT_KE_PASA_PAT not set; skipping git sync")
        return results
    
    repo = os.getenv('ARTICLES_REPO') or 'ke-pasa/ke_pasa_site'
    branch = os.getenv('ARTICLES_REPO_BRANCH') or 'main'
    
    logging.info(f"🔄 Starting git sync to {repo} ({branch})...")

    root_dir = Path(__file__).resolve().parent.parent.parent
    temp_dir = tempfile.mkdtemp()
    try:
        repo_url = f"https://{pat}@github.com/{repo}"
        # Configure git (global is fine in container)
        subprocess.run(['git', 'config', '--global', 'user.name', 'ke-pasa-bot'], check=True)
        subprocess.run(['git', 'config', '--global', 'user.email', 'bot@ke-pasa.com'], check=True)
        
        # Clone
        logging.info("Cloning repo...")
        subprocess.run(['git', 'clone', '--depth', '1', '--branch', branch, repo_url, temp_dir], check=True, capture_output=True)
        # Ensure the cloned repo is up-to-date with remote branch
        try:
            logging.info(f"Updating cloned repo to latest {branch} (git pull)")
            subprocess.run(['git', 'pull', '--ff-only', 'origin', branch], cwd=temp_dir, check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logging.warning(f"git pull failed (continuing with cloned snapshot): {e}")
        
        target_dir = os.path.join(temp_dir, 'src', 'content', 'news')

        os.makedirs(target_dir, exist_ok=True)

        # 2. Copy local articles -> target repo
        local_articles_dir = os.path.join(str(root_dir), 'articles')
        copied_files = []
        if os.path.exists(local_articles_dir):
            try:
                for name in os.listdir(local_articles_dir):
                    if not name.lower().endswith('.md'):
                        continue
                    src_path = os.path.join(local_articles_dir, name)
                    dst_path = os.path.join(target_dir, name)
                    try:
                        shutil.copy2(src_path, dst_path)
                        copied_files.append(name)
                        results['synced'] += 1
                    except Exception as cp_err:
                        logging.warning(f"Failed to copy {src_path} -> {dst_path}: {cp_err}")
                        results['errors'].append(f"Copy error for {name}: {cp_err}")
            except Exception as e:
                logging.error(f"Failed to enumerate local articles at {local_articles_dir}: {e}")
                results['errors'].append(f"Local articles read error: {e}")
        else:
            logging.info(f"Local articles directory not found: {local_articles_dir}")

        # 3. Git commit and push
        logging.info("Checking for changes (only news folder)...")
        # Add only the generated articles folder to avoid adding unrelated files
        subprocess.run(['git', 'add', '--all', 'src/content/news'], cwd=temp_dir, check=True)
        
        status = subprocess.run(['git', 'status', '--porcelain'], cwd=temp_dir, capture_output=True, text=True)
        if not status.stdout.strip():
            logging.info("No changes to commit.")
        else:
            msg = f"chore: update articles (synced {results['synced']} files) at {datetime.now().isoformat()}"
            subprocess.run(['git', 'commit', '-m', msg], cwd=temp_dir, check=True)
            logging.info("Pushing changes...")
            subprocess.run(['git', 'push', repo_url, branch], cwd=temp_dir, check=True)
            # After successful push, remove local article files that were the source
            try:
                if copied_files:
                    local_root = os.path.join(str(root_dir), 'articles')
                    removed_count = 0
                    for name in copied_files:
                        try:
                            local_path = os.path.join(local_root, name)
                            if os.path.exists(local_path):
                                os.remove(local_path)
                                removed_count += 1
                        except Exception as rm_err:
                            logging.warning(f"Failed to remove local article file {local_path}: {rm_err}")
                            results['errors'].append(f"Failed to remove local article file {local_path}: {rm_err}")
                    if removed_count:
                        logging.info(f"Removed {removed_count} local article file(s) from {local_root} after sync")
            except Exception:
                logging.exception('Failed during local articles pruning step')
            logging.info("✅ Git sync successful")

    except subprocess.CalledProcessError as e:
        err = f"Git operation failed: {e}"
        if e.stderr:
             err += f" | Stderr: {e.stderr.decode('utf-8', errors='ignore')}"
        logging.error(err)
        results['errors'].append(err)
    except Exception as e:
        err = f"Sync failed: {e}"
        logging.error(err)
        results['errors'].append(err)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
        
    return results

stop_requested = False


def handle_sigterm(signum, frame):
    global stop_requested
    logging.info('Received stop signal (%s), shutting down...', signum)
    stop_requested = True


def do_sync():
    try:
        res = sync_to_git_repo()
        logging.info('sync_to_git_repo result: %s', res)
    except Exception as e:
        logging.exception('Git sync failed: %s', e)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', type=int, default=30, help='Interval in minutes between syncs')
    parser.add_argument('--once', action='store_true', help='Run once then exit')
    parser.add_argument('--articles-dir', type=str, default='articles', help='Local articles directory')
    parser.add_argument('--trigger-file', type=str, default='', help='Optional path to trigger file; when present the daemon will run sync immediately and remove the file')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')

    signal.signal(signal.SIGINT, handle_sigterm)
    try:
        signal.signal(signal.SIGTERM, handle_sigterm)
    except Exception:
        pass

    articles_dir = Path(args.articles_dir)
    trigger_path = Path(args.trigger_file) if args.trigger_file else None
    interval_sec = max(1, args.interval) * 60

    if args.once:
        logging.info('Running one-off git sync (articles_dir=%s)', articles_dir)
        if articles_dir.exists() and any(articles_dir.glob('*.md')):
            do_sync()
        else:
            logging.info('No markdown files found in %s; skipping sync', articles_dir)
        return

    logging.info('Starting git sync daemon: interval=%d minutes, articles_dir=%s', args.interval, articles_dir)
    while not stop_requested:
        try:
            # Priority: if trigger file exists, run sync immediately
            if trigger_path and trigger_path.exists():
                logging.info('Trigger file detected (%s); running immediate sync', trigger_path)
                do_sync()
                try:
                    trigger_path.unlink()
                    logging.info('Removed trigger file %s after sync', trigger_path)
                except Exception:
                    logging.warning('Failed to remove trigger file %s', trigger_path)
            elif articles_dir.exists() and any(articles_dir.glob('*.md')):
                logging.info('Found markdown files in %s; attempting sync...', articles_dir)
                do_sync()
            else:
                logging.debug('No markdown files in %s; skipping sync', articles_dir)
        except Exception:
            logging.exception('Unexpected error in sync loop')

        # Sleep with interruptible loop
        slept = 0
        while slept < interval_sec and not stop_requested:
            time.sleep(1)
            slept += 1

    logging.info('Git sync daemon stopped')


if __name__ == '__main__':
    main()
