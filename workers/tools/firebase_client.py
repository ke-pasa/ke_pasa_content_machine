#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Centralized client for interacting with Firebase Firestore.

Provides a fixed set of collection names and helper methods used by the
news-generation pipeline.
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional
# Require firebase_admin at import time: any Firebase import error should
# stop module import so calling code sees configuration issues early.
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
    from firebase_admin import firestore as firestore_types
except Exception as e:
    # Fail import early with a helpful message
    raise ImportError(f"firebase_admin is required by workers.tools.firebase_client but failed to import: {e}")

# Constants for collection names
COLLECTIONS = {
    'CLUSTERS': 'clusters',
    'ARTICLES': 'articles', 
    'PUBLISHED': 'published',
    'SOURCES': 'sources',
    'SKIPPED': 'skipped',
    'JOBS': 'jobs',
    'LOG': 'log',
    'SETTINGS': 'settings'
}

# Cache for settings
_settings_cache = None
_settings_cache_time = None
_settings_cache_ttl = 300  # 5 minutes


class FirebaseClient:
    """Centralized client for working with Firebase Firestore."""
    
    def __init__(self, credentials_path: str = 'firebase_key.json'):
        """
        Initialize the Firebase client.

        Args:
            credentials_path: Path to the Firebase service account JSON file.
        """
        self.db = None
        # Verbose mode for additional debug prints
        try:
            self._verbose = os.getenv('FIREBASE_VERBOSE', '0') == '1'
        except Exception:
            self._verbose = False
        self._init_firebase(credentials_path)
    
    def _init_firebase(self, credentials_path: str):
        """Initialize the connection to Firebase using the provided credentials.

        Raises an exception if initialization fails so callers can handle
        configuration issues early.
        """
        try:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"File {credentials_path} not found")
            # Check whether Firebase has already been initialized
            if not firebase_admin._apps:
                cred = credentials.Certificate(credentials_path)
                firebase_admin.initialize_app(cred)

            self.db = firestore.client()
            # Try to determine project/credentials info for debugging
            proj = None
            try:
                # Try reading project_id from the credentials JSON if present
                if os.path.exists(credentials_path):
                    try:
                        with open(credentials_path, 'r', encoding='utf-8') as _f:
                            _j = json.load(_f)
                            proj = _j.get('project_id')
                    except Exception:
                        proj = None
                # Fallback: try to get from firebase_admin app if available
                try:
                    app = firebase_admin.get_app()
                    proj = getattr(app, 'project_id', proj)
                except Exception:
                    pass
            except Exception:
                proj = None

            if proj:
                self._log_event(f"Firebase client initialized (project: {proj})", "info")
            else:
                self._log_event("Firebase client initialized", "info")
            if self._verbose:
                print(f"[FIREBASE_VERBOSE] Initialized Firebase client; project={proj}")
            
        except Exception as e:
            self._log_event(f"Firebase initialization error: {e}", "error")
            raise
    
    def _log_event(self, message: str, level: str = "info"):
        """Log events into the `log` collection.

        If the Firestore client is not available, messages are printed to
        stdout/stderr as a fallback.
        """
        try:
            if os.getenv('FIREBASE_LOG_DISABLED', '0') == '1':
                return
        except Exception:
            pass
        if not self.db:
            print(f"[{level.upper()}] {message}")
            return
        
        try:
            log_data = {
                'message': message,
                'level': level,
                'timestamp': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            
            self.db.collection(COLLECTIONS['LOG']).add(log_data)
            
        except Exception as e:
            print(f"Logging error: {e}")
            print(f"[{level.upper()}] {message}")
    
    def save_cluster(self, cluster: Dict[str, Any]) -> bool:
        """
        Save a cluster document into Firestore.

        Args:
            cluster: Dictionary containing cluster data. Expected to include
                required fields such as 'cluster_id' and 'topic_summary'.

        Returns:
            True when the save succeeded, False otherwise.
        """
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return False
        
        try:
            # Check required fields
            required_fields = ['cluster_id', 'topic_summary', 'sources']
            for field in required_fields:
                if field not in cluster:
                    raise ValueError(f"Missing required field: {field}")
            
            # Add timestamps
            cluster['created_at'] = firestore_types.SERVER_TIMESTAMP
            cluster['updated_at'] = firestore_types.SERVER_TIMESTAMP
            
            # Save to the clusters collection
            doc_ref = self.db.collection(COLLECTIONS['CLUSTERS']).document(cluster['cluster_id'])
            doc_ref.set(cluster, merge=True)
            
            self._log_event(f"Cluster saved: {cluster['cluster_id']}", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Error saving cluster: {e}", "error")
            return False
    
    def get_unpublished_clusters(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Retrieve unpublished clusters from Firestore.

        Args:
            limit: Maximum number of clusters to return.

        Returns:
            A list of cluster dictionaries.
        """
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return []
        
        try:
            clusters_ref = self.db.collection(COLLECTIONS['CLUSTERS'])
            query = clusters_ref.where('published', '==', False).order_by('created_at', direction=firestore_types.Query.DESCENDING).limit(limit)
            
            docs = query.stream()
            clusters = []
            
            for doc in docs:
                cluster_data = doc.to_dict()
                cluster_data['doc_id'] = doc.id
                clusters.append(cluster_data)
            
            self._log_event(f"Retrieved {len(clusters)} unpublished clusters", "info")
            return clusters
            
        except Exception as e:
            self._log_event(f"Error fetching clusters: {e}", "error")
            return []


    def mark_cluster_as_published(self, cluster_id: str) -> bool:
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return False
        try:
            cluster_ref = self.db.collection(COLLECTIONS['CLUSTERS']).document(cluster_id)
            cluster_ref.update({
                'published': True,
                'published_at': firestore_types.SERVER_TIMESTAMP,
                'updated_at': firestore_types.SERVER_TIMESTAMP
            })
            published_data = {
                'cluster_id': cluster_id,
                'published_at': firestore_types.SERVER_TIMESTAMP,
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            self.db.collection(COLLECTIONS['PUBLISHED']).add(published_data)
            self._log_event(f"Cluster marked as published: {cluster_id}", "info")
            return True
        except Exception as e:
            self._log_event(f"Error marking cluster as published: {e}", "error")
            return False

    def is_duplicate_source(self, link: str) -> bool:
        """Return True if a source document with the given link already exists."""
        if not self.db:
            return False
        try:
            sources_ref = self.db.collection(COLLECTIONS['SOURCES'])
            query = sources_ref.where('link', '==', link).limit(1)
            docs = list(query.stream())
            return len(docs) > 0
        except Exception as e:
            self._log_event(f"Error checking duplicate source: {e}", "error")
            return False

    def is_duplicate_hash(self, hash_value: str) -> bool:
        """Return True if a source with the given hash already exists."""
        if not self.db:
            return False
        try:
            sources_ref = self.db.collection(COLLECTIONS['SOURCES'])
            query = sources_ref.where('hash', '==', hash_value).limit(1)
            docs = list(query.stream())
            return len(docs) > 0
        except Exception as e:
            self._log_event(f"Error checking duplicate hash: {e}", "error")
            return False

    def is_duplicate_article(self, link: str, title: str) -> bool:
        """Check whether an article document (by md5(link+title)) exists."""
        if not self.db:
            return False
        try:
            content_hash = hashlib.md5(f"{link}{title}".encode()).hexdigest()
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(content_hash)
            doc = doc_ref.get()
            return getattr(doc, 'exists', False)
        except Exception as e:
            self._log_event(f"Error checking duplicate article: {e}", "error")
            return False

    def is_duplicate_by_link(self, link: str) -> bool:
        """Check whether an article document exists with the same link."""
        if not self.db:
            return False
        try:
            docs = list(self.db.collection(COLLECTIONS['ARTICLES']).where('link', '==', link).limit(1).stream())
            return len(docs) > 0
        except Exception as e:
            self._log_event(f"Error checking duplicate by link: {e}", "error")
            return False

    def mark_skipped(self, link: str, title: str, summary: str, reason: str) -> None:
        """Record a skipped article entry to avoid repeated processing.

        Stores a short-lived marker keyed by md5(link|title|summary[:400]).
        """
        if not self.db:
            return
        try:
            key = f"{link}|{title}|{(summary or '')[:400]}"
            summary_hash = hashlib.md5(key.encode()).hexdigest()
            doc_ref = self.db.collection(COLLECTIONS['SKIPPED']).document(summary_hash)
            doc_ref.set({
                'link': link,
                'title': title,
                'summary_hash': summary_hash,
                'reason': reason,
                'skipped_at': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }, merge=True)
        except Exception as e:
            self._log_event(f"Error saving SKIPPED: {e}", "error")

    def was_skipped_recently(self, link: str, title: str, summary: str, ttl_days: int = 7) -> bool:
        """Return True if a given (link,title,summary) was recorded as skipped within ttl_days."""
        if not self.db:
            return False
        try:
            import datetime as dt
            key = f"{link}|{title}|{(summary or '')[:400]}"
            summary_hash = hashlib.md5(key.encode()).hexdigest()
            doc = self.db.collection(COLLECTIONS['SKIPPED']).document(summary_hash).get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            skipped_at = data.get('skipped_at')
            if not skipped_at:
                return True
            t = dt.datetime.fromisoformat(skipped_at)
            return (dt.datetime.now() - t).days < ttl_days
        except Exception as e:
            self._log_event(f"Error checking SKIPPED: {e}", "error")
            return False

    def save_source_hash(self, link: str, title: str = "", summary: str = "", source_id: str = "", feed_url: str = "") -> bool:
        """Save a source document and its computed hash to Firestore."""
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return False
        try:
            content_for_hash = f"{title}{summary}".strip()
            if not content_for_hash:
                content_for_hash = link
            hash_value = hashlib.md5(content_for_hash.encode()).hexdigest()
            if self.is_duplicate_hash(hash_value):
                self._log_event(f"Source with this hash already exists: {hash_value[:8]}...", "info")
                return True
            source_data = {
                'link': link,
                'hash': hash_value,
                'title': title,
                'summary': summary,
                'source_id': source_id,
                'feed_url': feed_url,
                'parsed_at': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            self.db.collection(COLLECTIONS['SOURCES']).add(source_data)
            self._log_event(f"Source saved: {hash_value[:8]}...", "info")
            return True
        except Exception as e:
            self._log_event(f"Error saving source: {e}", "error")
            return False

    def get_settings(self) -> Dict[str, Any]:
        global _settings_cache, _settings_cache_time
        if (_settings_cache and _settings_cache_time and 
            (datetime.now() - _settings_cache_time).seconds < _settings_cache_ttl):
            return _settings_cache
        if not self.db:
            raise Exception("Firebase is not initialized")
        try:
            settings_ref = self.db.collection(COLLECTIONS['SETTINGS']).document('main')
            doc = settings_ref.get()
            if not doc.exists:
                default_settings = {
                    'cluster_batch_size': 20,
                    'llm_model': 'gpt-4o-mini',
                    'publishing_times': ['09:00', '14:00', '20:00'],
                    'publishing_windows': [
                        {"start": "09:00", "end": "11:00"},
                        {"start": "12:00", "end": "14:00"},
                        {"start": "16:00", "end": "18:00"},
                        {"start": "20:00", "end": "22:00"}
                    ],
                    'max_articles_per_post': 2,
                    'rss_check_interval_minutes': 30,
                    'telegram_chat_id': '',
                    'openai_api_key': '',
                    'created_at': firestore_types.SERVER_TIMESTAMP,
                    'updated_at': firestore_types.SERVER_TIMESTAMP
                }
                settings_ref.set(default_settings)
                settings = default_settings
                self._log_event("Default settings created", "info")
            else:
                settings = doc.to_dict()
            critical_settings = ['llm_model', 'telegram_chat_id']
            missing_settings = [s for s in critical_settings if not settings.get(s)]
            if missing_settings:
                raise Exception(f"Missing critical settings: {', '.join(missing_settings)}")
            _settings_cache = settings
            _settings_cache_time = datetime.now()
            self._log_event("Settings loaded from Firebase", "info")
            return settings
        except Exception as e:
            self._log_event(f"Error getting settings: {e}", "error")
            raise

    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """Persist settings into the `settings/main` document."""
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return False
        try:
            settings['updated_at'] = firestore_types.SERVER_TIMESTAMP
            settings_ref = self.db.collection(COLLECTIONS['SETTINGS']).document('main')
            settings_ref.set(settings, merge=True)
            global _settings_cache, _settings_cache_time
            _settings_cache = None
            _settings_cache_time = None
            self._log_event("Settings updated successfully", "info")
            return True
        except Exception as e:
            self._log_event(f"Error saving settings: {e}", "error")
            return False

    def log_event(self, message: str, level: str = "info") -> None:
        """Public wrapper to log an event into Firestore or stdout fallback."""
        self._log_event(message, level)

    def save_article(self, article: Dict[str, Any]) -> bool:
        """Save an article document to the `articles` collection.

        Uses md5(link+title) as the document id and performs a merge set so
        subsequent pipeline stages can add fields.
        """
        if not self.db:
            self._log_event("Firebase is not initialized", "error")
            return False
        try:
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            content_hash = hashlib.md5(f"{article_link}{article_title}".encode()).hexdigest()
            article['created_at'] = firestore_types.SERVER_TIMESTAMP
            article['updated_at'] = firestore_types.SERVER_TIMESTAMP
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(content_hash)

            # Check if doc exists before saving (useful to diagnose overwrites)
            try:
                existing = doc_ref.get()
                existed = getattr(existing, 'exists', False)
            except Exception:
                existed = False

            doc_ref.set(article, merge=True)

            if existed:
                self._log_event(f"Article updated (was existing): {content_hash[:8]}...", "info")
            else:
                self._log_event(f"Article saved (new): {content_hash[:8]}...", "info")

            if self._verbose:
                try:
                    # Print a compact summary of the article keys being saved
                    sample = article.copy()
                    keys = ','.join(sorted(list(sample.keys())))
                    print(f"[FIREBASE_VERBOSE] save_article: id={content_hash} existed={existed} keys={keys}")
                except Exception:
                    pass

            return True
        except Exception as e:
            self._log_event(f"Error saving article: {e}", "error")
            return False

    def get_article_doc(self, article_id: str) -> Optional[Dict[str, Any]]:
        """Return the article document dict for a given article_id (or None)."""
        if not self.db:
            return None
        try:
            doc = self.db.collection(COLLECTIONS['ARTICLES']).document(article_id).get()
            if getattr(doc, 'exists', False):
                return doc.to_dict()
            return None
        except Exception:
            return None

    def count_articles(self) -> int:
        """Return an approximate count of documents in the `articles` collection.

        Note: this performs a simple stream() count and may be slow for large collections.
        """
        if not self.db:
            return 0
        try:
            docs = list(self.db.collection(COLLECTIONS['ARTICLES']).stream())
            return len(docs)
        except Exception:
            return 0


def compute_article_id(link: str, title: str) -> str:
    """Compute deterministic article document id (md5 of link+title).

    Centralized helper used by multiple modules to ensure the same id
    generation strategy is applied throughout the codebase.
    """
    content = f"{link}{title}"
    return hashlib.md5(content.encode()).hexdigest()

_firebase_client = None


def get_firebase_client() -> FirebaseClient:
    global _firebase_client
    if _firebase_client is None:
        _firebase_client = FirebaseClient()
    return _firebase_client


def reset_firebase_client():
    global _firebase_client
    _firebase_client = None
