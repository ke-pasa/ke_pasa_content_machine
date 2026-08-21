import base64
import io
import logging
import sys
import types

from PIL import Image

from workers.article_generator.image_generator import ImageGenerator
from workers.tools import openai_client as clientmod


def test_resolve_model_name_for_openrouter(monkeypatch):
    monkeypatch.setenv('OR_API_KEY', 'test-key')

    assert clientmod.resolve_model_name('gpt-5.4', provider='openrouter') == clientmod.OPENROUTER_FREE_TEXT_MODEL
    assert clientmod.resolve_model_name('gpt-5.4-mini', provider='openrouter') == clientmod.OPENROUTER_FREE_TEXT_MODEL_MINI
    assert clientmod.resolve_model_name('text-embedding-3-small', provider='openrouter') == clientmod.OPENROUTER_FREE_EMBEDDING_MODEL
    assert clientmod.resolve_model_name('gpt-image-1', provider='openrouter') is None


def test_resolve_model_name_for_gemini():
    """Legacy names map onto the free-tier Gemini slugs that actually exist."""
    assert clientmod.resolve_model_name('gpt-5.4', provider='gemini') == clientmod.GEMINI_FREE_TEXT_MODEL
    assert clientmod.resolve_model_name('gpt-5.4-mini', provider='gemini') == clientmod.GEMINI_FREE_TEXT_MODEL_MINI
    assert clientmod.resolve_model_name('gpt-4o-mini', provider='gemini') == clientmod.GEMINI_FREE_TEXT_MODEL_MINI
    assert clientmod.resolve_model_name('text-embedding-3-small', provider='gemini') == clientmod.GEMINI_FREE_EMBEDDING_MODEL
    assert clientmod.resolve_model_name('gpt-image-1', provider='gemini') == clientmod.GEMINI_FREE_IMAGE_MODEL


def test_resolve_model_name_remaps_retired_gemini_models():
    """Slugs Google retired for new keys must not reach the API as-is."""
    for retired in ('gemini-2.0-flash', 'gemini-2.0-flash-lite', 'gemini-2.5-flash-lite'):
        resolved = clientmod.resolve_model_name(retired, provider='gemini')
        assert resolved not in clientmod._RETIRED_GEMINI_MODELS
        assert resolved in clientmod.GEMINI_FREE_TEXT_MODELS

    # An OpenRouter-style prefix resolves to the bare Gemini slug.
    assert clientmod.resolve_model_name('google/gemini-2.5-flash-lite', provider='gemini') == clientmod.GEMINI_FREE_TEXT_MODEL


def test_gemini_preferred_over_openrouter(monkeypatch):
    """Gemini's free tier is far larger, so it wins when both keys exist."""
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.setenv('GEMINI_API_KEY', 'gm-key')
    monkeypatch.delenv('PREFER_OPENROUTER', raising=False)

    assert clientmod.is_gemini_enabled() is True
    assert clientmod.is_openrouter_enabled() is False
    assert clientmod.default_provider() == 'gemini'


def test_prefer_openrouter_override(monkeypatch):
    """PREFER_OPENROUTER=1 forces the old routing back on."""
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.setenv('GEMINI_API_KEY', 'gm-key')
    monkeypatch.setenv('PREFER_OPENROUTER', '1')

    assert clientmod.is_openrouter_enabled() is True
    assert clientmod.default_provider() == 'openrouter'


def test_openrouter_used_when_no_gemini_key(monkeypatch):
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('PREFER_OPENROUTER', raising=False)

    assert clientmod.is_openrouter_enabled() is True
    assert clientmod.default_provider() == 'openrouter'


def test_unavailable_free_models_filtered(monkeypatch):
    """Slugs that always 403 must never lead the OpenRouter fallback chain."""
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.setattr(
        clientmod,
        '_openrouter_free_text_models_cache',
        {'expires_at': 0.0, 'models': []},
    )

    def boom(*a, **kw):
        raise RuntimeError('no network in tests')

    monkeypatch.setattr(clientmod.requests, 'get', boom)

    models = clientmod.get_openrouter_free_text_models(refresh=True)
    assert models, 'must fall back to the local preferred list'
    assert not (set(models) & clientmod.OPENROUTER_UNAVAILABLE_FREE_MODELS)


def test_get_openai_client_prefers_openrouter(monkeypatch):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_openai_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, 'openai', fake_openai_module)
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
    monkeypatch.delenv('PREFER_OPENROUTER', raising=False)
    monkeypatch.setenv('OPENROUTER_APP_URL', 'https://ke-pasa.es')
    monkeypatch.setenv('OPENROUTER_APP_TITLE', 'Ke Pasa Content Machine')

    monkeypatch.setattr(clientmod, '_client', None)
    monkeypatch.setattr(clientmod, '_openrouter_client', None)
    monkeypatch.setattr(clientmod, '_gemini_client', None)

    client = clientmod.get_openai_client()

    assert getattr(client, '_ke_provider', None) == 'openrouter'
    assert client.kwargs['base_url'] == clientmod.OPENROUTER_BASE_URL
    assert client.kwargs['default_headers']['HTTP-Referer'] == 'https://ke-pasa.es'
    assert client.kwargs['default_headers']['X-Title'] == 'Ke Pasa Content Machine'

def test_download_and_save_image_supports_data_urls(tmp_path):
    source = Image.new('RGB', (64, 64), color=(12, 34, 56))
    buf = io.BytesIO()
    source.save(buf, format='PNG')
    data_url = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')

    generator = ImageGenerator.__new__(ImageGenerator)
    generator.logger = logging.getLogger('tests.image_generator')
    generator.images_dir = tmp_path

    relative_path = generator._download_and_save_image(data_url, 'doc123')

    assert relative_path == 'public/images/news/doc123.jpg'
    assert (tmp_path / 'doc123.jpg').exists()
