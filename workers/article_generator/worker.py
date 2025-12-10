import argparse
import json
import sys
from pathlib import Path
from dotenv import load_dotenv
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import datetime

root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()

from .ArticleGenerator import ArticleGenerator


def sync_to_git_repo(article_ids: list[str] = None) -> dict:
    results = {'synced': 0, 'errors': []}
    pat = os.getenv('GIT_KE_PASA_PAT')
    if not pat:
        logging.warning("GIT_KE_PASA_PAT not set; skipping git sync")
        return results
    
    repo = os.getenv('ARTICLES_REPO') or 'ke-pasa/ke_pasa_site'
    branch = os.getenv('ARTICLES_REPO_BRANCH') or 'main'
    
    logging.info(f"🔄 Starting git sync to {repo} ({branch})...")
    
    try:
        from workers.tools.pg_client import get_pg_client
        pg = get_pg_client()

        rows = pg.fetch_articles_with_markdown(limit=10000, article_ids=article_ids)
        articles_to_sync = rows
        
        mode_str = f"incremental ({len(article_ids)} articles)" if article_ids else "full"
        logging.info(f"Found {len(articles_to_sync)} articles with markdown content for {mode_str} sync")
    except Exception as e:
        err = f"Failed to fetch articles for sync: {e}"
        logging.error(err)
        results['errors'].append(err)
        return results

    temp_dir = tempfile.mkdtemp()
    try:
        repo_url = f"https://{pat}@github.com/{repo}"
        # Configure git (global is fine in container)
        subprocess.run(['git', 'config', '--global', 'user.name', 'ke-pasa-bot'], check=True)
        subprocess.run(['git', 'config', '--global', 'user.email', 'bot@ke-pasa.com'], check=True)
        
        # Clone
        logging.info("Cloning repo...")
        subprocess.run(['git', 'clone', '--depth', '1', '--branch', branch, repo_url, temp_dir], check=True, capture_output=True)
        
        target_dir = os.path.join(temp_dir, 'src', 'content', 'news')

        os.makedirs(target_dir, exist_ok=True)
        
        # 3. Write files
        for art in articles_to_sync:
            try:
                md = art.get('publish_md')
                # Regex to extract slug from frontmatter
                import re
                slug_match = re.search(r'^slug:\s*(.+)$', md, re.MULTILINE)
                if slug_match:
                    # Strip quotes if present
                    slug = slug_match.group(1).strip().strip('"\'')
                else:
                    title = art.get('title_ru') or 'article'
                    slug = re.sub(r'[^a-z0-9\-]', '-', title.lower())
                    slug = re.sub(r'-{2,}', '-', slug).strip('-')
                    if not slug:
                        slug = str(art.get('article_id') or art.get('id'))

                filename = f"{slug}_{art.get('article_id') or art.get('id')}.md"
                file_path = os.path.join(target_dir, filename)
                
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(md)
                    
                results['synced'] += 1
            except Exception as e:
                logging.error(f"Failed to write file for article {art.get('id')}: {e}")

        # 4. Git commit and push
        logging.info("Checking for changes...")
        subprocess.run(['git', 'add', '.'], cwd=temp_dir, check=True)
        
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
                local_articles_dir = 'articles'
                local_root = os.path.join(str(root_dir), local_articles_dir)
                removed_count = 0
                import re as _re
                for art in articles_to_sync:
                    try:
                        md = art.get('publish_md')
                        slug = None
                        if isinstance(md, str):
                            m = _re.search(r'^slug:\s*(.+)$', md, _re.MULTILINE)
                            if m:
                                slug = m.group(1).strip().strip('"\'')
                        if not slug:
                            title = art.get('title_ru') or 'article'
                            slug = _re.sub(r'[^a-z0-9\-]', '-', (title or '').lower())
                            slug = _re.sub(r'-{2,}', '-', slug).strip('-')
                            if not slug:
                                slug = str(art.get('article_id') or art.get('id'))

                        filename = f"{slug}_{art.get('article_id') or art.get('id')}.md"
                        local_path = os.path.join(local_root, filename)
                        if os.path.exists(local_path):
                            try:
                                os.remove(local_path)
                                removed_count += 1
                            except Exception as rm_err:
                                logging.warning(f"Failed to remove local article file {local_path}: {rm_err}")
                                results['errors'].append(f"Failed to remove local article file {local_path}: {rm_err}")
                    except Exception as perr:
                        logging.warning(f"Error while pruning local file for article {art.get('id')}: {perr}")
                        results['errors'].append(f"Prune error for {art.get('id')}: {perr}")
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


def main() -> None:
    parser = argparse.ArgumentParser(description='Article generator worker CLI')
    parser.add_argument('--batch-size', type=int, default=None, help='How many categorized articles to process in this run')
    parser.add_argument('--article-id', type=str, default=None, help='Process a single article by id')
    parser.add_argument('--continuous', action='store_true', help='Run in continuous mode (infinite loop processing top articles)')
    parser.add_argument('--git-sync-interval', type=int, default=30, help='Git sync interval in minutes (for continuous mode, default 30)')
    parser.add_argument('--save-stages', action='store_true', help='Save translation stage outputs to logs/article_generator_stages/{doc_id}.json')
    args = parser.parse_args()

    # Always configure logging to stdout so CI (GitHub Actions) captures worker logs
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    # ensure not to add multiple StreamHandlers
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)

    # Allow worker logger to propagate to root handler so supervisord/stdout captures it
    logging.getLogger('workers.article_generator').propagate = True

    # Enable stage saving via CLI flag (propagated to worker.metadata.save_stages)

    worker = ArticleGenerator(batch_size=args.batch_size)
    if getattr(args, 'save_stages', False):
        try:
            # set attribute on instance so translator receives flag via metadata
            worker.save_stages = True
        except Exception:
            logging.getLogger('workers.article_generator').exception('Failed to set save_stages on worker')
    
    # Continuous mode - runs indefinitely
    if args.continuous:
        logging.info('🔄 Starting in CONTINUOUS mode')
        try:
            worker.process_continuous(git_sync_interval_minutes=args.git_sync_interval)
        except KeyboardInterrupt:
            logging.info('👋 Continuous mode interrupted by user')
            sys.exit(0)
        except Exception as e:
            logging.exception(f'❌ Continuous mode failed: {e}')
            sys.exit(1)
        return
    
    # Single article mode
    if args.article_id:
        result = worker.process_single_article(args.article_id)
    else:
        # Batch mode
        result = worker.process_articles()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    if not args.article_id:
        translated_ids = result.get('translated_ids') or []
        if translated_ids:
            logging.info(f"Processing incremental git sync for {len(translated_ids)} articles...")
            sync_result = sync_to_git_repo(article_ids=translated_ids)
            logging.info(f"Sync result: {sync_result}")
        else:
             logging.info("No new translated articles to sync.")

    # Treat any non-success status or any collected errors as a failure for CI
    has_errors = bool(result.get('errors'))
    success_status = result.get('status') == 'success'
    exit_code = 0 if (success_status and not has_errors) else 1
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
