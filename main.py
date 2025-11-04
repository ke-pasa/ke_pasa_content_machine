#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
KE PASA - Main Entry Point
Unified interface for all workers

Usage:
    python main.py rss              # Run RSS parser
    python main.py generator        # Run article generator
    python main.py publisher        # Run publisher
    python main.py categorization   # Run categorization
    python main.py all              # Run all workers sequentially
    python main.py status           # Show workers status
"""

import sys
import argparse
from pathlib import Path
from datetime import datetime

# Add workers directory to path
workers_dir = Path(__file__).parent / 'workers'
sys.path.insert(0, str(workers_dir))


def print_banner():
    """Prints application banner"""
    print("=" * 70)
    print("🇪🇸 KE PASA - News Automation System")
    print("=" * 70)
    print(f"⏰ Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()


def run_rss_worker():
    """Runs RSS parser worker"""
    print("📰 Starting RSS Worker...")
    print("-" * 70)
    from workers.rss.worker import main as rss_main
    return rss_main()


def run_generator_worker():
    """Runs article generator worker"""
    print("📝 Starting Article Generator Worker...")
    print("-" * 70)
    from workers.article_generator.worker import main as generator_main
    return generator_main()


def run_publisher_worker():
    """Runs publisher worker"""
    print("📢 Starting Publisher Worker...")
    print("-" * 70)
    from workers.publisher.worker import main as publisher_main
    return publisher_main()


def run_categorization_worker():
    """Runs categorization worker"""
    print("🏷️  Starting Categorization Worker...")
    print("-" * 70)
    from workers.categorization.worker import main as categorization_main
    return categorization_main()


def run_all_workers():
    """Runs all workers sequentially"""
    print("🚀 Running All Workers Sequentially")
    print("=" * 70)
    
    workers = [
        ("RSS Parser", run_rss_worker),
        ("Article Generator", run_generator_worker),
        ("Publisher", run_publisher_worker),
        ("Categorization", run_categorization_worker)
    ]
    
    results = []
    
    for name, worker_func in workers:
        print(f"\n{'='*70}")
        print(f"▶️  Starting: {name}")
        print('='*70)
        
        try:
            worker_func()
            results.append((name, "✅ Success"))
        except SystemExit as e:
            if e.code == 0:
                results.append((name, "✅ Success"))
            else:
                results.append((name, f"❌ Failed (exit code: {e.code})"))
        except Exception as e:
            results.append((name, f"❌ Error: {str(e)}"))
    
    # Print summary
    print("\n" + "=" * 70)
    print("📊 EXECUTION SUMMARY")
    print("=" * 70)
    
    for name, status in results:
        print(f"{name:.<30} {status}")
    
    print("=" * 70)


def show_status():
    """Shows current status of all workers"""
    print("📊 Workers Status")
    print("=" * 70)
    
    try:
    from workers.tools.firebase_client import get_firebase_client
        db = get_firebase_client().db
        
        workers = ['rss_worker', 'article_generator', 'publisher', 'categorization']
        
        for worker_name in workers:
            try:
                lock_doc = db.collection('locks').document(worker_name).get()
                
                if lock_doc.exists:
                    lock_data = lock_doc.to_dict()
                    holder = lock_data.get('holder_id', 'unknown')
                    acquired = lock_data.get('acquired_at', 'N/A')
                    expires = lock_data.get('expires_at', 'N/A')
                    
                    print(f"\n🔒 {worker_name.upper()}")
                    print(f"   Status: LOCKED")
                    print(f"   Holder: {holder}")
                    print(f"   Acquired: {acquired}")
                    print(f"   Expires: {expires}")
                else:
                    print(f"\n✅ {worker_name.upper()}")
                    print(f"   Status: FREE")
                    
            except Exception as e:
                print(f"\n⚠️  {worker_name.upper()}")
                print(f"   Error: {str(e)}")
        
        print("\n" + "=" * 70)
        
    except Exception as e:
        print(f"❌ Error checking status: {e}")


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='KE PASA - News Automation System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py rss              # Run RSS parser
  python main.py generator        # Run article generator
  python main.py publisher        # Run publisher
  python main.py categorization   # Run categorization
  python main.py all              # Run all workers
  python main.py status           # Show status
        """
    )
    
    parser.add_argument(
        'worker',
        choices=['rss', 'generator', 'publisher', 'categorization', 'all', 'status'],
        help='Worker to run'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='KE PASA v1.0.0'
    )
    
    args = parser.parse_args()
    
    print_banner()
    
    try:
        if args.worker == 'rss':
            run_rss_worker()
        elif args.worker == 'generator':
            run_generator_worker()
        elif args.worker == 'publisher':
            run_publisher_worker()
        elif args.worker == 'categorization':
            run_categorization_worker()
        elif args.worker == 'all':
            run_all_workers()
        elif args.worker == 'status':
            show_status()
            
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n\n❌ Critical error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
