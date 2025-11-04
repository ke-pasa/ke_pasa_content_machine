"""
Categorization Worker - handles article prioritization and categorization
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
from daily_prioritization import DailyPrioritization
from .config import CategorizationConfig


class CategorizationWorker:
    """Worker for article prioritization and categorization"""
    
    def __init__(self, config: CategorizationConfig = None):
        """
        Initialize categorization worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or CategorizationConfig.from_env()
        self.db = get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        
        print(f"[categorization] Starting worker id={self.instance_id}")
        print(f"[categorization] Batch size: {self.config.batch_size}")
        print(f"[categorization] Urgent detection: {self.config.detect_urgent}")
        print(f"[categorization] Urgent threshold: {self.config.urgent_threshold}")

    def _acquire_lock(self) -> bool:
        """
        Acquires lock for categorization process
        
        Returns:
            True if lock acquired, False otherwise
        """
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('categorization')
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
                        print(f"[categorization] Another instance is active (holder: {holder})")
                        return False
                    else:
                        print(f"[categorization] Found stale lock, releasing...")
            
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self.config.lock_lease_sec)).isoformat(),
                'worker_type': 'categorization'
            })
            print(f"[categorization] ✅ Lock acquired")
            return True
            
        except Exception as e:
            print(f"[categorization] ❌ Lock acquisition error: {e}")
            return False

    def _release_lock(self):
        """Releases the lock"""
        try:
            self.db.collection('locks').document('categorization').delete()
            print(f"[categorization] ✅ Lock released")
        except Exception as e:
            print(f"[categorization] ⚠️  Lock release error: {e}")

    def update_priorities(self) -> Dict:
        """
        Updates article priorities and categories
        
        Returns:
            Dictionary with update results
        """
        if not self._acquire_lock():
            return {
                'status': 'skipped',
                'reason': 'locked',
                'message': 'Another instance is already running'
            }
        
        try:
            print(f"[categorization] 🔄 Updating article priorities...")
            
            # Create prioritization instance
            prioritization = DailyPrioritization()
            results = prioritization.update_all_article_priorities()
            
            updated = results.get('updated', 0)
            urgent = results.get('urgent', 0)
            errors = results.get('errors', [])
            
            print(f"[categorization] ✅ Prioritization completed")
            print(f"[categorization] Updated: {updated} articles")
            print(f"[categorization] Urgent: {urgent} articles")
            
            if errors:
                print(f"[categorization] ⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    print(f"  • {error}")
            
            return {
                'status': 'success',
                'updated': updated,
                'urgent': urgent,
                'errors': errors,
                'message': f'Updated {updated} articles, marked {urgent} as urgent',
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            print(f"[categorization] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            self._release_lock()

    def get_statistics(self) -> Dict:
        """
        Gets categorization statistics from Firebase
        
        Returns:
            Dictionary with statistics
        """
        try:
            articles = list(self.db.collection('articles').stream())
            
            stats = {
                'total': len(articles),
                'urgent': 0,
                'by_priority': {
                    'high': 0,  # 8-10
                    'medium': 0,  # 5-7
                    'low': 0  # 0-4
                },
                'by_category': {}
            }
            
            for doc in articles:
                data = doc.to_dict() or {}
                
                # Count urgent
                if data.get('urgent', False):
                    stats['urgent'] += 1
                
                # Count by priority
                priority = data.get('priority_score', 0)
                if priority >= 8:
                    stats['by_priority']['high'] += 1
                elif priority >= 5:
                    stats['by_priority']['medium'] += 1
                else:
                    stats['by_priority']['low'] += 1
                
                # Count by categories
                categories = data.get('categories', [])
                for category in categories:
                    stats['by_category'][category] = stats['by_category'].get(category, 0) + 1
            
            return stats
            
        except Exception as e:
            print(f"[categorization] ⚠️  Statistics error: {e}")
            return {}


def main():
    """Entry point for worker execution"""
    print("=" * 60)
    print("🏷️  Categorization Worker - Article Prioritization")
    print("=" * 60)
    
    try:
        config = CategorizationConfig.from_env()
        worker = CategorizationWorker(config)
        
        # Show current statistics
        stats = worker.get_statistics()
        if stats:
            print(f"\n📊 Current Statistics:")
            print(f"  Total articles: {stats.get('total', 0)}")
            print(f"  Urgent articles: {stats.get('urgent', 0)}")
            print(f"  High priority: {stats.get('by_priority', {}).get('high', 0)}")
            print(f"  Medium priority: {stats.get('by_priority', {}).get('medium', 0)}")
            print(f"  Low priority: {stats.get('by_priority', {}).get('low', 0)}")
        
        # Run prioritization
        result = worker.update_priorities()
        
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Updated: {result.get('updated', 0)}")
        print(f"Urgent: {result.get('urgent', 0)}")
        
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
