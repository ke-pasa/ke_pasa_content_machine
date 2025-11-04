#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS Parser - RSS feeds parser with support for multiple feed structures.
Extracts title, link, summary, published, image and categories from RSS feeds.
Performs content extraction and basic filtering; LLM-based filtering is
currently disabled in this parser. Full text is extracted for interesting
articles. This module previously used a separate content generation pipeline;
that dependency has been removed and this parser saves base article records
directly to Firebase.
"""

import feedparser
import argparse
import os
import re
import json
import time
import requests
from datetime import datetime
from dateutil import parser as date_parser
from urllib.parse import urlparse
from typing import Dict, List, Optional, Any
from bs4 import BeautifulSoup
from readability import Document
from slugify import slugify
# firebase_client import is deferred to avoid heavy initialization at module import time
from dotenv import load_dotenv


def load_env_file():
    """
    Load environment variables from a .env file (if present).
    Not required when running in CI/CD where env vars are set directly.
    """
    try:
        result = load_dotenv()
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
                # Try the standard feedparser first
                feed = feedparser.parse(feed_url)
                
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
                        feed = feedparser.parse(corrected_url)
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
        
        # Remove HTML comments
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

        # Try to find the main content using BeautifulSoup
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
            '#post'
        ]

        content = None
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                # Choose the largest element by text length
                largest_element = max(elements, key=lambda x: len(x.get_text()))
                if len(largest_element.get_text().strip()) > 100:
                    content = largest_element
                    break

        # If BeautifulSoup didn't find content, fall back to readability-lxml
        if not content:
            try:
                doc = Document(response.text)
                content_html = doc.summary()
                content_soup = BeautifulSoup(content_html, 'html.parser')
                content = content_soup
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
    
    def __init__(self):
        # Load environment variables from .env file
        load_env_file()

        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': os.getenv('RSS_USER_AGENT', 'Mozilla/5.0 (compatible; SpainQuePasaBot/1.0)')
        })
        # Anti-block: per-host delay, ETag/Last-Modified caches
        self._host_last_time = {}
        # Flag to bypass Firebase cache (duplicates/skips) for a single run
        self._bypass_db_cache = os.getenv('BYPASS_DB_CACHE', '0') == '1'
        try:
            self._per_host_delay_ms = int(os.getenv('RSS_PER_HOST_DELAY_MS', '1500'))
        except Exception:
            self._per_host_delay_ms = 1500
        self._etag_cache_path = os.getenv('RSS_ETAG_CACHE', 'rss_etag_cache.json')
        self._lm_cache_path = os.getenv('RSS_LM_CACHE', 'rss_lastmod_cache.json')
        self._etag_cache = load_json_cache(self._etag_cache_path)
        self._lm_cache = load_json_cache(self._lm_cache_path)
        # Initialize Firebase lazily (import inside __init__ to avoid network calls at module import)
        try:
            from workers.tools.firebase_client import get_firebase_client
            self.db = get_firebase_client()
            print("✅ Firebase connected successfully")
        except Exception as e:
            print(f"❌ Firebase initialization error: {e}")
            self.db = None

        # Set to track unique articles processed in this run
        self.processed_articles = set()
        self._seen_links_runtime = set()

        # Always use direct requests (batch system removed)
        self.use_batch = False


    def _respect_per_host_delay(self, feed_url: str):
        """Respect per-host delay to avoid hammering the same host.

        Uses self._per_host_delay_ms and self._host_last_time.
        """
        try:
            p = urlparse(feed_url)
            host = p.netloc
            now_ms = int(time.time() * 1000)
            last = self._host_last_time.get(host)
            if last:
                elapsed = now_ms - last
                if elapsed < self._per_host_delay_ms:
                    to_sleep = (self._per_host_delay_ms - elapsed) / 1000.0
                    time.sleep(to_sleep)
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
    
    def process_single_article(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Process a single article: save base article record to Firebase.
        This method now extracts full text for a single article and returns
        the updated article dict (with 'content') or None on failure.
        It does NOT save anything to Firebase — persistence is a downstream concern.

        Args:
            article: Dictionary with article data

        Returns:
            Article dict with 'content' or None on error
        """
        try:
            # Extract full text and return article with content (no DB save here)
            if article.get('link'):
                full_text = get_full_text(article['link'])
                if full_text:
                    article['content'] = full_text
                    print(f"    ✅ Article processed (content extracted)")
                    return article
                else:
                    print(f"    ❌ Failed to extract full text for article")
                    return None
            else:
                print(f"    ⚠️  No link to extract for single article")
                return None
                
        except Exception as e:
            print(f"    ❌ Error while processing article: {e}")
            return None
    
    def save_article_for_clustering(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Save a base article record to Firebase for later processing.

        Args:
            article: Article data dictionary

        Returns:
            Created article ID or None on error
        """
        # Deprecated stub: parser no longer performs persistence.
        # Downstream workers are responsible for saving articles to Firebase or other stores.
        print("⚠️  save_article_for_clustering is deprecated in RSSParser; persistence is handled downstream.")
        return None

    
    def save_article_md(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Save article as a Markdown file (legacy method for compatibility).

        Args:
            article: Dictionary with article data

        Returns:
            Path to the saved markdown file or None on error
        """
        if not article.get('translated'):
            print("⚠️  Article has not been processed (no translated content)")
            return None
        
        translated = article['translated']
        title = translated.get('title', '')
        description = translated.get('description', '')
        content = translated.get('content', '')
        tags = translated.get('tags', [])
        
        if not title or not content:
            print("⚠️  Not enough data to save (title/content missing)")
            return None
        
    # Determine category and target directory
        category = article.get('category', 'news')
        if category == 'article':
            save_dir = 'spain-news-portal/src/content/articles'
        else:
            save_dir = 'spain-news-portal/src/content/news'
        
    # Create directory if it doesn't exist
        os.makedirs(save_dir, exist_ok=True)

        # Generate slug from title
        slug = slugify(title, max_length=50)

        # Get publication date
        pub_date = article.get('published', datetime.now().strftime('%Y-%m-%d'))
        if isinstance(pub_date, str):
            try:
                # Parse date if it's string
                parsed_date = date_parser.parse(pub_date)
                pub_date = parsed_date.strftime('%Y-%m-%d')
            except:
                pub_date = datetime.now().strftime('%Y-%m-%d')

        # Build filename
        filename = f"{pub_date}-{slug}.md"
        filepath = os.path.join(save_dir, filename)

        # Check file doesn't already exist
        if os.path.exists(filepath):
            print(f"⚠️  File already exists: {filepath}")
            return None

        # Get image
        image_url = article.get('image', '')

        # Build frontmatter
        frontmatter = f"""---
title: "{title}"
description: "{description}"
pubDate: {pub_date}
tags: {tags}
slug: "{slug}"
image: "{image_url}"
author: "AI-translation"
category: "{category}"
---

"""
        # Build the full file content
        file_content = frontmatter + content

        try:
            # Save file
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)

            print(f"✅ Saved: {filepath}")
            return filepath

        except Exception as e:
            print(f"❌ Error saving file: {e}")
            return None
    
    
    def parse_feed(self, feed_url: str) -> Dict[str, Any]:
        """
        Parses RSS feed by URL

        Args:
            feed_url: RSS feed URL

        Returns:
            Dictionary with RSS feed data
        """
        try:
            print(f"   🔍 Starting RSS feed parsing...")
            
            # Anti-block: per-host delay + Conditional GET
            self._respect_per_host_delay(feed_url)
            headers = {}
            if feed_url in self._etag_cache:
                headers['If-None-Match'] = self._etag_cache[feed_url]
            if feed_url in self._lm_cache:
                headers['If-Modified-Since'] = self._lm_cache[feed_url]
            
            print(f"   📡 Sending HTTP request...")
            
            # Backoff loop
            attempt = 0
            final_url = feed_url
            while True:
                attempt += 1
                try:
                    response = self.session.get(feed_url, headers=headers, timeout=30, allow_redirects=True)
                    final_url = response.url  # Save final URL after redirects
                    print(f"   ✅ HTTP request successful: {response.status_code}")
                except Exception as e:
                    print(f"   ❌ HTTP request failed (attempt {attempt}): {e}")
                    if attempt <= 3:
                        time.sleep(min(10, 2 ** attempt))
                        continue
                    raise e
                if response.status_code in (429, 503):
                    print(f"   ⚠️  HTTP {response.status_code}, retrying...")
                    if attempt <= 3:
                        time.sleep(min(20, 2 ** attempt))
                        continue
                break
            
            # If a redirect happened, show information
            if final_url != feed_url:
                print(f"   📍 Redirect: {feed_url} → {final_url}")
            if response.status_code == 304:
                # Not modified - try improved parser
                print(f"   ⚠️  HTTP 304 (Not Modified), trying improved parser...")
                try:
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)
                    
                    if improved_feed and improved_feed.get('entries'):
                        print(f"   ✅ Improved parser succeeded: {len(improved_feed['entries'])} entries")
                        return self._process_improved_feed(improved_feed, feed_url)
                    else:
                        print(f"   ❌ Improved parser did not succeed")
                        return {'title': '', 'description': '', 'link': feed_url, 'entries': []}
                        
                except Exception as fallback_error:
                    print(f"   ❌ Fallback parser failed: {fallback_error}")
                    return {'title': '', 'description': '', 'link': feed_url, 'entries': []}
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
                feed = feedparser.parse(response.content)
                
                # If standard parsing failed, try improved parser
                if feed.bozo or len(feed.entries) == 0:
                    print(f"⚠️  Standard parsing failed, trying improved parser...")
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)
                    
                    if improved_feed and improved_feed.get('entries'):
                        print(f"✅ Improved parser succeeded: {len(improved_feed['entries'])} entries")
                        feed = improved_feed
                    else:
                        print(f"❌ Improved parser also failed")
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


    def filter_articles(self, articles: List[Dict[str, Any]], feed_url: str = None) -> List[Dict[str, Any]]:
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
        
        def _norm_link(u: str) -> str:
            try:
                pu = urlparse(u)
                return f"{pu.scheme}://{pu.netloc}{pu.path}"
            except Exception:
                return u or ''

        unique = {}
        for a in articles:
            k = _norm_link(a.get('link', '')) or a.get('title', '')
            if k and k not in unique:
                unique[k] = a
        articles = list(unique.values())

        for i, article in enumerate(articles, 1):
            print(f"  Checking article {i}/{len(articles)}: {article.get('title', '')[:50]}...")
            
            # Check article uniqueness by link and title
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            article_key = (article_link, article_title)
            stats['valid'] += 1
            
            if article_key in self.processed_articles:
                print(f"    ⚠️  Duplicate: {article_title[:30]}...")
                stats['duplicates'] += 1
                duplicate_count += 1
                continue
            
            # Local duplicate in current run
            if article_link and article_link in self._seen_links_runtime:
                print(f"    ⚠️  Duplicate link in current run, skipping")
                duplicate_count += 1
                continue
            self._seen_links_runtime.add(article_link)

            # Check duplicate in Firebase by link (can be disabled with BYPASS_DB_CACHE=1)
            if self.db and (not self._bypass_db_cache) and self.db.is_duplicate_by_link(article_link):
                print(f"    🔁 Already in DB by link, skipping")
                duplicate_count += 1
                continue

            # Check: recently skipped entries (can be disabled with BYPASS_DB_CACHE=1)
            if self.db and (not self._bypass_db_cache) and self.db.was_skipped_recently(article_link, article_title, article.get('summary', '')):
                print(f"    🔁 Previously skipped (SKIPPED cache), skipping")
                duplicate_count += 1
                continue

            # Check duplicate in Firebase (combined), can be disabled with BYPASS_DB_CACHE=1
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
                    # Do not save to Firebase here — saving is handled by a downstream worker
                    stats['saved'] += 1
                    saved_count += 1
                    # Mark as processed in this run
                    self.processed_articles.add(article_key)
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
    
    def process_multiple_feeds(self, feeds_file: str = 'feeds.txt') -> List[Dict[str, Any]]:
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
        
        all_articles = []
        total_processed = 0
        total_saved = 0
        
        for i, feed_url in enumerate(feeds, 1):
            print(f"\n🔄 [{i}/{len(feeds)}] Loading RSS: {feed_url}")
            
            try:
                # Parse RSS feed
                feed_data = self.parse_feed(feed_url)
                if not feed_data or not feed_data.get('entries'):
                    print(f"   ⚠️  Failed to load RSS feed")
                    continue
                
                articles = feed_data['entries']
                # Limit number of items per feed so orchestrator isn't blocked for too long
                try:
                    max_per_feed = int(os.getenv('RSS_MAX_ITEMS_PER_FEED', '0') or '0')
                except Exception:
                    max_per_feed = 0
                total_in_feed = len(articles)
                if max_per_feed and total_in_feed > max_per_feed:
                    print(f"   ⚖️ Limiting {total_in_feed} → {max_per_feed} items for this feed (RSS_MAX_ITEMS_PER_FEED)")
                    articles = articles[:max_per_feed]
                print(f"   ✅ Found {len(articles)} articles")
                
                # Filter and process articles
                filtered_articles = self.filter_articles(articles, feed_url=feed_url)
                
                # Calculate statistics for this feed
                processed_in_feed = len(filtered_articles)
                saved_in_feed = len([a for a in filtered_articles if a.get('content')])
                
                total_processed += processed_in_feed
                total_saved += saved_in_feed
                
                all_articles.extend(filtered_articles)
                
                print(f"   📊 Processed: {processed_in_feed}, Saved: {saved_in_feed}")
                
            except Exception as e:
                print(f"   ❌ Error processing {feed_url}: {e}")
                continue
        # After processing all feeds, show final statistics
        print("\n" + "=" * 60)
        print(f"🎯 FINAL STATISTICS:")
        print(f"   📋 Feeds processed: {len(feeds)}")
        print(f"   📰 Articles found: {len(all_articles)}")
        print(f"   🤖 Articles filtered: {total_processed}")
        print(f"   💾 Articles saved for generation: {total_saved}")
        print(f"   🔄 Unique processed articles: {len(self.processed_articles)}")
        print(f"   ℹ️  Next step: generate articles from filtered announcements")

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
        if not self.db:
            return False
        
        try:
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            
            # Check duplicate via the new Firebase client
            is_duplicate = self.db.is_duplicate_article(article_link, article_title)
            
            if is_duplicate:
                print(f"    🔁 Already published, skipping")
                return True
            else:
                print(f"    ✅ New article, saving")
                return False
                
        except Exception as e:
            print(f"    ⚠️  Duplicate check error: {e}")
            return False

    def save_to_firebase(self, article: Dict[str, Any], translated: Dict[str, Any]) -> bool:
        """
        Save an article to Firebase.

        Args:
            article: Dictionary with original article data
            translated: Dictionary with translated article data

        Returns:
            True on success, False otherwise
        """
        if not self.db:
            print("⚠️  Firebase not initialized, cannot save article.")
            return False
        
        try:
            # Prepare data for saving
            data_to_save = {
                'title': translated['title'],
                'description': translated['description'],
                'content': translated['content'],
                'tags': translated['tags'],
                'link': article['link'],
                'published': article['published'],
                'image': article['image'],
                'category': article['category'],
                'source_feed': article['feed_title'], # Add feed title
                'source_link': article['link'], # Add original article link
                'created_at': datetime.now().isoformat()
            }
            
            # Save using the new Firebase client
            success = self.db.save_article(data_to_save)
            
            if success:
                print(f"✅ Article saved to Firebase")
                return True
            else:
                print(f"❌ Error saving article to Firebase")
                return False
            
        except Exception as e:
            print(f"❌ Error saving article to Firebase: {e}")
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
                filtered_articles = rss_parser.filter_articles(feed_data['entries'])
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