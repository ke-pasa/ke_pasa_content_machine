"""
RSS Worker - Entry point for RSS feed processing
"""

import sys
from .rss_worker import RSSWorker
from .config import RSSConfig
import logging

def main():
    """Entry point for starting the worker"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    logger = logging.getLogger('workers.rss')

    logger.info("=" * 60)
    logger.info("🚀 RSS Worker - RSS Feed Parser")
    logger.info("=" * 60)
    
    try:
        # Create configuration
        config = RSSConfig.from_env()
        
        # Create and run worker
        worker = RSSWorker(config)
        result = worker.process_feeds()
        
        # Output result
        logger.info("\n" + "=" * 60)
        logger.info("📊 RESULTS")
        logger.info("=" * 60)
        logger.info(f"Status: {result['status']}")
        logger.info(f"Message: {result.get('message', 'N/A')}")
        
        if result.get('timestamp'):
            logger.info(f"Time: {result['timestamp']}")
        
        # Exit code
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        logger.info("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        logger.critical(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

