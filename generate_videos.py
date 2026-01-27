#!/usr/bin/env python3
"""
Video Generation Script - Generate videos without publishing
"""
import sys
import os
import logging
from pathlib import Path

# Add root directory to path
root_dir = Path(__file__).parent
sys.path.insert(0, str(root_dir))

from workers.publisher.worker import PublisherWorker
from workers.publisher.config import PublisherConfig

def main():
    """Generate videos for articles without publishing"""
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    logger = logging.getLogger(__name__)
    
    print("🎬" + "=" * 60)
    print("📹 VIDEO GENERATION MODE")
    print("🎬" + "=" * 60)
    print("🔹 This mode will generate videos for articles without publishing")
    print("🔹 Videos will be saved in videos/ directory")
    print("🔹 No content will be published to social media")
    print("🎬" + "=" * 60)
    
    try:
        # Create config
        config = PublisherConfig.from_env()
        
        # Initialize worker in video-only mode
        worker = PublisherWorker(config=config, video_only_mode=True)
        
        # Run video generation
        logger.info("🚀 Starting video generation...")
        
        # Run publication (but in video-only mode)
        results = worker.publish_articles(force=True)  # force=True to bypass night hours
        
        logger.info("📊 Video generation completed!")
        logger.info(f"✅ Videos processed: {results.get('published', 0)}")
        logger.info(f"📋 Articles checked: {results.get('checked', 0)}")
        
        if results.get('errors'):
            logger.warning(f"⚠️ Errors encountered: {len(results['errors'])}")
            for error in results['errors']:
                logger.warning(f"  - {error}")
        
        print("🎬" + "=" * 60)
        print("✅ Video generation completed successfully!")
        print("📁 Check the videos/ directory for generated videos")
        print("🎬" + "=" * 60)
        
    except KeyboardInterrupt:
        logger.info("🛑 Video generation interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Video generation failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()