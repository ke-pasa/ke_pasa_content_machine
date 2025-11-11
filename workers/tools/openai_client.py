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
import re
import logging
import time

_client = None


def get_openai_client() -> Optional[object]:
    """Return an instantiated OpenAI client or None.

    Uses the OPENAI_API_KEY environment variable. If the openai package
    is not installed or the key is missing, returns None.
    """
    global _client
    if _client is not None:
        return _client

    try:
        from openai import OpenAI
    except Exception:
        return None

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        return None

    try:
        _client = OpenAI(api_key=api_key)
        return _client
    except Exception:
        return None


def chat_completion(client: object, model: str, messages: List[Dict[str, str]],
                    max_tokens: int = 600, temperature: float = 0.0) -> Optional[str]:
    """Perform a chat completion and return the text content or None on error.

    This wraps the common call-site used across workers. It does not attempt
    to interpret the response; callers should parse JSON if needed.
    """
    logger = logging.getLogger('workers.tools.openai_client')
    # Basic validation and sanitization of inputs to surface obvious issues early
    try:
        msg_count = len(messages) if messages is not None else 0
    except Exception:
        msg_count = 0

    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 600

    logger.debug('OpenAI request: model=%s messages=%d max_tokens=%d', model, msg_count, max_tokens)

    # Build a safe, truncated payload snippet for logging to aid debugging without
    # dumping possibly huge or sensitive content. Each message content is truncated.
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
            logger.debug('OpenAI payload snippet: %s', json.dumps({'model': model, 'messages_sample': snippet_messages, 'max_tokens': max_tokens}, ensure_ascii=False)[:2000])
        except Exception:
            logger.debug('OpenAI payload snippet available but failed to serialize details')
    except Exception:
        # Don't fail on logging preparations
        pass

    # Simple payload size guard to catch accidentally huge inputs (helps avoid 400s)
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
        if approx_payload_size > 200000:  # 200k chars threshold
            logger.warning('OpenAI request payload appears very large (%d chars); aborting request to avoid 400', approx_payload_size)
            return None
    except Exception:
        pass

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature
            )
            # Support both newer structured responses and older text fields
            try:
                return resp.choices[0].message.content.strip()
            except Exception:
                return getattr(resp.choices[0], 'text', '').strip()

        except Exception as e:
            # Determine if this is a transient (5xx) error; if so, retry a few times with backoff.
            status = None
            try:
                if hasattr(e, 'response') and getattr(e.response, 'status_code', None) is not None:
                    status = int(getattr(e.response, 'status_code'))
                elif hasattr(e, 'status_code'):
                    status = int(getattr(e, 'status_code'))
                elif hasattr(e, 'http_status'):
                    status = int(getattr(e, 'http_status'))
                elif hasattr(e, 'code'):
                    # some libs put code strings here; ignore for numeric check
                    try:
                        status = int(getattr(e, 'code'))
                    except Exception:
                        status = None
            except Exception:
                status = None

            # If status is a 4xx, do not retry — it's a client error
            if status is not None and 400 <= status < 500:
                logger.warning('OpenAI request failed with client error status=%s; not retrying (attempt %d/%d)', status, attempt, max_attempts)
                try:
                    details = {'model': model, 'messages_count': len(messages) if messages is not None else 0, 'status': status}
                    # Attempt to extract HTTP-like response body/text for diagnostics
                    resp_text = None
                    try:
                        if hasattr(e, 'response'):
                            resp = getattr(e, 'response')
                            resp_text = getattr(resp, 'text', None) or getattr(resp, 'body', None)
                        # Some SDK exceptions include a raw 'response_text' or similar
                        if not resp_text and hasattr(e, 'response_text'):
                            resp_text = getattr(e, 'response_text')
                    except Exception:
                        resp_text = None

                    if resp_text:
                        try:
                            details['response_text_snippet'] = (resp_text[:1000] + '...') if len(resp_text) > 1000 else resp_text
                        except Exception:
                            details['response_text_snippet'] = '<<failed to capture response text>>'

                    # If the exception carries headers or request id, include them for tracing
                    try:
                        hdrs = getattr(e, 'headers', None) or getattr(getattr(e, 'response', None), 'headers', None)
                        if hdrs:
                            # include a couple of useful headers when present
                            for h in ('x-request-id', 'x-request-id', 'x-openai-request-id', 'x-request-id'):
                                if isinstance(h, str) and h in hdrs:
                                    details.setdefault('headers', {})[h] = hdrs.get(h)
                    except Exception:
                        pass

                    logger.exception('OpenAI chat completion failed (client error): %s; details=%s', str(e), details)
                except Exception:
                    logger.exception('OpenAI chat completion failed and error logging failed: %s', e)
                try:
                    logger.error('OpenAI exception (raw): %s', repr(e))
                    logger.error('OpenAI exception attrs: %s', getattr(e, '__dict__', {}))
                except Exception:
                    pass
                return None

            # For 5xx or unknown status, retry up to max_attempts
            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning('OpenAI request failed (attempt %d/%d) status=%s; retrying in %.1fs', attempt, max_attempts, status, backoff)
                time.sleep(backoff)
                continue

            # final attempt failed — log full details and return None
            try:
                details = {'model': model, 'messages_count': len(messages) if messages is not None else 0, 'status': status}
                if hasattr(e, 'response'):
                    try:
                        text = getattr(e.response, 'text', None)
                        if text:
                            details['response_text_snippet'] = (text[:400] + '...') if len(text) > 400 else text
                    except Exception:
                        pass
                logger.exception('OpenAI chat completion failed after retries: %s; details=%s', str(e), details)
            except Exception:
                logger.exception('OpenAI chat completion final failure and logging failed: %s', e)

            try:
                logger.error('OpenAI exception (raw): %s', repr(e))
                logger.error('OpenAI exception attrs: %s', getattr(e, '__dict__', {}))
            except Exception:
                pass

            return None
    try:
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            max_completion_tokens=max_tokens,
            temperature=temperature
        )
        # Support both newer structured responses and older text fields
        try:
            return resp.choices[0].message.content.strip()
        except Exception:
            return getattr(resp.choices[0], 'text', '').strip()
    except Exception as e:
        # Log helpful, non-sensitive diagnostics to aid debugging in CI.
        try:
            details = {'model': model, 'messages_count': len(messages) if messages is not None else 0}
            # capture any HTTP/status-like attributes if available
            for attr in ('http_status', 'status_code', 'code'):
                if hasattr(e, attr):
                    try:
                        details[attr] = getattr(e, attr)
                    except Exception:
                        pass

            # some client exceptions expose a response with text
            if hasattr(e, 'response'):
                try:
                    resp_obj = getattr(e, 'response')
                    text = getattr(resp_obj, 'text', None)
                    if text:
                        details['response_text_snippet'] = (text[:400] + '...') if len(text) > 400 else text
                except Exception:
                    pass

            logger.exception('OpenAI chat completion failed: %s; details=%s', str(e), details)
            # Also emit the raw exception repr and attributes for full debugging visibility
            try:
                logger.error('OpenAI exception (raw): %s', repr(e))
                logger.error('OpenAI exception attrs: %s', getattr(e, '__dict__', {}))
            except Exception:
                pass
        except Exception:
            # Ensure we never raise while trying to log an error
            logger.exception('OpenAI chat completion failed and error logging failed: %s', e)
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
