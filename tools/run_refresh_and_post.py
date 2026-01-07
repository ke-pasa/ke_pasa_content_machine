"""Attempt token refresh and perform one real post+delete for diagnostics.

Usage: python tools/run_refresh_and_post.py

This script will unset `X_DRY_RUN`, call _get_valid_access_token() to force a refresh
if needed, then post a short test tweet and delete it. It prints clear status codes
for debugging the OAuth/token problems observed earlier.
"""
from __future__ import annotations

import logging
import os
import sys
import time

from workers.tools.x_helper import _get_valid_access_token, post_tweet
from tools.x_test_post import delete_tweet

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger('run_refresh_and_post')


def main() -> int:
    # Ensure dry-run is disabled for a real attempt
    os.environ.pop('X_DRY_RUN', None)

    logger.info('Ensuring access token is valid (may trigger refresh)')
    try:
        tok = _get_valid_access_token()
        logger.info('Got access token prefix: %s', tok[:60])
    except Exception as e:
        logger.exception('Failed to obtain valid access token: %s', e)
        return 1

    text = 'ke-pasa integration test (will be deleted)'
    logger.info('Posting test tweet...')
    try:
        res = post_tweet(text)
    except Exception:
        logger.exception('post_tweet raised an exception')
        return 2

    # If dry-run returned a mock (should not happen when X_DRY_RUN removed), handle
    if isinstance(res, dict) and res.get('mock'):
        logger.info('Got dry-run mock response: %s', res)
        return 0

    tweet_id = None
    try:
        tweet_id = res.get('data', {}).get('id')
    except Exception:
        logger.exception('Failed to parse post response')

    if not tweet_id:
        logger.error('No tweet id found in response: %s', res)
        return 3

    logger.info('Posted tweet id=%s. Waiting 2s then deleting...', tweet_id)
    time.sleep(2)

    try:
        status, body = delete_tweet(tweet_id)
        if status in (200, 204):
            logger.info('Deleted tweet %s successfully (status=%s)', tweet_id, status)
            return 0
        else:
            logger.error('Failed to delete tweet %s: status=%s body=%s', tweet_id, status, body)
            return 4
    except Exception:
        logger.exception('Exception while deleting tweet')
        return 5


if __name__ == '__main__':
    sys.exit(main())
