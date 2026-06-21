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


def test_get_openai_client_prefers_openrouter(monkeypatch):
    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    fake_openai_module = types.SimpleNamespace(OpenAI=FakeOpenAI)
    monkeypatch.setitem(sys.modules, 'openai', fake_openai_module)
    monkeypatch.setenv('OR_API_KEY', 'or-key')
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
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
