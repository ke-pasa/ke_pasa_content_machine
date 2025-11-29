import json
import types

import pytest


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
        g.exists = False
        return g


class FakeArticlesCollection:
    def __init__(self, articles):
        # articles: dict id -> FakeDoc
        self._articles = articles

    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        return self

    def stream(self):
        return list(self._articles.values())

    def document(self, doc_id):
        return FakeDocumentRef(self._articles.get(doc_id))


class FakeDB:
    def __init__(self, docs):
        self._articles = {d.id: d for d in docs}

    def collection(self, name):
        if name == 'articles':
            return FakeArticlesCollection(self._articles)
        # minimal support for locks not needed because worker lock is monkeypatched
        raise NotImplementedError(name)


def make_fake_firebase(docs):
    return types.SimpleNamespace(db=FakeDB(docs))


def test_categorize_with_openai_json(monkeypatch):
    # Prepare fake article
    doc = FakeDoc('a1', {
        'title': 'Продление ВНЖ для мигрантов',
        'description': '',
        'content': 'Новость о продлении ВНЖ...',
        'tags': ['внж', 'виза'],
        'source': 'elpais',
        'pub_date': '2025-01-01T00:00:00Z',
        'status': 'NEW',
        'created_at': '2025-01-01T00:00:00Z'
    })

    # Monkeypatch firebase client
    fake_fb = make_fake_firebase([doc])

    # Import worker module, then patch the get_firebase_client symbol inside it
    from workers.categorization import worker as catmod
    monkeypatch.setattr(catmod, 'get_firebase_client', lambda: fake_fb, raising=False)

    # Locking disabled in worker; no need to patch locks

    # Mock OpenAI wrapper to return valid JSON. Patch the names imported
    # into the categorization worker module so the worker uses our mocks.
    from workers.categorization import worker as catmod
    monkeypatch.setattr(catmod, 'get_openai_client', lambda: object(), raising=False)
    sample = {
        'region_score': 8,
        'usefulness_score': 30,
        'emotion_score': 0,
        'virality_score': 0,
        'source_score': 7,
        'total_score': 85,
        'rating': 'publish',
        'category': 'documents',
        'comment': 'Актуально и полезно.'
    }
    monkeypatch.setattr(catmod, 'chat_completion', lambda client, model, messages, max_tokens=600, temperature=0: json.dumps(sample), raising=False)
    monkeypatch.setattr(catmod, 'parse_json_from_text', lambda t: json.loads(t), raising=False)

    # Run worker
    w = catmod.CategorizationWorker()
    res = w.categorize_new_articles()

    assert res['status'] == 'success'
    assert res['processed'] == 1

    # Verify that the article doc was updated in-place
    assert doc._data.get('status') == 'CATEGORIZED'
    assert 'interest' in doc._data
    assert doc._data['interest']['rating'] == 'publish'


def test_categorize_without_openai_heuristic(monkeypatch):
    # Prepare fake article
    doc = FakeDoc('b1', {
        'title': 'Местная ярмарка в Малаге',
        'description': '',
        'content': 'Информация о ярмарке и аренде...',
        'tags': ['жилье'],
        'source': 'localblog',
        'pub_date': '2025-02-01T00:00:00Z',
        'status': 'NEW',
        'created_at': '2025-02-01T00:00:00Z'
    })

    fake_fb = make_fake_firebase([doc])
    from workers.categorization import worker as catmod
    monkeypatch.setattr(catmod, 'get_firebase_client', lambda: fake_fb, raising=False)
    # Locking disabled in worker; no need to patch locks

    # No OpenAI available
    from workers.categorization import worker as catmod
    monkeypatch.setattr(catmod, 'get_openai_client', lambda: None, raising=False)

    w = catmod.CategorizationWorker()
    res = w.categorize_new_articles()

    assert res['status'] == 'success'
    assert res['processed'] == 1
    assert doc._data.get('status') == 'CATEGORIZED'
    # Local heuristic removed: interest may be None when no LLM available
    assert 'interest' in doc._data
    assert doc._data['interest'] is None
