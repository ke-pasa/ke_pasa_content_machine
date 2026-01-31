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

# Model to Azure deployment mapping with endpoint selection
# Format: 'model': ('deployment_name', 'endpoint_suffix')
# endpoint_suffix: '' for primary, '_MINI' for secondary
_AZURE_MODEL_MAPPING = {
    'gpt-4o': ('gpt-5.2-chat', ''),           # Heavy: content translation → pavel-mkfzym2a
    'gpt-4o-mini': ('gpt-4o-mini', '_MINI'),  # Light: titles, events → quepasa-resource
    'gpt-4': ('gpt-5.2-chat', ''),
    'gpt-3.5-turbo': ('gpt-4o-mini', '_MINI')
}

_clients = {}  # Cache for multiple clients


def _map_model_to_deployment(model: str) -> tuple:
    """Map OpenAI model name to Azure deployment name and endpoint suffix.
    
    Args:
        model: OpenAI model name (e.g., 'gpt-4o', 'gpt-4o-mini')
        
    Returns:
        Tuple of (deployment_name, endpoint_suffix) or (model, '') if not in mapping
    """
    # Check if using Azure OpenAI
    if os.getenv('AZURE_OPENAI_ENDPOINT'):
        mapping = _AZURE_MODEL_MAPPING.get(model, (model, ''))
        return mapping if isinstance(mapping, tuple) else (mapping, '')
    return (model, '')


def get_openai_client(endpoint_suffix: str = '') -> Optional[object]:
    """Get or create Azure OpenAI client instance.
    
    Supports multiple Azure endpoints for different models.
    
    Args:
        endpoint_suffix: Suffix for endpoint env var (e.g., '_MINI' for AZURE_OPENAI_ENDPOINT_MINI)
    
    Returns:
        AzureOpenAI client instance, or None if no valid credentials found.
    """
    global _client, _clients
    
    # Return cached client for this endpoint
    if endpoint_suffix in _clients:
        return _clients[endpoint_suffix]
    
    # Return legacy singleton for default endpoint
    if not endpoint_suffix and _client is not None:
        return _client

    try:
        from openai import AzureOpenAI
    except Exception:
        return None

    # Get Azure OpenAI credentials
    azure_endpoint = os.getenv(f'AZURE_OPENAI_ENDPOINT{endpoint_suffix}')
    azure_key = os.getenv(f'AZURE_OPENAI_KEY{endpoint_suffix}')
    
    if not azure_endpoint or not azure_key:
        logging.getLogger('workers.tools.openai_client').error(
            f"Azure OpenAI credentials not found: AZURE_OPENAI_ENDPOINT{endpoint_suffix} or AZURE_OPENAI_KEY{endpoint_suffix}"
        )
        return None
    
    try:
        # Determine API version based on endpoint
        if 'pavel-mkfzym2a' in azure_endpoint:
            api_version = "2024-05-01-preview"
        elif 'quepasa-resource' in azure_endpoint:
            if 'openai.azure.com' in azure_endpoint:
                api_version = "2024-08-01-preview"  # Chat completions
            else:
                api_version = "2023-05-15"  # Embeddings via cognitiveservices.azure.com
        else:
            api_version = "2024-08-01-preview"  # Default stable version
        
        client = AzureOpenAI(
            azure_endpoint=azure_endpoint,
            api_key=azure_key,
            api_version=api_version
        )
        logging.getLogger('workers.tools.openai_client').info(f"Using Azure OpenAI ({azure_endpoint})")
        
        # Cache this client
        if endpoint_suffix:
            _clients[endpoint_suffix] = client
        else:
            _client = client
        return client
    except Exception as e:
        logging.getLogger('workers.tools.openai_client').error(f"Azure OpenAI init failed: {e}")
        return None


def chat_completion(client: object, model: str, messages: List[Dict[str, str]],
                    max_tokens: int = 6000, temperature: float = 0.0,
                    reasoning_effort: Optional[str] = 'low') -> Optional[str]:
    """Perform a response generation and return the text content or None on error.

    Uses the modern Responses API (client.responses.create) or Azure chat completions.
    Automatically selects correct Azure endpoint based on model.
    
    Args:
        client: OpenAI client instance (can be overridden by model mapping).
        model: Model name to use.
        messages: List of message dicts with 'role' and 'content' keys.
        max_tokens: Maximum tokens to generate.
        temperature: Sampling temperature (0.0-2.0).
        reasoning_effort: Controls reasoning depth. Valid values: 'low', 'medium', 'high'. Default is 'low'.
    """
    logger = logging.getLogger('workers.tools.openai_client')
    
    # Map model to deployment and get correct client
    deployment_model, endpoint_suffix = _map_model_to_deployment(model)
    
    # Get the correct client for this model's endpoint
    if endpoint_suffix or os.getenv('AZURE_OPENAI_ENDPOINT'):
        client = get_openai_client(endpoint_suffix)
        if not client:
            logger.error(f'Failed to get Azure OpenAI client for endpoint suffix: {endpoint_suffix}')
            return None
    
    # Basic validation and sanitization of inputs to surface obvious issues early
    try:
        msg_count = len(messages) if messages is not None else 0
    except Exception:
        msg_count = 0

    try:
        max_tokens = int(max_tokens)
    except Exception:
        max_tokens = 600

    logger.debug('OpenAI request: model=%s deployment=%s endpoint_suffix=%s messages=%d max_tokens=%d', 
                 model, deployment_model, endpoint_suffix, msg_count, max_tokens)

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
            # Azure uses chat.completions API
            # Check if using newer model that requires max_completion_tokens
            if deployment_model.startswith('gpt-5') or deployment_model.startswith('o1'):
                max_tokens_param = 'max_completion_tokens'
            else:
                max_tokens_param = 'max_tokens'
            
            req_kwargs = {
                'model': deployment_model,
                'messages': messages,
                max_tokens_param: max_tokens,
                'stream': False,
            }
            
            # Only certain models support custom temperature
            # gpt-5 models only support temperature=1 (default)
            if (model.startswith('gpt-4') or model.startswith('gpt-3')) and not deployment_model.startswith('gpt-5'):
                req_kwargs['temperature'] = temperature
            
            resp = client.chat.completions.create(**req_kwargs)
            
            # Extract content from chat completion response
            if resp.choices and len(resp.choices) > 0:
                content = resp.choices[0].message.content
                if content:
                    # Log token usage
                    try:
                        if resp.usage:
                            logger.info('Azure OpenAI usage: prompt=%d completion=%d total=%d', 
                                      resp.usage.prompt_tokens, 
                                      resp.usage.completion_tokens, 
                                      resp.usage.total_tokens)
                    except Exception:
                        pass
                    return content.strip()
            logger.warning('Azure OpenAI returned empty content (attempt %d/%d); not retrying', attempt, max_attempts)
            return None

        except Exception as e:
            status = _extract_status(e)
            resp_text = _extract_response_text(e)

            # If status is a 4xx, it's a client error - don't retry
            if status is not None and 400 <= status < 500:
                logger.warning('OpenAI request failed with client error status=%s', status)
                if resp_text:
                    logger.warning('Response snippet: %s', resp_text[:500])
                return None

            # Server errors (5xx) or unknown: retry with backoff
            if attempt < max_attempts:
                backoff = 0.5 * attempt
                logger.warning('OpenAI request failed (attempt %d/%d) status=%s; retrying in %.1fs', 
                             attempt, max_attempts, status, backoff)
                time.sleep(backoff)
                continue

            # Final attempt failed
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
