"""
Publisher worker configuration
"""

import os
from dataclasses import dataclass


@dataclass
class PublisherConfig:
    """Configuration for publisher worker"""

    # Maximum articles to publish per run
    max_articles_per_run: int = 3

    # Delay between publications (seconds)
    publication_delay: int = 60

    # Retry failed publications
    retry_failed: bool = os.getenv('PUBLISHER_RETRY_FAILED', 'true').lower() == 'true'

    # Maximum retry attempts
    max_retry_attempts: int = 3

    @classmethod
    def from_env(cls) -> 'PublisherConfig':
        """Creates configuration from environment variables"""
        return cls()

    duplicate_check_days: int = 2
