"""
RSS Worker - Entry point for RSS feed processing
"""

import sys
from .rss_worker import RSSWorker
from .config import RSSConfig


def main():
    """Entry point for starting the worker"""
    print("=" * 60)
    print("🚀 RSS Worker - RSS Feed Parser")
    print("=" * 60)
    
    try:
        # Create configuration
        config = RSSConfig.from_env()
        
        # Create and run worker
        worker = RSSWorker(config)
        result = worker.process_feeds()
        
        # Output result
        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Message: {result.get('message', 'N/A')}")
        
        if result.get('timestamp'):
            print(f"Time: {result['timestamp']}")
        
        # Exit code
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

