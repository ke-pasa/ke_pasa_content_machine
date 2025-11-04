"""
Article generator worker configuration
"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class GeneratorConfig:
    """Configuration for article generator worker"""
    
    # Lock lease time (seconds)
    lock_lease_sec: int = int(os.getenv('GENERATOR_LOCK_LEASE_SEC', '300'))
    
    # Maximum articles per run
    batch_size: int = int(os.getenv('GENERATOR_BATCH_SIZE', '50'))
    
    # Folder for saving articles
    articles_dir: str = os.getenv('GENERATOR_ARTICLES_DIR', 'articles')
    
    # Save articles to files
    save_to_files: bool = os.getenv('GENERATOR_SAVE_FILES', 'true').lower() == 'true'
    
    # Minimum text length for generation
    min_text_length: int = int(os.getenv('GENERATOR_MIN_TEXT_LENGTH', '50'))
    
    # Use AI for enhancement
    use_ai_enhancement: bool = os.getenv('GENERATOR_USE_AI', 'true').lower() == 'true'
    
    @classmethod
    def from_env(cls) -> 'GeneratorConfig':
        """Creates configuration from environment variables"""
        return cls()
    
    def ensure_directories(self):
        """Creates necessary directories"""
        if self.save_to_files:
            Path(self.articles_dir).mkdir(parents=True, exist_ok=True)
