#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS Parser - RSS feeds parser with support for multiple feed structures.
Extracts title, link, summary, published, image and categories from RSS feeds.
Performs content extraction and basic filtering. Full text is extracted for
interesting articles. This module previously used a separate content
generation pipeline; that dependency has been removed and this parser saves
base article records directly to Firebase.
"""

import argparse
import os
import re
import json
import time
import requests
import threading
from workers.tools.url_utils import compute_article_id
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
from datetime import datetime
from dateutil import parser as date_parser
from urllib.parse import urlparse
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup
# Heavy optional runtime dependencies (feedparser, readability, slugify, dotenv)
# are imported lazily inside functions to keep this module import-safe in CI.


def load_env_file():
    """
    Load environment variables from a .env file (if present).
    Not required when running in CI/CD where env vars are set directly.
    """
    try:
        # Import dotenv lazily so missing package won't break imports
        try:
            from dotenv import load_dotenv as _load_dotenv
        except Exception:
            _load_dotenv = None

        if not _load_dotenv:
            print("ℹ️  python-dotenv not installed; using environment variables")
            return False

        result = _load_dotenv()
        if result:
            print("✅ Local .env file loaded")
        else:
            print("ℹ️  No .env file found - using environment variables")
        return result
    except Exception as e:
        print(f"ℹ️  Environment will be used from system variables: {e}")
        return False


# Module-level small JSON cache helpers used by both parser classes.
def load_json_cache(path: str) -> dict:
    """Load a small JSON cache file and return its contents as a dict.

    Returns empty dict on any error.
    """
    try:
        if not os.path.exists(path):
            return {}
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def save_json_cache(path: str, data: dict):
    """Save a small JSON cache to disk atomically (best-effort)."""
    try:
        tmp = f"{path}.tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    except Exception:
        pass


class ImprovedFeedParser:
    """Improved feed parser with handling for problematic feeds."""
    
    def __init__(self):
        self.session = requests.Session()
        # Note: requests.Session does not support a persistent timeout; pass timeouts per request when needed
        
        # User-Agent for better compatibility
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def parse_feed(self, feed_url, max_retries=3):
        """Parse an RSS feed with improved error handling and fallbacks."""
        for attempt in range(max_retries):
            try:
                # Try the standard feedparser first (import lazily)
                try:
                    import feedparser as _feedparser
                except Exception:
                    _feedparser = None

                feed = None
                # Fetch the URL ourselves first to get consistent behavior and
                # to be able to inspect headers/content when parsing fails.
                try:
                    resp = self.session.get(feed_url, timeout=20)
                    resp.raise_for_status()
                    content_type = resp.headers.get('content-type')
                    content_bytes = resp.content
                    if _feedparser:
                        try:
                            feed = _feedparser.parse(content_bytes)
                        except Exception as e:
                            feed = None
                            print(f"⚠️  feedparser.parse raised while parsing bytes: {e}")
                except Exception as e:
                    # If fetching fails, fall back to letting feedparser fetch itself
                    print(f"⚠️  HTTP fetch failed for {feed_url}: {e}")
                    content_type = None
                    content_bytes = None
                
                if not feed.bozo and feed.entries:
                    return feed
                
                # Try manual XML parsing as a fallback
                manual_feed = self._manual_xml_parse(feed_url)
                if manual_feed and manual_feed.get('entries'):
                    return manual_feed

                # If still failing, try correcting the feed URL
                if attempt == 0:
                    corrected_url = self._fix_feed_url(feed_url)
                    if corrected_url != feed_url:
                        if _feedparser:
                            feed = _feedparser.parse(corrected_url)
                        else:
                            feed = None
                        if not feed.bozo and feed.entries:
                            return feed

                # Pause between attempts (exponential backoff)
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)

        return None
    
    def _manual_xml_parse(self, feed_url):
        """Manual XML parsing for problematic feeds."""
        try:
            response = self.session.get(feed_url)
            response.raise_for_status()
            
            # Clean XML from invalid elements
            xml_content = self._clean_xml_content(response.text)
            
            # Parse the cleaned XML
            import xml.etree.ElementTree as ET
            root = ET.fromstring(xml_content)
            
            feed_data = {
                'title': '',
                'link': '',
                'description': '',
                'entries': []
            }
            
            # Extract channel information
            channel = root.find('channel')
            if channel is not None:
                feed_data['title'] = self._safe_text(channel.find('title'))
                feed_data['link'] = self._safe_text(channel.find('link'))
                feed_data['description'] = self._safe_text(channel.find('description'))
                
                # Extract items
                for item in channel.findall('item'):
                    entry = self._create_feed_entry(item)
                    if entry:
                        feed_data['entries'].append(entry)
            
            return feed_data if feed_data['entries'] else None
            
        except Exception as e:
            return None
    
    def _clean_xml_content(self, xml_content):
        """Remove problematic elements from XML content to make it parseable."""
        # Remove div elements embedded in RSS
        xml_content = re.sub(r'<div[^>]*>.*?</div>', '', xml_content, flags=re.DOTALL)
        
        xml_content = re.sub(r'<!--.*?-->', '', xml_content, flags=re.DOTALL)
        
        # Collapse excessive whitespace and newlines
        xml_content = re.sub(r'\s+', ' ', xml_content)
        
        return xml_content.strip()
    
    def _safe_text(self, element):
        """Safely extract text from an XML element."""
        if element is not None and element.text:
            return element.text.strip()
        return ''
    
    def _create_feed_entry(self, item):
        """Create an entry object suitable for downstream processing."""
        try:
            from types import SimpleNamespace
            
            entry = SimpleNamespace()
            entry.title = self._safe_text(item.find('title'))
            entry.link = self._safe_text(item.find('link'))
            entry.description = self._safe_text(item.find('description'))
            entry.published = self._safe_text(item.find('pubDate'))
            entry.guid = self._safe_text(item.find('guid'))
            
            # Validate the entry
            if self._is_valid_entry(entry):
                return entry
            
        except Exception:
            pass
        
        return None
    
    def _is_valid_entry(self, entry):
        """Validate feed entry: must have title and link."""
        # Must have title and link
        if not entry.title or not entry.link:
            return False
        
        # Link must be HTTP/HTTPS
        if not entry.link.startswith(('http://', 'https://')):
            return False
        
        # Filter out archive and XML files
        if any(ext in entry.link.lower() for ext in ['.tar.gz', '.xml', '.zip']):
            return False
        
        return True
    
    def _fix_feed_url(self, original_url):
        """Try to fix common broken RSS feed URLs."""
        parsed = urlparse(original_url)
        
        # Remove query parameters
        if '?' in original_url:
            base_url = original_url.split('?')[0]
            return base_url
        
        # Try alternative paths for known providers
        if 'aemet.es' in original_url:
            # For AEMET try the main page URL
            return 'https://www.aemet.es/es/eltiempo/prediccion/avisos'
        
        return original_url
    
    def _process_improved_feed(self, improved_feed, feed_url):
        """Process data returned by the improved feed parser."""
        feed_info = {
            'title': improved_feed.get('title', 'Untitled'),
            'description': improved_feed.get('description', 'No description'),
            'link': improved_feed.get('link', ''),
            'entries': []
        }
        
        # Process each entry
        for entry in improved_feed.get('entries', []):
            # Extract published date
            published = None
            if hasattr(entry, 'published') and entry.published:
                try:
                    published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                except:
                    published = entry.published
            
            # Create an article record for the improved parser
            article = {
                'title': getattr(entry, 'title', ''),
                'link': getattr(entry, 'link', ''),
                'summary': getattr(entry, 'description', ''),
                'published': published,
                'image': None,  # Improved parser does not extract images
                'categories': [],  # Improved parser does not extract categories
                'category': 'news',  # Default category
                'feed_title': feed_info['title'],  # Add feed title
                'feed_url': feed_url  # Add feed URL
            }
            
            feed_info['entries'].append(article)
        
        return feed_info
    

    def _respect_per_host_delay(self, feed_url: str):
        """Ensure we wait between requests to the same host to avoid throttling."""
        try:
            parsed = urlparse(feed_url)
            host = parsed.netloc or feed_url
            now = int(time.time() * 1000)
            last = self._host_last_time.get(host, 0)
            wait_ms = max(0, self._per_host_delay_ms - (now - last))
            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)
            self._host_last_time[host] = int(time.time() * 1000)
        except Exception:
            pass


def get_full_text(link: str) -> Optional[str]:
    """
    Extract the full text of an article given its URL.

    Args:
        link: Article URL

    Returns:
        Full text string or None if extraction failed
    """
    try:
        # Load the page
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(link, headers=headers, timeout=30)
        response.raise_for_status()

        # Determine encoding
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding

        # Parse HTML
        soup = BeautifulSoup(response.content, 'html.parser')

        # Remove unwanted elements
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()

        # Remove advertisement blocks
        ad_selectors = [
            '[class*="ad"]', '[class*="advertisement"]', '[class*="banner"]',
            '[id*="ad"]', '[id*="advertisement"]', '[id*="banner"]',
            '[class*="social"]', '[class*="share"]', '[class*="comment"]'
        ]
        for selector in ad_selectors:
            for element in soup.select(selector):
                element.decompose()

        # Try to find the main content using BeautifulSoup heuristics first
        content = None

        # Candidate selectors to inspect for main content
        content_selectors = [
            'article',
            '[class*="content"]',
            '[class*="article"]',
            '[class*="post"]',
            '[class*="entry"]',
            '.main-content',
            '.article-content',
            '.post-content',
            '.entry-content',
            '#content',
            '#article',
            '#post',
            'div'
        ]

        candidates = []
        for selector in content_selectors:
            try:
                elems = soup.select(selector)
            except Exception:
                elems = []
            for el in elems:
                text = el.get_text(separator=' ', strip=True)
                if not text:
                    continue
                # score candidate by length and tag density (text / total length)
                text_len = len(text)
                html_len = len(str(el))
                density = float(text_len) / max(1, html_len)
                score = text_len * (0.5 + density)
                candidates.append((score, text_len, density, el))

        if candidates:
            # choose best candidate by score
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            if best[1] > 150 or best[2] > 0.15:
                content = best[3]

        # If BeautifulSoup heuristics didn't find good content, fall back to readability-lxml
        if not content:
            try:
                try:
                    from readability import Document as _Document
                except Exception:
                    _Document = None

                if _Document:
                    doc = _Document(response.text)
                    content_html = doc.summary()
                    content_soup = BeautifulSoup(content_html, 'html.parser')
                    content = content_soup
                else:
                    # readability not available; skip this fallback
                    print("ℹ️  readability-lxml not installed; skipping fallback content extraction")
            except Exception as e:
                print(f"⚠️  readability-lxml failed to extract text: {e}")
                return None

        if not content:
            return None

        # Extract text
        text = content.get_text(separator=' ', strip=True)

        # Clean text
        text = re.sub(r'\s+', ' ', text)  # Remove excessive whitespace
        text = re.sub(r'\n\s*\n', '\n', text)  # Remove empty lines
        text = text.strip()

        # Verify text length is sufficient
        if len(text) < 50:
            return None

        return text

    except Exception as e:
        print(f"⚠️  Error extracting text from {link}: {e}")
        return None


class RSSParser:
    """RSS parser class that extracts content and performs basic filtering."""
    
    def __init__(self, shared_host_last_time: dict = None, shared_processed_articles: set = None, shared_seen_links_runtime: set = None, shared_lock: threading.Lock = None, shared_uploaded_links: set = None):
        # Load environment variables from .env file
        load_env_file()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': os.getenv('RSS_USER_AGENT', 'Mozilla/5.0 (compatible; SpainQuePasaBot/1.0)')
        })
        # Anti-block: per-host delay, ETag/Last-Modified caches
        # Allow sharing host timing between parser instances for correct per-host delay
        self._host_last_time = shared_host_last_time if shared_host_last_time is not None else {}
        # Shared lock to protect host timing and runtime sets when used concurrently
        self._lock = shared_lock or threading.Lock()

        self._bypass_db_cache = os.getenv('BYPASS_DB_CACHE', '0') == '1'
        try:
            self._per_host_delay_ms = int(os.getenv('RSS_PER_HOST_DELAY_MS', '1500'))
        except Exception:
            self._per_host_delay_ms = 1500
        self._etag_cache_path = os.getenv('RSS_ETAG_CACHE', 'rss_etag_cache.json')
        self._lm_cache_path = os.getenv('RSS_LM_CACHE', 'rss_lastmod_cache.json')
        self._etag_cache = load_json_cache(self._etag_cache_path)
        self._lm_cache = load_json_cache(self._lm_cache_path)

        self.db = None
        self.pg = None

        self.processed_articles = shared_processed_articles if shared_processed_articles is not None else set()
        self._seen_links_runtime = shared_seen_links_runtime if shared_seen_links_runtime is not None else set()

        self._uploaded_links = shared_uploaded_links if shared_uploaded_links is not None else set()


    def _respect_per_host_delay(self, feed_url: str):
        """Respect per-host delay to avoid hammering the same host.

        Uses self._per_host_delay_ms and self._host_last_time.
        """
        try:
            p = urlparse(feed_url)
            host = p.netloc
            now_ms = int(time.time() * 1000)
            # Protect reads/writes to the shared host timing map
            try:
                # Compute required wait time while holding the lock, then sleep without the lock.
                wait_ms = 0
                with self._lock:
                    last = self._host_last_time.get(host)
                    if last:
                        elapsed = now_ms - last
                        if elapsed < self._per_host_delay_ms:
                            wait_ms = self._per_host_delay_ms - elapsed
                    else:
                        # No previous access -> no wait
                        wait_ms = 0

                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)

                # After sleeping (or immediately if no wait), update last access time under lock
                with self._lock:
                    self._host_last_time[host] = int(time.time() * 1000)
            except Exception:
                # Fallback: best-effort non-locked wait/update
                last = self._host_last_time.get(host)
                if last:
                    elapsed = now_ms - last
                    if elapsed < self._per_host_delay_ms:
                        time.sleep((self._per_host_delay_ms - elapsed) / 1000.0)
                self._host_last_time[host] = int(time.time() * 1000)
        except Exception:
            pass

    
    def _process_improved_feed(self, improved_feed, feed_url):
        """Process data returned by the improved feed parser."""
        feed_info = {
            'title': improved_feed.get('title', 'Untitled'),
            'description': improved_feed.get('description', 'No description'),
            'link': improved_feed.get('link', ''),
            'entries': []
        }
        
        # Process each entry
        for entry in improved_feed.get('entries', []):
            # Extract published date
            published = None
            if hasattr(entry, 'published') and entry.published:
                try:
                    published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                except:
                    published = entry.published
            
            # Create article record for improved parser
            article = {
                'title': getattr(entry, 'title', ''),
                'link': getattr(entry, 'link', ''),
                'summary': getattr(entry, 'description', ''),
                'published': published,
                'image': None,  # Improved parser does not extract images
                'categories': [],  # Improved parser does not extract categories
                'category': 'news',  # Default category
                'feed_title': feed_info['title'],  # Add feed title
                'feed_url': feed_url  # Add feed URL
            }
            
            feed_info['entries'].append(article)
        
        return feed_info

    
    def save_article(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Save a base article record to Firebase for later processing.

        Args:
            article: Article data dictionary

        Returns:
            Created article ID or None on error
        """
        # Postgres-only save path
        # Create deterministic ID and prepare article_data
        link = article.get('link', '')
        title = article.get('title', '')
        # Deterministic id (centralized helper)
        article_id = compute_article_id(link or '', title or '')[:32]

        article_data = {
            'article_id': article_id,
            'id': article_id,
            'title': title,
            'summary': article.get('summary', ''),
            'content': article.get('content', ''),
            'link': link,
            'published_date': article.get('published', None),
            'image': article.get('image', ''),
            'categories': article.get('categories', []),
            'source_feed': article.get('feed_title', ''),
            'source_link': link,
            'created_at': article.get('created_at') or datetime.now().isoformat(),
            'updated_at': article.get('updated_at') or datetime.now().isoformat(),
            'status': article.get('status', 'NEW'),
            'published': article.get('published_flag') if 'published_flag' in article else None
        }

        try:
            if not self.pg:
                from workers.tools.pg_client import get_pg_client
                self.pg = get_pg_client()
        except Exception as e:
            print(f"    ⚠️  Could not initialize Postgres client: {e}")
            traceback.print_exc()
            self.pg = None

        if self.pg:
            try:
                status = self.pg.save_article(article_data)
                # status is one of: 'inserted', 'exists', 'error'
                if status == 'inserted':
                    try:
                        verbose = os.getenv('RSS_VERBOSE', '0')
                        verbose = True if verbose.lower() in ('1', 'true', 'yes') else False
                    except Exception:
                        verbose = False
                    if verbose:
                        print(f"[RSS_VERBOSE] Article saved to Postgres: {article_id[:8]}")
                    return article_id
                elif status == 'exists':
                    print(f"    🔁 Already in DB by id (Postgres): {article_id[:8]}")
                    # Treat existing row as effectively saved for callers
                    return article_id
                else:
                    print(f"    ⚠️  Postgres reported save failure for {article_id[:8]}")
                    return None
            except Exception as e:
                print(f"    ⚠️  Postgres save error: {e}")
                traceback.print_exc()
                return None
        else:
            print("❌ No Postgres client available to save article")
            return None

    
    def parse_feed(self, feed_url: str):
        """Parse a single RSS feed URL and return normalized feed info.

        Returns a dict with 'title', 'description', 'link', 'entries' or None on failure.
        """
        try:
            # Respect per-host politeness
            self._respect_per_host_delay(feed_url)

            # Conditional GET headers
            headers = {}
            if feed_url in self._etag_cache:
                headers['If-None-Match'] = self._etag_cache[feed_url]
            if feed_url in self._lm_cache:
                headers['If-Modified-Since'] = self._lm_cache[feed_url]

            response = self.session.get(feed_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Save ETag/Last-Modified
            et = response.headers.get('ETag')
            lm = response.headers.get('Last-Modified')
            if et:
                self._etag_cache[feed_url] = et
                save_json_cache(self._etag_cache_path, self._etag_cache)
            if lm:
                self._lm_cache[feed_url] = lm
                save_json_cache(self._lm_cache_path, self._lm_cache)

            # Parse RSS with improved error handling
            try:
                # Use feedparser if available (lazy import)
                try:
                    import feedparser as _feedparser
                except Exception:
                    _feedparser = None

                feed = None
                if _feedparser:
                    feed = _feedparser.parse(response.content)

                # If standard parsing failed or feedparser missing, try improved parser
                if (not feed) or getattr(feed, 'bozo', False) or len(getattr(feed, 'entries', [])) == 0:
                    print(f"⚠️  Standard parsing failed or feedparser missing, trying improved parser...")
                    # Diagnostic dump when content_bytes available
                    try:
                        if content_bytes:
                            snippet = content_bytes[:800].decode('utf-8', 'replace')
                            print(f"⚠️  Response content-type={content_type}; snippet={snippet[:300].replace(chr(10),' ')}")
                    except Exception:
                        pass

                    # Try improved parser as a fallback which does manual XML parsing
                    try:
                        improved_parser = ImprovedFeedParser()
                        improved_feed = improved_parser.parse_feed(feed_url)
                        if improved_feed and improved_feed.get('entries'):
                            print(f"✅ Improved parser succeeded: {len(improved_feed['entries'])} entries")
                            feed = improved_feed
                        else:
                            print(f"❌ Improved parser also failed (no entries)")
                            return None
                    except Exception as e:
                        print(f"❌ Improved parser exception: {e}")
                        import traceback
                        traceback.print_exc()
                        return None

            except Exception as parse_error:
                print(f"❌ RSS parsing error {feed_url}: {parse_error}")

                # Try improved parser as a fallback
                print(f"🔄 Trying improved parser as a fallback...")
                try:
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)

                    if improved_feed and improved_feed.get('entries'):
                        print(f"✅ Improved parser succeeded: {len(improved_feed['entries'])} entries")
                        feed = improved_feed
                    else:
                        print(f"❌ Improved parser did not succeed")
                        return None

                except Exception as fallback_error:
                    print(f"❌ Fallback parser also failed: {fallback_error}")
                    return None

            # Extract feed metadata
            feed_info = {
                'title': '',
                'description': '',
                'link': '',
                'entries': []
            }

            # Determine feed type (standard feedparser or improved parser)
            if hasattr(feed, 'feed'):
                # Standard feedparser
                feed_info['title'] = feed.feed.get('title', 'Untitled')
                feed_info['description'] = feed.feed.get('description', 'No description')
                feed_info['link'] = feed.feed.get('link', '')
                entries = feed.entries
            else:
                # Improved parser
                feed_info['title'] = feed.get('title', 'Untitled')
                feed_info['description'] = feed.get('description', 'No description')
                feed_info['link'] = feed.get('link', '')
                entries = feed.get('entries', [])

            # Process each entry using a single parser helper to avoid duplication
            for entry in entries:
                parsed = self._parse_entry(entry)
                if not parsed:
                    continue

                # Ensure some defaults and source info
                parsed.setdefault('category', 'news')
                parsed['feed_title'] = feed_info['title']
                parsed['feed_url'] = feed_url

                feed_info['entries'].append(parsed)

            return feed_info

        except Exception as e:
            print(f"❌ Error parsing RSS feed {feed_url}: {e}")
            traceback.print_exc()
            return None
    
    def _parse_entry(self, entry) -> Optional[Dict[str, Any]]:
        """
        Parse a single RSS entry

        Args:
            entry: feedparser entry object

        Returns:
            Dictionary with article data
        """
        try:
            # Helper to get field from both dict-like entries and SimpleNamespace
            def _entry_get(name, default=''):
                try:
                    return entry.get(name, default)
                except Exception:
                    return getattr(entry, name, default)

            # Extract main fields
            parsed_entry = {
                'title': _entry_get('title', ''),
                'link': _entry_get('link', ''),
                'summary': self._get_summary(entry),
                'published': self._get_published_date(entry),
                'image': self._get_image(entry),
                'categories': self._get_categories(entry)
            }
            
            # Remove empty fields
            parsed_entry = {k: v for k, v in parsed_entry.items() if v}
            
            return parsed_entry
            
        except Exception as e:
            print(f"Error parsing entry: {e}")
            return None
    
    def _get_summary(self, entry) -> Optional[str]:
        """Extract a short summary/description for an entry"""
        # Try different fields for summary
        try:
            summary = entry.get('summary', '')
        except Exception:
            summary = getattr(entry, 'summary', '')

        if not summary:
            try:
                summary = entry.get('description', '')
            except Exception:
                summary = getattr(entry, 'description', '')

        if not summary:
            # Try content
            try:
                content = entry.get('content', [])
            except Exception:
                content = getattr(entry, 'content', [])
            if content and len(content) > 0:
                try:
                    summary = content[0].get('value', '')
                except Exception:
                    summary = getattr(content[0], 'value', '') if hasattr(content[0], 'value') else ''
        
        return summary
    
    def _get_published_date(self, entry) -> Optional[str]:
        """Extract published date in YYYY-MM-DD format"""
        date_fields = ['published', 'pubDate', 'updated', 'date']
        
        for field in date_fields:
            try:
                date_str = entry.get(field, '')
            except Exception:
                date_str = getattr(entry, field, '')

            if date_str:
                try:
                    # Parse date using dateutil
                    parsed_date = date_parser.parse(date_str)
                    return parsed_date.strftime('%Y-%m-%d')
                except:
                    continue
        
        return None
    
    def _get_image(self, entry) -> Optional[str]:
        """
        Extract an image URL from various sources within the RSS entry

        Args:
            entry: feedparser entry object

        Returns:
            Image URL or None if not found
        """
    # 1. Try media:content (most reliable)
        try:
            media_content = entry.get('media_content', [])
        except Exception:
            media_content = getattr(entry, 'media_content', []) or []
        for media in media_content:
            media_type = media.get('type', '')
            if media_type.startswith('image/'):
                url = media.get('url')
                if url and self._is_valid_image_url(url):
                    return url
        
    # 2. Try media:thumbnail
        try:
            media_thumbnail = entry.get('media_thumbnail', [])
        except Exception:
            media_thumbnail = getattr(entry, 'media_thumbnail', []) or []
        if media_thumbnail:
            url = media_thumbnail[0].get('url')
            if url and self._is_valid_image_url(url):
                return url
        
    # 3. Try enclosures
        try:
            enclosures = entry.get('enclosures', [])
        except Exception:
            enclosures = getattr(entry, 'enclosures', []) or []
        for enclosure in enclosures:
            enclosure_type = enclosure.get('type', '')
            if enclosure_type.startswith('image/'):
                url = enclosure.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
    # 4. Try links with image type
        try:
            links = entry.get('links', [])
        except Exception:
            links = getattr(entry, 'links', []) or []
        for link in links:
            link_type = link.get('type', '')
            if link_type.startswith('image/'):
                url = link.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
    # 5. Try extract from summary/description (look for img tags)
        try:
            summary = entry.get('summary', '') or entry.get('description', '')
        except Exception:
            summary = getattr(entry, 'summary', '') or getattr(entry, 'description', '')
        if summary:
            img_url = self._extract_image_from_html(summary)
            if img_url:
                return img_url
        
    # 6. Try content with HTML
        try:
            content = entry.get('content', [])
        except Exception:
            content = getattr(entry, 'content', []) or []
        if content and len(content) > 0:
            content_value = content[0].get('value', '')
            if content_value:
                img_url = self._extract_image_from_html(content_value)
                if img_url:
                    return img_url
        
    # 7. Try extract from title (if it contains HTML)
        try:
            title = entry.get('title', '')
        except Exception:
            title = getattr(entry, 'title', '')
        if title:
            img_url = self._extract_image_from_html(title)
            if img_url:
                return img_url
        
        return None
    
    def _is_valid_image_url(self, url: str) -> bool:
        """
        Validate whether a URL likely points to an image

        Args:
            url: URL to validate

        Returns:
            True if likely an image, False otherwise
        """
        if not url:
            return False
        
    # Check file extension
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
        url_lower = url.lower()
        
    # Check extension in URL
        for ext in image_extensions:
            if ext in url_lower:
                return True
        
    # Ensure URL does not clearly point to a non-image
        non_image_patterns = ['/ads/', '/banner/', '/logo/', '/icon/']
        for pattern in non_image_patterns:
            if pattern in url_lower:
                return False
        
        return True
    
    def _extract_image_from_html(self, html_content: str) -> Optional[str]:
        """
        Extract first image URL from HTML content

        Args:
            html_content: HTML to search for images

        Returns:
            First image URL found or None
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Find img tags
            img_tags = soup.find_all('img')
            for img in img_tags:
                src = img.get('src')
                if src and self._is_valid_image_url(src):
                    return src
                
                # Try data-src (lazy-loaded images)
                data_src = img.get('data-src')
                if data_src and self._is_valid_image_url(data_src):
                    return data_src

                # Try data-lazy-src (lazy-loaded images)
                data_lazy_src = img.get('data-lazy-src')
                if data_lazy_src and self._is_valid_image_url(data_lazy_src):
                    return data_lazy_src
            
            return None
            
        except Exception as e:
            print(f"⚠️  Error extracting image from HTML: {e}")
            return None
    
    def _get_categories(self, entry) -> List[str]:
        """Extract categories/tags from entry"""
        categories = []
        
    # Try tags
        try:
            tags = entry.get('tags', [])
        except Exception:
            tags = getattr(entry, 'tags', []) or []
        for tag in tags:
            try:
                if tag.get('term'):
                    categories.append(tag['term'])
            except Exception:
                # tag may be a SimpleNamespace
                term = getattr(tag, 'term', None)
                if term:
                    categories.append(term)
        
    # Try category
        try:
            category = entry.get('category', '')
        except Exception:
            category = getattr(entry, 'category', '')
        if category:
            categories.append(category)
        
        return list(set(categories))  # Remove duplicates


    def filter_articles(self, articles: List[Dict[str, Any]], feed_url: str = None, return_stats: bool = False):
        """
        Filter articles for Russian-speaking migrants in Spain
        and save filtered announcements for subsequent clustering.

        Args:
            articles: List of news items to filter
            feed_url: Optional URL of the feed being processed (for logging)

        Returns:
            Filtered list of announcements (only summaries, no article generation)
        """
        feed_info = f"[{feed_url}] " if feed_url else ""
        stats = {
            'total': len(articles),
            'valid': 0,
            'duplicates': 0,
            'text_extracted': 0,
            'saved': 0
        }

        # Limit number of articles only for tests (can be disabled)
        max_articles = None  # Set a number (e.g., 3) to limit in tests
        if max_articles and len(articles) > max_articles:
            articles = articles[:max_articles]
            print(f"{feed_info}🔍 Filtering {len(articles)} articles (test-limited)...")
        else:
            print(f"{feed_info}🔍 Processing {len(articles)} articles...")
        
        filtered_articles = []
        saved_count = 0
        duplicate_count = 0
        
        from workers.tools.url_utils import normalize_link as _norm_link

        # De-duplicate only by normalized link within the incoming batch.
        unique = {}
        for idx, a in enumerate(articles):
            k = _norm_link(a.get('link', ''))
            # If there's no link, treat each item as unique (don't collapse by title)
            if not k:
                k = f"__nolink__{idx}"
            if k not in unique:
                unique[k] = a
        articles = list(unique.values())

        for i, article in enumerate(articles, 1):
            print(f"  Checking article {i}/{len(articles)}: {article.get('title', '')[:50]}...")
            
            # Check article uniqueness by normalized link only
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            article_link_norm = _norm_link(article_link) if article_link else ''
            stats['valid'] += 1
            
            # Check processed_articles with lock when shared between threads (use normalized link)
            try:
                with self._lock:
                    if article_link_norm and article_link_norm in self.processed_articles:
                        print(f"    ⚠️  Duplicate: {article_title[:30]}...")
                        stats['duplicates'] += 1
                        duplicate_count += 1
                        continue
            except Exception:
                if article_link_norm and article_link_norm in self.processed_articles:
                    print(f"    ⚠️  Duplicate: {article_title[:30]}...")
                    stats['duplicates'] += 1
                    duplicate_count += 1
                    continue

            # Local duplicate in current run (use normalized link)
            try:
                with self._lock:
                    if article_link_norm and article_link_norm in self._seen_links_runtime:
                        print(f"    ⚠️  Duplicate link in current run, skipping")
                        duplicate_count += 1
                        continue
                    if article_link_norm:
                        self._seen_links_runtime.add(article_link_norm)
            except Exception:
                if article_link_norm and article_link_norm in self._seen_links_runtime:
                    print(f"    ⚠️  Duplicate link in current run, skipping")
                    duplicate_count += 1
                    continue
                if article_link_norm:
                    self._seen_links_runtime.add(article_link_norm)

            # QUICK CHECK: if link was seen in the last 24 hours (prefetched), skip
            try:
                if article_link_norm and article_link_norm in getattr(self, '_uploaded_links', set()):
                    print(f"    🔁 Recently processed within 24h, skipping")
                    duplicate_count += 1
                    continue
            except Exception:
                # Fail-safe: if something goes wrong with recent-links set, continue normally
                pass

            # Check duplicate by link using Postgres (if available)
            try:
                if (not self._bypass_db_cache) and self.pg and hasattr(self.pg, 'is_duplicate_by_link'):
                    try:
                        if self.pg.is_duplicate_by_link(article_link):
                            print(f"    🔁 Already in DB by link (Postgres), skipping")
                            duplicate_count += 1
                            continue
                    except Exception as e:
                        print(f"    ⚠️  Duplicate-by-link check error (Postgres): {e}")
            except Exception:
                pass

            # Check: recently skipped entries (Postgres helper if available)
            try:
                if (not self._bypass_db_cache) and self.pg and hasattr(self.pg, 'was_skipped_recently'):
                    try:
                        if self.pg.was_skipped_recently(article_link, article_title, article.get('summary', '')):
                            print(f"    🔁 Previously skipped (SKIPPED cache), skipping")
                            duplicate_count += 1
                            continue
                    except Exception as e:
                        print(f"    ⚠️  SKIPPED check error (Postgres): {e}")
            except Exception:
                pass

            # Final duplicate check (Postgres-backed) — prefer link-only check
            if (not self._bypass_db_cache) and self.is_duplicate(article):
                duplicate_count += 1
                continue
            
            # Attempt to extract full text for non-duplicate articles
            print(f"    ⬇️ Extracting full text...")
            if article.get('link'):
                full_text = get_full_text(article['link'])
                if full_text:
                    article['content'] = full_text
                    print(f"    📄 Full text extracted ({len(full_text)} characters)")
                    stats['text_extracted'] += 1

                    try:
                        article_id = self.save_article(article)
                        if article_id:
                            article['article_id'] = article_id
                            stats['saved'] += 1
                            saved_count += 1
                        else:
                            print(f"    ⚠️  Failed to persist article to Postgres: {article.get('title','')[:40]}")
                    except RuntimeError:
                        raise
                    except Exception as e:
                        # Non-initialization errors when saving should be logged but
                        # not crash the entire run.
                        print(f"    ⚠️  Exception while saving article: {e}")

                    # Mark as processed in this run and append to results (protected by lock)
                    try:
                        with self._lock:
                            # store normalized link as processed key
                            self.processed_articles.add(article_link_norm)
                            filtered_articles.append(article)
                    except Exception:
                        self.processed_articles.add(article_link_norm)
                        filtered_articles.append(article)
                else:
                    print(f"    ⚠️  Failed to extract full text")
            else:
                print(f"    ⚠️  No link to extract text from")
        
        feed_stats = f"{feed_info} " if feed_info else ""
        print(f"\n{feed_stats}📊 PROCESSING STATISTICS:")
        print(f"   📋 Total articles found: {stats['total']}")
        print(f"   ✔️  Valid articles: {stats['valid']}")
        print(f"   🔄 Duplicates skipped: {stats['duplicates']}")
        print(f"   📄 Full text extracted: {stats['text_extracted']}")
        print(f"   💾 Articles saved: {stats['saved']}")
        print(f"ℹ️  Next step: generate articles from filtered announcements")
        if return_stats:
            return filtered_articles, stats
        return filtered_articles
    
    def display_feed(self, articles: List[Dict[str, Any]], show_all: bool = False):
        """
        Display RSS feed data in a readable format
        
        Args:
            articles: List of articles to display
            show_all: Show all articles, including not interesting ones
        """
        if not articles:
            print("No data to display")
            return
        
        print("=" * 80)
        print(f"FEED: {articles[0].get('feed_title', 'Untitled')}") # Assuming feed_title is added by parse_feed
        if articles[0].get('feed_description'):
            print(f"Description: {articles[0].get('feed_description')}")
        if articles[0].get('feed_link'):
            print(f"Link: {articles[0].get('feed_link')}")
        print("=" * 80)
        print()
        
        for i, article in enumerate(articles, 1):
            print(f"ARTICLE #{i}")
            print("-" * 40)
            
            # Show translated version if available
            if article.get('translated'):
                translated = article['translated']
                print(f"🌐 TRANSLATED VERSION:")
                print(f"Title: {translated.get('title', '')}")
                print(f"Tags: {', '.join(translated.get('tags', []))}")
                
                content = translated.get('content', '')
                if len(content) > 500:
                    content = content[:500] + "..."
                print(f"Text: {content}")
                print()
                
                # Show original link
                if article.get('link'):
                    print(f"Original: {article['link']}")
            else:
                # Show original version
                if article.get('title'):
                    print(f"Title: {article['title']}")
                
                if article.get('link'):
                    print(f"Link: {article['link']}")
                
                if article.get('published'):
                    print(f"Date: {article['published']}")
                
                if article.get('summary'):
                    # Truncate long description
                    summary = article['summary']
                    if len(summary) > 200:
                        summary = summary[:200] + "..."
                    print(f"Description: {summary}")
                
                if article.get('image'):
                    print(f"Image: {article['image']}")
                
                if article.get('categories'):
                    print(f"Categories: {', '.join(article['categories'])}")
                
                # Show full text (truncated to 500 characters)
                if article.get('content'):
                    content = article['content']
                    if len(content) > 500:
                        content = content[:500] + "..."
                    print(f"Full text: {content}")
            
            print()
    
    def process_multiple_feeds(self, feeds_file: str = 'feeds.txt', shared_uploaded_links: set = None) -> List[Dict[str, Any]]:
        """
        Process multiple RSS feeds listed in a file.

        Args:
            feeds_file: Path to the file with RSS feed URLs

        Returns:
            List of filtered announcements for clustering
        """
        if not os.path.exists(feeds_file):
            print(f"❌ File {feeds_file} not found")
            return []
        
        # Load list of RSS feeds
        feeds = self.load_feeds_from_file(feeds_file)
        if not feeds:
            print(f"❌ Failed to load RSS feeds from {feeds_file}")
            return []
        
        print(f"📋 Found {len(feeds)} RSS feeds to process")
        print("=" * 60)

        # Allow caller to provide a prefetch set to avoid multiple DB queries.
        if shared_uploaded_links is None:
            shared_uploaded_links = set()

        shared_host_last_time = {}
        shared_processed_articles = set()
        shared_seen_links_runtime = set()
        shared_lock = threading.Lock()

        # Number of parallel feed workers (configurable)
        try:
            max_workers = int(os.getenv('RSS_PARALLEL_FEEDS', '4'))
        except Exception:
            max_workers = 4

        all_articles = []
        total_processed = 0
        total_saved = 0

        # Worker that processes a single feed using its own parser but shared runtime state
        def _process_feed(feed_url: str):
            try:
                print(f"\n🔄 Processing (worker) feed: {feed_url}")
                parser = RSSParser(shared_host_last_time=shared_host_last_time,
                                   shared_processed_articles=shared_processed_articles,
                                   shared_seen_links_runtime=shared_seen_links_runtime,
                                   shared_lock=shared_lock,
                                   shared_uploaded_links=shared_uploaded_links)

                feed_data = parser.parse_feed(feed_url)
                if not feed_data or not feed_data.get('entries'):
                    print(f"   ⚠️  Failed to load RSS feed: {feed_url}")
                    # Return empty filtered list and stats indicating zero
                    return [], {'url': feed_url, 'total': 0, 'removed': 0, 'saved': 0}

                articles = feed_data['entries']
                try:
                    max_per_feed = int(os.getenv('RSS_MAX_ITEMS_PER_FEED', '0') or '0')
                except Exception:
                    max_per_feed = 0
                total_in_feed = len(articles)
                if max_per_feed and total_in_feed > max_per_feed:
                    print(f"   ⚖️ Limiting {total_in_feed} → {max_per_feed} items for this feed (RSS_MAX_ITEMS_PER_FEED)")
                    articles = articles[:max_per_feed]

                filtered, stats = parser.filter_articles(articles, feed_url=feed_url, return_stats=True)
                # Build a compact per-feed stats row
                feed_stats = {
                    'url': feed_url,
                    'total': stats.get('total', len(articles)),
                    'removed': stats.get('total', len(articles)) - stats.get('saved', len(filtered)),
                    'saved': stats.get('saved', len(filtered))
                }
                print(f"   📊 Worker processed {len(filtered)} filtered articles for feed {feed_url} (saved={feed_stats['saved']})")
                return filtered, feed_stats
            except Exception as e:
                print(f"   ❌ Error processing {feed_url}: {e}")
                return [], {'url': feed_url, 'total': 0, 'removed': 0, 'saved': 0}

        # Run feed processing in parallel
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for feed_url in feeds:
                futures.append(ex.submit(_process_feed, feed_url))

            # Collect results and per-feed stats from futures
            per_feed_stats = []
            for f in as_completed(futures):
                try:
                    result = f.result()
                    # Support both (filtered, stats) tuple and legacy single-list return
                    if isinstance(result, tuple) and len(result) == 2:
                        filtered_articles, feed_stats = result
                    else:
                        filtered_articles = result or []
                        feed_stats = None

                    if filtered_articles:
                        all_articles.extend(filtered_articles)
                        total_processed += len(filtered_articles)
                        total_saved += len([a for a in filtered_articles if a.get('content')])

                    if feed_stats:
                        per_feed_stats.append(feed_stats)
                except Exception as e:
                    print(f"   ❌ Worker future error: {e}")
        # After processing all feeds, show final statistics
        print("\n" + "=" * 60)
        print(f"🎯 FINAL STATISTICS:")
        print(f"   📋 Feeds processed: {len(feeds)}")
        print(f"   📰 Articles found: {len(all_articles)}")
        print(f"   🤖 Articles filtered: {total_processed}")
        print(f"   💾 Articles saved for generation: {total_saved}")
        print(f"   🔄 Unique processed articles: {len(shared_processed_articles)}")

        # Print per-feed table: URL : #of articles : # of removed : # of saved
        if per_feed_stats:
            print('\n' + '-' * 80)
            print('Per-feed import summary:')
            print(f"{'URL':60} {'#found':>7} {'#removed':>9} {'#saved':>7}")
            print('-' * 80)
            totals = {'total': 0, 'removed': 0, 'saved': 0}
            for row in per_feed_stats:
                url = (row.get('url') or '')[:60]
                found = int(row.get('total', 0))
                removed = int(row.get('removed', 0))
                saved = int(row.get('saved', 0))
                print(f"{url:60} {found:7d} {removed:9d} {saved:7d}")
                totals['total'] += found
                totals['removed'] += removed
                totals['saved'] += saved

            # Totals row
            print('-' * 80)
            print(f"{'TOTAL':60} {totals['total']:7d} {totals['removed']:9d} {totals['saved']:7d}")
            print('-' * 80)

        print(f"   ℹ️  Next step: generate articles from filtered announcements")

        # Optional cleanup: purge old articles older than 15 days from Postgres
        try:
            if hasattr(self, 'pg') and self.pg:
                try:
                    deleted = self.pg.purge_older_than(15)
                    if deleted >= 0:
                        print(f"   🧹 Purged {deleted} articles older than 15 days from Postgres")
                    else:
                        print("   🧹 Purge executed but rowcount unknown")
                except Exception as e:
                    print(f"   ⚠️  Purge failed: {e}")
        except Exception:
            pass

        return all_articles

    def load_feeds_from_file(self, filename: str) -> List[str]:
        """
        Load list of RSS feed URLs from a file.

        Args:
            filename: Path to the file containing feed URLs (one per line)

        Returns:
            List of feed URLs
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            return feeds
        except Exception as e:
            print(f"❌ Error loading file {filename}: {e}")
            return []

    def is_duplicate(self, article: Dict[str, Any]) -> bool:
        """
        Check whether the article already exists in the Firebase database.

        Args:
            article: Dictionary with article data

        Returns:
            True if the article already exists in the DB, False if new
        """
        article_link = article.get('link', '')
        article_title = article.get('title', '')

        # Prefer Postgres duplicate checks
        try:
            if not self.pg:
                from workers.tools.pg_client import get_pg_client
                self.pg = get_pg_client()
        except Exception:
            self.pg = None

        try:
            if self.pg and hasattr(self.pg, 'is_duplicate_article'):
                if self.pg.is_duplicate_article(article_link, article_title):
                    print(f"    🔁 Already in Postgres, skipping")
                    return True
        except Exception as e:
            print(f"    ⚠️  Duplicate check error (Postgres): {e}")

        print(f"    ✅ New article, saving")
        return False


def main():
    parser = argparse.ArgumentParser(description='RSS Parser for Russian-speaking migrants in Spain')
    parser.add_argument('url', nargs='?', help='RSS feed URL to parse')
    parser.add_argument('--feeds', '-f', default='feeds.txt', help='File with list of RSS feed URLs (default: feeds.txt)')
    parser.add_argument('--no-filter', action='store_true', help='Skip filtering')
    parser.add_argument('--display-all', action='store_true', help='Display all items, including not interesting ones')
    
    args = parser.parse_args()
    
    rss_parser = RSSParser()
    
    if args.url:
        # Process a single RSS feed
        print(f"Loading RSS feed: {args.url}")
        feed_data = rss_parser.parse_feed(args.url)
        
        if feed_data and feed_data.get('entries'):
            print(f"✅ Loaded {len(feed_data['entries'])} items")
            print("=" * 80)
            print(f"FEED: {feed_data.get('title', 'Untitled')}")
            print(f"Description: {feed_data.get('description', 'No description')}")
            print(f"Link: {feed_data.get('link', 'No link')}")
            print("=" * 80)
            
            if args.no_filter:
                rss_parser.display_feed(feed_data['entries'], show_all=True)
            else:
                result = rss_parser.filter_articles(feed_data['entries'])
                # filter_articles may return (filtered, stats) if return_stats=True; keep compatibility
                if isinstance(result, tuple):
                    filtered_articles = result[0]
                else:
                    filtered_articles = result
                rss_parser.display_feed(filtered_articles, show_all=args.display_all)
        else:
            print("❌ Failed to load RSS feed")
    else:
        # Process multiple RSS feeds
        print("🚀 Starting processing multiple RSS feeds")
        print("=" * 60)

        if args.no_filter:
            print("⚠️  --no-filter mode is not supported for multiple RSS feeds")
            return

        all_articles = rss_parser.process_multiple_feeds(args.feeds)

        if all_articles:
            print(f"\n📰 Total processed articles: {len(all_articles)}")
        else:
            print("❌ Failed to process RSS feeds")
            return

        if args.display_all:
            print("\n📋 ALL PROCESSED ARTICLES:")
            print("=" * 60)
            for i, article in enumerate(all_articles, 1):
                print(f"\n{i}. {article.get('title', 'No title')}")
                if article.get('content'):
                    print(f"   📝 Content ready")
                print(f"   🔗 {article.get('link', '')}")

if __name__ == "__main__":
    main() 