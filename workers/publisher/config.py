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
    retry_failed: bool = True

    # Maximum retry attempts
    max_retry_attempts: int = 3
    similarity_threshold: float = 0.8
    duplicate_check_days: int = 3

    @classmethod
    def from_env(cls) -> 'PublisherConfig':
        """Creates configuration from environment variables"""
        return cls()

