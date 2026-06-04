"""
Categorization worker configuration
"""
import os
from dataclasses import dataclass

@dataclass
class CategorizationConfig:
    """Configuration for categorization worker"""
    
    batch_size: int = 10
    
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
