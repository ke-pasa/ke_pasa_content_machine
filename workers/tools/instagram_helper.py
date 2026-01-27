"""Helper for posting to Instagram using Meta Graph API.

Uses Instagram Graph API with Business/Creator accounts.
Tokens are stored in .instagram_tokens.json.
Supports dry-run via `INSTAGRAM_DRY_RUN` environment variable.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timedelta, timezone
import time

import requests

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(__file__).parent.parent.parent / '.instagram_tokens.json'


def _load_tokens() -> Optional[Dict[str, Any]]:
    """Load tokens from file or environment variables."""
    if not TOKEN_FILE.exists():
        # Try to auto-create from environment variables
        return _try_create_tokens_from_env()
    try:
        content = TOKEN_FILE.read_text().strip()
        if not content:
            # Empty file, try to create from environment
            logger.info('Token file is empty, attempting to create from environment variables')
            return _try_create_tokens_from_env()
        return json.loads(content)
    except Exception as e:
        logger.warning(f'Failed to load Instagram tokens: {e}')
        # Try to recover by creating from environment
        return _try_create_tokens_from_env()


def _save_tokens(tokens: Dict[str, Any]):
    """Save tokens to file."""
    try:
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
        logger.info(f'✓ Instagram tokens saved to {TOKEN_FILE}')
    except Exception as e:
        logger.error(f'Failed to save Instagram tokens: {e}')


def _try_create_tokens_from_env() -> Optional[Dict[str, Any]]:
    """Try to create token file from environment variables.
    
    Supports two modes:
    1. INSTAGRAM_ACCESS_TOKEN (long-lived) - direct use
    2. INSTAGRAM_SHORT_TOKEN (short-lived) - exchange for long-lived
    """
    # Check for long-lived token in environment
    access_token = os.environ.get('INSTAGRAM_ACCESS_TOKEN', '').strip()
    if access_token:
        logger.info('📦 Creating Instagram token file from INSTAGRAM_ACCESS_TOKEN...')
        
        user_id = os.environ.get('INSTAGRAM_USER_ID', '').strip()
        if not user_id:
            logger.error('❌ INSTAGRAM_USER_ID not set in environment')
            return None
        
        # Assume 60-day expiry if not specified
        expires_in = int(os.environ.get('INSTAGRAM_EXPIRES_IN', '5184000'))
        
        now = datetime.now(timezone.utc)
        tokens = {
            'access_token': access_token,
            'token_type': 'bearer',
            'expires_in': expires_in,
            'obtained_at': now.isoformat(),
            'expires_at': (now + timedelta(seconds=expires_in)).isoformat(),
            'user_id': user_id
        }
        
        _save_tokens(tokens)
        return tokens
    
    # Check for short-lived token to exchange
    short_token = os.environ.get('INSTAGRAM_SHORT_TOKEN', '').strip()
    app_secret = (os.environ.get('INSTAGRAM_APP_SECRET', '').strip() or 
                  os.environ.get('FACEBOOK_APP_SECRET', '').strip())
    
    if short_token and app_secret:
        logger.info('📦 Exchanging Instagram short-lived token for long-lived token...')
        
        user_id = os.environ.get('INSTAGRAM_USER_ID')
        if not user_id:
            logger.error('❌ INSTAGRAM_USER_ID not set in environment')
            return None
        
        # Get Meta App ID (required for token exchange)
        app_id = os.environ.get('INSTAGRAM_APP_ID') or os.environ.get('FACEBOOK_APP_ID')
        if not app_id:
            logger.error('❌ INSTAGRAM_APP_ID or FACEBOOK_APP_ID not set in environment')
            return None
        
        try:
            # Exchange short-lived for long-lived Instagram token
            # https://developers.facebook.com/docs/instagram-basic-display-api/guides/long-lived-access-tokens
            url = 'https://graph.instagram.com/access_token'
            params = {
                'grant_type': 'ig_exchange_token',
                'client_secret': app_secret,
                'access_token': short_token
            }
            
            resp = requests.get(url, params=params, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                long_lived_token = data.get('access_token')
                expires_in = data.get('expires_in', 5184000)
                
                if long_lived_token:
                    now = datetime.now(timezone.utc)
                    tokens = {
                        'access_token': long_lived_token,
                        'token_type': 'bearer',
                        'expires_in': expires_in,
                        'obtained_at': now.isoformat(),
                        'expires_at': (now + timedelta(seconds=expires_in)).isoformat(),
                        'user_id': user_id
                    }
                    
                    _save_tokens(tokens)
                    logger.info(f'✅ Long-lived Instagram token created (expires in {expires_in // 86400} days)')
                    return tokens
            
            logger.error(f'Failed to exchange Instagram token: {resp.status_code} {resp.text}')
        except Exception as e:
            logger.error(f'Failed to exchange Instagram token: {e}')
    
    return None


def _get_valid_access_token() -> str:
    """Get valid access token, checking expiry."""
    tokens = _load_tokens()
    
    if not tokens:
        # Try to show helpful error message
        if os.environ.get('INSTAGRAM_ACCESS_TOKEN'):
            raise RuntimeError(
                'Failed to create Instagram tokens from INSTAGRAM_ACCESS_TOKEN. '
                'Check that the token is valid and INSTAGRAM_USER_ID is set.'
            )
        elif os.environ.get('INSTAGRAM_SHORT_TOKEN'):
            raise RuntimeError(
                'Failed to create Instagram tokens from INSTAGRAM_SHORT_TOKEN. '
                'Check that INSTAGRAM_APP_SECRET and INSTAGRAM_USER_ID are set correctly.'
            )
        else:
            raise RuntimeError(
                'No Instagram tokens found. Set INSTAGRAM_ACCESS_TOKEN or INSTAGRAM_SHORT_TOKEN in environment, '
                'or run tools/instagram_oauth_setup.py to authorize the app.'
            )
    
    access_token = tokens.get('access_token')
    expires_at_str = tokens.get('expires_at')
    
    if not access_token:
        raise RuntimeError('Invalid Instagram token data. Re-run tools/instagram_oauth_setup.py')
    
    # Check if token is expiring soon (warn if less than 7 days)
    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            days_until_expiry = (expires_at - datetime.now(timezone.utc)).days
            
            if days_until_expiry < 0:
                raise RuntimeError(
                    '❌ Instagram access token has expired! Re-run tools/instagram_oauth_setup.py to refresh.'
                )
            elif days_until_expiry < 7:
                logger.warning(
                    f'⚠️ Instagram access token expires in {days_until_expiry} days. '
                    'Please refresh it soon using tools/instagram_oauth_setup.py'
                )
        except ValueError as e:
            logger.warning(f'Failed to parse token expiry date: {e}')
    
    return access_token


def _create_media_container(
    user_id: str,
    media_url: str,
    caption: str,
    access_token: str,
    media_type: str = 'IMAGE'
) -> Optional[str]:
    """Create Instagram media container (step 1 of publishing).
    
    Args:
        user_id: Instagram Business/Creator account user ID
        media_url: Publicly accessible media URL (image or video)
        caption: Post caption (max 2,200 chars)
        access_token: Valid Instagram access token
        media_type: 'IMAGE' or 'VIDEO'
    
    Returns:
        Container ID if successful, None otherwise
    """
    # Truncate caption if too long
    if len(caption) > 2200:
        caption = caption[:2197] + '...'
    
    url = f'https://graph.facebook.com/v18.0/{user_id}/media'
    
    # Different parameters for image vs video
    if media_type.upper() == 'VIDEO':
        params = {
            'video_url': media_url,
            'caption': caption,
            'access_token': access_token,
            'media_type': 'VIDEO'
        }
    else:
        params = {
            'image_url': media_url,
            'caption': caption,
            'access_token': access_token
        }
    
    logger.info(f'📦 Creating Instagram media container ({media_type})...')
    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, data=params, timeout=30)
            
            if resp.status_code == 200:
                data = resp.json()
                container_id = data.get('id')
                if container_id:
                    logger.info(f'✅ Media container created: {container_id}')
                    return container_id
                else:
                    logger.error(f'No container ID in response: {data}')
                    return None
            else:
                status = resp.status_code
                error_text = resp.text
                logger.error(f'Failed to create container: {status} {error_text}')
                
                # Don't retry on client errors (4xx)
                if 400 <= status < 500:
                    logger.warning('Client error, not retrying')
                    return None
                
                # Retry on server errors (5xx)
                if attempt < max_attempts - 1:
                    backoff = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f'Retrying in {backoff}s... (attempt {attempt + 1}/{max_attempts})')
                    time.sleep(backoff)
                    continue
                
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f'Request failed: {e}')
            if attempt < max_attempts - 1:
                backoff = 2 ** attempt
                time.sleep(backoff)
                continue
            return None
    
    return None


def _publish_media_container(
    user_id: str,
    container_id: str,
    access_token: str
) -> Optional[Dict[str, Any]]:
    """Publish Instagram media container (step 2 of publishing).
    
    Args:
        user_id: Instagram Business/Creator account user ID
        container_id: Container ID from create_media_container
        access_token: Valid Instagram access token
    
    Returns:
        Dict with published post data including 'id', or None on failure
    """
    url = f'https://graph.facebook.com/v18.0/{user_id}/media_publish'
    params = {
        'creation_id': container_id,
        'access_token': access_token
    }
    
    logger.info(f'🚀 Publishing Instagram media container {container_id}...')
    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            resp = requests.post(url, data=params, timeout=30)
            
            if resp.status_code == 200:
                data = resp.json()
                post_id = data.get('id')
                if post_id:
                    logger.info(f'✅ Media published successfully: {post_id}')
                    return {'id': post_id, 'status': 'published'}
                else:
                    logger.error(f'No post ID in response: {data}')
                    return None
            else:
                status = resp.status_code
                error_text = resp.text
                logger.error(f'Failed to publish container: {status} {error_text}')
                
                # Don't retry on client errors (4xx)
                if 400 <= status < 500:
                    logger.warning('Client error, not retrying')
                    return None
                
                # Retry on server errors (5xx)
                if attempt < max_attempts - 1:
                    backoff = 2 ** attempt
                    logger.info(f'Retrying in {backoff}s... (attempt {attempt + 1}/{max_attempts})')
                    time.sleep(backoff)
                    continue
                
                return None
                
        except requests.exceptions.RequestException as e:
            logger.error(f'Request failed: {e}')
            if attempt < max_attempts - 1:
                backoff = 2 ** attempt
                time.sleep(backoff)
                continue
            return None
    
    return None


def post_instagram(
    media_url: str,
    caption: str,
    user_id: Optional[str] = None,
    access_token: Optional[str] = None,
    media_type: str = 'IMAGE'
) -> Dict[str, Any]:
    """Post image or video with caption to Instagram using Graph API.
    
    This is a two-step process:
    1. Create media container with media URL and caption
    2. Publish the container
    
    Args:
        media_url: Publicly accessible media URL (image or video)
        caption: Post caption (max 2,200 characters, will be truncated)
        user_id: Instagram user ID (reads from env INSTAGRAM_USER_ID if not provided)
        access_token: Access token (reads from tokens file if not provided)
        media_type: 'IMAGE' or 'VIDEO'
    
    Returns:
        Dict with post data including 'id' and 'status', or error info
    
    Raises:
        RuntimeError on failure
    """
    if not media_url:
        raise ValueError('media_url is required')
    
    if not caption:
        caption = ''  # Empty caption is allowed
    
    # Get user ID from environment if not provided
    if not user_id:
        user_id = os.environ.get('INSTAGRAM_USER_ID')
        if not user_id:
            raise RuntimeError('INSTAGRAM_USER_ID not set in environment')
    
    # Get access token from file if not provided
    if not access_token:
        try:
            access_token = _get_valid_access_token()
        except Exception as e:
            logger.error(f'Failed to get Instagram access token: {e}')
            raise
    
    logger.info(f'🟣 Posting to Instagram ({media_type}): {caption[:50]}...')
    
    # Step 1: Create media container
    container_id = _create_media_container(user_id, media_url, caption, access_token, media_type)
    if not container_id:
        raise RuntimeError(f'Failed to create Instagram media container for {media_type}')
    
    # Step 2: Wait for media to be ready (Instagram needs time to process)
    logger.info(f'⏳ Waiting for Instagram to process media...')
    max_wait_time = 30  # seconds
    poll_interval = 2  # seconds
    waited = 0
    
    while waited < max_wait_time:
        time.sleep(poll_interval)
        waited += poll_interval
        
        # Check container status
        status_url = f'https://graph.facebook.com/v18.0/{container_id}'
        params = {'fields': 'status_code', 'access_token': access_token}
        
        try:
            resp = requests.get(status_url, params=params, timeout=10)
            if resp.status_code == 200:
                status_data = resp.json()
                status_code = status_data.get('status_code')
                
                if status_code == 'FINISHED':
                    logger.info(f'✓ Media processing complete (waited {waited}s)')
                    break
                elif status_code == 'ERROR':
                    raise RuntimeError(f'Instagram media processing failed: {status_data}')
                else:
                    logger.info(f'  Status: {status_code}, waited {waited}s...')
        except Exception as e:
            logger.warning(f'Could not check status: {e}')
    
    # Step 3: Publish container
    result = _publish_media_container(user_id, container_id, access_token)
    if not result:
        raise RuntimeError(f'Failed to publish Instagram container {container_id}')
    
    logger.info(f'✅ Successfully posted to Instagram: {result.get("id")}')
    return result
