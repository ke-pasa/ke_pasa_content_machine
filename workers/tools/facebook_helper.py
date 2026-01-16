"""Helper for posting to Facebook Page using Meta Graph API.

Uses Facebook Graph API with Page access tokens.
Tokens are stored in .facebook_tokens.json.
"""
from __future__ import annotations

import os
import json
import logging
from typing import Optional, Dict, Any
from pathlib import Path
from datetime import datetime, timezone
import time

import requests

logger = logging.getLogger(__name__)

TOKEN_FILE = Path(__file__).parent.parent.parent / '.facebook_tokens.json'


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
        logger.warning(f'Failed to load Facebook tokens: {e}')
        # Try to recover by creating from environment
        return _try_create_tokens_from_env()


def _save_tokens(tokens: Dict[str, Any]):
    """Save tokens to file."""
    try:
        TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
        logger.info(f'✓ Facebook tokens saved to {TOKEN_FILE}')
    except Exception as e:
        logger.error(f'Failed to save Facebook tokens: {e}')


def _exchange_for_long_lived_token(short_token: str) -> Optional[str]:
    """Exchange short-lived user token for long-lived (60 days)."""
    app_id = os.environ.get('FACEBOOK_APP_ID')
    app_secret = os.environ.get('FACEBOOK_APP_SECRET')
    
    if not app_id or not app_secret:
        logger.error('FACEBOOK_APP_ID and FACEBOOK_APP_SECRET required for token exchange')
        return None
    
    logger.info('🔄 Exchanging short-lived token for long-lived...')
    
    try:
        url = 'https://graph.facebook.com/v18.0/oauth/access_token'
        params = {
            'grant_type': 'fb_exchange_token',
            'client_id': app_id,
            'client_secret': app_secret,
            'fb_exchange_token': short_token
        }
        
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            long_token = data.get('access_token')
            expires_in = data.get('expires_in', 0)
            
            logger.info(f'✅ Long-lived user token obtained (expires in {expires_in // 86400} days)')
            return long_token
        else:
            logger.error(f'Failed to exchange token: {resp.status_code} {resp.text}')
    except Exception as e:
        logger.error(f'Token exchange error: {e}')
    
    return None


def _fetch_page_token_from_user_token(user_token: str) -> Optional[Dict[str, Any]]:
    """Fetch page access token from user token."""
    page_id = os.environ.get('FACEBOOK_PAGE_ID')
    
    logger.info('📦 Fetching Facebook page token from user token...')
    
    try:
        url = f'https://graph.facebook.com/v18.0/{page_id if page_id else "me/accounts"}'
        params = {
            'fields': 'access_token,name' if page_id else 'access_token',
            'access_token': user_token
        }
        
        resp = requests.get(url, params=params, timeout=30)
        if resp.status_code == 200:
            if page_id:
                # Direct page query
                data = resp.json()
                page_token = data.get('access_token')
                page_name = data.get('name')
                
                if page_token:
                    tokens = {
                        'access_token': page_token,
                        'token_type': 'bearer',
                        'page_id': page_id,
                        'page_name': page_name,
                        'obtained_at': datetime.now(timezone.utc).isoformat(),
                        'expires_at': 'never'
                    }
                    
                    _save_tokens(tokens)
                    logger.info(f'✅ Page token created for: {page_name}')
                    return tokens
            else:
                # me/accounts query
                pages = resp.json().get('data', [])
                if pages:
                    target_page = pages[0]
                    page_token = target_page.get('access_token')
                    
                    if page_token:
                        tokens = {
                            'access_token': page_token,
                            'token_type': 'bearer',
                            'page_id': target_page.get('id'),
                            'page_name': target_page.get('name'),
                            'obtained_at': datetime.now(timezone.utc).isoformat(),
                            'expires_at': 'never'
                        }
                        
                        _save_tokens(tokens)
                        logger.info(f'✅ Page token created for: {target_page.get("name")}')
                        return tokens
        else:
            logger.error(f'Failed to fetch page token: {resp.status_code} {resp.text}')
    except Exception as e:
        logger.error(f'Failed to fetch page token: {e}')
    
    return None


def _refresh_page_token_from_user_token() -> Optional[Dict[str, Any]]:
    """Refresh page token by exchanging user token for long-lived, then fetching page token."""
    short_user_token = os.environ.get('FACEBOOK_USER_TOKEN', '').strip()
    
    if not short_user_token:
        logger.debug('No FACEBOOK_USER_TOKEN set for auto-refresh')
        return None
    
    # Step 1: Exchange for long-lived user token
    long_user_token = _exchange_for_long_lived_token(short_user_token)
    if not long_user_token:
        return None
    
    # Step 2: Fetch page token from long-lived user token
    return _fetch_page_token_from_user_token(long_user_token)


def _try_create_tokens_from_env() -> Optional[Dict[str, Any]]:
    """Try to create token file from environment variables.
    
    Supports three modes:
    1. FACEBOOK_PAGE_ACCESS_TOKEN - direct page token (recommended)
    2. FACEBOOK_ACCESS_TOKEN - user token, will fetch page token  
    3. FACEBOOK_USER_TOKEN - will exchange for long-lived, then fetch page token
    """
    page_id = os.environ.get('FACEBOOK_PAGE_ID', '').strip()
    
    # Mode 1: Direct page access token (simplest)
    page_token = os.environ.get('FACEBOOK_PAGE_ACCESS_TOKEN', '').strip()
    if page_token and page_id:
        logger.info('📦 Creating Facebook token file from FACEBOOK_PAGE_ACCESS_TOKEN...')
        
        tokens = {
            'access_token': page_token,
            'token_type': 'bearer',
            'page_id': page_id,
            'obtained_at': datetime.now(timezone.utc).isoformat(),
            'expires_at': 'never'
        }
        
        # Try to get page name
        try:
            url = f'https://graph.facebook.com/v18.0/{page_id}'
            params = {'fields': 'name', 'access_token': page_token}
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code == 200:
                page_name = resp.json().get('name')
                if page_name:
                    tokens['page_name'] = page_name
                    logger.info(f'✓ Verified page: {page_name}')
        except Exception as e:
            logger.warning(f'Could not verify page name: {e}')
        
        _save_tokens(tokens)
        return tokens
    
    # Mode 2: User token (already long-lived)
    user_token = os.environ.get('FACEBOOK_ACCESS_TOKEN', '').strip()
    
    if user_token:
        return _fetch_page_token_from_user_token(user_token)
    
    # Mode 3: Short-lived user token (needs exchange)
    short_user_token = os.environ.get('FACEBOOK_USER_TOKEN', '').strip()
    
    if short_user_token:
        return _refresh_page_token_from_user_token()
    
    return None


def _get_valid_access_token() -> str:
    """Get valid access token, refreshing if necessary.
    
    Note: Page access tokens are permanent and don't expire.
    But this will auto-refresh if token is missing and FACEBOOK_USER_TOKEN is set.
    """
    tokens = _load_tokens()
    
    if not tokens:
        # Try to refresh from FACEBOOK_USER_TOKEN
        logger.info('No Facebook tokens found, attempting auto-refresh...')
        tokens = _refresh_page_token_from_user_token()
        
        if not tokens:
            # Try to show helpful error message
            if os.environ.get('FACEBOOK_PAGE_ACCESS_TOKEN'):
                raise RuntimeError(
                    'Failed to create Facebook tokens from FACEBOOK_PAGE_ACCESS_TOKEN. '
                    'Check that the token is valid and FACEBOOK_PAGE_ID is set.'
                )
            elif os.environ.get('FACEBOOK_ACCESS_TOKEN'):
                raise RuntimeError(
                    'Failed to create Facebook tokens from FACEBOOK_ACCESS_TOKEN. '
                    'Check that the token is valid. FACEBOOK_PAGE_ID is optional.'
                )
            else:
                raise RuntimeError(
                    'No Facebook tokens found. Set FACEBOOK_PAGE_ACCESS_TOKEN, FACEBOOK_ACCESS_TOKEN, or FACEBOOK_USER_TOKEN in environment, '
                    'or run tools/facebook_oauth_setup.py to authorize the app.'
                )
    
    access_token = tokens.get('access_token')
    
    if not access_token:
        raise RuntimeError('Invalid Facebook token data. Re-run tools/facebook_oauth_setup.py')
    
    # Check expiry if available (some page tokens don't expire)
    expires_at_str = tokens.get('expires_at')
    if expires_at_str and expires_at_str != 'never':
        try:
            expires_at = datetime.fromisoformat(expires_at_str)
            days_until_expiry = (expires_at - datetime.now(timezone.utc)).days
            
            if days_until_expiry < 0:
                raise RuntimeError(
                    '❌ Facebook access token has expired! Re-run tools/facebook_oauth_setup.py to refresh.'
                )
            elif days_until_expiry < 7:
                logger.warning(
                    f'⚠️ Facebook access token expires in {days_until_expiry} days. '
                    'Please refresh it soon using tools/facebook_oauth_setup.py'
                )
        except ValueError as e:
            logger.warning(f'Failed to parse token expiry date: {e}')
    
    return access_token


def post_facebook(
    image_url: str,
    message: str,
    page_id: Optional[str] = None,
    access_token: Optional[str] = None
) -> Dict[str, Any]:
    """Post image with message to Facebook Page using Graph API.
    
    Args:
        image_url: Publicly accessible image URL
        message: Post message/caption (max 63,206 characters)
        page_id: Facebook Page ID (reads from env FACEBOOK_PAGE_ID if not provided)
        access_token: Page access token (reads from tokens file if not provided)
    
    Returns:
        Dict with post data including 'id' and 'post_id'
    
    Raises:
        RuntimeError on failure
    """
    if not image_url:
        raise ValueError('image_url is required')
    
    if not message:
        message = ''  # Empty message is allowed
    
    # Get page ID from environment if not provided
    if not page_id:
        page_id = os.environ.get('FACEBOOK_PAGE_ID')
        if not page_id:
            logger.warning('FACEBOOK_PAGE_ID not set in environment; skipping Facebook post')
            return None
    
    # Get access token from file if not provided
    if not access_token:
        try:
            access_token = _get_valid_access_token()
        except Exception as e:
            logger.warning(f'Failed to get Facebook access token: {e}; skipping Facebook post')
            return None
    
    logger.info(f'🔵 Posting to Facebook Page: {message[:50]}...')
    
    # Post photo with message to Facebook Page
    url = f'https://graph.facebook.com/v18.0/{page_id}/photos'

    # Determine whether image_url is a public HTTP URL or a local filesystem path
    is_http = isinstance(image_url, str) and image_url.lower().startswith(('http://', 'https://'))

    
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            if is_http:
                # Send by public URL
                params = {'url': image_url, 'caption': message, 'access_token': access_token}
                resp = requests.post(url, data=params, timeout=30)
            else:
                # Treat image_url as local filesystem path and upload binary via 'source'
                from pathlib import Path
                p = Path(image_url)
                if not p.is_absolute():
                    # Resolve relative paths against project root
                    proj_root = Path(__file__).resolve().parent.parent.parent
                    p = (proj_root / image_url).resolve()

                if not p.exists():
                    raise RuntimeError(f'Local image file not found: {p}')

                data = {'caption': message, 'access_token': access_token}
                with open(p, 'rb') as fh:
                    files = {'source': fh}
                    resp = requests.post(url, data=data, files=files, timeout=120)
            
            if resp.status_code == 200:
                data = resp.json()
                photo_id = data.get('id')
                post_id = data.get('post_id')
                
                if photo_id:
                    logger.info(f'✅ Successfully posted to Facebook: photo_id={photo_id}, post_id={post_id}')
                    return {
                        'id': photo_id,
                        'post_id': post_id,
                        'status': 'published'
                    }
                else:
                    logger.error(f'No photo ID in response: {data}')
                    raise RuntimeError(f'No photo ID in Facebook response: {data}')
            else:
                status = resp.status_code
                try:
                    error_data = resp.json()
                    error_msg = error_data.get('error', {}).get('message', resp.text)
                except Exception:
                    error_msg = resp.text
                
                logger.error(f'Failed to post to Facebook: {status} {error_msg}')
                
                # Don't retry on client errors (4xx)
                if 400 <= status < 500:
                    logger.warning('Client error, not retrying')
                    raise RuntimeError(f'Facebook API error: {status} {error_msg}')
                
                # Retry on server errors (5xx)
                if attempt < max_attempts - 1:
                    backoff = 2 ** attempt  # Exponential backoff: 1s, 2s, 4s
                    logger.info(f'Retrying in {backoff}s... (attempt {attempt + 1}/{max_attempts})')
                    time.sleep(backoff)
                    continue
                
                raise RuntimeError(f'Facebook API error after {max_attempts} attempts: {status} {error_msg}')
                
        except requests.exceptions.RequestException as e:
            logger.error(f'Request failed: {e}')
            if attempt < max_attempts - 1:
                backoff = 2 ** attempt
                time.sleep(backoff)
                continue
            raise RuntimeError(f'Facebook request failed: {e}')
    
    raise RuntimeError('Failed to post to Facebook after all retry attempts')


__all__ = ['post_facebook']
