"""
Publisher worker configuration
"""

import os
from dataclasses import dataclass


@dataclass
class PublisherConfig:
    """Configuration for publisher worker"""
    
    # Lock lease time (seconds)
    lock_lease_sec: int = int(os.getenv('PUBLISHER_LOCK_LEASE_SEC', '300'))
    
    # Maximum articles to publish per run
    max_articles_per_run: int = int(os.getenv('PUBLISHER_MAX_ARTICLES', '10'))
    
    # Delay between publications (seconds)
    publication_delay: int = int(os.getenv('PUBLISHER_DELAY_SEC', '60'))
    
    # Retry failed publications
    retry_failed: bool = os.getenv('PUBLISHER_RETRY_FAILED', 'true').lower() == 'true'
    
    # Maximum retry attempts
    max_retry_attempts: int = int(os.getenv('PUBLISHER_MAX_RETRIES', '3'))
    
    @classmethod
    def from_env(cls) -> 'PublisherConfig':
        """Creates configuration from environment variables"""
        return cls()
