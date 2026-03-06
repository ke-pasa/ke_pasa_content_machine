"""
Threads API Helper - posts content to Threads (Instagram's text-based app)

Threads is part of Meta ecosystem and uses Instagram Business/Creator credentials.

Note: Threads API requires:
1. Instagram Business or Creator account
2. Account must be connected to Threads
3. Token needs threads_basic, threads_content_publish permissions

Required environment variables:
- FACEBOOK_APP_ID: Meta app ID
- FACEBOOK_APP_SECRET: Meta app secret
- THREADS_USER_ID: Threads user ID (or INSTAGRAM_USER_ID as fallback)
- THREADS_ACCESS_TOKEN: Threads-specific token (or INSTAGRAM_ACCESS_TOKEN as fallback)
"""
import os
import logging
import requests
from typing import Dict

logger = logging.getLogger(__name__)

def post_threads(image_url: str = None, text: str = None) -> Dict:
    """
    Post to Threads using Meta Graph API
    
    Uses Instagram Business/Creator credentials (Threads is part of Meta ecosystem).

    Args:
        image_url: Optional URL of the image to post. If None, creates text-only post
        text: Text content for the post (required)
        
    Returns:
        Dictionary with post result containing 'id' and 'container_id'
        
    Raises:
        ValueError: If required credentials are not configured or if no text provided
        Exception: If API call fails
    """
    # Validate input
    if not text or not text.strip():
        raise ValueError('Text content is required for Threads post')
    
    # Use Instagram credentials (Threads requires Instagram Business/Creator account)
    app_id = os.getenv('FACEBOOK_APP_ID')
    app_secret = os.getenv('FACEBOOK_APP_SECRET')
    # Threads can use separate User ID or fall back to Instagram User ID
    user_id = os.getenv('THREADS_USER_ID') or os.getenv('INSTAGRAM_USER_ID')
    # Threads can use separate token or fall back to Instagram token
    access_token = os.getenv('THREADS_ACCESS_TOKEN') or os.getenv('INSTAGRAM_ACCESS_TOKEN')
    
    if not app_id or not app_secret:
        raise ValueError('FACEBOOK_APP_ID and FACEBOOK_APP_SECRET must be set')
    
    if not user_id:
        raise ValueError('THREADS_USER_ID or INSTAGRAM_USER_ID must be set (Threads User ID)')
    
    if not access_token:
        raise ValueError('THREADS_ACCESS_TOKEN or INSTAGRAM_ACCESS_TOKEN must be set (needs threads_basic, threads_content_publish permissions)')
    
    # Step 1: Create media container
    create_url = f'https://graph.threads.net/v1.0/{user_id}/threads'
    
    # Build params based on whether we have an image or not
    params = {
        'text': text,
        'access_token': access_token
    }
    
    if image_url:
        params['media_type'] = 'IMAGE'
        params['image_url'] = image_url
        logger.info(f"🧵 Creating Threads media container (with image)...")
        logger.debug(f"Image URL: {image_url}")
    else:
        params['media_type'] = 'TEXT'
        logger.info(f"🧵 Creating Threads media container (text-only)...")
    
    logger.debug(f"Threads API request: POST {create_url}")
    logger.debug(f"User ID: {user_id}")
    logger.debug(f"Text length: {len(text)} chars")
    
    response = requests.post(create_url, params=params, timeout=30)
    
    if response.status_code != 200:
        error_data = response.json() if response.headers.get('content-type', '').startswith('application/json') else {}
        error_code = error_data.get('error', {}).get('code')
        error_message = error_data.get('error', {}).get('message', response.text)
        
        # Provide helpful error messages
        if 'Invalid platform app' in error_message or 'platform app' in error_message.lower():
            error_msg = (
                f"Threads API: Invalid platform app. This means:\n"
                f"  1. Your Meta app needs Threads product added in developers.facebook.com\n"
                f"  2. Go to your app → Add Product → Threads → Set Up\n"
                f"  3. After adding Threads, regenerate your access token\n"
                f"  See docs/THREADS_SETUP.md for detailed instructions"
            )
        elif error_code == 190 or 'OAuth' in error_message:
            error_msg = (
                f"Threads API: Invalid access token (code {error_code}). This means:\n"
                f"  1. Instagram account may not be connected to Threads app\n"
                f"  2. Token was created before Threads was added to your Meta app\n"
                f"  3. Need to regenerate token after connecting Threads\n"
                f"  Open Threads app and ensure @{user_id} is active"
            )
        elif response.status_code == 500:
            error_msg = (
                f"Threads API internal error (500). This usually means:\n"
                f"  1. Instagram account is not connected to Threads app\n"
                f"  2. Account is not a Business or Creator account\n"
                f"  3. Threads service might be temporarily unavailable\n"
                f"Error: {error_message}"
            )
        elif response.status_code == 403:
            error_msg = f"Threads API permission denied (403). Check token permissions: {error_message}"
        elif response.status_code == 400:
            error_msg = f"Threads API bad request (400). {error_message}"
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
