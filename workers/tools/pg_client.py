"""
Minimal PostgreSQL client wrapper used by RSS parser when
`RSS_SAVE_BACKEND` includes 'postgres'.

Features:
- Lazy connection using environment variables
- Ensure simple `articles` table exists
- `save_article(article_data)` to insert base fields
- `is_duplicate_by_link(link)` and `is_duplicate_article(link, title)` helpers

This implementation is intentionally small and defensive so it won't
raise on import if psycopg2 isn't installed; errors surface only when
used.
"""
import os
import json
from typing import Optional, Dict, Any
from datetime import datetime, timedelta
from urllib.parse import urlparse
from workers.tools.url_utils import normalize_link
import traceback


class PGClient:
    def __init__(self):
        self._conn = None
        self._cursor = None

    def _connect(self):
        if self._conn:
            return
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
        except Exception as e:
            raise RuntimeError(f"psycopg2 is required for PostgreSQL support: {e}")

        # Prefer new environment variable POSTGRES_URL, then existing ones
        dsn = os.getenv('POSTGRES_URL') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL')

        # Attempt to prefer IPv6 address when resolving hostnames. If the DSN is
        # a URL (postgresql://...) parse it and pass numeric address via
        # `hostaddr` to libpq; this forces an IPv6 connect while preserving the
        # original hostname for SSL verification.
        try:
            import socket
            from urllib.parse import urlparse, parse_qs, unquote
        except Exception:
            socket = None

        # If DSN is a URL string, prefer that parsing path
        if dsn and (dsn.startswith('postgres://') or dsn.startswith('postgresql://')):
            parsed = urlparse(dsn)
            user = unquote(parsed.username) if parsed.username else None
            password = unquote(parsed.password) if parsed.password else None
            host = parsed.hostname
            port = parsed.port or 5432
            db = parsed.path.lstrip('/') or None
            query = parse_qs(parsed.query)
            sslmode = query.get('sslmode', [None])[0]

            connect_kwargs = {}
            if user:
                connect_kwargs['user'] = user
            if password:
                connect_kwargs['password'] = password
            if db:
                connect_kwargs['dbname'] = db
            if host:
                connect_kwargs['host'] = host
            if port:
                connect_kwargs['port'] = port
            if sslmode:
                connect_kwargs['sslmode'] = sslmode
            else:
                # default to require remote SSL when connecting to non-local hosts
                if host and host not in ('localhost', '127.0.0.1', '::1'):
                    connect_kwargs.setdefault('sslmode', 'require')


            env_hostaddr = os.getenv('PG_HOSTADDR')
            if env_hostaddr:
                connect_kwargs['hostaddr'] = env_hostaddr
            elif socket and host:
                try:
                    addrs = socket.getaddrinfo(host, port, family=socket.AF_INET6, type=socket.SOCK_STREAM)
                    if addrs:
                        ipv6_addr = addrs[0][4][0]
                        connect_kwargs['hostaddr'] = ipv6_addr
                except Exception:
                    pass

            # Finally connect using keyword args to avoid DSN parsing
            self._conn = psycopg2.connect(**connect_kwargs)
        else:
            # Fall back to previous behavior: accept full DSN string or build
            # connection kwargs from individual PG_* variables.
            if not dsn:
                user = os.getenv('PG_USER')
                password = os.getenv('PG_PASSWORD')
                host = os.getenv('PG_HOST', 'localhost')
                port = os.getenv('PG_PORT', '5432')
                db = os.getenv('PG_DB')
                if not (user and password and db):
                    raise RuntimeError('Postgres DSN or PG_USER/PG_PASSWORD/PG_DB must be set')

                connect_kwargs = {
                    'user': user,
                    'password': password,
                    'host': host,
                    'port': port,
                    'dbname': db,
                }

                # Try to resolve IPv6 for provided host
                if socket and host:
                    try:
                        addrs = socket.getaddrinfo(host, port, family=socket.AF_INET6, type=socket.SOCK_STREAM)
                        if addrs:
                            connect_kwargs['hostaddr'] = addrs[0][4][0]
                    except Exception:
                        pass

                self._conn = psycopg2.connect(**connect_kwargs)
            else:
                # DSN provided as generic libpq string; rely on libpq resolution.
                self._conn = psycopg2.connect(dsn)
        self._conn.autocommit = True
        # Use a simple cursor; callers only use basic execute/fetch operations
        self._cursor = self._conn.cursor()
        self._ensure_table()

    def _ensure_table(self):
        # Create articles table matching provided schema
        create_sql = """
        CREATE TABLE IF NOT EXISTS public.articles (
            id character varying(32) PRIMARY KEY,
            title character varying(512),
            summary text,
            content text,
            link character varying(1024),
            image character varying(1024),
            categories jsonb,
            published_date date,
            source_feed character varying(255),
            source_link character varying(1024),
            status character varying(32) DEFAULT 'NEW',
            published boolean DEFAULT false,
            created_at timestamptz DEFAULT now(),
            updated_at timestamptz DEFAULT now()
        )
        """
        self._cursor.execute(create_sql)

        # Create indexes if not exist (safe to run repeatedly)
        try:
            self._cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_date ON public.articles USING btree (published_date)")
            self._cursor.execute("CREATE INDEX IF NOT EXISTS idx_articles_created_at ON public.articles USING btree (created_at)")
        except Exception:
            pass

    def save_article(self, article: Dict[str, Any]) -> str:
        try:
            self._connect()
            insert_sql = """
            INSERT INTO public.articles(
                id, title, summary, content, link, image, categories, published_date,
                source_feed, source_link, status, published, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (id) DO NOTHING
            """
            categories = article.get('categories') or []
            categories_json = json.dumps(categories, ensure_ascii=False)
            article_id = article.get('id') or article.get('article_id')
            # Store normalized link for robust deduplication
            try:
                norm_link = normalize_link(article.get('link') or '')
            except Exception:
                parsed = urlparse(article.get('link') or '')
                if not parsed.scheme or not parsed.netloc:
                    norm_link = article.get('link') or ''
                else:
                    norm_link = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/') if parsed.path and parsed.path != '/' else parsed.path}"

            # Store normalized link into the `link` column
            params = (
                article_id,
                article.get('title'),
                article.get('summary'),
                article.get('content'),
                norm_link,
                article.get('image'),
                categories_json,
                article.get('published_date'),
                article.get('source_feed'),
                article.get('source_link'),
                article.get('status') or None,
                article.get('published') if 'published' in article else None,
                article.get('created_at')
            )
            self._cursor.execute(insert_sql, params)
            # If a row was inserted, rowcount == 1; if conflict DO NOTHING, rowcount == 0
            try:
                inserted = self._cursor.rowcount == 1
            except Exception:
                inserted = True

            if inserted:
                return 'inserted'
            else:
                # Existing row (no-op)
                return 'exists'
        except Exception as e:
            try:
                article_id = article.get('id') or article.get('article_id')
            except Exception:
                article_id = None
            print(f"    ⚠️  Postgres save exception for article {article_id}: {e}")
            traceback.print_exc()
            return 'error'

    def is_duplicate_by_link(self, link: str) -> bool:
        try:
            self._connect()
            try:
                link_norm = normalize_link(link or '')
            except Exception:
                parsed = urlparse(link or '')
                if not parsed.scheme or not parsed.netloc:
                    link_norm = link or ''
                else:
                    link_norm = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/') if parsed.path and parsed.path != '/' else parsed.path}"
            self._cursor.execute('SELECT 1 FROM public.articles WHERE link = %s LIMIT 1', (link_norm,))
            return self._cursor.fetchone() is not None
        except Exception:
            return False

    def get_recent_article_links(self, hours: int = 24) -> set:
        """
        Retrieve a set of article links created within the last `hours` hours.

        Returns normalized links (best-effort). Non-fatal on errors.
        """
        results = set()
        try:
            self._connect()
        except Exception:
            return results

        try:
            cutoff = datetime.utcnow() - timedelta(hours=hours)
            self._cursor.execute('SELECT link FROM public.articles WHERE created_at >= %s', (cutoff,))
            rows = self._cursor.fetchall()
            for row in rows:
                try:
                    link = row[0]
                    if not link:
                        continue
                    # Normalize link using existing helper if available
                    try:
                        norm = normalize_link(link)
                    except Exception:
                        parsed = urlparse(link)
                        if not parsed.scheme or not parsed.netloc:
                            norm = link
                        else:
                            norm = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}{parsed.path.rstrip('/') if parsed.path and parsed.path != '/' else parsed.path}"
                    results.add(norm)
                except Exception:
                    continue
        except Exception:
            return results

        return results

    def purge_older_than(self, days: int = 15) -> int:
        """
        Delete articles older than `days` days from the `public.articles` table.

        Returns number of deleted rows, or -1 on error.
        """
        try:
            self._connect()
            cutoff = datetime.utcnow() - timedelta(days=days)
            # Use parameterized query with a Python cutoff timestamp
            self._cursor.execute('DELETE FROM public.articles WHERE created_at < %s', (cutoff,))
            try:
                deleted = self._cursor.rowcount
            except Exception:
                deleted = -1
            return deleted
        except Exception as e:
            print(f"    ⚠️  Failed to purge old articles: {e}")
            traceback.print_exc()
            return -1


_client = None


def get_pg_client():
    global _client
    if _client is None:
        _client = PGClient()
    return _client
