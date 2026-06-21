#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Light wrapper around OpenAI-compatible client usage.

This module centralizes OpenAI/OpenRouter/Gemini client creation and a small
helper to perform chat completions. Other workers should import and use these
helpers instead of importing SDKs directly.
"""
from typing import Optional, List, Dict
import os
import json
import requests
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
_openrouter_client = None


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
OPENROUTER_BASE_URL = os.getenv('OPENROUTER_BASE_URL', 'https://openrouter.ai/api/v1')
OPENROUTER_FREE_TEXT_MODEL = 'google/gemma-4-31b-it:free'
OPENROUTER_FREE_TEXT_MODEL_MINI = 'openai/gpt-oss-20b:free'
OPENROUTER_FREE_EMBEDDING_MODEL = 'nvidia/llama-nemotron-embed-vl-1b-v2:free'
OPENROUTER_FREE_IMAGE_MODEL = None

# Map legacy deployment / provider-local names to stable logical names first.
_LOGICAL_MODEL_ALIASES = {
    'gpt-5.2-chat': 'gpt-5.4',
    'gpt-4o-mini': 'gpt-5.4-mini',
}

# Then map logical names to OpenRouter slugs when routing through OpenRouter.
_OPENROUTER_MODEL_ALIASES = {
    'gpt-5.4': OPENROUTER_FREE_TEXT_MODEL,
    'gpt-5.4-mini': OPENROUTER_FREE_TEXT_MODEL_MINI,
    'text-embedding-3-small': OPENROUTER_FREE_EMBEDDING_MODEL,
    'gemini-2.5-flash': 'google/gemini-2.5-flash',
    'gemini-3.5-flash': 'google/gemini-3.5-flash',
    'gemini-3.1-flash-lite': 'google/gemini-3.1-flash-lite',
    'gemini-3.1-flash-image-preview': 'google/gemini-3.1-flash-image-preview',
    'dall-e-3': OPENROUTER_FREE_IMAGE_MODEL,
    'dall-e-2': OPENROUTER_FREE_IMAGE_MODEL,
    'gpt-image-1': OPENROUTER_FREE_IMAGE_MODEL,
}


def get_openrouter_api_key() -> Optional[str]:
    """Return the OpenRouter API key."""
    return os.getenv('OR_API_KEY')


def is_openrouter_enabled() -> bool:
    """Return True when OpenRouter should be used as the primary backend."""
    return bool(get_openrouter_api_key())


def _client_provider(client: Optional[object]) -> Optional[str]:
    try:
        return getattr(client, '_ke_provider', None)
    except Exception:
        return None


def _tag_client(client: object, provider: str) -> object:
    try:
        setattr(client, '_ke_provider', provider)
    except Exception:
        pass
    return client


def is_openrouter_client(client: Optional[object]) -> bool:
    """Return True if the client is configured for OpenRouter."""
    return _client_provider(client) == 'openrouter'


def _build_openrouter_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {}
    referer = os.getenv('OPENROUTER_APP_URL') or os.getenv('OPENROUTER_HTTP_REFERER')
    title = os.getenv('OPENROUTER_APP_TITLE') or os.getenv('OPENROUTER_X_TITLE')
    if referer:
        headers['HTTP-Referer'] = referer
    if title:
        headers['X-Title'] = title
    return headers


def get_openrouter_headers() -> Dict[str, str]:
    """Build HTTP headers for direct OpenRouter REST calls."""
    api_key = get_openrouter_api_key()
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    headers.update(_build_openrouter_headers())
    return headers


def resolve_model_name(model: str, provider: Optional[str] = None) -> str:
    """Resolve legacy model names to provider-specific slugs when needed."""
    logical_model = _LOGICAL_MODEL_ALIASES.get(model, model)
    target_provider = provider or ('openrouter' if is_openrouter_enabled() else 'openai')
    if target_provider == 'openrouter':
        return _OPENROUTER_MODEL_ALIASES.get(logical_model, logical_model)
    return logical_model


def _is_gemini_model(model: str) -> bool:
    """Return True if the model name targets Google Gemini."""
    normalized = (model or '').lower()
    return normalized.startswith('gemini') or normalized.startswith('google/gemini')


def get_openrouter_client() -> Optional[object]:
    """Get or create an OpenRouter-backed OpenAI-compatible client."""
    global _openrouter_client

    if _openrouter_client is not None:
        return _openrouter_client

    try:
        from openai import OpenAI

        api_key = get_openrouter_api_key()
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error('OR_API_KEY not configured')
            return None

        kwargs = {
            'api_key': api_key,
            'base_url': OPENROUTER_BASE_URL,
        }
        headers = _build_openrouter_headers()
        if headers:
            kwargs['default_headers'] = headers

        _openrouter_client = _tag_client(OpenAI(**kwargs), 'openrouter')
        logging.getLogger('workers.tools.openai_client').info('Using OpenRouter API (OR_API_KEY)')
        return _openrouter_client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"OpenRouter client init failed: {e}")
        return None


def get_gemini_client() -> Optional[object]:
    """Get or create a Gemini client or OpenRouter fallback for Gemini models."""
    global _gemini_client

    if is_openrouter_enabled():
        return get_openrouter_client()

    if _gemini_client is not None:
        return _gemini_client

    try:
        from openai import OpenAI

        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error('GEMINI_API_KEY not configured')
            return None

        _gemini_client = _tag_client(OpenAI(api_key=api_key, base_url=GEMINI_BASE_URL), 'gemini')
        logging.getLogger('workers.tools.openai_client').info('Using Gemini API (GEMINI_API_KEY)')
        return _gemini_client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"Gemini client init failed: {e}")
        return None


def get_openai_client(endpoint_suffix: str = '') -> Optional[object]:
    """Get or create the primary OpenAI-compatible client instance.

    Args:
        endpoint_suffix: Ignored (kept for backward compatibility with Azure multi-endpoint callers).

    Returns:
        Client instance, or None if no compatible API key is configured.
    """
    global _client

    if is_openrouter_enabled():
        return get_openrouter_client()

    if _client is not None:
        return _client

    try:
        from openai import OpenAI

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error('OPENAI_API_KEY not configured')
            return None

        _client = _tag_client(OpenAI(api_key=api_key), 'openai')
        logging.getLogger('workers.tools.openai_client').info('Using OpenAI API (OPENAI_API_KEY)')
        return _client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"OpenAI client init failed: {e}")
        return None


def create_embedding(client: object, model: str, input_texts: List[str]) -> object:
    """Create embeddings via the configured provider.

    OpenRouter's free NVIDIA embedding model currently returns a response shape
    that the OpenAI SDK parser rejects, so we call the REST endpoint directly
    and return a dict-like payload in that case.
    """
    if client is None:
        client = get_openai_client()
        if not client:
            raise RuntimeError('No OpenAI-compatible client available')

    provider = _client_provider(client) or ('openrouter' if is_openrouter_enabled() else 'openai')
    resolved_model = resolve_model_name(model, provider=provider)

    if provider == 'openrouter':
        response = requests.post(
            f"{OPENROUTER_BASE_URL.rstrip('/')}/embeddings",
            headers=get_openrouter_headers(),
            json={
                'model': resolved_model,
                'input': input_texts,
            },
            timeout=120,
        )
        response.raise_for_status()
        return response.json()

    return client.embeddings.create(model=resolved_model, input=input_texts)


def chat_completion(client: object, model: str, messages: List[Dict[str, str]],
                    max_tokens: int = 6000,
                    reasoning_effort: Optional[str] = None,
                    raise_errors: bool = False,
                    **_kwargs) -> Optional[str]:
    """Perform a chat completion and return the text content or None on error.

    Args:
        client: OpenAI-compatible client instance (if None, will be fetched automatically).
        model: Model name to use. Legacy local aliases are resolved automatically.
        messages: List of message dicts with 'role' and 'content' keys.
        max_tokens: Maximum tokens to generate.
        reasoning_effort: Reasoning effort level (none/low/medium/high/xhigh). None = model default.
        raise_errors: If True, raise RateLimitError on HTTP 429 and LLMError on
            other terminal request failures instead of returning None.
    """
    logger = logging.getLogger('workers.tools.openai_client')

    if client is None:
        client = get_openai_client()
        if not client:
            logger.error('No OpenAI-compatible client available')
            return None

    provider = _client_provider(client) or ('openrouter' if is_openrouter_enabled() else 'openai')
    resolved_model = resolve_model_name(model, provider=provider)
    is_gemini = _is_gemini_model(resolved_model)
    is_openrouter = provider == 'openrouter'

    try:
        msg_count = len(messages) if messages is not None else 0
    except Exception:
        msg_count = 0

    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 600

    logger.debug('%s request: model=%s messages=%d max_tokens=%d', provider, resolved_model, msg_count, max_tokens)

    try:
        snippet_messages = []
        if isinstance(messages, list):
            for m in messages:
                try:
                    role = m.get('role') if isinstance(m, dict) else str(type(m))
                    content = m.get('content', '') if isinstance(m, dict) else ''
                    if content and not isinstance(content, str):
                        content = str(content)
                    snippet_messages.append({
                        'role': role,
                        'content_snippet': (content[:500] + '...') if len(content) > 500 else content,
                    })
                except Exception:
                    snippet_messages.append({'role': '??', 'content_snippet': '<<unserializable>>'})
        else:
            snippet_messages = [{'role': '??', 'content_snippet': '<<invalid messages type>>'}]
        try:
            logger.debug(
                '%s payload snippet: %s',
                provider,
                json.dumps(
                    {
                        'model': resolved_model,
                        'messages_sample': snippet_messages,
                        'max_tokens': max_tokens,
                    },
                    ensure_ascii=False,
                )[:2000],
            )
        except Exception:
            logger.debug('%s payload snippet available but failed to serialize details', provider)
    except Exception:
        pass

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
            logger.warning('%s request payload appears very large (%d chars); aborting request to avoid 400', provider, approx_payload_size)
            return None
    except Exception:
        pass

    max_attempts = 3

    def _extract_status(e: Exception) -> Optional[int]:
        try:
            if hasattr(e, 'response') and getattr(e.response, 'status_code', None) is not None:
                return int(getattr(e.response, 'status_code'))
            if hasattr(e, 'status_code'):
                return int(getattr(e, 'status_code'))
            if hasattr(e, 'http_status'):
                return int(getattr(e, 'http_status'))
            if hasattr(e, 'code'):
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
            if is_openrouter:
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_tokens': max_tokens,
                }
                if reasoning_effort is not None:
                    req_kwargs['reasoning'] = {'effort': reasoning_effort}
            elif is_gemini:
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
                            logger.info(
                                '%s usage: prompt=%d completion=%d total=%d',
                                provider,
                                resp.usage.prompt_tokens,
                                resp.usage.completion_tokens,
                                resp.usage.total_tokens,
                            )
                    except Exception:
                        pass
                    return content.strip()
            logger.warning('%s returned empty content (attempt %d/%d); not retrying', provider, attempt, max_attempts)
            return None

        except Exception as e:
            status = _extract_status(e)
            resp_text = _extract_response_text(e)

            if status is not None and 400 <= status < 500:
                logger.warning('%s request failed with client error status=%s', provider, status)
                if resp_text:
                    logger.warning('Response snippet: %s', resp_text[:500])
                if raise_errors:
                    if status == 429:
                        raise RateLimitError('rate limit / quota exhausted (429)', status=429)
                    raise LLMError(f'client error {status}', status=status)
                return None

            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning(
                    '%s request failed (attempt %d/%d) status=%s; retrying in %.1fs',
                    provider,
                    attempt,
                    max_attempts,
                    status,
                    backoff,
                )
                time.sleep(backoff)
                continue

            logger.exception('%s request failed after %d attempts: %s', provider, max_attempts, str(e))
            if raise_errors:
                raise LLMError(str(e), status=status)
            return None

    return None


def parse_json_from_text(text: str) -> Optional[dict]:
    """Try to parse JSON from a model response string."""
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
