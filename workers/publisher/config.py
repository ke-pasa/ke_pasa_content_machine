"""
Publisher worker configuration
"""

import os
from dataclasses import dataclass


def _env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


@dataclass
class PublisherConfig:
    """Configuration for publisher worker"""

    # Maximum articles to publish per run
    max_articles_per_run: int = 1

    # Delay between publications (seconds)
    publication_delay: int = 60

    # Retry failed publications
    retry_failed: bool = True

    # Maximum retry attempts
    max_retry_attempts: int = 3
    similarity_threshold: float = 0.8
    duplicate_check_days: int = 3
    enable_video_generation: bool = False

    @classmethod
    def from_env(cls) -> 'PublisherConfig':
        """Creates configuration from environment variables"""
        return cls(
            enable_video_generation=_env_flag('ENABLE_VIDEO_GENERATION', default=False),
        )
