"""
Publisher Worker - handles article publication to Telegram
"""

import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict
from dotenv import load_dotenv

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()

from workers.tools.firebase_client import get_firebase_client
from jobs_scheduler_backup import PublicationScheduler
from .config import PublisherConfig


class PublisherWorker:
    """Worker for publishing articles to Telegram channels"""
    
    def __init__(self, config: PublisherConfig = None):
        """
        Initialize publisher worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or PublisherConfig.from_env()
        self.db = get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        
        print(f"[publisher] Starting worker id={self.instance_id}")
        print(f"[publisher] Max articles per run: {self.config.max_articles_per_run}")
        print(f"[publisher] Publication delay: {self.config.publication_delay}s")

    def _acquire_lock(self) -> bool:
        """
        Acquires lock for publication process
        
        Returns:
            True if lock acquired, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('publisher')
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
                        print(f"[publisher] Another instance is active (holder: {holder})")
                        return False
            
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self.config.lock_lease_sec)).isoformat(),
                'worker_type': 'publisher'
            })
            print(f"[publisher] ✅ Lock acquired")
            return True
            
        except Exception as e:
            print(f"[publisher] ❌ Lock acquisition error: {e}")
            return False

    def _release_lock(self):
        """Releases the lock"""
        try:
            self.db.collection('locks').document('publisher').delete()
            print(f"[publisher] ✅ Lock released")
        except Exception as e:
            print(f"[publisher] ⚠️  Lock release error: {e}")

    def publish_articles(self) -> Dict:
        """
        Publishes ready articles to Telegram
        
        Returns:
            Dictionary with publication results
        """
        if not self._acquire_lock():
            return {
                'status': 'skipped',
                'reason': 'locked',
                'message': 'Another instance is already running'
            }
        
        try:
            print(f"[publisher] 🚀 Starting publication scheduler...")
            
            # Create and run scheduler
            scheduler = PublicationScheduler()
            results = scheduler.run_scheduler()
            
            published = results.get('articles_published', 0)
            total_checked = results.get('total_articles_checked', 0)
            errors = results.get('errors', [])
            
            print(f"[publisher] ✅ Publication completed")
            print(f"[publisher] Published: {published}/{total_checked}")
            
            if errors:
                print(f"[publisher] ⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    print(f"  • {error}")
            
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
            print(f"[publisher] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            self._release_lock()


def main():
    """Entry point for worker execution"""
    print("=" * 60)
    print("📢 Publisher Worker - Telegram Publication Handler")
    print("=" * 60)
    
    try:
        config = PublisherConfig.from_env()
        worker = PublisherWorker(config)
        result = worker.publish_articles()
        
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Published: {result.get('published', 0)}")
        print(f"Total checked: {result.get('total_checked', 0)}")
        
        if result.get('errors'):
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors'][:5]:
                print(f"  • {error}")
        
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
