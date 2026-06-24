import pytest
import datetime
import sys
from unittest.mock import MagicMock, patch

# Mock readability and other dependencies that might be missing
sys.modules['readability'] = MagicMock()
sys.modules['readability.Document'] = MagicMock()
sys.modules['requests'] = MagicMock()
sys.modules['bs4'] = MagicMock()

from workers.article_generator.ArticleGenerator import ArticleGenerator

# --- Fake Firestore Classes ---

class FakeDoc:
    def __init__(self, id_, data):
        self.id = id_
        self._data = data

    def to_dict(self):
        return dict(self._data)

class FakeDocumentRef:
    def __init__(self, doc: FakeDoc | None):
        self._doc = doc
        self.last_set = None

    def set(self, payload, merge=False):
        self.last_set = (payload, merge)
        if self._doc:
            # simulate merge behavior
            self._doc._data.update(payload)
    
    def get(self):
        class G:
            pass
        g = G()
        g.exists = self._doc is not None
        g.to_dict = lambda: self._doc.to_dict() if self._doc else {}
        return g

class FakeArticlesCollection:
    def __init__(self, articles):
        # articles: dict id -> FakeDoc
        self._articles = articles
        self._query_results = list(articles.values())

    def where(self, *args, **kwargs):
        # Minimal filtering for test purposes
        field, op, value = args
        if field == 'status' and op == '==' and value == 'CATEGORIZED':
             self._query_results = [d for d in self._articles.values() if d._data.get('status') == 'CATEGORIZED']
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._query_results = self._query_results[:n]
        return self
    
    def start_after(self, doc):
        # not implemented for simple list
        return self

    def stream(self):
        return self._query_results

    def document(self, doc_id):
        return FakeDocumentRef(self._articles.get(doc_id))

class FakeDB:
    def __init__(self, docs):
        self._articles = {d.id: d for d in docs}
        self.collection_calls = []

    def collection(self, name):
        self.collection_calls.append(name)
        if name == 'articles' or name == 'articles_ru':
             # Share the same storage for simplicity in checking updates, 
             # or separate if needed. The worker writes to 'articles_ru' and updates 'articles'.
             # For 'articles_ru', we might want to allow creating new docs.
             if name == 'articles_ru':
                 return FakeArticlesCollection(self._articles) # Simplified: writing to same fake storage
             return FakeArticlesCollection(self._articles)
        raise NotImplementedError(name)

def make_fake_firebase(docs):
    return MagicMock(db=FakeDB(docs))

# --- Tests ---

@pytest.fixture
def mock_firebase(monkeypatch):
    docs = []
    fake_fb = make_fake_firebase(docs)
    
    # Patch the helper that ArticleGenerator uses
    # Note: ArticleGenerator uses _get_firebase_client which tries to import from worker.py
    # We can patch workers.article_generator.ArticleGenerator._get_firebase_client directly
    # or patch the module it imports.
    
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    return fake_fb

@pytest.fixture
def article_generator(mock_firebase):
    return ArticleGenerator()

def test_prescan_skips_low_score(monkeypatch):
    # Setup data
    recent_date = datetime.datetime.now(datetime.timezone.utc).isoformat()
    doc1 = FakeDoc('doc1', {'status': 'CATEGORIZED', 'total_score': 50, 'created_at': recent_date})
    doc2 = FakeDoc('doc2', {'status': 'CATEGORIZED', 'total_score': 80, 'created_at': recent_date})
    
    fake_fb = make_fake_firebase([doc1, doc2])
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    
    gen = ArticleGenerator()
    
    # Run prescan
    skipped_count = gen._phase1_prescan_and_skip()
    
    assert skipped_count == 1
    assert doc1._data['status'] == 'SKIPPED'
    assert doc1._data['skipped_reason'] == 'low_score'
    assert doc2._data['status'] == 'CATEGORIZED'

def test_prescan_skips_old_articles(monkeypatch):
    # Setup data
    old_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)).isoformat()
    new_date = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=1)).isoformat()
    
    doc1 = FakeDoc('doc1', {'status': 'CATEGORIZED', 'total_score': 80, 'published_at': old_date})
    doc2 = FakeDoc('doc2', {'status': 'CATEGORIZED', 'total_score': 80, 'published_at': new_date})
    
    fake_fb = make_fake_firebase([doc1, doc2])
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    
    gen = ArticleGenerator()
    
    # Run prescan
    skipped_count = gen._phase1_prescan_and_skip()
    
    assert skipped_count == 1
    assert doc1._data['status'] == 'SKIPPED'
    assert doc1._data['skipped_reason'] == 'too_old'
    assert doc2._data['status'] == 'CATEGORIZED'

def test_translation_success(monkeypatch):
    # Setup data
    doc1 = FakeDoc('doc1', {
        'status': 'CATEGORIZED', 
        'total_score': 80, 
        'title': 'Original Title',
        'content': 'Original Content',
        'link': 'http://example.com'
    })
    
    fake_fb = make_fake_firebase([doc1])
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    
    # Mock translator
    mock_translator = MagicMock()
    mock_translator.translate.return_value = {
        'title_ru': 'Russian Title',
        'content_ru': 'Russian Content',
        'translation_ru': 'Russian Content',
        'flags': ['flag1']
    }
    
    gen = ArticleGenerator(translator=mock_translator)
    
    # Mock fetch content to avoid network call
    monkeypatch.setattr(gen, '_fetch_article_content', lambda url: 'Fetched Content')
    
    # Run translation phase
    results = gen._phase2_translate_articles(requested_total=1)
    
    assert results['processed'] == 1
    assert results['translated'] == 1
    
    # Verify translator called
    mock_translator.translate.assert_called_once()
    
    # Verify DB updates
    # Check articles_ru (simulated in same dict)
    assert doc1._data['title_ru'] == 'Russian Title'
    assert doc1._data['status'] == 'TRANSLATED'
    assert doc1._data['fetched_content'] == 'Fetched Content'

def test_translation_failure(monkeypatch):
    # Setup data
    doc1 = FakeDoc('doc1', {'status': 'CATEGORIZED', 'total_score': 80})
    
    fake_fb = make_fake_firebase([doc1])
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    
    # Mock translator to return None (failure)
    mock_translator = MagicMock()
    mock_translator.translate.return_value = None
    
    gen = ArticleGenerator(translator=mock_translator)
    monkeypatch.setattr(gen, '_fetch_article_content', lambda url: None)

    results = gen._phase2_translate_articles(requested_total=1)
    
    assert results['processed'] == 1
    assert results['translated'] == 0
    assert len(results['errors']) > 0
    
    assert doc1._data['status'] == 'TRANSLATION_FAILED'

def test_fetches_content(monkeypatch):
    doc1 = FakeDoc('doc1', {
        'status': 'CATEGORIZED', 
        'total_score': 80,
        'link': 'http://example.com',
        'content': 'Short'
    })
    
    fake_fb = make_fake_firebase([doc1])
    monkeypatch.setattr('workers.article_generator.ArticleGenerator._get_firebase_client', lambda: fake_fb)
    
    mock_translator = MagicMock()
    mock_translator.translate.return_value = {'translation_ru': 'Ru'}
    
    gen = ArticleGenerator(translator=mock_translator)
    
    # Mock _fetch_article_content to return longer content
    mock_fetch = MagicMock(return_value="Longer Fetched Content")
    monkeypatch.setattr(gen, '_fetch_article_content', mock_fetch)
    
    gen._phase2_translate_articles(requested_total=1)
    
    mock_fetch.assert_called_with('http://example.com')
    # Verify that the translator was called with the fetched content
    args, kwargs = mock_translator.translate.call_args
    assert args[2] == "Longer Fetched Content"


def test_continuous_mode_keeps_running_after_processing_error(monkeypatch):
    class FakePG:
        def fetch_top_categorized_article_24h(self):
            return {'id': 'doc1', 'status': 'CATEGORIZED', 'total_score': 80}

    monkeypatch.setattr('workers.article_generator.ArticleGenerator.get_pg_client', lambda: FakePG())

    gen = ArticleGenerator(translator=MagicMock())

    def fail_processing(article, chunk_results, lock):
        chunk_results['processed'] = 1
        chunk_results['errors'].append('translation failed')

    slept = []

    def stop_after_error_pause(seconds):
        slept.append(seconds)
        raise SystemExit()

    monkeypatch.setattr(gen, '_process_single_document', fail_processing)
    monkeypatch.setattr('workers.article_generator.ArticleGenerator.time.sleep', stop_after_error_pause)

    with pytest.raises(SystemExit):
        gen.process_continuous()

    assert slept == [5]
