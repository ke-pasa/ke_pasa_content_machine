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
        self._pool = None
        self._pool_min = 1
        self._pool_max = 10

    def _connect(self):
        if self._conn:
            return
        try:
            import psycopg2
            from psycopg2.extras import RealDictCursor
            from psycopg2.pool import ThreadedConnectionPool
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

            # Initialize a threaded connection pool using the same kwargs
            try:
                self._pool = ThreadedConnectionPool(self._pool_min, self._pool_max, **connect_kwargs)
                # pre-warm a single connection for table creation (run DDL inline to avoid recursion)
                conn = self._pool.getconn()
                conn.autocommit = True
                cur = conn.cursor()
                try:
                    cur.execute("""
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
                    """)
                    try:
                        cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_date ON public.articles USING btree (published_date)")
                        cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_created_at ON public.articles USING btree (created_at)")
                    except Exception:
                        pass
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    self._pool.putconn(conn)
                return
            except Exception:
                # Fallback to single connection if pool creation fails
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

                try:
                    self._pool = ThreadedConnectionPool(self._pool_min, self._pool_max, **connect_kwargs)
                    conn = self._pool.getconn()
                    conn.autocommit = True
                    cur = conn.cursor()
                    try:
                        cur.execute("""
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
                        """)
                        try:
                            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_date ON public.articles USING btree (published_date)")
                            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_created_at ON public.articles USING btree (created_at)")
                        except Exception:
                            pass
                    finally:
                        try:
                            cur.close()
                        except Exception:
                            pass
                        self._pool.putconn(conn)
                    return
                except Exception:
                    self._conn = psycopg2.connect(**connect_kwargs)
            else:
                # DSN provided as generic libpq string; rely on libpq resolution.
                # DSN provided as generic libpq string; rely on libpq resolution.
                try:
                    self._pool = ThreadedConnectionPool(self._pool_min, self._pool_max, dsn)
                    conn = self._pool.getconn()
                    conn.autocommit = True
                    cur = conn.cursor()
                    try:
                        cur.execute("""
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
                        """)
                        try:
                            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_date ON public.articles USING btree (published_date)")
                            cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_created_at ON public.articles USING btree (created_at)")
                        except Exception:
                            pass
                    finally:
                        try:
                            cur.close()
                        except Exception:
                            pass
                        self._pool.putconn(conn)
                    return
                except Exception:
                    self._conn = psycopg2.connect(dsn)

        self._conn.autocommit = True
        # Use a simple cursor; callers only use basic execute/fetch operations
        self._cursor = self._conn.cursor()
        self._ensure_table()

    def _get_conn(self):
        """Acquire a connection. Returns (conn, returned_to_pool_flag).

        If a pool is configured the returned flag will be True (caller should putconn).
        If using single connection the flag will be False and caller must not close/put it.
        """
        self._connect()
        if self._pool:
            conn = self._pool.getconn()
            try:
                conn.autocommit = True
            except Exception:
                pass
            return conn, True
        else:
            return self._conn, False

    def _put_conn(self, conn, returned: bool):
        if returned and self._pool:
            try:
                self._pool.putconn(conn)
            except Exception:
                try:
                    conn.close()
                except Exception:
                    pass

    def _ensure_table(self):
        # Create articles table matching provided schema. Use a per-call connection/cursor.
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
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(create_sql)
            try:
                cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_published_date ON public.articles USING btree (published_date)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_articles_created_at ON public.articles USING btree (created_at)")
            except Exception:
                pass
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

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
            conn, pooled = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute(insert_sql, params)
                try:
                    inserted = cur.rowcount == 1
                except Exception:
                    inserted = True
                if inserted:
                    return 'inserted'
                else:
                    return 'exists'
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)
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
            conn, pooled = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute('SELECT 1 FROM public.articles WHERE link = %s LIMIT 1', (link_norm,))
                return cur.fetchone() is not None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)
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
            conn, pooled = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute('SELECT link FROM public.articles WHERE created_at >= %s', (cutoff,))
                rows = cur.fetchall()
                for row in rows:
                    try:
                        link = row[0]
                        if not link:
                            continue
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
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)

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
            conn, pooled = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute('DELETE FROM public.articles WHERE created_at < %s', (cutoff,))
                try:
                    deleted = cur.rowcount
                except Exception:
                    deleted = -1
                return deleted
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)
        except Exception as e:
            print(f"    ⚠️  Failed to purge old articles: {e}")
            traceback.print_exc()
            return -1

    def fetch_articles_new(self, limit: int = 30, last_cursor: dict = None, status: str = 'NEW'):
        """
        Fetch up to `limit` articles with given `status` ordered by (created_at, id) ascending.

        `last_cursor` expected shape: {'created_at': <ISO string or datetime>, 'id': <str>}
        Returns list of dict rows normalized to keys used by the worker (includes 'id',
        'title', 'description', 'content', 'tags', 'source', 'pub_date', 'feed_name',
        'region_hint', 'created_at', 'interest').
        """
        try:
            self._connect()
        except Exception:
            return []

        try:
            from psycopg2.extras import RealDictCursor
            conn, pooled = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            sql = [
                "SELECT id, title, summary AS description, content, categories, link AS source,",
                "published_date AS pub_date, source_feed AS feed_name, status, created_at, updated_at, interest",
                "FROM public.articles",
                "WHERE status = %s"
            ]
            params = [status]
            if last_cursor:
                # Accept either ISO string or datetime for created_at
                cursor_created = last_cursor.get('created_at')
                cursor_id = last_cursor.get('id')
                sql.append("AND (created_at, id) > (%s::timestamptz, %s)")
                params.extend([cursor_created, cursor_id])

            sql.append("ORDER BY created_at ASC, id ASC")
            sql.append("LIMIT %s")
            params.append(limit)

            query = '\n'.join(sql)
            cur.execute(query, tuple(params))
            rows = cur.fetchall()
            results = []
            for r in rows:
                try:
                    # Normalize categories (jsonb) -> tags list
                    tags = r.get('categories') if r.get('categories') is not None else []
                    # `interest` may be stored as text; try to parse JSON
                    interest_raw = r.get('interest')
                    interest = None
                    if interest_raw is not None:
                        if isinstance(interest_raw, (str, bytes)):
                            try:
                                interest = json.loads(interest_raw)
                            except Exception:
                                interest = None
                        elif isinstance(interest_raw, dict):
                            interest = interest_raw

                    # pub_date -> ISO string when present
                    pub_date = r.get('pub_date')
                    if hasattr(pub_date, 'isoformat'):
                        pub_date_val = pub_date.isoformat()
                    else:
                        pub_date_val = pub_date

                    normalized = {
                        'id': r.get('id'),
                        'title': r.get('title'),
                        'description': r.get('description'),
                        'content': r.get('content'),
                        'tags': tags or [],
                        'source': r.get('source'),
                        'pub_date': pub_date_val,
                        'feed_name': r.get('feed_name'),
                        'region_hint': None,
                        'created_at': r.get('created_at'),
                        'updated_at': r.get('updated_at'),
                        'interest': interest
                    }
                    results.append(normalized)
                except Exception:
                    continue
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)
            return results
        except Exception as e:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)
            print(f"    ⚠️  Postgres fetch_articles_new exception: {e}")
            traceback.print_exc()
            return []

    def fetch_article_by_id(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Fetch a single article by id and return normalized dict (same shape as fetch_articles_new rows).
        Returns None if not found or on error.
        """
        try:
            self._connect()
        except Exception:
            return None

        try:
            from psycopg2.extras import RealDictCursor
            conn, pooled = self._get_conn()
            cur = conn.cursor(cursor_factory=RealDictCursor)
            try:
                cur.execute("SELECT id, title, summary AS description, content, categories, link AS source, published_date AS pub_date, source_feed AS feed_name, status, created_at, updated_at, interest FROM public.articles WHERE id = %s LIMIT 1", (article_id,))
                r = cur.fetchone()
                if not r:
                    return None

                # Normalize like fetch_articles_new
                tags = r.get('categories') if r.get('categories') is not None else []
                interest_raw = r.get('interest')
                interest = None
                if interest_raw is not None:
                    if isinstance(interest_raw, (str, bytes)):
                        try:
                            interest = json.loads(interest_raw)
                        except Exception:
                            interest = None
                    elif isinstance(interest_raw, dict):
                        interest = interest_raw

                pub_date = r.get('pub_date')
                if hasattr(pub_date, 'isoformat'):
                    pub_date_val = pub_date.isoformat()
                else:
                    pub_date_val = pub_date

                normalized = {
                    'id': r.get('id'),
                    'title': r.get('title'),
                    'description': r.get('description'),
                    'content': r.get('content'),
                    'tags': tags or [],
                    'source': r.get('source'),
                    'pub_date': pub_date_val,
                    'feed_name': r.get('feed_name'),
                    'region_hint': None,
                    'created_at': r.get('created_at'),
                    'updated_at': r.get('updated_at'),
                    'interest': interest
                }
                return normalized
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)
        except Exception:
            return None

    def save_article_categorization(self, article_id: str, payload: Dict[str, Any]) -> bool:
        """
        Upsert categorization fields for article with `article_id`.

        Expected payload keys (any subset): `interest` (dict), `status`, `total_score`,
        `rating`, `short_note`, `category`, `comment`, `publish_on_site`, `publish_on_social`,
        `newsletter`, `categorized_at`, `updated_at`.
        """
        try:
            self._connect()
            # Prepare interest as text (table column is text)
            interest_val = None
            if 'interest' in payload and payload.get('interest') is not None:
                try:
                    interest_val = json.dumps(payload.get('interest'), ensure_ascii=False)
                except Exception:
                    interest_val = str(payload.get('interest'))

            # Perform UPDATE only (assume the article row already exists)

            update_sql = '''
            UPDATE public.articles SET
                interest = COALESCE(%s, interest),
                status = COALESCE(%s, status),
                total_score = COALESCE(%s, total_score),
                rating = COALESCE(%s, rating),
                category = COALESCE(%s, category),
                publish_on_site = COALESCE(%s, publish_on_site),
                publish_on_social = COALESCE(%s, publish_on_social),
                categorized_at = now(),
                updated_at = now()
            WHERE id = %s
            '''

            params = (
                interest_val,
                payload.get('status'),
                payload.get('total_score'),
                payload.get('rating'),
                payload.get('category'),
                payload.get('publish_on_site'),
                payload.get('publish_on_social'),
                article_id,
            )

            conn, pooled = self._get_conn()
            cur = conn.cursor()
            try:
                cur.execute(update_sql, params)
                try:
                    updated = cur.rowcount and cur.rowcount > 0
                except Exception:
                    updated = False
                return bool(updated)
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self._put_conn(conn, pooled)
        except Exception as e:
            print(f"    ⚠️  Postgres save categorization exception for {article_id}: {e}")
            traceback.print_exc()
            return False


_client = None


def get_pg_client():
    global _client
    if _client is None:
        _client = PGClient()
    return _client
