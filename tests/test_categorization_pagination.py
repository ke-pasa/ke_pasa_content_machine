import json
import types

from workers.categorization import worker as catmod


class FakeDoc:
    def __init__(self, id_, data):
        self.id = id_
        self._data = data

    def to_dict(self):
        return dict(self._data)


class PagingArticlesCollection:
    def __init__(self, docs):
        # docs: list of FakeDoc in order
        self._docs = list(docs)
        self._limit = None
        self._start_after_id = None

    def where(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def start_after(self, last_snapshot):
        # accept either a FakeDoc or an id string
        if last_snapshot is None:
            self._start_after_id = None
        else:
            if hasattr(last_snapshot, 'id'):
                self._start_after_id = last_snapshot.id
            else:
                self._start_after_id = getattr(last_snapshot, 'id', None)
        return self

    def stream(self):
        start_idx = 0
        if self._start_after_id is not None:
            # find index of id
            ids = [d.id for d in self._docs]
            try:
                start_idx = ids.index(self._start_after_id) + 1
            except ValueError:
                start_idx = 0
        end_idx = start_idx + (self._limit or len(self._docs))
        # return slice
        return self._docs[start_idx:end_idx]

    def document(self, doc_id):
        for d in self._docs:
            if d.id == doc_id:
                return FakeDocumentRef(d)
        return FakeDocumentRef(None)


class FakeDocumentRef:
    def __init__(self, doc):
        self._doc = doc

    def set(self, payload, merge=False):
        if self._doc:
            self._doc._data.update(payload)


class FakeDB:
    def __init__(self, docs):
        # docs: list of FakeDoc
        self._articles = docs

    def collection(self, name):
        if name == 'articles':
            return PagingArticlesCollection(self._articles)
        raise NotImplementedError(name)


def make_fake_firebase_paging(docs):
    return types.SimpleNamespace(db=FakeDB(docs))


def test_pagination_processes_requested_total(monkeypatch):
    # Create 45 fake docs
    docs = []
    for i in range(45):
        idx = i + 1
        docs.append(FakeDoc(f'd{idx}', {
            'title': f'Title {idx}',
            'description': '',
            'content': 'x',
            'tags': [],
            'source': 'test',
            'pub_date': '2025-01-01T00:00:00Z',
            'status': 'NEW',
            'created_at': f'2025-01-01T00:00:{idx:02d}Z'
        }))

    fake_fb = make_fake_firebase_paging(docs)

    # Monkeypatch firebase client used by worker
    monkeypatch.setattr(catmod, 'get_firebase_client', lambda: fake_fb, raising=False)

    # Monkeypatch OpenAI client to return a simple JSON per request
    monkeypatch.setattr(catmod, 'get_openai_client', lambda: object(), raising=False)

    sample = {
        'total_score': 80,
        'rating': 'publish',
        'category': 'general',
        'comment': 'ok'
    }
    monkeypatch.setattr(catmod, 'chat_completion', lambda client, model, messages, max_tokens=600, temperature=0: json.dumps(sample), raising=False)
    monkeypatch.setattr(catmod, 'parse_json_from_text', lambda t: json.loads(t), raising=False)

    # Instantiate worker with batch_size 45 to force multiple pages (20 per page)
    w = catmod.CategorizationWorker(batch_size=45)
    res = w.categorize_new_articles()

    assert res['status'] == 'success'
    assert res['processed'] == 45

    # Ensure all docs were marked categorized
    for d in docs:
        assert d._data.get('status') == 'CATEGORIZED'
        assert 'interest' in d._data
        assert d._data['interest']['rating'] == 'publish'
