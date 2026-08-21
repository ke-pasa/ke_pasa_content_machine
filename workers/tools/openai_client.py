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
_openrouter_free_text_models_cache = {'expires_at': 0.0, 'models': []}


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

# --- Google AI Studio free tier -------------------------------------------------
# Verified against the live account quota dashboard: the *-flash-lite models get
# 30K requests / 30M tokens per day and bill honestly (total == prompt +
# completion). The plain *-flash models share a 20M/day pool but silently burn
# ~285 extra tokens per call on hidden reasoning, so they are kept for quality
# work only, never as the default.
GEMINI_FREE_TEXT_MODEL = 'gemini-3.5-flash-lite'
GEMINI_FREE_TEXT_MODEL_MINI = 'gemini-3.1-flash-lite'
GEMINI_FREE_TEXT_MODELS = [
    GEMINI_FREE_TEXT_MODEL,
    GEMINI_FREE_TEXT_MODEL_MINI,
    'gemini-flash-lite-latest',
    'gemini-2.5-flash',
]
GEMINI_FREE_EMBEDDING_MODEL = 'gemini-embedding-001'
GEMINI_FREE_IMAGE_MODEL = 'gemini-3.1-flash-image'

# Models that report a tiny completion_tokens while charging a large
# total_tokens (hidden reasoning). Using them for bulk work drains the daily
# token quota ~25x faster than the visible output suggests.
GEMINI_HIGH_OVERHEAD_MODELS = {
    'gemini-3.6-flash',
    'gemini-3.7-flash',
    'gemini-3-flash-preview',
}

OPENROUTER_FREE_TEXT_MODEL = 'nvidia/nemotron-3-ultra-550b-a55b:free'
OPENROUTER_FREE_TEXT_MODEL_MINI = 'nvidia/nemotron-3-super-120b-a12b:free'
OPENROUTER_FREE_TEXT_MODELS = [
    OPENROUTER_FREE_TEXT_MODEL,
    OPENROUTER_FREE_TEXT_MODEL_MINI,
    'nvidia/nemotron-3.5-lightning:free',
]
# OpenRouter has no working free embedding or image model; those routes must go
# through Google AI Studio instead.
OPENROUTER_FREE_EMBEDDING_MODEL = None
OPENROUTER_FREE_IMAGE_MODEL = None

# OpenRouter free slugs that exist in the catalog but always refuse our key.
OPENROUTER_UNAVAILABLE_FREE_MODELS = {
    'thinkingmachines/inkling:free',
    'thinkingmachines/inkling-small:free',
}

# Map legacy deployment / provider-local names to stable logical names first.
_LOGICAL_MODEL_ALIASES = {
    'gpt-5.2-chat': 'gpt-5.4',
    'gpt-4o-mini': 'gpt-5.4-mini',
}

# Google retired these for new API keys; they now return HTTP 404.
_RETIRED_GEMINI_MODELS = {
    'gemini-2.0-flash': GEMINI_FREE_TEXT_MODEL,
    'gemini-2.0-flash-lite': GEMINI_FREE_TEXT_MODEL_MINI,
    'gemini-2.5-flash-lite': GEMINI_FREE_TEXT_MODEL,
    'google/gemini-2.0-flash': GEMINI_FREE_TEXT_MODEL,
    'google/gemini-2.5-flash-lite': GEMINI_FREE_TEXT_MODEL,
}

# Logical names -> Google AI Studio slugs (the primary free backend).
_GEMINI_MODEL_ALIASES = {
    'gpt-5.4': GEMINI_FREE_TEXT_MODEL,
    'gpt-5.4-mini': GEMINI_FREE_TEXT_MODEL_MINI,
    'text-embedding-3-small': GEMINI_FREE_EMBEDDING_MODEL,
    'text-embedding-3-large': GEMINI_FREE_EMBEDDING_MODEL,
    'text-embedding-004': GEMINI_FREE_EMBEDDING_MODEL,
    'gemini-embedding-002': GEMINI_FREE_EMBEDDING_MODEL,
    'dall-e-3': GEMINI_FREE_IMAGE_MODEL,
    'dall-e-2': GEMINI_FREE_IMAGE_MODEL,
    'gpt-image-1': GEMINI_FREE_IMAGE_MODEL,
}

# Then map logical names to OpenRouter slugs when routing through OpenRouter.
_OPENROUTER_MODEL_ALIASES = {
    'gpt-5.4': OPENROUTER_FREE_TEXT_MODEL,
    'gpt-5.4-mini': OPENROUTER_FREE_TEXT_MODEL_MINI,
    'text-embedding-3-small': OPENROUTER_FREE_EMBEDDING_MODEL,
    'gemini-2.5-flash': 'google/gemini-2.5-flash',
    'gemini-3.5-flash': 'google/gemini-3.5-flash',
    'gemini-3.1-flash-lite': 'google/gemini-3.1-flash-lite',
    'gemini-3.5-flash-lite': 'google/gemini-3.5-flash-lite',
    'gemini-3.1-flash-image-preview': 'google/gemini-3.1-flash-image-preview',
    'dall-e-3': OPENROUTER_FREE_IMAGE_MODEL,
    'dall-e-2': OPENROUTER_FREE_IMAGE_MODEL,
    'gpt-image-1': OPENROUTER_FREE_IMAGE_MODEL,
}


def _env_flag(name: str) -> bool:
    """Return True when an env var is set to a truthy value."""
    return str(os.getenv(name, '')).strip().lower() in {'1', 'true', 'yes', 'on'}


def get_openrouter_api_key() -> Optional[str]:
    """Return the OpenRouter API key."""
    return os.getenv('OR_API_KEY')


def get_gemini_api_key() -> Optional[str]:
    """Return the Google AI Studio API key."""
    return os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_API_KEY')


def is_gemini_enabled() -> bool:
    """Return True when Google AI Studio should serve as the primary backend."""
    return bool(get_gemini_api_key())


def is_openrouter_enabled() -> bool:
    """Return True when OpenRouter should be used as the primary backend.

    Google AI Studio's free tier gives 30K requests / 30M tokens per day per
    model on its *-flash-lite models, while OpenRouter's free tier caps out at
    50 requests/day on a zero balance and routes through a shared upstream pool
    that returns HTTP 429 for most :free slugs. So OpenRouter is only the
    primary backend when no Gemini key is configured, or when it is explicitly
    forced via PREFER_OPENROUTER=1.
    """
    if not get_openrouter_api_key():
        return False
    if _env_flag('PREFER_OPENROUTER'):
        return True
    return not is_gemini_enabled()


def default_provider() -> str:
    """Return the provider name used when no client is supplied."""
    if is_openrouter_enabled():
        return 'openrouter'
    if is_gemini_enabled():
        return 'gemini'
    if os.getenv('OPENAI_API_KEY'):
        return 'openai'
    return 'openai'


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


def get_openrouter_free_text_models(refresh: bool = False, ttl_seconds: int = 900) -> List[str]:
    """Return currently available free text models from OpenRouter.

    Falls back to the local preferred list if the catalog request fails or
    returns nothing useful.
    """
    global _openrouter_free_text_models_cache

    now = time.time()
    cached_models = _openrouter_free_text_models_cache.get('models') or []
    expires_at = float(_openrouter_free_text_models_cache.get('expires_at') or 0.0)
    if not refresh and cached_models and now < expires_at:
        return list(cached_models)

    preferred = [m for m in OPENROUTER_FREE_TEXT_MODELS if m not in OPENROUTER_UNAVAILABLE_FREE_MODELS]
    try:
        response = requests.get(
            f"{OPENROUTER_BASE_URL.rstrip('/')}/models",
            headers=get_openrouter_headers(),
            timeout=60,
        )
        response.raise_for_status()
        payload = response.json() or {}
        data = payload.get('data') if isinstance(payload, dict) else None
        discovered: List[str] = []
        for item in data or []:
            if not isinstance(item, dict):
                continue
            model_id = item.get('id')
            if not isinstance(model_id, str) or ':free' not in model_id:
                continue
            if model_id in OPENROUTER_UNAVAILABLE_FREE_MODELS:
                continue

            pricing = item.get('pricing') or {}
            prompt_price = str(pricing.get('prompt', ''))
            completion_price = str(pricing.get('completion', ''))
            if prompt_price != '0' or completion_price != '0':
                continue

            architecture = item.get('architecture') or {}
            input_modalities = architecture.get('input_modalities') or []
            output_modalities = architecture.get('output_modalities') or []
            if 'text' not in input_modalities or 'text' not in output_modalities:
                continue
            if 'image' in output_modalities or 'audio' in output_modalities:
                continue

            discovered.append(model_id)

        merged: List[str] = []
        for model_id in preferred + discovered:
            if not model_id or model_id in OPENROUTER_UNAVAILABLE_FREE_MODELS:
                continue
            if model_id not in merged:
                merged.append(model_id)

        if merged:
            _openrouter_free_text_models_cache = {
                'expires_at': now + max(int(ttl_seconds), 60),
                'models': merged,
            }
            return merged
    except Exception:
        logging.getLogger('workers.tools.openai_client').warning(
            'Failed to refresh OpenRouter free text model catalog; using local fallback list'
        )

    return preferred


def _is_openrouter_text_fallback_candidate(model: str, resolved_model: str) -> bool:
    """Return True when this request should use free-text fallback routing."""
    logical_model = _LOGICAL_MODEL_ALIASES.get(model, model)
    if logical_model in {'gpt-5.4', 'gpt-5.4-mini'}:
        return True
    if resolved_model in OPENROUTER_FREE_TEXT_MODELS:
        return True
    if isinstance(resolved_model, str) and resolved_model.endswith(':free'):
        if resolved_model == OPENROUTER_FREE_EMBEDDING_MODEL:
            return False
        if _is_gemini_model(resolved_model):
            return False
        return True
    return False


def get_openrouter_text_fallback_models(model: str, resolved_model: str, refresh: bool = False) -> List[str]:
    """Build a fallback chain for free text generation on OpenRouter."""
    candidates: List[str] = []
    if resolved_model and _is_openrouter_text_fallback_candidate(model, resolved_model):
        candidates.append(resolved_model)

    for model_id in get_openrouter_free_text_models(refresh=refresh):
        if model_id and model_id not in candidates:
            candidates.append(model_id)
    return candidates


def resolve_model_name(model: str, provider: Optional[str] = None) -> str:
    """Resolve legacy model names to provider-specific slugs when needed."""
    logical_model = _LOGICAL_MODEL_ALIASES.get(model, model)
    target_provider = provider or default_provider()
    if target_provider == 'openrouter':
        return _OPENROUTER_MODEL_ALIASES.get(logical_model, logical_model)
    if target_provider == 'gemini':
        # Retired slugs 404 for keys created after Google pulled them.
        logical_model = _RETIRED_GEMINI_MODELS.get(logical_model, logical_model)
        # Strip an OpenRouter-style "google/" prefix so the same logical name
        # works against both backends.
        if logical_model.startswith('google/'):
            candidate = logical_model.split('/', 1)[1]
            logical_model = _RETIRED_GEMINI_MODELS.get(candidate, candidate)
        return _GEMINI_MODEL_ALIASES.get(logical_model, logical_model)
    return logical_model


def get_gemini_text_fallback_models(model: str, resolved_model: str) -> List[str]:
    """Build a fallback chain for free text generation on Google AI Studio."""
    candidates: List[str] = []
    if resolved_model and resolved_model not in GEMINI_HIGH_OVERHEAD_MODELS:
        candidates.append(resolved_model)
    for model_id in GEMINI_FREE_TEXT_MODELS:
        if model_id and model_id not in candidates:
            candidates.append(model_id)
    return candidates


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
    """Get or create a Google AI Studio client (OpenAI-compatible endpoint).

    Falls back to OpenRouter only when no Gemini key is configured, since the
    Gemini free tier is far more generous than OpenRouter's.
    """
    global _gemini_client

    if not is_gemini_enabled():
        if get_openrouter_api_key():
            return get_openrouter_client()
        logging.getLogger('workers.tools.openai_client').error('GEMINI_API_KEY not configured')
        return None

    if is_openrouter_enabled():
        return get_openrouter_client()

    if _gemini_client is not None:
        return _gemini_client

    try:
        from openai import OpenAI

        api_key = get_gemini_api_key()
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

    # Google AI Studio is the primary free backend (30M tokens/day per model).
    if is_gemini_enabled():
        return get_gemini_client()

    if _client is not None:
        return _client

    try:
        from openai import OpenAI

        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            logging.getLogger('workers.tools.openai_client').error(
                'No API key configured (looked for GEMINI_API_KEY, OR_API_KEY, OPENAI_API_KEY)'
            )
            return None

        _client = _tag_client(OpenAI(api_key=api_key), 'openai')
        logging.getLogger('workers.tools.openai_client').info('Using OpenAI API (OPENAI_API_KEY)')
        return _client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"OpenAI client init failed: {e}")
        return None


# gemini-embedding-001 returns 3072 dimensions by default, but supports
# Matryoshka truncation via the OpenAI-compatible `dimensions` parameter. The
# topic.emb column is vector(2048), so the default is matched to it and can be
# overridden with EMBEDDING_DIMENSIONS.
GEMINI_EMBEDDING_DIMENSIONS = 2048


def _embedding_dimensions() -> Optional[int]:
    """Return the embedding width to request, or None to use the model default."""
    raw = os.getenv('EMBEDDING_DIMENSIONS')
    if raw is None or str(raw).strip() == '':
        return GEMINI_EMBEDDING_DIMENSIONS
    try:
        value = int(raw)
    except Exception:
        return GEMINI_EMBEDDING_DIMENSIONS
    return value if value > 0 else None


def create_embedding(client: object, model: str, input_texts: List[str]) -> object:
    """Create embeddings via the configured provider.

    OpenRouter has no usable free embedding model, so embeddings always route
    to Google AI Studio's gemini-embedding-001 (20K requests / 20M tokens per
    day on the free tier) whenever a Gemini key is available.
    """
    if client is None or _client_provider(client) == 'openrouter':
        if is_gemini_enabled():
            client = get_gemini_client()
        elif client is None:
            client = get_openai_client()
        if not client:
            raise RuntimeError('No embedding-capable client available')

    provider = _client_provider(client) or default_provider()

    if provider == 'openrouter':
        raise RuntimeError(
            'OpenRouter has no working free embedding model; set GEMINI_API_KEY '
            'to use gemini-embedding-001'
        )

    resolved_model = resolve_model_name(model, provider=provider)
    if provider == 'gemini' and resolved_model in {None, '', 'text-embedding-3-small'}:
        resolved_model = GEMINI_FREE_EMBEDDING_MODEL

    kwargs = {'model': resolved_model, 'input': input_texts}
    dimensions = _embedding_dimensions()
    if dimensions:
        kwargs['dimensions'] = dimensions
    try:
        return client.embeddings.create(**kwargs)
    except TypeError:
        # Older SDKs reject the `dimensions` kwarg outright.
        kwargs.pop('dimensions', None)
        return client.embeddings.create(**kwargs)


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

    provider = _client_provider(client) or default_provider()
    resolved_model = resolve_model_name(model, provider=provider)
    is_gemini = provider == 'gemini' or _is_gemini_model(resolved_model)
    is_openrouter = provider == 'openrouter'
    fallback_refresh_attempted = False

    if provider == 'gemini' and resolved_model in GEMINI_HIGH_OVERHEAD_MODELS:
        logger.warning(
            '%s: model %s hides ~285 reasoning tokens per call in total_tokens; '
            'it drains the daily quota far faster than its visible output suggests',
            provider,
            resolved_model,
        )

    # Gemini fallback chain, walked in order when a model 404s or rate-limits.
    gemini_candidates: List[str] = []
    gemini_candidate_index = 0
    if provider == 'gemini' and not _kwargs.get('_no_fallback'):
        gemini_candidates = get_gemini_text_fallback_models(model, resolved_model)
        if gemini_candidates:
            resolved_model = gemini_candidates[0]
    _kwargs.pop('_no_fallback', None)

    try:
        msg_count = len(messages) if messages is not None else 0
    except Exception:
        msg_count = 0

    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 600

    # Reasoning models spend the budget on hidden thinking first and return an
    # empty content field when max_tokens is small, so enforce a floor.
    _MIN_REASONING_TOKENS = 512
    if max_tokens < _MIN_REASONING_TOKENS and (is_openrouter or resolved_model in GEMINI_HIGH_OVERHEAD_MODELS):
        logger.debug(
            'raising max_tokens %d -> %d for reasoning-capable model %s',
            max_tokens,
            _MIN_REASONING_TOKENS,
            resolved_model,
        )
        max_tokens = _MIN_REASONING_TOKENS

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
    if gemini_candidates:
        max_attempts = max(max_attempts, len(gemini_candidates) + 1)

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

    def _next_gemini_candidate() -> Optional[str]:
        """Advance the Gemini fallback chain; return the new model or None."""
        nonlocal gemini_candidate_index
        while gemini_candidate_index + 1 < len(gemini_candidates):
            gemini_candidate_index += 1
            candidate = gemini_candidates[gemini_candidate_index]
            if candidate and candidate != resolved_model:
                return candidate
        return None

    for attempt in range(1, max_attempts + 1):
        try:
            if is_openrouter:
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_tokens': max_tokens,
                }
                # OpenRouter routing params ('models', 'route') are NOT valid
                # named arguments on the typed OpenAI SDK create() call — the SDK
                # raises "unexpected keyword argument 'models'". They must be
                # forwarded via extra_body so the SDK serializes them into the
                # request body.
                extra_body = {}
                if 'models' not in _kwargs and 'route' not in _kwargs:
                    fallback_models = get_openrouter_text_fallback_models(
                        model=model,
                        resolved_model=resolved_model,
                        refresh=fallback_refresh_attempted,
                    )
                    if len(fallback_models) > 1:
                        # OpenRouter rejects a fallback array with more than 3
                        # models ("'models' array must have 3 items or fewer").
                        extra_body['models'] = fallback_models[:3]
                        extra_body['route'] = 'fallback'
                req_kwargs.update(_kwargs)
                # Relocate any caller-supplied routing params (or a caller
                # extra_body) into a single extra_body so they reach OpenRouter
                # in the body instead of crashing as unknown kwargs.
                for or_param in ('models', 'route'):
                    if or_param in req_kwargs:
                        extra_body[or_param] = req_kwargs.pop(or_param)
                caller_extra = req_kwargs.pop('extra_body', None)
                if isinstance(caller_extra, dict):
                    extra_body = {**caller_extra, **extra_body}
                # Enforce OpenRouter's hard cap on the fallback array regardless
                # of where 'models' came from (fallback chain or caller kwargs).
                if isinstance(extra_body.get('models'), list) and len(extra_body['models']) > 3:
                    extra_body['models'] = extra_body['models'][:3]
                if extra_body:
                    req_kwargs['extra_body'] = extra_body
            elif is_gemini:
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_tokens': max_tokens,
                }
                if reasoning_effort is not None and '2.5' in resolved_model:
                    req_kwargs['reasoning_effort'] = reasoning_effort
                req_kwargs.update(_kwargs)
            else:
                req_kwargs = {
                    'model': resolved_model,
                    'messages': messages,
                    'max_completion_tokens': max_tokens,
                }
                if reasoning_effort is not None:
                    req_kwargs['reasoning_effort'] = reasoning_effort
                req_kwargs.update(_kwargs)

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
            if is_openrouter and not fallback_refresh_attempted and 'models' not in _kwargs and 'route' not in _kwargs:
                fallback_refresh_attempted = True
                logger.warning('%s returned empty content; refreshing OpenRouter free model catalog and retrying once', provider)
                continue
            if provider == 'gemini':
                next_model = _next_gemini_candidate()
                if next_model:
                    logger.warning(
                        '%s returned empty content for %s; falling back to %s',
                        provider,
                        resolved_model,
                        next_model,
                    )
                    resolved_model = next_model
                    continue
            logger.warning('%s returned empty content (attempt %d/%d); not retrying', provider, attempt, max_attempts)
            return None

        except Exception as e:
            status = _extract_status(e)
            resp_text = _extract_response_text(e)

            if (
                is_openrouter
                and not fallback_refresh_attempted
                and 'models' not in _kwargs
                and 'route' not in _kwargs
                and status in {400, 404, 429}
            ):
                fallback_refresh_attempted = True
                logger.warning(
                    '%s request failed with status=%s; refreshing OpenRouter free model catalog and retrying once',
                    provider,
                    status,
                )
                continue

            if provider == 'gemini' and status in {404, 429}:
                next_model = _next_gemini_candidate()
                if next_model:
                    logger.warning(
                        '%s request for %s failed with status=%s; falling back to %s',
                        provider,
                        resolved_model,
                        status,
                        next_model,
                    )
                    resolved_model = next_model
                    if status == 429:
                        time.sleep(0.5 * attempt)
                    continue

            if status is not None and 400 <= status < 500:
                logger.warning('%s request failed with client error status=%s model=%s', provider, status, resolved_model)
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
