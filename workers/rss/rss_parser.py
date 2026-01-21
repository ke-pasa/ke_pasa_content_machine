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
from workers.tools.url_utils import compute_article_id
from concurrent.futures import ThreadPoolExecutor, as_completed
import traceback
from datetime import datetime
from dateutil import parser as date_parser
from urllib.parse import urlparse
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup

import feedparser
import types
import xml.etree.ElementTree as ET
import openai
from readability import Document as ReadabilityDocument
from workers.tools.pg_client import get_pg_client

# Optional module-level helpers (moved from lazy/function-local imports)
from workers.tools.url_utils import normalize_link as _norm_link
from workers.tools.openai_client import get_openai_client, chat_completion as _chat

try:
    # Prefer categorization wrapper if available
    from workers.categorization.CategorizationWorker import _chat_completion as _cc
except Exception:
    _cc = None

# Configuration constants
DEFAULT_REQUEST_TIMEOUT = 30
FEED_FETCH_TIMEOUT = 20
MIN_TEXT_LENGTH = 50
MIN_CONTENT_LENGTH = 150
MIN_CONTENT_DENSITY = 0.15
MAX_SUMMARY_DISPLAY_LENGTH = 200
MAX_CONTENT_DISPLAY_LENGTH = 500
DEFAULT_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
DEFAULT_PER_HOST_DELAY_MS = 1500
IMAGE_EXTENSIONS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg')
NON_IMAGE_PATTERNS = ('/ads/', '/banner/', '/logo/', '/icon/')
AD_SELECTORS = [
    '[class*="ad"]', '[class*="advertisement"]', '[class*="banner"]',
    '[id*="ad"]', '[id*="advertisement"]', '[id*="banner"]',
    '[class*="social"]', '[class*="share"]', '[class*="comment"]'
]
CONTENT_SELECTORS = [
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
    except Exception as e:
        print(f"⚠️  Failed to save cache {path}: {e}")


class EntryHelper:
    """Helper class to extract data from feed entries with fallback support."""
    
    @staticmethod
    def get_field(entry, field_name: str, default=''):
        """Get field from entry, trying both dict-like and attribute access."""
        try:
            return entry.get(field_name, default)
        except (AttributeError, TypeError):
            return getattr(entry, field_name, default)
    
    @staticmethod
    def get_summary(entry) -> str:
        """Extract summary/description from entry with multiple fallbacks."""
        # Try summary field
        summary = EntryHelper.get_field(entry, 'summary', '')
        if summary:
            return summary
        
        # Try description field
        summary = EntryHelper.get_field(entry, 'description', '')
        if summary:
            return summary
        
        # Try content field
        content = EntryHelper.get_field(entry, 'content', [])
        if content and len(content) > 0:
            try:
                return content[0].get('value', '')
            except (AttributeError, TypeError):
                return getattr(content[0], 'value', '') if hasattr(content[0], 'value') else ''
        
        return ''
    
    @staticmethod
    def get_published_date(entry) -> Optional[str]:
        """Extract published date in YYYY-MM-DD format."""
        date_fields = ['published', 'pubDate', 'updated', 'date']
        
        for field in date_fields:
            date_str = EntryHelper.get_field(entry, field, '')
            if date_str:
                try:
                    parsed_date = date_parser.parse(date_str)
                    return parsed_date.strftime('%Y-%m-%d')
                except Exception:
                    continue
        
        return None
    
    @staticmethod
    def get_categories(entry) -> List[str]:
        """Extract categories/tags from entry."""
        categories = []
        
        # Try tags
        tags = EntryHelper.get_field(entry, 'tags', []) or []
        for tag in tags:
            try:
                term = tag.get('term') if hasattr(tag, 'get') else getattr(tag, 'term', None)
                if term:
                    categories.append(term)
            except Exception:
                pass
        
        # Try category
        category = EntryHelper.get_field(entry, 'category', '')
        if category:
            categories.append(category)
        
        return list(set(categories))  # Remove duplicates


class ImprovedFeedParser:
    """Improved feed parser with handling for problematic feeds."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': DEFAULT_USER_AGENT
        })
        # Initialize attributes for per-host delay
        self._host_last_time = {}
        self._per_host_delay_ms = DEFAULT_PER_HOST_DELAY_MS
    
    def parse_feed(self, feed_url, max_retries=3):
        """Parse an RSS feed with improved error handling and fallbacks."""
        for attempt in range(max_retries):
            try:
                # Try the standard feedparser first (import lazily)
                _feedparser = feedparser

                feed = None
                content_type = None
                content_bytes = None
                
                # Fetch the URL ourselves first to get consistent behavior
                try:
                    resp = self.session.get(feed_url, timeout=FEED_FETCH_TIMEOUT)
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
                    print(f"⚠️  HTTP fetch failed for {feed_url}: {e}")
                
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
            response = self.session.get(feed_url, timeout=FEED_FETCH_TIMEOUT)
            response.raise_for_status()
            
            # Clean XML from invalid elements
            xml_content = self._clean_xml_content(response.text)
            
            # Parse the cleaned XML (use module-level ET if available)
            if ET is None:
                raise RuntimeError('xml.etree.ElementTree not available')
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
            print(f"⚠️  Manual XML parsing failed for {feed_url}: {e}")
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
            
        except Exception as e:
            print(f"⚠️  Failed to create feed entry: {e}")
        
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


class ContentExtractor:
    """Extracts full text content from web pages."""
    
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': DEFAULT_USER_AGENT
        })
    
    def extract_full_text(self, link: str) -> Optional[str]:
        """
        Extract the full text of an article given its URL.

        Args:
            link: Article URL

        Returns:
            Full text string or None if extraction failed
        """
        try:
            response = self.session.get(link, timeout=DEFAULT_REQUEST_TIMEOUT)
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
            for selector in AD_SELECTORS:
                for element in soup.select(selector):
                    element.decompose()

            # Try to find the main content using BeautifulSoup heuristics first
            content = self._find_best_content(soup, response.text)

            if not content:
                return None

            # Extract and clean text
            text = content.get_text(separator=' ', strip=True)
            text = re.sub(r'\s+', ' ', text)  # Remove excessive whitespace
            text = re.sub(r'\n\s*\n', '\n', text)  # Remove empty lines
            text = text.strip()

            # Verify text length is sufficient
            if len(text) < MIN_TEXT_LENGTH:
                return None

            return text

        except Exception as e:
            print(f"⚠️  Error extracting text from {link}: {e}")
            return None
    
    def _find_best_content(self, soup: BeautifulSoup, html_text: str) -> Optional[BeautifulSoup]:
        """Find the best content element using heuristics and fallbacks."""
        candidates = []
        
        for selector in CONTENT_SELECTORS:
            try:
                elems = soup.select(selector)
            except Exception:
                elems = []
            
            for el in elems:
                text = el.get_text(separator=' ', strip=True)
                if not text:
                    continue
                
                # Score candidate by length and tag density
                text_len = len(text)
                html_len = len(str(el))
                density = float(text_len) / max(1, html_len)
                score = text_len * (0.5 + density)
                candidates.append((score, text_len, density, el))

        if candidates:
            candidates.sort(key=lambda x: x[0], reverse=True)
            best = candidates[0]
            if best[1] > MIN_CONTENT_LENGTH or best[2] > MIN_CONTENT_DENSITY:
                return best[3]

        # Fallback to readability-lxml
        return self._extract_with_readability(html_text)
    
    def _extract_with_readability(self, html_text: str) -> Optional[BeautifulSoup]:
        """Try to extract content using readability-lxml library."""
        try:
            if ReadabilityDocument is None:
                print("ℹ️  readability-lxml not installed; skipping fallback content extraction")
                return None

            doc = ReadabilityDocument(html_text)
            content_html = doc.summary()
            return BeautifulSoup(content_html, 'html.parser')
            
        except Exception as e:
            print(f"⚠️  readability-lxml failed to extract text: {e}")
            return None


# Legacy function for backward compatibility
def get_full_text(link: str) -> Optional[str]:
    """
    Extract the full text of an article given its URL.
    Legacy wrapper around ContentExtractor.
    
    Args:
        link: Article URL

    Returns:
        Full text string or None if extraction failed
    """
    extractor = ContentExtractor()
    return extractor.extract_full_text(link)


class RSSParser:
    """RSS parser class that extracts content and performs basic filtering."""
    
    def __init__(self, shared_host_last_time: dict = None, shared_processed_articles: set = None, shared_seen_links_runtime: set = None, shared_uploaded_links: set = None):
        # Load environment variables from .env file
        load_env_file()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; SpainQuePasaBot/1.0)'
        })

        self._host_last_time = shared_host_last_time if shared_host_last_time is not None else {}

        self._bypass_db_cache = False
        self._per_host_delay_ms = 1500
        self._etag_cache_path = 'rss_etag_cache.json'
        self._lm_cache_path = 'rss_lastmod_cache.json'
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
            
            # Check if we need to wait (dict access is atomic in Python)
            last = self._host_last_time.get(host)
            wait_ms = 0
            if last:
                elapsed = now_ms - last
                if elapsed < self._per_host_delay_ms:
                    wait_ms = self._per_host_delay_ms - elapsed

            if wait_ms > 0:
                time.sleep(wait_ms / 1000.0)

            # Update last access time (dict write is atomic in Python)
            self._host_last_time[host] = int(time.time() * 1000)
                
        except Exception as e:
            print(f"⚠️  Error in per-host delay for {feed_url}: {e}")

    
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
            'published': article.get('published_flag') if 'published_flag' in article else None,
            'total_score': article.get('total_score')
        }

        self.pg = get_pg_client()

        if self.pg:
            try:
                status = self.pg.save_article(article_data)
                # status is one of: 'inserted', 'exists', 'error'
                if status == 'inserted':
                    print(f"    💾 Inserted to Postgres: {article_id}")
                    return article_id
                elif status == 'exists':
                    print(f"    🔁 Already in DB by id (Postgres): {article_id}")
                    # Treat existing row as effectively saved for callers
                    return article_id
                else:
                    print(f"    ⚠️  Postgres reported save failure for {article_id}")
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

            response = self.session.get(feed_url, headers=headers, timeout=DEFAULT_REQUEST_TIMEOUT)
            
            # Handle 304 Not Modified (no new content since last check)
            if response.status_code == 304:
                print(f"   ℹ️  Feed not modified since last check (304)")
                return None
            
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
            print(f"   🔍 Starting RSS parsing...")
            try:
                # Use feedparser if available (lazy import)
                feed = None
                content_type = response.headers.get('content-type', 'unknown')
                content_bytes = response.content
                
                if feedparser:
                    try:
                        feed = feedparser.parse(content_bytes)
                        print(f"   🔍 feedparser result: bozo={getattr(feed, 'bozo', 'N/A')}, entries={len(getattr(feed, 'entries', []))}")
                    except Exception as fp_err:
                        print(f"   ⚠️ feedparser.parse() exception: {fp_err}")
                        feed = None

                # If standard parsing failed or feedparser missing, try improved parser
                if (not feed) or getattr(feed, 'bozo', False) or len(getattr(feed, 'entries', [])) == 0:
                    print(f"⚠️  Standard parsing failed or feedparser missing, trying improved parser...")
                    # Diagnostic dump
                    try:
                        if content_bytes:
                            snippet = content_bytes[:800].decode('utf-8', 'replace')
                            print(f"⚠️  Response content-type={content_type}; snippet={snippet[:300].replace(chr(10),' ')}")
                    except Exception as e:
                        print(f"⚠️  Could not log diagnostic info: {e}")

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
                        traceback.print_exc()
                        return None

            except Exception as parse_error:
                print(f"❌ RSS parsing error {feed_url}: {parse_error}")
                traceback.print_exc()

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
                    traceback.print_exc()
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
            # Extract main fields using EntryHelper
            parsed_entry = {
                'title': EntryHelper.get_field(entry, 'title', ''),
                'link': EntryHelper.get_field(entry, 'link', ''),
                'summary': EntryHelper.get_summary(entry),
                'published': EntryHelper.get_published_date(entry),
                'image': self._get_image(entry),
                'categories': EntryHelper.get_categories(entry)
            }
            
            # Remove empty fields
            parsed_entry = {k: v for k, v in parsed_entry.items() if v}
            
            return parsed_entry
            
        except Exception as e:
            print(f"⚠️  Error parsing entry: {e}")
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
        media_content = EntryHelper.get_field(entry, 'media_content', []) or []
        for media in media_content:
            media_type = media.get('type', '')
            if media_type.startswith('image/'):
                url = media.get('url')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 2. Try media:thumbnail
        media_thumbnail = EntryHelper.get_field(entry, 'media_thumbnail', []) or []
        if media_thumbnail:
            url = media_thumbnail[0].get('url')
            if url and self._is_valid_image_url(url):
                return url
        
        # 3. Try enclosures
        enclosures = EntryHelper.get_field(entry, 'enclosures', []) or []
        for enclosure in enclosures:
            enclosure_type = enclosure.get('type', '')
            if enclosure_type.startswith('image/'):
                url = enclosure.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 4. Try links with image type
        links = EntryHelper.get_field(entry, 'links', []) or []
        for link in links:
            link_type = link.get('type', '')
            if link_type.startswith('image/'):
                url = link.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 5. Try extract from summary/description (look for img tags)
        summary = EntryHelper.get_summary(entry)
        if summary:
            img_url = self._extract_image_from_html(summary)
            if img_url:
                return img_url
        
        # 6. Try content with HTML
        content = EntryHelper.get_field(entry, 'content', []) or []
        if content and len(content) > 0:
            content_value = content[0].get('value', '')
            if content_value:
                img_url = self._extract_image_from_html(content_value)
                if img_url:
                    return img_url
        
        # 7. Try extract from title (if it contains HTML)
        title = EntryHelper.get_field(entry, 'title', '')
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
        
        url_lower = url.lower()
        
        if any(ext in url_lower for ext in IMAGE_EXTENSIONS):
            return True
        
        if any(pattern in url_lower for pattern in NON_IMAGE_PATTERNS):
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

    def _is_valuable_article(self, article: Dict[str, Any]) -> bool:
        """
        Heuristic to decide whether an article is worth full-text extraction.
        Uses GPT-5-nano to classify news as trash or valuable.
        """        
        return True, 0
    
    def _is_duplicate_by_various_checks(self, article_link: str, article_title: str, article_summary: str, article_link_norm: str) -> bool:
        """
        Consolidated duplicate check using multiple methods.
        
        Returns:
            True if article is a duplicate, False otherwise
        """
        # Check processed_articles (set membership check is atomic)
        if article_link_norm and article_link_norm in self.processed_articles:
            print(f"    ⚠️  Duplicate in processed_articles")
            return True
        
        # Check runtime seen links
        if article_link_norm and article_link_norm in self._seen_links_runtime:
            print(f"    ⚠️  Duplicate link in current run")
            return True
        
        # Check recently uploaded (last 24h)
        if article_link_norm and article_link_norm in self._uploaded_links:
            print(f"    🔁 Recently processed within 24h")
            return True
        
        # Check Postgres duplicate by link
        if not self._bypass_db_cache and self.pg:
            try:
                if hasattr(self.pg, 'is_duplicate_by_link') and self.pg.is_duplicate_by_link(article_link):
                    print(f"    🔁 Already in DB by link (Postgres)")
                    return True
            except Exception as e:
                print(f"    ⚠️  Duplicate-by-link check error (Postgres): {e}")
            
            # Check recently skipped entries
            try:
                if hasattr(self.pg, 'was_skipped_recently') and self.pg.was_skipped_recently(article_link, article_title, article_summary):
                    print(f"    🔁 Previously skipped (SKIPPED cache)")
                    return True
            except Exception as e:
                print(f"    ⚠️  SKIPPED check error (Postgres): {e}")
        
        # Final comprehensive duplicate check
        if not self._bypass_db_cache and self.is_duplicate({'link': article_link, 'title': article_title}):
            return True
        
        return False


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
            'saved': 0,
            'wasted': 0,
            'tokens_used': 0
        }
        
        filtered_articles = []
        saved_count = 0
        duplicate_count = 0

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
            
            # Check article uniqueness by normalized link
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            article_summary = article.get('summary', '')
            article_link_norm = _norm_link(article_link) if article_link else ''
            stats['valid'] += 1
            
            # Consolidated duplicate check
            if self._is_duplicate_by_various_checks(article_link, article_title, article_summary, article_link_norm):
                stats['duplicates'] += 1
                duplicate_count += 1
                continue
            
            # Add to seen links (set.add is atomic)
            if article_link_norm:
                self._seen_links_runtime.add(article_link_norm)
            # Decide if article is valuable enough to fetch full text
            try:
                result = self._is_valuable_article(article)
                if isinstance(result, tuple):
                    valuable, tokens = result
                    stats['tokens_used'] += tokens
                else:
                    valuable = result
            except Exception:
                valuable = True

            if not valuable:
                print(f"    💤 Article considered low-value — saving as wasted")
                # mark as wasted and save minimal record
                article_min = {
                    'title': article.get('title', ''),
                    'link': article.get('link', ''),
                    'summary': article.get('summary', ''),
                    'published': article.get('published', None),
                    'image': article.get('image', ''),
                    'categories': article.get('categories', []),
                    'feed_title': article.get('feed_title', ''),
                    'feed_url': article.get('feed_url', ''),
                    'status': 'WASTED'
                }

                try:
                    article_id = self.save_article(article_min)
                    if article_id:
                        article_min['article_id'] = article_id
                        stats['saved'] += 1
                        stats['wasted'] += 1
                        saved_count += 1
                    else:
                        print(f"    ⚠️  Failed to persist wasted article: {article.get('title','')[:40]}")
                except Exception as e:
                    print(f"    ⚠️  Exception while saving wasted article: {e}")

                self.processed_articles.add(article_link_norm)
                filtered_articles.append(article_min)

                continue

            # Attempt to extract full text only if article marked valuable
            if valuable:
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
                            print(f"    ⚠️  Exception while saving article: {e}")

                        self.processed_articles.add(article_link_norm)
                        filtered_articles.append(article)
                    else:
                        print(f"    ⚠️  Failed to extract full text")
                        # Persist a minimal record marking extraction failure
                        article_failed = {
                            'title': article.get('title', ''),
                            'link': article.get('link', ''),
                            'summary': article.get('summary', ''),
                            'published': article.get('published', None),
                            'image': article.get('image', ''),
                            'categories': article.get('categories', []),
                            'feed_title': article.get('feed_title', ''),
                            'feed_url': article.get('feed_url', ''),
                            'status': 'FAILED'
                        }

                        try:
                            article_id = self.save_article(article_failed)
                            if article_id:
                                article_failed['article_id'] = article_id
                                stats['saved'] += 1
                                saved_count += 1
                                print(f"    💾 Saved record with status FAILED: {article_id}")
                            else:
                                print(f"    ⚠️  Failed to persist FAILED article: {article.get('title','')[:40]}")
                        except Exception as e:
                            print(f"    ⚠️  Exception while saving FAILED article: {e}")

                        # Mark as processed to avoid reprocessing in the same run
                        if article_link_norm:
                            self.processed_articles.add(article_link_norm)
                        filtered_articles.append(article_failed)
                else:
                    print(f"    ⚠️  No link to extract text from")
            else:
                # Defensive: should not reach here because non-valuable articles are continued above
                print(f"    ⚠️  Skipping full-text extraction (article not valuable)")
        
        feed_stats = f"{feed_info} " if feed_info else ""
        print(f"\n{feed_stats}📊 PROCESSING STATISTICS:")
        print(f"   📋 Total articles found: {stats['total']}")
        print(f"   ✔️  Valid articles: {stats['valid']}")
        print(f"   🔄 Duplicates skipped: {stats['duplicates']}")
        print(f"   📄 Full text extracted: {stats['text_extracted']}")
        print(f"   💾 Articles saved: {stats['saved']}")
        print(f"   💭 Wasted (low-value): {stats['wasted']}")
        print(f"   💰 Tokens used: {stats['tokens_used']}")
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
                    if len(summary) > MAX_SUMMARY_DISPLAY_LENGTH:
                        summary = summary[:MAX_SUMMARY_DISPLAY_LENGTH] + "..."
                    print(f"Description: {summary}")
                
                if article.get('image'):
                    print(f"Image: {article['image']}")
                
                if article.get('categories'):
                    print(f"Categories: {', '.join(article['categories'])}")
                
                # Show full text (truncated)
                if article.get('content'):
                    content = article['content']
                    if len(content) > MAX_CONTENT_DISPLAY_LENGTH:
                        content = content[:MAX_CONTENT_DISPLAY_LENGTH] + "..."
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

        # Number of parallel feed workers (configurable)
        try:
            max_workers = 4
        except Exception:
            max_workers = 4

        all_articles = []
        total_processed = 0
        total_saved = 0

        def _process_feed(feed_url: str):
            try:
                print(f"\n🔄 Processing (worker) feed: {feed_url}")
                parser = RSSParser(shared_host_last_time=shared_host_last_time,
                                   shared_processed_articles=shared_processed_articles,
                                   shared_seen_links_runtime=shared_seen_links_runtime,
                                   shared_uploaded_links=shared_uploaded_links)

                feed_data = parser.parse_feed(feed_url)
                if not feed_data or not feed_data.get('entries'):
                    print(f"   ⚠️  Failed to load RSS feed: {feed_url}")
                    return [], {'url': feed_url, 'total': 0, 'removed': 0, 'saved': 0}

                articles = feed_data['entries']

                max_per_feed = 0
                total_in_feed = len(articles)
                if max_per_feed and total_in_feed > max_per_feed:
                    print(f"   ⚖️ Limiting {total_in_feed} → {max_per_feed} items for this feed (RSS_MAX_ITEMS_PER_FEED)")
                    articles = articles[:max_per_feed]

                filtered, stats = parser.filter_articles(articles, feed_url=feed_url, return_stats=True)

                feed_stats = {
                    'url': feed_url,
                    'total': stats.get('total', len(articles)),
                    'removed': stats.get('total', len(articles)) - stats.get('saved', len(filtered)),
                    'saved': stats.get('saved', len(filtered)),
                    'wasted': stats.get('wasted', 0),
                    'tokens': stats.get('tokens_used', 0)
                }
                print(f"   📊 Worker processed {len(filtered)} filtered articles for feed {feed_url} (saved={feed_stats['saved']})")
                return filtered, feed_stats
            except Exception as e:
                print(f"   ❌ Error processing {feed_url}: {e}")
                return [], {'url': feed_url, 'total': 0, 'removed': 0, 'saved': 0, 'wasted': 0, 'tokens': 0}

        # Run feed processing in parallel
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            for feed_url in feeds:
                futures.append(ex.submit(_process_feed, feed_url))

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

        # Calculate total tokens used
        total_tokens = sum(row.get('tokens', 0) for row in per_feed_stats)
        
        print("\n" + "=" * 60)
        print(f"🎯 FINAL STATISTICS:")
        print(f"   📋 Feeds processed: {len(feeds)}")
        print(f"   📰 Articles found: {len(all_articles)}")
        print(f"   🤖 Articles filtered: {total_processed}")
        print(f"   💾 Articles saved for generation: {total_saved}")
        print(f"   🔄 Unique processed articles: {len(shared_processed_articles)}")
        print(f"   🪙 Total tokens used: {total_tokens:,}")


        if per_feed_stats:
            print('\n' + '-' * 105)
            print('Per-feed import summary:')
            print(f"{'URL':60} {'#found':>7} {'#removed':>9} {'#saved':>7} {'#wasted':>8} {'tokens':>10}")
            print('-' * 105)
            totals = {'total': 0, 'removed': 0, 'saved': 0, 'wasted': 0, 'tokens': 0}
            for row in per_feed_stats:
                url = (row.get('url') or '')[:60]
                found = int(row.get('total', 0))
                removed = int(row.get('removed', 0))
                saved = int(row.get('saved', 0))
                wasted = int(row.get('wasted', 0))
                tokens = int(row.get('tokens', 0))
                print(f"{url:60} {found:7d} {removed:9d} {saved:7d} {wasted:8d} {tokens:10d}")
                totals['total'] += found
                totals['removed'] += removed
                totals['saved'] += saved
                totals['wasted'] += wasted
                totals['tokens'] += tokens

            # Totals row
            print('-' * 105)
            print(f"{'TOTAL':60} {totals['total']:7d} {totals['removed']:9d} {totals['saved']:7d} {totals['wasted']:8d} {totals['tokens']:10d}")
            print('-' * 105)

        print(f"   ℹ️  Next step: generate articles from filtered announcements")

        try:
            self.pg = get_pg_client()

            try:
                # Purge articles older than 8 days per retention policy
                print("   🔔 ABOUT TO CALL purge_older_than(days=8) on Postgres client")
                deleted = self.pg.purge_older_than(8)
                if deleted >= 0:
                    print(f"   🧹 Purged {deleted} articles older than 8 days from Postgres")
                else:
                    print("   🧹 Purge executed but rowcount unknown")
            except Exception as e:
                print(f"   ⚠️  Purge failed: {e}")
        except Exception:
            pass

        # After processing feeds, handle any user-requested forced publishes
        try:
            self.process_user_requests()
        except Exception as e:
            print(f"   ⚠️  process_user_requests failed: {e}")

        return all_articles

    def process_user_requests(self) -> None:
        """
        Process rows from public.force_publish_links with status 'pending'.

        For each pending URL:
        - attempt to fetch full text using get_full_text
        - ask OpenAI `gpt-4o-mini` to split the article into JSON: {title, description, body}
        - save the article via `save_article` (status 'FORCED')
        - mark force_publish_links.status = 'done' or 'failed'
        """
        try:
            # Ensure Postgres client is available
            self.pg = get_pg_client()

            conn, pooled = self.pg._get_conn()
            cur = conn.cursor()
            try:
                cur.execute("SELECT id, url FROM public.force_publish_links WHERE status = 'pending'")
                rows = cur.fetchall()
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self.pg._put_conn(conn, pooled)

            if not rows:
                return

            client = get_openai_client()

            for row in rows:
                try:
                    fp_id = row[0]
                    url = row[1]
                    print(f"   🔔 Processing forced-publish request: {fp_id} -> {url}")

                    full_text = None
                    try:
                        full_text = get_full_text(url)
                    except Exception as e:
                        print(f"    ⚠️ Failed to fetch full text for {url}: {e}")

                    if not full_text:
                        # mark failed
                        try:
                            conn2, pooled2 = self.pg._get_conn()
                            cur2 = conn2.cursor()
                            try:
                                cur2.execute("UPDATE public.force_publish_links SET status = %s WHERE id = %s", ('failed', fp_id))
                                try:
                                    conn2.commit()
                                except Exception:
                                    pass
                            finally:
                                try:
                                    cur2.close()
                                except Exception:
                                    pass
                                self.pg._put_conn(conn2, pooled2)
                        except Exception:
                            pass
                        continue

                    # Ask LLM to split into title/description/body
                    title = None
                    description = None
                    body = None

                    if client:
                        try:
                            system = 'Split the provided article text into JSON with keys: title (short title), description (one-sentence summary), body (full article body). Return ONLY valid JSON, no markdown formatting.'
                            user = f"Article URL: {url}\n\nText:\n{full_text[:30000]}"
                            
                            # Call OpenAI with strict JSON response format
                            try:
                                response = client.chat.completions.create(
                                    model='gpt-4o-mini',
                                    messages=[
                                        {"role": "system", "content": system},
                                        {"role": "user", "content": user}
                                    ],
                                    max_tokens=1200,
                                    temperature=0,
                                    response_format={"type": "json_object"}
                                )
                                # Extract text from response
                                resp_text = None
                                if hasattr(response, 'choices') and len(response.choices) > 0:
                                    choice = response.choices[0]
                                    if hasattr(choice, 'message') and hasattr(choice.message, 'content'):
                                        resp_text = choice.message.content
                            except Exception as e:
                                print(f"    ⚠️ OpenAI call failed: {e}")
                                resp_text = None

                            if resp_text:
                                # Clean markdown code fences if present
                                resp_text = resp_text.strip()
                                if resp_text.startswith('```json'):
                                    resp_text = resp_text[7:]  # Remove ```json
                                if resp_text.startswith('```'):
                                    resp_text = resp_text[3:]  # Remove ```
                                if resp_text.endswith('```'):
                                    resp_text = resp_text[:-3]  # Remove trailing ```
                                resp_text = resp_text.strip()

                                # Try to parse JSON from cleaned text
                                try:
                                    parsed = json.loads(resp_text)
                                    title = parsed.get('title')
                                    description = parsed.get('description')
                                    body = parsed.get('body')
                                except Exception as json_err:
                                    print(f"    ⚠️ JSON parse failed: {json_err}")
                                    # fallback: heuristics
                                    parts = resp_text.split('\n\n', 2)
                                    if parts:
                                        title = parts[0].strip()
                                    if len(parts) > 1:
                                        description = parts[1].strip()
                                    if len(parts) > 2:
                                        body = parts[2].strip()
                        except Exception as e:
                            print(f"    ⚠️ LLM split failed for {url}: {e}")

                    # Fallback to using the fetched text as body if split failed
                    if not body:
                        body = full_text
                    if not title:
                        # try to take first headline-like line
                        title = (body.split('\n', 1)[0] or url)[:200]
                    if not description:
                        description = (body[:300].strip())

                    # Save to articles via existing save path
                    article = {
                        'title': title,
                        'summary': description,
                        'content': body,
                        'link': url,
                        'published': datetime.now().date().isoformat(),
                        'image': None,
                        'categories': [],
                        'feed_title': 'forced',
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat(),
                        'status': 'CATEGORIZED',
                        'published_flag': False,
                        'total_score': 90
                    }

                    try:
                        aid = self.save_article(article)
                        if aid:
                            print(f"    💾 Forced-publish saved article id: {aid}")
                            # mark as done
                            try:
                                conn3, pooled3 = self.pg._get_conn()
                                cur3 = conn3.cursor()
                                try:
                                    cur3.execute("UPDATE public.force_publish_links SET status = %s WHERE id = %s", ('done', fp_id))
                                    try:
                                        conn3.commit()
                                    except Exception:
                                        pass
                                finally:
                                    try:
                                        cur3.close()
                                    except Exception:
                                        pass
                                    self.pg._put_conn(conn3, pooled3)
                            except Exception:
                                pass
                        else:
                            # mark failed
                            try:
                                conn4, pooled4 = self.pg._get_conn()
                                cur4 = conn4.cursor()
                                try:
                                    cur4.execute("UPDATE public.force_publish_links SET status = %s WHERE id = %s", ('failed', fp_id))
                                    try:
                                        conn4.commit()
                                    except Exception:
                                        pass
                                finally:
                                    try:
                                        cur4.close()
                                    except Exception:
                                        pass
                                    self.pg._put_conn(conn4, pooled4)
                            except Exception:
                                pass

                    except Exception as e:
                        print(f"    ⚠️  Saving forced article failed for {url}: {e}")
                        try:
                            conn5, pooled5 = self.pg._get_conn()
                            cur5 = conn5.cursor()
                            try:
                                cur5.execute("UPDATE public.force_publish_links SET status = %s WHERE id = %s", ('failed', fp_id))
                                try:
                                    conn5.commit()
                                except Exception:
                                    pass
                            finally:
                                try:
                                    cur5.close()
                                except Exception:
                                    pass
                                self.pg._put_conn(conn5, pooled5)
                        except Exception:
                            pass

                except Exception as e:
                    print(f"    ⚠️  Error processing force_publish_links row: {e}")

        except Exception as overall:
            print(f"    ⚠️ process_user_requests overall error: {overall}")

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

        self.pg = get_pg_client()

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
            
            result = rss_parser.filter_articles(feed_data['entries'])

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