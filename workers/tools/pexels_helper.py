"""
Pexels API Helper - Search and retrieve high-quality videos
Simplified version - only video functionality used by video generator
"""
import os
import logging
import requests
from typing import Optional, List, Dict, Tuple

_logger = logging.getLogger('workers.tools.pexels_helper')

class PexelsHelper:
    """Helper for Pexels API to search and retrieve videos"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Pexels helper
        
        Args:
            api_key: Pexels API key. If not provided, will try to get from environment
        """
        self.api_key = api_key or os.getenv('PEXELS_API_KEY')
        if not self.api_key:
            raise ValueError("PEXELS_API_KEY must be set in environment variables or passed as parameter")
        
        self.base_url = "https://api.pexels.com/v1"
        self.headers = {
            "Authorization": self.api_key,
            "User-Agent": "ke-pasa-content-machine/1.0"
        }
        
        _logger.info("PexelsHelper initialized")
    
    def search_videos(self, query: str, per_page: int = 15, page: int = 1, 
                     orientation: Optional[str] = None, size: Optional[str] = None) -> Tuple[bool, Optional[Dict], Optional[str]]:
        """
        Search for videos on Pexels
        
        Args:
            query: Search query (e.g. "technology", "news", "business")
            per_page: Number of results per page (max 80)
            page: Page number
            orientation: 'landscape', 'portrait', or 'square'
            size: 'large' (4K), 'medium' (Full HD), or 'small' (HD)
            
        Returns:
            Tuple of (success: bool, data: Dict, error_message: str)
        """
        try:
            url = f"{self.base_url}/videos/search"
            params = {
                "query": query,
                "per_page": min(per_page, 80),  # API limit
                "page": page
            }
            
            if orientation:
                params["orientation"] = orientation
            if size:
                params["size"] = size
            
            _logger.info(f"Searching Pexels videos: {query} (page {page}, per_page {per_page})")
            
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                _logger.info(f"Found {data.get('total_results', 0)} videos for query: {query}")
                return True, data, None
            elif response.status_code == 429:
                return False, None, "Rate limit exceeded. Please try again later."
            else:
                return False, None, f"HTTP {response.status_code}: {response.text}"
                
        except requests.exceptions.RequestException as e:
            error_msg = f"Request failed: {str(e)}"
            _logger.error(error_msg)
            return False, None, error_msg
        except Exception as e:
            error_msg = f"Unexpected error: {str(e)}"
            _logger.exception(error_msg)
            return False, None, error_msg
    
    def get_multiple_videos_for_article(self, queries: List[str], videos_per_query: int = 1) -> Tuple[bool, List[str], Optional[str]]:
        """
        Get multiple videos for article using multiple queries
        
        Args:
            queries: List of search queries
            videos_per_query: Number of videos to get per query
            
        Returns:
            Tuple of (success: bool, video_urls: List[str], error_message: str)
        """
        try:
            all_video_urls = []
            
            for query in queries:
                success, data, error = self.search_videos(
                    query=query,
                    per_page=videos_per_query * 2,  # Get extra options
                    orientation="portrait"  # Good for vertical videos
                )
                
                if success and data and data.get('videos'):
                    # Take the best videos from this query
                    videos = data['videos'][:videos_per_query]
                    for video in videos:
                        # Get the best quality available (optimized for speed)
                        video_files = video.get('video_files', [])
                        if video_files:
                            # Sort by quality - prefer smaller files for speed
                            sorted_files = sorted(video_files, key=lambda x: (
                                x.get('width', 0) * x.get('height', 0),  # Smaller resolution first  
                                x.get('fps', 30)  # Lower FPS first
                            ))
                            
                            # Find video with lowest resolution for fastest processing
                            video_url = None
                            for video_file in sorted_files:
                                width = video_file.get('width', 0)
                                height = video_file.get('height', 0) 
                                fps = video_file.get('fps', 30)
                                
                                # Prefer videos ≤ 480p (SD) for maximum speed
                                if width <= 854 and height <= 480:
                                    video_url = video_file.get('link')
                                    _logger.info(f"Added SD video ({width}x{height}@{fps}fps)")
                                    break
                                # Fallback to 720p
                                elif width <= 1280 and height <= 720:
                                    video_url = video_file.get('link')
                                    _logger.info(f"Added HD video ({width}x{height}@{fps}fps)")
                                    break
                                    
                            # Fallback to smallest available
                            if not video_url and sorted_files:
                                video_url = sorted_files[0].get('link')
                                width = sorted_files[0].get('width', 0)
                                height = sorted_files[0].get('height', 0)
                                _logger.info(f"Added fallback video ({width}x{height})")
                                
                            if video_url:
                                all_video_urls.append(video_url)
                else:
                    _logger.warning(f"No videos found for query: {query}")
            
            if all_video_urls:
                # Remove duplicates while preserving order
                unique_video_urls = []
                seen_urls = set()
                for url in all_video_urls:
                    if url not in seen_urls:
                        unique_video_urls.append(url)
                        seen_urls.add(url)
                
                _logger.info(f"Collected {len(unique_video_urls)} unique videos (removed {len(all_video_urls) - len(unique_video_urls)} duplicates)")
                return True, unique_video_urls, None
            else:
                return False, [], "No videos found for any query"
                
        except Exception as e:
            error_msg = f"Failed to get videos: {str(e)}"
            _logger.exception(error_msg)
            return False, [], error_msg
    
    def get_videos_for_script(self, script_text: str, count: int = 3) -> List[str]:
        """
        Get videos for article script text
        
        Args:
            script_text: Article script text to extract keywords from
            count: Number of videos to get
            
        Returns:
            List of video URLs (guaranteed unique)
        """
        try:
            # Extract keywords from script for video search
            keywords = self.extract_keywords_from_script(script_text)
            
            # Start with more videos per query to ensure we get enough unique ones
            videos_per_query = max(2, count)  # At least 2 per query to have options
            
            success, video_urls, error = self.get_multiple_videos_for_article(
                queries=keywords[:3],  # Use first 3 keywords
                videos_per_query=videos_per_query
            )
            
            if success and video_urls:
                # Return exactly the number requested
                unique_videos = video_urls[:count]
                
                # If we don't have enough unique videos, try broader search
                if len(unique_videos) < count:
                    _logger.warning(f"Only found {len(unique_videos)} unique videos, need {count}")
                    
                    # Try with more general keywords
                    fallback_keywords = ['business', 'technology', 'city', 'office', 'corporate']
                    success2, video_urls2, error2 = self.get_multiple_videos_for_article(
                        queries=fallback_keywords[:2],
                        videos_per_query=count
                    )
                    
                    if success2 and video_urls2:
                        # Add new unique videos
                        seen_urls = set(unique_videos)
                        for url in video_urls2:
                            if url not in seen_urls and len(unique_videos) < count:
                                unique_videos.append(url)
                                seen_urls.add(url)
                
                _logger.info(f"Returning {len(unique_videos)} unique videos for script")
                return unique_videos[:count]  # Ensure exact count
            else:
                _logger.warning(f"Failed to get videos: {error}")
                return []
                
        except Exception as e:
            _logger.error(f"Error getting videos for script: {e}")
            return []
            
    def extract_keywords_from_script(self, script_text: str) -> List[str]:
        """Extract English keywords from script text for video search"""
        # Use English keywords that work well with Pexels
        # Based on common news/business themes
        
        script_lower = script_text.lower()
        
        # Map common themes to English keywords
        theme_keywords = {
            'мошенн': ['scam', 'fraud', 'security'],
            'сайт': ['website', 'internet', 'technology'], 
            'деньги': ['money', 'finance', 'business'],
            'продаж': ['business', 'commerce', 'shopping'],
            'безопас': ['security', 'safety', 'protection'],
            'полиц': ['police', 'law', 'justice'],
            'банк': ['banking', 'finance', 'money'],
            'компан': ['business', 'office', 'corporate'],
            'суд': ['court', 'legal', 'justice'],
            'город': ['city', 'urban', 'street'],
            'дом': ['house', 'home', 'residential'],
            'машин': ['car', 'transport', 'traffic'],
            'работ': ['work', 'office', 'business'],
            'люди': ['people', 'crowd', 'social']
        }
        
        keywords = []
        # Find matching themes
        for theme, eng_words in theme_keywords.items():
            if theme in script_lower:
                keywords.extend(eng_words)
                break  # Use first match
        
        # Fallback to general business/news keywords  
        if not keywords:
            keywords = ['business', 'office', 'city', 'technology', 'people']
        
        # Remove duplicates and limit to 3 keywords
        unique_keywords = list(dict.fromkeys(keywords))[:3]
        
        _logger.info(f"Extracted English keywords: {unique_keywords}")
        return unique_keywords


__all__ = ['PexelsHelper']
