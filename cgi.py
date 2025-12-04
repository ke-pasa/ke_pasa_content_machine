"""Minimal compatibility shim for removed stdlib `cgi` module.

This provides a lightweight `parse_header` implementation which is
used by `feedparser` (via `feedparser.encodings`) to parse the
Content-Type header. The real `cgi` module contains many more
helpers; only the subset needed by this project is implemented here.
"""
from typing import Tuple, Dict


def parse_header(header_value: str) -> Tuple[str, Dict[str, str]]:
    """Parse a Content-Type style header into (value, params)

    Args:
        header_value: e.g. "text/xml; charset=\"utf-8\"; foo=bar"

    Returns:
        (main_value, params_dict)
    """
    if not header_value:
        return '', {}

    parts = header_value.split(';')
    main = parts[0].strip()
    params = {}
    for p in parts[1:]:
        if '=' not in p:
            continue
        k, v = p.split('=', 1)
        k = k.strip().lower()
        v = v.strip()
        # Remove surrounding quotes if present
        if len(v) >= 2 and ((v[0] == v[-1]) and v[0] in ('"', "'")):
            v = v[1:-1]
        params[k] = v
    return main, params


__all__ = ["parse_header"]
