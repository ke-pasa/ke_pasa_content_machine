"""
Pexels API Helper - Search and retrieve high-quality videos
Simplified version - only video functionality used by video generator
"""
import os
import logging
import requests
import random
import json
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
                    per_page=20,  # Get top 20 results for variety
                    orientation="portrait"  # Good for vertical videos
                )
                
                if success and data and data.get('videos'):
                    # Get random videos from top 20 for variety (instead of always taking first ones)
                    available_videos = data['videos'][:20]  # Top 20 results
                    
                    # Randomly select videos_per_query videos from available
                    if len(available_videos) <= videos_per_query:
                        videos = available_videos
                    else:
                        videos = random.sample(available_videos, videos_per_query)
                    
                    _logger.info(f"Selected {len(videos)} random videos from {len(available_videos)} available for query: {query}")
                    for video in videos:
                        # Get HD quality MAXIMUM (no 4K allowed)
                        video_files = video.get('video_files', [])
                        if video_files:
                            # Filter STRICTLY for HD quality videos (720p-1080p ONLY, exclude 4K)
                            hd_files = [
                                vf for vf in video_files
                                if 1280 <= vf.get('width', 0) <= 1920 
                                and 720 <= vf.get('height', 0) <= 1080
                            ]
                            
                            # If no HD files found, use lower quality (SD) but NOT 4K
                            if not hd_files:
                                _logger.warning(f"No HD quality found, using lower quality (excluding 4K)")
                                # Take anything below Full HD but exclude 4K (over 1920x1080)
                                lower_quality_files = [
                                    vf for vf in video_files
                                    if vf.get('width', 0) <= 1920 and vf.get('height', 0) <= 1080
                                ]
                                candidates = lower_quality_files
                            else:
                                candidates = hd_files
                            
                            # If still no candidates, skip this video
                            if not candidates:
                                _logger.warning(f"Only 4K quality available, skipping video")
                                continue
                            
                            # Sort by quality - prefer higher resolution within our limit
                            sorted_files = sorted(candidates, key=lambda x: (
                                x.get('width', 0) * x.get('height', 0),  # Higher resolution first
                                x.get('fps', 0)  # Higher FPS first
                            ), reverse=True)
                            
                            # Get the best quality video (HD or lower, but never 4K)
                            best_video = sorted_files[0]
                            video_url = best_video.get('link')
                            width = best_video.get('width', 0)
                            height = best_video.get('height', 0)
                            fps = best_video.get('fps', 30)
                            quality = best_video.get('quality', 'hd')
                            
                            _logger.info(f"Added HD video: {width}x{height}@{fps}fps ({quality})")
                            
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
        """Extract English keyword pairs from script text using OpenAI for video search"""
        try:
            # Try to use OpenAI to generate relevant keyword pairs
            keywords = self._generate_keywords_with_openai(script_text)
            if keywords:
                _logger.info(f"Generated keywords with OpenAI: {keywords}")
                return keywords
        except Exception as e:
            _logger.warning(f"Failed to generate keywords with OpenAI: {e}, using fallback")
        
        # Fallback to simple keyword extraction
        script_lower = script_text.lower()
        
        # Map common themes to English keyword pairs
        theme_keywords = {
            'мошенн': ['fraud security', 'scam alert', 'cyber crime'],
            'сайт': ['website design', 'internet technology', 'digital network'], 
            'деньги': ['money business', 'finance banking', 'cash payment'],
            'продаж': ['business office', 'commerce shopping', 'retail store'],
            'безопас': ['security camera', 'safety protection', 'police patrol'],
            'полиц': ['police car', 'law enforcement', 'justice court'],
            'банк': ['banking finance', 'money business', 'financial office'],
            'компан': ['business office', 'corporate meeting', 'work team'],
            'суд': ['court legal', 'justice law', 'judge trial'],
            'город': ['city street', 'urban architecture', 'downtown building'],
            'дом': ['house home', 'residential building', 'apartment property'],
            'машин': ['car traffic', 'vehicle transport', 'road highway'],
            'работ': ['work office', 'business meeting', 'professional team'],
            'люди': ['people crowd', 'social gathering', 'group meeting']
        }
        
        keywords = []
        # Find matching themes
        for theme, eng_pairs in theme_keywords.items():
            if theme in script_lower:
                keywords = eng_pairs[:3]
                break
        
        # Fallback to general business/news keyword pairs
        if not keywords:
            keywords = ['business office', 'city street', 'people work']
        
        _logger.info(f"Extracted fallback keywords: {keywords}")
        return keywords[:3]
    
    def _generate_keywords_with_openai(self, script_text: str) -> Optional[List[str]]:
        """Use OpenAI to generate relevant keyword pairs for Pexels video search"""
        try:
            from workers.tools.openai_client import get_openai_client, chat_completion

            client = get_openai_client()
            if not client:
                _logger.warning("OpenAI client not available for keyword generation")
                return None

            prompt = f"""Based on this Russian news script, generate 3 pairs of English keywords for searching stock videos on Pexels.

IMPORTANT: The video will be 30 seconds long with 3 segments:
- First keyword pair: for first 10 seconds (beginning of the story)
- Second keyword pair: for middle 10 seconds (development of the story)
- Third keyword pair: for last 10 seconds (conclusion/end of the story)

Each pair should match the content of its corresponding part of the script.

Requirements:
- Each pair should be exactly 2 words (e.g., "business office", "city street")
- Keywords should be generic enough to find stock footage on Pexels
- Focus on visual elements that can be filmed
- Use common English words that work well for stock video search
- Return ONLY the 3 keyword pairs, one per line, nothing else

Script:
{script_text[:800]}

Output format (example):
fraud alert
phone scam
police investigation"""

            result = chat_completion(
                client=client,
                model="gpt-5.4-mini",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant that generates English keyword pairs for stock video search based on script progression."},
                    {"role": "user", "content": prompt}
                ],

                max_tokens=100,
            )

            if not result:
                _logger.warning("OpenAI returned no result for keyword generation")
                return None

            # Parse the result - expect 3 lines with keyword pairs
            keywords = [line.strip() for line in result.split('\n') if line.strip()]

            if len(keywords) >= 3:
                return keywords[:3]
            else:
                _logger.warning(f"OpenAI returned {len(keywords)} keywords, expected 3")
                return None

        except Exception as e:
            _logger.error(f"OpenAI keyword generation failed: {e}")
            return None


__all__ = ['PexelsHelper']
