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
_gemini_client = None


class LLMError(Exception):
    """Raised by chat_completion when raise_errors=True and the request fails.

    Carries the HTTP status code (when available) so callers can implement
    model-fallback logic (e.g. skip a model on 404, bench it on 429).
    """
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


class RateLimitError(LLMError):
    """Raised on HTTP 429 (rate limit / quota exhausted) when raise_errors=True."""
    pass

# Gemini exposes an OpenAI-compatible endpoint, so we reuse the openai SDK
# pointed at this base URL. See https://ai.google.dev/gemini-api/docs/openai
GEMINI_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta/openai/'

# Map legacy Azure deployment names to standard OpenAI model names
_MODEL_ALIASES = {
    'gpt-5.2-chat': 'gpt-5.4',
    'gpt-4o-mini': 'gpt-5.4-mini',
}


def _is_gemini_model(model: str) -> bool:
    """Return True if the model name targets Google Gemini."""
    return bool(model) and str(model).lower().startswith('gemini')


def get_gemini_client() -> Optional[object]:
    """Get or create a Gemini client (via the OpenAI-compatible endpoint).

    Uses the GEMINI_API_KEY env var (Google AI Studio key, free tier eligible).
    Returns an OpenAI client instance configured for Gemini, or None if the key
    is not configured.
    """
    global _gemini_client

    if _gemini_client is not None:
        return _gemini_client

    try:
        from openai import OpenAI
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error('GEMINI_API_KEY not configured')
            return None

        _gemini_client = OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL)
        logging.getLogger('workers.tools.openai_client').info('Using Gemini API (GEMINI_API_KEY)')
        return _gemini_client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"Gemini client init failed: {e}")
        return None


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
                    reasoning_effort: Optional[str] = None,
                    raise_errors: bool = False,
                    **_kwargs) -> Optional[str]:
    """Perform a chat completion and return the text content or None on error.

    Args:
        client: OpenAI client instance (if None, will be fetched automatically).
        model: Model name to use. Azure-specific deployment names are aliased to OpenAI equivalents.
        messages: List of message dicts with 'role' and 'content' keys.
        max_tokens: Maximum tokens to generate.
        reasoning_effort: Reasoning effort level (none/low/medium/high/xhigh). None = model default.
        raise_errors: If True, raise RateLimitError on HTTP 429 and LLMError on
            other terminal request failures instead of returning None. Lets
            callers implement model-fallback chains. Default False preserves the
            return-None-on-error behavior other callers rely on.
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

    is_gemini = _is_gemini_model(resolved_model)

    for attempt in range(1, max_attempts + 1):
        try:
            if is_gemini:
                # Gemini's OpenAI-compatible endpoint expects `max_tokens`.
                # `reasoning_effort` is only honored by 2.5 thinking models;
                # sending it to others (e.g. 2.0-flash) causes a 400.
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_tokens': max_tokens,
                }
                if reasoning_effort is not None and '2.5' in resolved_model:
                    req_kwargs['reasoning_effort'] = reasoning_effort
            else:
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_completion_tokens': max_tokens,
                }
                if reasoning_effort is not None:
                    req_kwargs['reasoning_effort'] = reasoning_effort

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
                if raise_errors:
                    if status == 429:
                        raise RateLimitError('rate limit / quota exhausted (429)', status=429)
                    raise LLMError(f'client error {status}', status=status)
                return None

            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning('OpenAI request failed (attempt %d/%d) status=%s; retrying in %.1fs',
                               attempt, max_attempts, status, backoff)
                time.sleep(backoff)
                continue

            logger.exception('OpenAI request failed after %d attempts: %s', max_attempts, str(e))
            if raise_errors:
                raise LLMError(str(e), status=status)
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
