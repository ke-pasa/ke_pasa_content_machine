from __future__ import annotations

import sys
from typing import Any, Dict, List

try:
    from firebase_client import get_firebase_client
except Exception as exc:  # pragma: no cover
    print(f"firebase import error: {exc}")
    sys.exit(1)


def trunc(text: Any, limit: int = 240) -> str:
    s = str(text or "")
    t = s[:limit].replace("\n", " ")
    return t + ("..." if len(s) > limit else "")


def main() -> None:
    client = get_firebase_client()
    db = client.db

    # Считываем ограниченный набор статей для быстрой сводки
    items: List[Dict[str, Any]] = []
    try:
        for d in db.collection("articles").limit(100).stream():
            try:
                doc = d.to_dict() or {}
                doc["article_id"] = d.id
                items.append(doc)
            except Exception:
                continue
    except Exception as exc:
        print(f"read articles error: {exc}")

    total = len(items)
    with_md = [a for a in items if a.get("content_markdown")]  # готовые md
    with_post = [a for a in items if a.get("telegram_post")]   # готовые телепосты
    ready_to_publish = [
        a for a in items
        if a.get("telegram_post") and not a.get("published", False)
    ]

    print(f"articles_total {total}")
    print(f"articles_with_markdown {len(with_md)}")
    print(f"articles_with_telegram_post {len(with_post)}")
    print(f"unpublished_ready_posts {len(ready_to_publish)}")

    print("\n=== sample_markdown_articles ===")
    for a in with_md[:3]:
        print("—", a.get("title", "(no title)"))
        print(trunc(a.get("content_markdown")))

    print("\n=== sample_telegram_posts ===")
    for a in with_post[:3]:
        print("—", a.get("title", "(no title)"))
        print(trunc(a.get("telegram_post")))


if __name__ == "__main__":
    main()





