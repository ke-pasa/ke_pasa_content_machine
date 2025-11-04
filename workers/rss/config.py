"""
RSS worker configuration
"""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class RSSConfig:
    """Configuration for RSS worker"""
    
    # Path to feeds file
    feeds_file: str = os.path.join(os.path.dirname(__file__), "feeds.txt")
    
    # Lock lease time (seconds)
    lock_lease_sec: int = int(os.getenv('RSS_LOCK_LEASE_SEC', '300'))
    
    # Maximum articles to process per run
    max_articles_per_run: Optional[int] = None
    
    # Request timeout (seconds)
    request_timeout: int = 30
    
    # Number of retry attempts on error
    retry_attempts: int = 3
    
    # Delay between retry attempts (seconds)
    retry_delay: int = 5
    
    @classmethod
    def from_env(cls) -> 'RSSConfig':
        """Creates configuration from environment variables"""
        return cls(
            feeds_file=os.getenv('RSS_FEEDS_FILE', os.path.join(os.path.dirname(__file__), "feeds.txt")),
            lock_lease_sec=int(os.getenv('RSS_LOCK_LEASE_SEC', '300')),
            max_articles_per_run=int(os.getenv('RSS_MAX_ARTICLES', '0')) or None,
            request_timeout=int(os.getenv('RSS_REQUEST_TIMEOUT', '30')),
            retry_attempts=int(os.getenv('RSS_RETRY_ATTEMPTS', '3')),
            retry_delay=int(os.getenv('RSS_RETRY_DELAY', '5'))
        )
