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
    logger.debug('OpenAI request: model=%s messages=%d max_tokens=%s', model, len(messages) if messages is not None else 0, max_tokens)

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
