"""
Article Generator Worker - module for generating articles
"""

from .ArticleGenerator import ArticleGenerator as ArticleGeneratorWorker
from .config import GeneratorConfig

__all__ = ['ArticleGeneratorWorker', 'GeneratorConfig']
