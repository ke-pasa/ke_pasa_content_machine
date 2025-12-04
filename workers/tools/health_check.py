"""Simple runtime health checks for Postgres and outbound connectivity."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Optional

import requests

from workers.tools.pg_client import PGClient

DEFAULT_TIMEOUT = float(os.getenv("HEALTHCHECK_TIMEOUT", "5"))
RSS_FEEDS_FILE = os.getenv("RSS_FEEDS_FILE", "workers/rss/feeds.txt")
TELEGRAM_BASE_URL = os.getenv("TELEGRAM_API_BASE", "https://api.telegram.org")


@dataclass
class HealthResult:
    """Represents a single health check result."""

    status: str
    details: str

    def to_dict(self) -> Dict[str, str]:
        return {"status": self.status, "details": self.details}


def _first_feed_from_file(feeds_file: str = RSS_FEEDS_FILE) -> Optional[str]:
    try:
        with open(feeds_file, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped
    except FileNotFoundError:
        return None
    except Exception as exc:  # pragma: no cover - defensive log path
        return None
    return None


def check_postgres() -> HealthResult:
    """Perform a lightweight Postgres connectivity check."""

    client = PGClient()
    try:
        client._connect()
        conn, pooled = client._get_conn()
        cur = conn.cursor()
        try:
            cur.execute("SELECT 1")
            cur.fetchone()
            return HealthResult("ok", "postgres reachable")
        finally:
            try:
                cur.close()
            finally:
                client._put_conn(conn, pooled)
    except Exception as exc:
        return HealthResult("error", f"postgres unreachable: {exc}")


def check_rss(feed_url: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT) -> HealthResult:
    """Check outbound connectivity to an RSS feed URL."""

    url = feed_url or os.getenv("HEALTHCHECK_RSS_URL") or _first_feed_from_file()
    if not url:
        return HealthResult("skipped", "no rss url configured")
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": "health-check"})
        if resp.status_code >= 400:
            return HealthResult("error", f"rss returned {resp.status_code}")
        return HealthResult("ok", f"rss reachable: {url}")
    except Exception as exc:
        return HealthResult("error", f"rss unreachable: {exc}")


def check_telegram(timeout: float = DEFAULT_TIMEOUT) -> HealthResult:
    """Check outbound connectivity to Telegram API."""

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    url = TELEGRAM_BASE_URL.rstrip("/")
    if token:
        url = f"{url}/bot{token}/getMe"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code >= 400:
            return HealthResult("error", f"telegram returned {resp.status_code}")
        return HealthResult("ok", "telegram reachable")
    except Exception as exc:
        return HealthResult("error", f"telegram unreachable: {exc}")


def run_health_checks() -> Dict[str, Dict[str, str]]:
    results = {
        "postgres": check_postgres(),
        "rss": check_rss(),
        "telegram": check_telegram(),
    }
    return {name: result.to_dict() for name, result in results.items()}


def main(argv: Optional[list] = None) -> int:
    """Run all health checks and exit with non-zero on failure."""

    results = run_health_checks()
    print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [name for name, res in results.items() if res["status"] == "error"]
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
