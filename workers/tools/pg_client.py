"""
Lightweight Postgres client used by workers.

Provides a simple connection pool and helper methods the workers expect.
This file favors clarity and defensive behavior: connection errors raise
so callers can log and handle them explicitly.
"""

import os
import json
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta

from workers.tools.url_utils import normalize_link


class PGClient:
    def __init__(self):
        self._conn = None
        self._pool = None

    def _connect(self):
        if self._conn or self._pool:
            return
        try:
            import psycopg2
            from psycopg2.pool import ThreadedConnectionPool
        except Exception as e:
            raise RuntimeError(f"psycopg2 is required for Postgres support: {e}")

        dsn = os.getenv('POSTGRES_URL') or os.getenv('PG_DSN') or os.getenv('DATABASE_URL')
        if not dsn:
            user = os.getenv('PG_USER')
            password = os.getenv('PG_PASSWORD')
            host = os.getenv('PG_HOST', 'localhost')
            port = os.getenv('PG_PORT', '5432')
            db = os.getenv('PG_DB')
            if user and password and db:
                dsn = f"host={host} port={port} dbname={db} user={user} password={password}"
            else:
                raise RuntimeError('Postgres DSN or PG_USER/PG_PASSWORD/PG_DB must be set')

        # Try to use a small threaded pool first, fall back to a single connection.
        try:
            try:
                self._pool = ThreadedConnectionPool(1, 5, dsn)
                conn = self._pool.getconn()
                conn.autocommit = True
                cur = conn.cursor()
                try:
                    # Create minimal tables if they don't exist (harmless if present)
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.articles (
                        id varchar(64) PRIMARY KEY,
                        title varchar(512),
                        summary text,
                        content text,
                        link varchar(1024),
                        image varchar(1024),
                        categories jsonb,
                        published_date date,
                        source_feed varchar(255),
                        source_link varchar(1024),
                        status varchar(32) DEFAULT 'NEW',
                        published boolean DEFAULT false,
                        created_at timestamptz DEFAULT now(),
                        updated_at timestamptz DEFAULT now()
                    )
                    """)
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.articles_ru (
                        id serial PRIMARY KEY,
                        article_id text,
                        source_url text,
                        source_link text,
                        source_name text,
                        source_published_at timestamptz,
                        image_url text,
                        status text,
                        total_score numeric,
                        title_ru text,
                        description_ru text,
                        content_ru text,
                        publish_md text,
                        telegram_final jsonb,
                        published_at timestamptz,
                        updated_at timestamptz
                    )
                    """)
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
                    self._pool.putconn(conn)
            except Exception:
                import psycopg2 as _ps
                self._conn = _ps.connect(dsn)
                self._conn.autocommit = True
        except Exception as e:
            raise RuntimeError(f"Failed to initialize Postgres connection: {e}")

    def _get_conn(self):
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

    def save_article(self, article: Dict[str, Any]) -> str:
        try:
            self._connect()
        except Exception:
            return 'error'

        insert_sql = '''
        INSERT INTO public.articles(id, title, summary, content, link, image, categories, published_date, source_feed, source_link, status, published, created_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,now())
        ON CONFLICT (id) DO NOTHING
        '''
        article_id = article.get('id') or article.get('article_id')
        try:
            norm = normalize_link(article.get('link') or '')
        except Exception:
            norm = article.get('link') or ''
        params = (
            article_id,
            article.get('title'),
            article.get('summary'),
            article.get('content'),
            norm,
            article.get('image'),
            json.dumps(article.get('categories') or [], ensure_ascii=False),
            article.get('published_date'),
            article.get('source_feed'),
            article.get('source_link'),
            article.get('status'),
            article.get('published') if 'published' in article else None,
        )
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(insert_sql, params)
            try:
                inserted = cur.rowcount == 1
            except Exception:
                inserted = True
            return 'inserted' if inserted else 'exists'
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def is_duplicate_by_link(self, link: str) -> bool:
        try:
            self._connect()
        except Exception:
            return False
        try:
            norm = normalize_link(link or '')
        except Exception:
            norm = link or ''
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute('SELECT 1 FROM public.articles WHERE link = %s LIMIT 1', (norm,))
            return cur.fetchone() is not None
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def get_recent_article_links(self, hours: int = 24) -> set:
        results = set()
        try:
            self._connect()
        except Exception:
            return results
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute('SELECT link FROM public.articles WHERE created_at >= %s', (cutoff,))
            rows = cur.fetchall()
            for r in rows:
                link = r[0]
                if not link:
                    continue
                try:
                    results.add(normalize_link(link))
                except Exception:
                    results.add(link)
            return results
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def purge_older_than(self, days: int = 15) -> int:
        try:
            self._connect()
        except Exception:
            return -1
        cutoff = datetime.utcnow() - timedelta(days=days)
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute('DELETE FROM public.articles WHERE created_at < %s', (cutoff,))
            return cur.rowcount if cur.rowcount is not None else -1
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_articles_new(self, limit: int = 30, last_cursor: dict = None, status: str = 'NEW') -> List[Dict[str, Any]]:
        # Let connection/driver errors propagate so callers (workers) can see and log them.
        self._connect()
        from psycopg2.extras import RealDictCursor
        conn, pooled = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            sql = [
                "SELECT id, title, summary AS description, content, categories, link AS source,",
                "published_date AS pub_date, source_feed AS feed_name, status, created_at, updated_at, interest",
                "FROM public.articles",
                "WHERE status = %s"
            ]
            params = [status]
            if last_cursor:
                sql.append("AND (created_at, id) > (%s::timestamptz, %s)")
                params.extend([last_cursor.get('created_at'), last_cursor.get('id')])
            sql.append("ORDER BY created_at ASC, id ASC")
            sql.append("LIMIT %s")
            params.append(limit)
            cur.execute('\n'.join(sql), tuple(params))
            rows = cur.fetchall()
            results = []
            for r in rows:
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
                pub_date_val = pub_date.isoformat() if hasattr(pub_date, 'isoformat') else pub_date
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
            return results
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_article_by_id(self, article_id: str) -> Optional[Dict[str, Any]]:
        try:
            self._connect()
        except Exception:
            return None
        from psycopg2.extras import RealDictCursor
        conn, pooled = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT id, title, summary AS description, content, categories, link AS source, published_date AS pub_date, source_feed AS feed_name, status, created_at, updated_at, interest FROM public.articles WHERE id = %s LIMIT 1", (article_id,))
            r = cur.fetchone()
            if not r:
                return None
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
            pub_date_val = pub_date.isoformat() if hasattr(pub_date, 'isoformat') else pub_date
            normalized = {
                'id': r.get('id'),
                'title': r.get('title'),
                'description': r.get('description'),
                'content': r.get('content'),
                'status': r.get('status'),
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

    def save_article_categorization(self, article_id: str, payload: Dict[str, Any]) -> bool:
        try:
            self._connect()
        except Exception:
            return False
        interest_val = None
        if 'interest' in payload and payload.get('interest') is not None:
            try:
                interest_val = json.dumps(payload.get('interest'), ensure_ascii=False)
            except Exception:
                interest_val = str(payload.get('interest'))
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
            return bool(cur.rowcount and cur.rowcount > 0)
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def save_generated_article(self, article_id: str, payload: Dict[str, Any]) -> bool:
        try:
            self._connect()
        except Exception:
            return False
        telegram_final = payload.get('telegram_final')
        try:
            telegram_json = json.dumps(telegram_final, ensure_ascii=False) if telegram_final is not None else None
        except Exception:
            telegram_json = None

        # Use DELETE then INSERT to avoid relying on ON CONFLICT or unique constraints.
        delete_sql = 'DELETE FROM public.articles_ru WHERE article_id = %s'
        insert_sql = '''
        INSERT INTO public.articles_ru (article_id, source_url, source_link, source_name, source_published_at, image_url, status, total_score, title_ru, description_ru, content_ru, publish_md, telegram_final, published_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
        '''

        params_insert = (
            article_id,
            payload.get('source_url'),
            payload.get('source_link'),
            payload.get('source_name'),
            payload.get('source_published_at'),
            payload.get('image_url'),
            payload.get('status'),
            payload.get('total_score'),
            payload.get('title_ru'),
            payload.get('description_ru'),
            payload.get('content_ru'),
            payload.get('publish_md'),
            telegram_json,
        )

        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            try:
                cur.execute(delete_sql, (article_id,))
            except Exception:
                # If delete fails for some reason, continue to insert to attempt to recover
                pass
            cur.execute(insert_sql, params_insert)
            # Also update status/updated_at in public.articles to reflect translation result
            try:
                # Determine SKIPPED rules:
                # - payload may explicitly contain skipped=True
                # - or total_score < 60 -> SKIPPED
                # - or created_at older than 60 hours -> SKIPPED
                forced_skipped = False
                if payload.get('skipped') is True:
                    forced_skipped = True

                total_score = None
                try:
                    total_score = float(payload.get('total_score')) if payload.get('total_score') is not None else None
                except Exception:
                    total_score = None

                status_to_set = None
                if forced_skipped:
                    status_to_set = 'SKIPPED'
                elif total_score is not None and total_score < 60:
                    status_to_set = 'SKIPPED'
                else:
                    # check created_at age: prefer payload.created_at, otherwise fetch existing created_at
                    created_at_val = None
                    if payload.get('created_at'):
                        created_at_val = payload.get('created_at')
                    else:
                        try:
                            # try to read existing created_at from public.articles
                            cur.execute('SELECT created_at FROM public.articles WHERE id = %s LIMIT 1', (article_id,))
                            row = cur.fetchone()
                            if row:
                                created_at_val = row[0]
                        except Exception:
                            created_at_val = None

                    try:
                        if created_at_val is not None:
                            # created_at_val may be a string or datetime
                            from datetime import datetime, timezone
                            if isinstance(created_at_val, str):
                                try:
                                    created_dt = datetime.fromisoformat(created_at_val)
                                except Exception:
                                    created_dt = None
                            else:
                                created_dt = created_at_val

                            if created_dt is not None:
                                # normalize timezone-naive to UTC
                                if created_dt.tzinfo is None:
                                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                                age_hours = (datetime.utcnow().replace(tzinfo=timezone.utc) - created_dt).total_seconds() / 3600.0
                                if age_hours > 60:
                                    status_to_set = 'SKIPPED'
                    except Exception:
                        status_to_set = None

                if status_to_set is None:
                    # use explicit payload status if provided, otherwise default to TRANSLATED
                    status_to_set = payload.get('status') or 'TRANSLATED'

                cur.execute('UPDATE public.articles SET status = %s, updated_at = now() WHERE id = %s', (status_to_set, article_id))
            except Exception:
                # Non-fatal: if updating articles fails, still consider the generated article saved
                pass
            return True
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_translated_for_publish(self, limit: int = 10, min_score: float = 0.0) -> List[Dict[str, Any]]:
        results = []
        try:
            self._connect()
        except Exception:
            return results
        conn, pooled = self._get_conn()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(
                "SELECT * FROM public.articles_ru WHERE status = %s AND (total_score IS NULL OR total_score >= %s) ORDER BY published_at ASC NULLS LAST, id ASC LIMIT %s",
                ('TRANSLATED', min_score, limit)
            )
            rows = cur.fetchall()
            for r in rows:
                results.append(dict(r))
            return results
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)


_client: Optional[PGClient] = None


def get_pg_client() -> PGClient:
    global _client
    if _client is None:
        _client = PGClient()
    return _client
