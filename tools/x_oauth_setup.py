"""Interactive X OAuth 2.0 authorization to obtain tokens.

Запускает локальный HTTP сервер на :8080, открывает браузер для авторизации,
получает authorization code и обменивает его на access_token + refresh_token.
Сохраняет токены в .x_tokens.json в корне проекта.

Usage:
  python -m tools.x_oauth_setup

Требуется:
  - X_CLIENT_ID и X_CLIENT_SECRET в .env или environment
"""
from __future__ import annotations

import os
import sys
import json
import logging
import webbrowser
from pathlib import Path
from datetime import datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Load .env
load_dotenv()

CLIENT_ID = os.environ.get('X_CLIENT_ID')
CLIENT_SECRET = os.environ.get('X_CLIENT_SECRET')
REDIRECT_URI = 'http://localhost:8080/callback'
TOKEN_FILE = Path(__file__).parent.parent / '.x_tokens.json'

# OAuth URLs
AUTH_URL = 'https://twitter.com/i/oauth2/authorize'
TOKEN_URL = 'https://api.twitter.com/2/oauth2/token'

# Scopes для User Context (tweet.read + tweet.write + users.read + offline.access)
SCOPES = 'tweet.read tweet.write users.read offline.access'


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler для получения authorization code от X."""
    
    auth_code = None
    state_received = None
    
    def do_GET(self):
        """Обработка GET запроса от X OAuth redirect."""
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        
        if parsed.path == '/callback':
            # Получили authorization code
            CallbackHandler.auth_code = params.get('code', [None])[0]
            CallbackHandler.state_received = params.get('state', [None])[0]
            error = params.get('error', [None])[0]
            
            if error:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(f'<h1>Authorization failed: {error}</h1>'.encode())
                logger.error(f'Authorization error: {error}')
            elif CallbackHandler.auth_code:
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<h1>Authorization successful!</h1><p>You can close this window.</p>')
                logger.info('✓ Received authorization code')
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b'<h1>No code received</h1>')
        else:
            self.send_response(404)
            self.end_headers()
    
    def log_message(self, format, *args):
        """Отключаем логи HTTP сервера."""
        pass


def exchange_code_for_token(code: str) -> dict:
    """Обменивает authorization code на access_token и refresh_token."""
    logger.info('Exchanging authorization code for tokens...')
    
    data = {
        'code': code,
        'grant_type': 'authorization_code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'code_verifier': 'challenge',  # PKCE (в продакшене должен быть случайный)
    }
    
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
    }
    
    # Basic auth с client credentials
    auth = (CLIENT_ID, CLIENT_SECRET)
    
    resp = requests.post(TOKEN_URL, data=data, headers=headers, auth=auth, timeout=30)
    
    if resp.status_code != 200:
        logger.error(f'Token exchange failed: {resp.status_code} {resp.text}')
        raise RuntimeError(f'Failed to get tokens: {resp.status_code}')
    
    tokens = resp.json()
    logger.info('✓ Tokens received')
    return tokens


def save_tokens(tokens: dict):
    """Сохраняет токены в .x_tokens.json."""
    tokens['obtained_at'] = datetime.utcnow().isoformat()
    TOKEN_FILE.write_text(json.dumps(tokens, indent=2))
    logger.info(f'✓ Tokens saved to {TOKEN_FILE}')


def main() -> int:
    if not CLIENT_ID or not CLIENT_SECRET:
        logger.error('X_CLIENT_ID and X_CLIENT_SECRET must be set in .env or environment')
        return 1
    
    # Генерируем state для защиты от CSRF
    import secrets
    state = secrets.token_urlsafe(32)
    
    # Формируем authorization URL
    auth_params = {
        'response_type': 'code',
        'client_id': CLIENT_ID,
        'redirect_uri': REDIRECT_URI,
        'scope': SCOPES,
        'state': state,
        'code_challenge': 'challenge',  # PKCE (в продакшене должен быть hash от verifier)
        'code_challenge_method': 'plain',
    }
    
    auth_url_full = AUTH_URL + '?' + '&'.join(f'{k}={v}' for k, v in auth_params.items())
    
    logger.info('Starting local HTTP server on :8080...')
    server = HTTPServer(('localhost', 8080), CallbackHandler)
    
    logger.info('Opening browser for authorization...')
    logger.info(f'If browser does not open, visit:\n  {auth_url_full}')
    webbrowser.open(auth_url_full)
    
    logger.info('Waiting for authorization callback...')
    # Ждём один запрос (callback от X)
    server.handle_request()
    
    if not CallbackHandler.auth_code:
        logger.error('No authorization code received')
        return 2
    
    # Проверяем state
    if CallbackHandler.state_received != state:
        logger.error('State mismatch — possible CSRF attack')
        return 3
    
    # Обмениваем code на токены
    try:
        tokens = exchange_code_for_token(CallbackHandler.auth_code)
    except Exception as e:
        logger.exception(f'Failed to exchange code for tokens: {e}')
        return 4
    
    # Сохраняем токены
    try:
        save_tokens(tokens)
    except Exception as e:
        logger.exception(f'Failed to save tokens: {e}')
        return 5
    
    logger.info('✅ Authorization complete!')
    logger.info(f'Tokens saved to: {TOKEN_FILE}')
    logger.info('\nNext steps:')
    logger.info('  1. Test locally: python -m tools.x_test_post --text "Test" --wait 2')
    logger.info(f'  2. Encode for GitHub Secret: python -c "import base64; print(base64.b64encode(open(\'{TOKEN_FILE}\').read().encode()).decode())"')
    logger.info('  3. Update GitHub Secret X_TOKENS_BASE64 and run Deploy workflow')
    
    return 0


if __name__ == '__main__':
    sys.exit(main())
