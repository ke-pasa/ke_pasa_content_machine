from __future__ import annotations

import os
from typing import Optional

try:
    from openai import OpenAI
except Exception as exc:  # pragma: no cover
    print(f"openai import error: {exc}")
    raise


def read_file_snippet(client: OpenAI, file_id: str, limit: int = 1200) -> str:
    try:
        stream = client.files.content(file_id)
        data = b"".join(stream.iter_bytes())
        text = data.decode("utf-8", "ignore")
        return text[:limit]
    except Exception as e:
        return f"<error reading file {file_id}: {e}>"


def main() -> None:
    api = os.getenv("OPENAI_API_KEY")
    print("api_key set:", bool(api))
    client = OpenAI(api_key=api)

    batches = list(client.batches.list(limit=5))
    if not batches:
        print("no batches")
        return

    for b in batches:
        status = getattr(b, "status", None)
        rc = getattr(b, "request_counts", None)
        err_id: Optional[str] = getattr(b, "error_file_id", None)
        out_id: Optional[str] = getattr(b, "output_file_id", None)
        print(f"batch {b.id} status={status} request_counts={rc}")
        if out_id:
            print(f"  output_file_id={out_id}")
        if err_id:
            print(f"  error_file_id={err_id}")
            snippet = read_file_snippet(client, err_id)
            print("  error snippet:\n" + snippet)


if __name__ == "__main__":
    main()





