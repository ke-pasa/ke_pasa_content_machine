from types import SimpleNamespace
from unittest.mock import Mock

from workers.tools import health_check


def test_check_postgres_success(monkeypatch):
    mock_client = Mock()
    mock_cursor = Mock()
    mock_conn = Mock(cursor=Mock(return_value=mock_cursor))

    monkeypatch.setattr(health_check, "PGClient", Mock(return_value=mock_client))
    mock_client._connect.return_value = None
    mock_client._get_conn.return_value = (mock_conn, True)

    result = health_check.check_postgres()

    mock_cursor.execute.assert_called_once_with("SELECT 1")
    mock_cursor.fetchone.assert_called_once()
    mock_client._put_conn.assert_called_once_with(mock_conn, True)
    assert result.status == "ok"


def test_check_postgres_failure(monkeypatch):
    mock_client = Mock()
    monkeypatch.setattr(health_check, "PGClient", Mock(return_value=mock_client))
    mock_client._connect.side_effect = RuntimeError("boom")

    result = health_check.check_postgres()

    assert result.status == "error"
    assert "boom" in result.details


def test_check_rss_skipped(monkeypatch):
    monkeypatch.setattr(health_check, "_first_feed_from_file", lambda: None)
    result = health_check.check_rss(feed_url=None)
    assert result.status == "skipped"


def test_check_rss_success(monkeypatch):
    response = SimpleNamespace(status_code=200)
    monkeypatch.setattr(health_check.requests, "get", lambda *args, **kwargs: response)

    result = health_check.check_rss(feed_url="https://example.com/rss")

    assert result.status == "ok"
    assert "example.com" in result.details


def test_check_rss_error(monkeypatch):
    response = SimpleNamespace(status_code=500)
    monkeypatch.setattr(health_check.requests, "get", lambda *args, **kwargs: response)

    result = health_check.check_rss(feed_url="https://example.com/rss")

    assert result.status == "error"
    assert "500" in result.details


def test_check_telegram_success(monkeypatch):
    response = SimpleNamespace(status_code=200)
    monkeypatch.setattr(health_check.requests, "get", lambda *args, **kwargs: response)

    result = health_check.check_telegram()

    assert result.status == "ok"


def test_check_telegram_error(monkeypatch):
    def raiser(*args, **kwargs):
        raise ConnectionError("fail")

    monkeypatch.setattr(health_check.requests, "get", raiser)

    result = health_check.check_telegram()

    assert result.status == "error"
    assert "fail" in result.details


def test_run_health_checks(monkeypatch):
    monkeypatch.setattr(health_check, "check_postgres", lambda: health_check.HealthResult("ok", "pg"))
    monkeypatch.setattr(health_check, "check_rss", lambda: health_check.HealthResult("skipped", "rss"))
    monkeypatch.setattr(health_check, "check_telegram", lambda: health_check.HealthResult("error", "tg"))

    results = health_check.run_health_checks()

    assert results["postgres"]["status"] == "ok"
    assert results["rss"]["status"] == "skipped"
    assert results["telegram"]["status"] == "error"
