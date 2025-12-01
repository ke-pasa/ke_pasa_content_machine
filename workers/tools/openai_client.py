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
                    max_tokens: int = 6000, temperature: float = 0.0) -> Optional[str]:
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
    UNSUPPORTED_TEMPERATURE_MODELS = {'gpt-5-mini'}

    def _extract_content(resp) -> Optional[str]:
        """Extract content from OpenAI response, with logging for empty responses."""
        try:
            content = resp.choices[0].message.content
            if content is None or (isinstance(content, str) and content.strip() == ''):
                try:
                    if hasattr(resp, 'to_dict'):
                        serial = resp.to_dict()
                    else:
                        serial = {'choices': [getattr(c, '__dict__', str(c)) for c in getattr(resp, 'choices', [])]}
                    logger.warning('OpenAI response empty content; full response: %s', json.dumps(serial, ensure_ascii=False)[:20000])
                except Exception:
                    logger.warning('OpenAI response empty content; resp repr: %s', repr(resp))
                return None
            return content.strip()
        except Exception:
            try:
                txt = getattr(resp.choices[0], 'text', '')
                if txt and isinstance(txt, str) and txt.strip():
                    return txt.strip()
            except Exception:
                pass
        return None

    def _extract_status(e: Exception) -> Optional[int]:
        """Extract HTTP status code from exception."""
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
        """Extract response body text from exception for logging."""
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
            # Build kwargs conditionally to avoid sending parameters unsupported by some models
            req_kwargs = {
                'model': model,
                'messages': messages,
                'max_completion_tokens': max_tokens,
                'max_reasoning_tokens': 0,  # Disable chain-of-thought reasoning
                'stream': False,
            }
            # Only include temperature when the model is known to accept it and a value was provided
            try:
                if temperature is not None and model not in UNSUPPORTED_TEMPERATURE_MODELS:
                    req_kwargs['temperature'] = temperature
            except Exception:
                # If anything goes wrong determining support, omit the temperature to be safe
                pass

            resp = client.chat.completions.create(**req_kwargs)
            content = _extract_content(resp)
            if content is not None:
                return content
            # Empty content is treated as non-recoverable
            logger.warning('OpenAI returned empty content (attempt %d/%d); not retrying', attempt, max_attempts)
            return None

        except Exception as e:
            status = _extract_status(e)
            resp_text = _extract_response_text(e)

            # If status is a 4xx, do not retry — it's a client error
            if status is not None and 400 <= status < 500:
                logger.warning('OpenAI request failed with client error status=%s; not retrying (attempt %d/%d)', status, attempt, max_attempts)
                try:
                    details = {'model': model, 'messages_count': len(messages) if messages is not None else 0, 'status': status}
                    if resp_text:
                        details['response_text_snippet'] = (resp_text[:1000] + '...') if len(resp_text) > 1000 else resp_text
                    logger.exception('OpenAI chat completion failed (client error): %s; details=%s', str(e), details)
                except Exception:
                    logger.exception('OpenAI chat completion failed and error logging failed: %s', e)

                # Fallback: retry without temperature if error mentions it
                try:
                    lowered = '' if resp_text is None else str(resp_text)
                    combined = (lowered + '\n' + str(e)).lower()
                    if 'temperature' in combined and ('unsupported' in combined or 'does not support' in combined):
                        logger.warning('Detected unsupported temperature for model=%s; retrying without temperature', model)
                        try:
                            resp2 = client.chat.completions.create(
                                model=model,
                                messages=messages,
                                max_completion_tokens=max_tokens,
                                max_reasoning_tokens=0,
                                stream=False
                            )
                            return _extract_content(resp2)
                        except Exception:
                            logger.exception('Retry without temperature also failed')
                except Exception:
                    pass

                return None

            # Server errors (5xx) or unknown: retry with backoff
            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning('OpenAI request failed (attempt %d/%d) status=%s; retrying in %.1fs', attempt, max_attempts, status, backoff)
                time.sleep(backoff)
                continue

            # Final attempt failed
            try:
                details = {'model': model, 'messages_count': len(messages) if messages is not None else 0, 'status': status}
                if resp_text:
                    details['response_text_snippet'] = (resp_text[:400] + '...') if len(resp_text) > 400 else resp_text
                logger.exception('OpenAI chat completion failed after retries: %s; details=%s', str(e), details)
            except Exception:
                logger.exception('OpenAI chat completion final failure and logging failed: %s', e)

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
