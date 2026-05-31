#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Light wrapper around OpenAI client usage.

This module centralizes OpenAI client creation and a small helper to
perform chat completions. Other workers should import and use these
helpers instead of importing openai directly.
"""
from typing import Optional, List, Dict, Any
import os
import json
try:
    from dotenv import load_dotenv as _load_dotenv
    try:
        _load_dotenv()
    except Exception:
        pass
except Exception:
    _load_dotenv = None
import re
import logging
import time

_client = None

# Map legacy Azure deployment names to standard OpenAI model names
_MODEL_ALIASES = {
    'gpt-5.2-chat': 'gpt-5.4',
    'gpt-4o-mini': 'gpt-5.4-mini',
}


def get_openai_client(endpoint_suffix: str = '') -> Optional[object]:
    """Get or create OpenAI client instance.

    Args:
        endpoint_suffix: Ignored (kept for backward compatibility with Azure multi-endpoint callers).

    Returns:
        OpenAI client instance, or None if OPENAI_API_KEY not configured.
    """
    global _client

    if _client is not None:
        return _client

    try:
        from openai import OpenAI
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error('OPENAI_API_KEY not configured')
            return None

        _client = OpenAI(api_key=api_key)
        logging.getLogger('workers.tools.openai_client').info('Using OpenAI API (OPENAI_API_KEY)')
        return _client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"OpenAI client init failed: {e}")
        return None


def chat_completion(client: object, model: str, messages: List[Dict[str, str]],
                    max_tokens: int = 6000,
                    reasoning_effort: Optional[str] = 'low',
                    **_kwargs) -> Optional[str]:
    """Perform a chat completion and return the text content or None on error.

    Args:
        client: OpenAI client instance (if None, will be fetched automatically).
        model: Model name to use. Azure-specific deployment names are aliased to OpenAI equivalents.
        messages: List of message dicts with 'role' and 'content' keys.
        max_tokens: Maximum tokens to generate.
        reasoning_effort: Unused, kept for backward compatibility.
    """
    logger = logging.getLogger('workers.tools.openai_client')

    # Resolve legacy Azure deployment names to standard OpenAI model names
    resolved_model = _MODEL_ALIASES.get(model, model)

    # Ensure we have a client
    if client is None:
        client = get_openai_client()
        if not client:
            logger.error('No OpenAI client available')
            return None

    try:
        msg_count = len(messages) if messages is not None else 0
    except Exception:
        msg_count = 0

    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 600

    logger.debug('OpenAI request: model=%s messages=%d max_tokens=%d', resolved_model, msg_count, max_tokens)

    try:
        snippet_messages = []
        if isinstance(messages, list):
            for m in messages:
                try:
                    role = m.get('role') if isinstance(m, dict) else str(type(m))
                    content = m.get('content', '') if isinstance(m, dict) else ''
                    if content and not isinstance(content, str):
                        content = str(content)
                    snippet_messages.append({'role': role, 'content_snippet': (content[:500] + '...') if len(content) > 500 else content})
                except Exception:
                    snippet_messages.append({'role': '??', 'content_snippet': '<<unserializable>>'})
        else:
            snippet_messages = [{'role': '??', 'content_snippet': '<<invalid messages type>>'}]
        try:
            logger.debug('OpenAI payload snippet: %s', json.dumps({'model': resolved_model, 'messages_sample': snippet_messages, 'max_tokens': max_tokens}, ensure_ascii=False)[:2000])
        except Exception:
            logger.debug('OpenAI payload snippet available but failed to serialize details')
    except Exception:
        pass

    # Payload size guard to avoid 400s on huge inputs
    try:
        approx_payload_size = 0
        if isinstance(messages, list):
            for m in messages:
                try:
                    if isinstance(m, dict):
                        approx_payload_size += len(str(m.get('content', '')))
                    else:
                        approx_payload_size += len(str(m))
                except Exception:
                    approx_payload_size += 1000
        else:
            approx_payload_size = len(str(messages))
        if approx_payload_size > 200000:
            logger.warning('OpenAI request payload appears very large (%d chars); aborting request to avoid 400', approx_payload_size)
            return None
    except Exception:
        pass

    max_attempts = 3

    def _extract_status(e: Exception) -> Optional[int]:
        try:
            if hasattr(e, 'response') and getattr(e.response, 'status_code', None) is not None:
                return int(getattr(e.response, 'status_code'))
            elif hasattr(e, 'status_code'):
                return int(getattr(e, 'status_code'))
            elif hasattr(e, 'http_status'):
                return int(getattr(e, 'http_status'))
            elif hasattr(e, 'code'):
                try:
                    return int(getattr(e, 'code'))
                except Exception:
                    pass
        except Exception:
            pass
        return None

    def _extract_response_text(e: Exception) -> Optional[str]:
        try:
            if hasattr(e, 'response'):
                resp = getattr(e, 'response')
                return getattr(resp, 'text', None) or getattr(resp, 'body', None)
            if hasattr(e, 'response_text'):
                return getattr(e, 'response_text')
        except Exception:
            pass
        return None

    for attempt in range(1, max_attempts + 1):
        try:
            req_kwargs = {
                'model': resolved_model,
                'messages': messages,
                'max_completion_tokens': max_tokens,
            }

            resp = client.chat.completions.create(**req_kwargs)

            if resp.choices and len(resp.choices) > 0:
                content = resp.choices[0].message.content
                if content:
                    try:
                        if resp.usage:
                            logger.info('OpenAI usage: prompt=%d completion=%d total=%d',
                                        resp.usage.prompt_tokens,
                                        resp.usage.completion_tokens,
                                        resp.usage.total_tokens)
                    except Exception:
                        pass
                    return content.strip()
            logger.warning('OpenAI returned empty content (attempt %d/%d); not retrying', attempt, max_attempts)
            return None

        except Exception as e:
            status = _extract_status(e)
            resp_text = _extract_response_text(e)

            if status is not None and 400 <= status < 500:
                logger.warning('OpenAI request failed with client error status=%s', status)
                if resp_text:
                    logger.warning('Response snippet: %s', resp_text[:500])
                return None

            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning('OpenAI request failed (attempt %d/%d) status=%s; retrying in %.1fs',
                               attempt, max_attempts, status, backoff)
                time.sleep(backoff)
                continue

            logger.exception('OpenAI request failed after %d attempts: %s', max_attempts, str(e))
            return None

    return None


def parse_json_from_text(text: str) -> Optional[dict]:
    """Try to parse JSON from a model response string.

    First attempts a direct json.loads(). If that fails, searches for the
    first JSON object substring and parses it. Returns dict on success or
    None on failure.
    """
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None
