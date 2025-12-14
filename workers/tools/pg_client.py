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
                    cur.execute("""
                    CREATE TABLE IF NOT EXISTS public.topic (
                        id serial PRIMARY KEY,
                        topic_name text NOT NULL,
                        created_at timestamptz DEFAULT now()
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

    def purge_older_than(self, days: int = 7) -> int:
        try:
            self._connect()
        except Exception:
            return -1
        cutoff = datetime.utcnow() - timedelta(days=days)
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            # Delete from primary articles table (by created_at)
            cur.execute('DELETE FROM public.articles WHERE created_at < %s', (cutoff,))
            deleted_articles = cur.rowcount if cur.rowcount is not None else 0

            # Also delete translated/generated articles that haven't been updated recently
            cur.execute('DELETE FROM public.articles_ru WHERE updated_at < %s', (cutoff,))
            deleted_articles_ru = cur.rowcount if cur.rowcount is not None else 0

            # Also delete old topics (by created_at) to keep metadata clean
            try:
                cur.execute('DELETE FROM public.topic WHERE created_at < %s', (cutoff,))
                deleted_topics = cur.rowcount if cur.rowcount is not None else 0
            except Exception:
                # If topic table is missing or deletion fails, treat as zero
                deleted_topics = 0

            return deleted_articles + deleted_articles_ru + deleted_topics
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_articles_new(self, limit: int = 30, last_cursor: dict = None, status: str = 'NEW', order_by: str = 'created_at', hours_ago: int = None) -> List[Dict[str, Any]]:
        # Let connection/driver errors propagate so callers (workers) can see and log them.
        self._connect()
        from psycopg2.extras import RealDictCursor
        conn, pooled = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            sql = [
                "SELECT id, title, summary AS description, content, categories, link AS source, link as link, image, source_link, source_feed AS source_name,",
                "published_date AS pub_date, published_date AS published_at, source_feed AS feed_name, status, created_at, updated_at, interest, total_score",
                "FROM public.articles",
                "WHERE status = %s"
            ]
            params = [status]
            if hours_ago is not None:
                sql.append("AND created_at >= NOW() - INTERVAL '%s hours'")
                params.append(hours_ago)
            if last_cursor:
                sql.append("AND (created_at, id) > (%s::timestamptz, %s)")
                params.extend([last_cursor.get('created_at'), last_cursor.get('id')])
            
            # Support ordering by total_score DESC or created_at ASC
            if order_by == 'total_score':
                sql.append("ORDER BY total_score DESC, id ASC")
            else:
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
                total_score = r.get('total_score')
                try:
                    total_score = float(total_score) if total_score is not None else 0.0
                except (ValueError, TypeError):
                    total_score = 0.0
                normalized = {
                    'id': r.get('id'),
                    'title': r.get('title'),
                    'description': r.get('description'),
                    'content': r.get('content'),
                    'tags': tags or [],
                    'source': r.get('source'),
                    'link': r.get('link'),
                    'image': r.get('image'),
                    'source_link': r.get('source_link'),
                    'source_name': r.get('source_name'),
                    'pub_date': pub_date_val,
                    'published_at': pub_date_val,
                    'feed_name': r.get('feed_name'),
                    'region_hint': None,
                    'created_at': r.get('created_at'),
                    'updated_at': r.get('updated_at'),
                    'interest': interest,
                    'total_score': total_score
                }
                results.append(normalized)
            return results
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_top_categorized_article_24h(self) -> Optional[Dict[str, Any]]:
        """Fetch single CATEGORIZED article with highest total_score from last 24 hours."""
        self._connect()
        from psycopg2.extras import RealDictCursor
        conn, pooled = self._get_conn()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            sql = """
                SELECT id, title, summary AS description, content, categories, link AS source, link as link, 
                       image, source_link, source_feed AS source_name,
                       published_date AS pub_date, published_date AS published_at, source_feed AS feed_name, 
                       status, created_at, updated_at, interest, total_score
                FROM public.articles
                WHERE status = 'CATEGORIZED'
                  AND created_at >= NOW() - INTERVAL '24 hours'
                ORDER BY total_score DESC, id ASC
                LIMIT 1
            """
            cur.execute(sql)
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
            total_score = r.get('total_score')
            try:
                total_score = float(total_score) if total_score is not None else 0.0
            except (ValueError, TypeError):
                total_score = 0.0
            
            normalized = {
                'id': r.get('id'),
                'title': r.get('title'),
                'description': r.get('description'),
                'content': r.get('content'),
                'tags': tags or [],
                'source': r.get('source'),
                'link': r.get('link'),
                'image': r.get('image'),
                'source_link': r.get('source_link'),
                'source_name': r.get('source_name'),
                'pub_date': pub_date_val,
                'published_at': pub_date_val,
                'feed_name': r.get('feed_name'),
                'region_hint': None,
                'created_at': r.get('created_at'),
                'updated_at': r.get('updated_at'),
                'interest': interest,
                'total_score': total_score
            }
            return normalized
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
            cur.execute("SELECT id, title, summary AS description, content, categories, link AS source, link as link, image, source_link, source_feed AS source_name, published_date AS pub_date, published_date AS published_at, source_feed AS feed_name, status, created_at, updated_at, interest, total_score FROM public.articles WHERE id = %s LIMIT 1", (article_id,))
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
            total_score = r.get('total_score')
            try:
                total_score = float(total_score) if total_score is not None else 0.0
            except (ValueError, TypeError):
                total_score = 0.0
            normalized = {
                'id': r.get('id'),
                'title': r.get('title'),
                'description': r.get('description'),
                'content': r.get('content'),
                'status': r.get('status'),
                'tags': tags or [],
                'source': r.get('source'),
                'link': r.get('link'),
                'image': r.get('image'),
                'source_link': r.get('source_link'),
                'source_name': r.get('source_name'),
                'pub_date': pub_date_val,
                'published_at': pub_date_val,
                'feed_name': r.get('feed_name'),
                'region_hint': None,
                'created_at': r.get('created_at'),
                'updated_at': r.get('updated_at'),
                'interest': interest,
                'total_score': total_score
            }
            return normalized
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def create_topic(self, topic_name: str) -> Optional[int]:
        try:
            self._connect()
        except Exception:
            return None
        
        if not topic_name or not isinstance(topic_name, str):
            return None
        
        topic_name = topic_name.strip()
        if not topic_name:
            return None
            
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            # Create a new topic
            cur.execute(
                'INSERT INTO public.topic (topic_name) VALUES (%s) RETURNING id',
                (topic_name,)
            )
            row = cur.fetchone()
            return int(row[0]) if row else None
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"create_topic failed: {e}")
            return None
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)


    def get_articles_by_topic(self, topic_id: int) -> List[Dict[str, Any]]:
        results = []
        try:
            self._connect()
        except Exception:
            return results
        conn, pooled = self._get_conn()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute("SELECT id, status, total_score FROM public.articles WHERE topic_id = %s", (topic_id,))
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

    def set_articles_status(self, article_ids: List[str], status: str) -> int:
        if not article_ids:
            return 0
        try:
            self._connect()
        except Exception:
            return 0
        conn, pooled = self._get_conn()
        cur = conn.cursor()
        try:
            cur.execute("UPDATE public.articles SET status = %s WHERE id = ANY(%s)", (status, article_ids))
            return cur.rowcount
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
            topic_id = COALESCE(%s, topic_id),
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
            payload.get('topic_id'),
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
            if isinstance(telegram_final, bytes):
                try:
                    telegram_final = telegram_final.decode('utf-8')
                except Exception:
                    telegram_final = str(telegram_final)
            if isinstance(telegram_final, str):
                telegram_final = {'tg_preview': telegram_final}
            telegram_json = json.dumps(telegram_final, ensure_ascii=False) if telegram_final is not None else None
        except Exception:
            telegram_json = None

        # Use DELETE then INSERT to avoid relying on ON CONFLICT or unique constraints.
        delete_sql = 'DELETE FROM public.articles_ru WHERE article_id = %s'
        insert_sql = '''
        INSERT INTO public.articles_ru (article_id, source_url, source_link, source_name, source_published_at, image_url, status, total_score, title_ru, description_ru, content_ru, telegram_final, published_at, updated_at)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now(), now())
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
                forced_skipped = False
                if payload.get('skipped') is True:
                    forced_skipped = True

                total_score = None
                try:
                    total_score = float(payload.get('total_score')) if payload.get('total_score') is not None else None
                except Exception:
                    total_score = None

                status_to_set = None
                from workers.tools.constants import SHORT_NOTE_THRESHOLD
                if forced_skipped:
                    status_to_set = 'SKIPPED'
                elif total_score is not None and total_score < SHORT_NOTE_THRESHOLD:
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
                """
                SELECT * FROM public.articles_ru 
                WHERE status = %s 
                  AND total_score >= %s
                  AND published_at >= NOW() - INTERVAL '24 hours'
                ORDER BY total_score DESC NULLS LAST, id ASC 
                LIMIT %s
                """,
                ('TRANSLATED', min_score, limit)
            )
            rows = cur.fetchall()
            for r in rows:
                row = dict(r)
                # Preserve raw telegram_final for debugging
                row['telegram_final_raw'] = row.get('telegram_final')
                # Use telegram_final value directly as a string (decode bytes). Do not parse dict/JSON here.
                try:
                    tf = row.get('telegram_final')
                    if tf is None:
                        row['telegram_final'] = None
                    else:
                        # If DB returned bytes, decode to str
                        if isinstance(tf, bytes):
                            try:
                                tf = tf.decode('utf-8')
                            except Exception:
                                tf = None
                        # At this point tf may be a dict, a JSON string, or plain string
                        if isinstance(tf, dict):
                            row['telegram_final'] = tf
                        elif isinstance(tf, str):
                            s = tf.strip()
                            if not s:
                                row['telegram_final'] = None
                            else:
                                # Try to parse JSON string that may be double-encoded
                                parsed = None
                                try:
                                    # If string seems to be a JSON object (starts with { or [) parse it
                                    if s[0] in ('{', '['):
                                        parsed = json.loads(s)
                                    else:
                                        # Sometimes the DB contains a quoted JSON string like '"<b>text</b>"'
                                        # Try to unescape once
                                        if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                                            inner = s[1:-1]
                                            try:
                                                parsed = json.loads(inner)
                                            except Exception:
                                                parsed = None
                                except Exception:
                                    parsed = None

                                if isinstance(parsed, dict):
                                    # Clean tg_preview if it contains surrounding quotes or escaped sequences
                                    try:
                                        tp = parsed.get('tg_preview') or parsed.get('text') or parsed.get('preview')
                                        if isinstance(tp, str):
                                            s = tp
                                            # Unescape common sequences
                                            s = s.replace('\\n', '\n')
                                            s = s.replace('\\"', '"')
                                            # If the preview is wrapped in quotes like '"..."' or '\'...\'', strip them
                                            if (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
                                                s = s[1:-1]
                                            s = s.strip()
                                            # Put cleaned value back
                                            parsed['tg_preview'] = s
                                    except Exception:
                                        pass

                                    row['telegram_final'] = parsed

                                    pass
                                elif isinstance(parsed, str) and parsed.strip():
                                    row['telegram_final'] = parsed.strip()
                                else:
                                    row['telegram_final'] = s
                        else:
                            try:
                                row['telegram_final'] = str(tf)
                            except Exception:
                                row['telegram_final'] = None
                except Exception:
                    row['telegram_final'] = None
                results.append(row)
            return results
        finally:
            try:
                cur.close()
            except Exception:
                pass
            self._put_conn(conn, pooled)

    def fetch_articles_with_markdown(self, limit: int = 1000, article_ids: List[str] = None) -> List[Dict[str, Any]]:
        results = []
        try:
            self._connect()
        except Exception:
            return results
        conn, pooled = self._get_conn()
        from psycopg2.extras import RealDictCursor
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            if article_ids:
                cur.execute(
                    "SELECT * FROM public.articles_ru WHERE publish_md IS NOT NULL AND length(publish_md) > 0 AND (article_id = ANY(%s) OR id::text = ANY(%s)) ORDER BY id DESC LIMIT %s",
                    (article_ids, article_ids, limit)
                )
            else:
                cur.execute(
                    "SELECT * FROM public.articles_ru WHERE publish_md IS NOT NULL AND length(publish_md) > 0 ORDER BY id DESC LIMIT %s",
                    (limit,)
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
