from __future__ import annotations

from typing import Optional
import time
from google.api_core.exceptions import ResourceExhausted, RetryError

from workers.tools.firebase_client import get_firebase_client


def wipe_collection(name: str, limit: int = 25, sleep_sec: float = 2.0) -> int:
    client = get_firebase_client()
    db = client.db
    total = 0
    backoff = 5.0
    while True:
        try:
            docs = list(db.collection(name).limit(limit).stream())
        except (ResourceExhausted, RetryError) as e:
            print(f"quota exceeded while listing {name}; sleep {int(backoff)}s and retry")
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        except Exception as e:
            msg = str(e)
            if 'Quota exceeded' in msg or 'RESOURCE_EXHAUSTED' in msg:
                print(f"quota exceeded (generic) on {name}; sleep {int(backoff)}s and retry")
                time.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            raise
        if not docs:
            break
        for d in docs:
            try:
                d.reference.delete()
                total += 1
            except Exception as e:
                print(f"delete error in {name}: {e}")
        print(f"deleted batch from {name}; total={total}")
        time.sleep(sleep_sec)
    print(f"wiped {name}: {total}")
    return total


def main() -> None:
    # Чистим кэши дедупликации/пропусков и очереди батчей с паузами
    wipe_collection('skipped')
    time.sleep(3)
    wipe_collection('sources')
    time.sleep(3)
    wipe_collection('llm_tasks')
    time.sleep(3)
    wipe_collection('llm_batches')


if __name__ == "__main__":
    main()


