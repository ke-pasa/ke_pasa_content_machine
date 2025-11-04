"""
Categorization worker configuration
"""

import os
from dataclasses import dataclass


@dataclass
class CategorizationConfig:
    """Configuration for categorization worker"""
    
    # Lock lease time (seconds)
    lock_lease_sec: int = int(os.getenv('CATEGORIZATION_LOCK_LEASE_SEC', '600'))
    
    # Batch size for processing
    batch_size: int = int(os.getenv('CATEGORIZATION_BATCH_SIZE', '100'))
    
    # Enable urgent news detection
    detect_urgent: bool = os.getenv('CATEGORIZATION_DETECT_URGENT', 'true').lower() == 'true'
    
    # Minimum priority score for urgent marking
    urgent_threshold: float = float(os.getenv('CATEGORIZATION_URGENT_THRESHOLD', '8.0'))
    
    # Update all articles or only new ones
    update_all: bool = os.getenv('CATEGORIZATION_UPDATE_ALL', 'false').lower() == 'true'
    
    @classmethod
    def from_env(cls) -> 'CategorizationConfig':
        """Creates configuration from environment variables"""
        return cls()
