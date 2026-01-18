"""
Threads API Helper - posts content to Threads (Instagram's text-based app)

Threads is part of Meta ecosystem and uses Facebook/Instagram credentials.
No separate THREADS_* environment variables needed.

Note: Threads API requires:
1. Instagram Business or Creator account
2. Account must be connected to Threads
3. Token needs threads_basic, threads_content_publish permissions
"""
import os
import logging
import requests
from typing import Dict

logger = logging.getLogger(__name__)

def post_threads(image_url: str, text: str) -> Dict:
    """
    Post to Threads using Meta Graph API
    
    Uses Facebook/Instagram credentials (same Meta ecosystem).
    Required environment variables:
    - FACEBOOK_APP_ID
    - FACEBOOK_APP_SECRET
    - INSTAGRAM_USER_ID (Threads uses Instagram user ID)
    - FACEBOOK_PAGE_ACCESS_TOKEN (long-lived token works for all Meta platforms)
    
    Args:
        image_url: URL of the image to post
        text: Text content for the post
        
    Returns:
        Dictionary with post result containing 'id' and 'container_id'
        
    Raises:
        ValueError: If required credentials are not configured
        Exception: If API call fails
    """
    # Use Facebook credentials (Threads is part of Meta ecosystem)
    app_id = os.getenv('FACEBOOK_APP_ID')
    app_secret = os.getenv('FACEBOOK_APP_SECRET')
    user_id = os.getenv('INSTAGRAM_USER_ID')
    access_token = os.getenv('FACEBOOK_PAGE_ACCESS_TOKEN')
    
    if not app_id or not app_secret:
        raise ValueError('FACEBOOK_APP_ID and FACEBOOK_APP_SECRET must be set')
    
    if not user_id:
        raise ValueError('INSTAGRAM_USER_ID must be set (Threads uses Instagram user ID)')
    
    if not access_token:
        raise ValueError('FACEBOOK_PAGE_ACCESS_TOKEN must be set (used for all Meta platforms)')
    
    # Step 1: Create media container
    create_url = f'https://graph.threads.net/v1.0/{user_id}/threads'
    
    params = {
        'media_type': 'IMAGE',
        'image_url': image_url,
        'text': text,
        'access_token': access_token
    }
    
    logger.info(f"🧵 Creating Threads media container...")
    logger.debug(f"Threads API request: POST {create_url}")
    logger.debug(f"User ID: {user_id}")
    logger.debug(f"Image URL: {image_url}")
    logger.debug(f"Text length: {len(text)} chars")
    
    response = requests.post(create_url, params=params, timeout=30)
    
    if response.status_code != 200:
        error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        error_code = error_data.get('error', {}).get('code')
        error_message = error_data.get('error', {}).get('message', response.text)
        
        # Provide helpful error messages
        if response.status_code == 500:
            error_msg = (
                f"Threads API internal error (500). This usually means:\n"
                f"  1. Instagram account is not connected to Threads\n"
                f"  2. Access token doesn't have threads_basic, threads_content_publish permissions\n"
                f"  3. Account is not a Business or Creator account\n"
                f"Error: {error_message}"
            )
        elif response.status_code == 403:
            error_msg = f"Threads API permission denied (403). Check token permissions: {error_message}"
        elif response.status_code == 400:
            error_msg = f"Threads API bad request (400). Check image URL and text: {error_message}"
        else:
            error_msg = f"Threads API error ({response.status_code}): {error_message}"
        
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    container_id = response.json().get('id')
    if not container_id:
        raise Exception('No container ID returned from Threads API')
    
    logger.info(f"✓ Threads container created: {container_id}")
    
    # Step 2: Publish the container
    publish_url = f'https://graph.threads.net/v1.0/{user_id}/threads_publish'
    
    publish_params = {
        'creation_id': container_id,
        'access_token': access_token
    }
    
    logger.info(f"🧵 Publishing Threads post...")
    publish_response = requests.post(publish_url, params=publish_params, timeout=30)
    
    if publish_response.status_code != 200:
        error_data = publish_response.json() if publish_response.headers.get('content-type', '').startswith('application/json') else {}
        error_message = error_data.get('error', {}).get('message', publish_response.text)
        error_msg = f"Failed to publish Threads post: {publish_response.status_code} - {error_message}"
        logger.error(f"❌ {error_msg}")
        raise Exception(error_msg)
    
    result = publish_response.json()
    post_id = result.get('id')
    
    if not post_id:
        raise Exception('No post ID returned from Threads publish')
    
    logger.info(f"✓ Threads post published: {post_id}")
    
    return {
        'id': post_id,
        'container_id': container_id
    }
