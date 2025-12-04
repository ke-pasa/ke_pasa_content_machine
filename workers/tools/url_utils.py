"""URL utility helpers: normalization and deterministic id computation."""
import re
from urllib.parse import urlparse, urlunparse, unquote
import hashlib


def compute_article_id(link: str, title: str) -> str:
    """Compute deterministic article id (md5 of link+title)."""
    content = f"{link}{title}"
    return hashlib.md5(content.encode()).hexdigest()


def normalize_link(link: str) -> str:
    """
    Normalize a URL for comparison purposes.

    Rules applied (conservative):
    - If link is empty or not a string, return as-is.
    - Lowercase scheme and host.
    - Remove query and fragment.
    - Remove default ports (80 for http, 443 for https).
    - Remove trailing slash from path (except when path is '/')
    - Percent-decode path components for normalization.
    """
    try:
        if not link or not isinstance(link, str):
            return link
        parsed = urlparse(link)
        if not parsed.scheme or not parsed.netloc:
            return link

        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        # Remove default ports
        netloc = re.sub(r":(80)$", "", netloc) if scheme == 'http' else netloc
        netloc = re.sub(r":(443)$", "", netloc) if scheme == 'https' else netloc

        # Decode percent-encoded path and collapse duplicate slashes
        path = unquote(parsed.path or '')
        path = re.sub(r'/{2,}', '/', path)
        if path.endswith('/') and path != '/':
            path = path[:-1]

        normalized = urlunparse((scheme, netloc, path, '', '', ''))
        return normalized
    except Exception:
        return link
