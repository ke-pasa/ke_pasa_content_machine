"""
Publisher Worker - handles article publication to Telegram
"""

import sys
import os
import uuid
import json

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict

# Add root directory to path
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

# dotenv not required for Postgres-based workflows; env vars are provided by runtime/CI

from workers.tools.pg_client import get_pg_client
import html
from workers.tools.telegram_helper import send_message, send_photo
from .config import PublisherConfig
from workers.tools import openai_client

class PublisherWorker:
    """Worker for publishing articles to Telegram channels"""
    
    def __init__(self, config: PublisherConfig = None):
        """
        Initialize publisher worker
        
        Args:
            config: Worker configuration
        """
        self.config = config or PublisherConfig.from_env()
        try:
            self.pg = get_pg_client()
        except Exception:
            raise RuntimeError('Postgres client is required for PublisherWorker')
        # Keep legacy db attribute for rare fallback usage
        self.db = None
        self.instance_id = str(uuid.uuid4())[:8]
        # Telegram bot token (we'll use HTTP requests for sync sends)
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN') or None
        if not bot_token:
            print("[publisher] ⚠️ TELEGRAM_BOT_TOKEN not set in environment; publishing will fail until configured")
        # Keep token for helper usage
        self.telegram_token = bot_token
        # Chat id may come from env or from Firebase settings
        self.telegram_chat_id = os.getenv('TELEGRAM_CHAT_ID') or None
        
        print(f"[publisher] Starting worker id={self.instance_id}")
        print(f"[publisher] Max articles per run: {self.config.max_articles_per_run}")
        print(f"[publisher] Publication delay: {self.config.publication_delay}s")

    # Locking disabled: run without acquiring Firestore locks

    def publish_articles(self) -> Dict:
        """
        Publishes ready articles to Telegram
        
        Returns:
            Dictionary with publication results
        """
        try:
            print(f"[publisher] 🚀 Starting publication run (articles_ru)...")

            results = self.publish_oldest_translated_high_score()

            target = int(self.config.max_articles_per_run or 1)
            published_so_far = results.get('published', 0)
            if published_so_far < target:
                remaining = target - published_so_far
                batch_results = self.publish_articles_from_articles_ru(max_to_publish=remaining)
                # Merge results
                results['checked'] = (results.get('checked', 0) or 0) + (batch_results.get('checked', 0) or 0)
                results['published'] = (results.get('published', 0) or 0) + (batch_results.get('published', 0) or 0)
                results['errors'] = (results.get('errors', []) or []) + (batch_results.get('errors', []) or [])

            published = results.get('published', 0)
            total_checked = results.get('checked', 0)
            errors = results.get('errors', [])
            
            print(f"[publisher] ✅ Publication completed")
            print(f"[publisher] Published: {published}/{total_checked}")
            
            if errors:
                print(f"[publisher] ⚠️  Errors occurred: {len(errors)}")
                for error in errors[:3]:  # Show first 3 errors
                    print(f"  • {error}")
            
            return {
                'status': 'success',
                'published': published,
                'total_checked': total_checked,
                'errors': errors,
                'message': f'Published {published} out of {total_checked} articles',
                'instance_id': self.instance_id,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            print(f"[publisher] ❌ Critical error: {e}")
            return {
                'status': 'error',
                'reason': 'processing_error',
                'message': str(e)
            }
        finally:
            pass

    def _get_chat_id(self) -> str:
        """Resolve telegram chat id from env or Firebase settings"""
        try:
            if self.telegram_chat_id:
                return self.telegram_chat_id
            # Try to get from settings via PG client helper
            settings = {}
            try:
                settings = self.pg.get_settings() if hasattr(self.pg, 'get_settings') else {}
            except Exception:
                settings = {}
            return settings.get('telegram_chat_id')
        except Exception:
            return None

    # --- Embedding + dedup helpers ---
    def _compute_embedding(self, text: str):
        """Return embedding vector for text or None on failure/unsupported."""
        try:
            client = openai_client.get_openai_client()
            if client is None or not text:
                return None
            resp = client.embeddings.create(model='text-embedding-3-small', input=[text])
            if getattr(resp, 'data', None) and len(resp.data) > 0:
                return resp.data[0].embedding
        except Exception:
            print(f"[publisher] ⚠️ Embedding compute failed: {text[:60]}")
        return None
    
    def _compute_and_save_embedding_for_doc(self, doc):
        """Compute embedding for candidate article and save it to the Postgres articles_ru row. Returns embedding or None."""
        try:
            data = doc.to_dict() or {}
            final_preview = None
            try:
                final_preview = data.get('telegram_final')
            except Exception:
                final_preview = None

            # Normalize preview text: accept dict or string, extract text, replace literal \n with newlines,
            # and strip surrounding parentheses like '(за январь)' -> 'за январь'.
            def _extract_preview(v):
                txt = None
                if v is None:
                    return None
                if isinstance(v, dict):
                    txt = v.get('tg_preview') or v.get('text') or v.get('preview')
                elif isinstance(v, (bytes, str)):
                    txt = v.decode('utf-8') if isinstance(v, bytes) else v
                else:
                    txt = str(v)
                if not txt:
                    return None
                # Replace escaped newlines with real newlines
                txt = txt.replace('\\n', '\n')
                # Remove parentheses that wrap short phrases like '(за январь)'
                txt = txt.strip()
                if txt.startswith('(') and txt.endswith(')'):
                    inner = txt[1:-1].strip()
                    # only unwrap if no other punctuation at ends
                    if inner and not inner.endswith('.'):
                        txt = inner
                return txt

            final_preview = _extract_preview(final_preview)
            # If telegram_final is None, empty string -> no preview
            if final_preview is None or final_preview.strip() == '':
                print(f"[publisher] ❌ Article {getattr(doc,'id', '?')} has empty telegram_final")
                return None

            emb = self._compute_embedding(final_preview)
            if not emb:
                return None

            try:
                pg = getattr(self, 'pg', None)
                if pg and getattr(doc, 'id', None):
                    try:
                        # Build a structured telegram_final dict to store embedding metadata.
                        existing_tf = (doc.to_dict() or {}).get('telegram_final')
                        tf_dict = {}
                        # If existing_tf is dict, copy it; if it's a string, try to parse JSON or store as tg_preview
                        if isinstance(existing_tf, dict):
                            tf_dict = dict(existing_tf)
                        elif isinstance(existing_tf, (str, bytes)):
                            try:
                                parsed = json.loads(existing_tf) if isinstance(existing_tf, str) else json.loads(existing_tf.decode('utf-8'))
                                if isinstance(parsed, dict):
                                    tf_dict = parsed
                                else:
                                    tf_dict = {'tg_preview': str(existing_tf)}
                            except Exception:
                                tf_dict = {'tg_preview': existing_tf.decode('utf-8') if isinstance(existing_tf, bytes) else str(existing_tf)}
                        else:
                            tf_dict = {}

                        # Save embeddings separately into `telegram_emd` to avoid
                        # modifying the user-visible `telegram_final` preview text.
                        te = {
                            'telegram_emb': emb,
                            'telegram_emb_computed_at': datetime.utcnow().isoformat()
                        }
                        pg.save_generated_article(doc.id, {'telegram_final': tf_dict, 'telegram_emd': te, 'updated_at': datetime.utcnow().isoformat()})
                    except Exception:
                        pass
                return emb
            except Exception:
                return None
        except Exception:
            return None

    def _fetch_recent_published_embeddings(self, days: int):
        """Return list of (doc_id, embedding) for articles published in the last `days` days."""
        try:
            cutoff = datetime.utcnow() - timedelta(days=days)
            out = []
            # Use Postgres to fetch recent published embeddings
            try:
                pg = self.pg
                rows = pg.fetch_translated_for_publish(limit=1000, min_score=0)
                for r in rows:
                    try:
                        data = r
                        emb = None
                        ts = None
                        # Prefer explicit raw value (may contain dict with metadata)
                        tf_raw = data.get('telegram_final_raw') if 'telegram_final_raw' in data else None
                        if tf_raw is not None:
                            try:
                                tf_parsed = tf_raw if isinstance(tf_raw, dict) else (json.loads(tf_raw) if isinstance(tf_raw, str) else None)
                                if isinstance(tf_parsed, dict):
                                    emb = tf_parsed.get('telegram_emb')
                                    ts = tf_parsed.get('telegram_emb_computed_at')
                            except Exception:
                                emb = None
                                ts = None
                        # Fallback: if telegram_final (normalized by PG client) contains embedding
                        if emb is None:
                            tf = data.get('telegram_final')
                            if isinstance(tf, dict):
                                emb = tf.get('telegram_emb')
                                ts = tf.get('telegram_emb_computed_at')
                            else:
                                emb = data.get('telegram_emb')
                                ts = data.get('telegram_emb_computed_at')

                        if not emb:
                            continue
                        include = True
                        if ts:
                            try:
                                t = datetime.fromisoformat(ts) if isinstance(ts, str) else ts
                                include = (t >= cutoff)
                            except Exception:
                                include = True
                        if include:
                            out.append((data.get('article_id') or data.get('id'), emb))
                    except Exception:
                        continue
            except Exception:
                return []
            return out
        except Exception:
            return []

    def _cosine_similarity(self, a, b):
        try:
            import math
            if not a or not b or len(a) != len(b):
                return 0.0
            dot = 0.0
            na = 0.0
            nb = 0.0
            for x, y in zip(a, b):
                dot += (float(x) * float(y))
                na += float(x) * float(x)
                nb += float(y) * float(y)
            if na == 0 or nb == 0:
                return 0.0
            return float(dot) / (math.sqrt(na) * math.sqrt(nb))
        except Exception:
            return 0.0

    def _check_duplicate_and_mark(self, doc, candidate_emb) -> bool:
        """Check candidate embedding against recent published embeddings.

        If a duplicate is detected (similarity >= threshold), mark the article
        with status 'DUBLICATED' and return True. Otherwise return False.
        """
        if not candidate_emb:
            return False
        try:
            cfg_days = int(getattr(self.config, 'duplicate_check_days', 3) or 3)
            threshold = float(getattr(self.config, 'similarity_threshold', 0.8))
            recent = self._fetch_recent_published_embeddings(cfg_days)
            for rid, emb in recent:
                try:
                    sim = self._cosine_similarity(candidate_emb, emb)
                    if sim >= threshold:
                        # Mark as duplicated in Postgres
                        try:
                            pg = getattr(self, 'pg', None)
                            if pg:
                                conn, pooled = pg._get_conn()
                                cur = conn.cursor()
                                try:
                                    cur.execute(
                                        "UPDATE public.articles_ru SET status = %s, duplicate_of = %s, duplicate_similarity = %s, updated_at = %s WHERE article_id = %s",
                                        ('DUBLICATED', rid, float(sim), datetime.utcnow().isoformat(), doc.id)
                                    )
                                    conn.commit()
                                finally:
                                    try:
                                        cur.close()
                                    except Exception:
                                        pass
                                    try:
                                        pg._put_conn(conn, pooled)
                                    except Exception:
                                        pass
                        except Exception as e:
                            print(f"[publisher] ⚠️ Failed to mark duplicate for {doc.id}: {e}")
                        print(f"[publisher] 🔁 Article {doc.id} marked DUBLICATED (sim={sim:.3f}) against {rid}")
                        return True
                except Exception:
                    continue
            return False
        except Exception as e:
            print(f"[publisher] ⚠️ Duplicate check failed for {getattr(doc,'id', '?')}: {e}")
            return False

    def _http_send_message(self, chat_id: str, text: str) -> dict:
        """Send a text message via Telegram (helper). Returns parsed result or raises."""
        return send_message(chat_id, text, token=self.telegram_token)

    def _http_send_photo(self, chat_id: str, photo_url: str, caption: str = None) -> dict:
        """Send a photo by URL using Telegram (helper). Returns parsed result or raises."""
        return send_photo(chat_id, photo_url, caption=caption, token=self.telegram_token)

    # --- Helpers to deduplicate publishing logic ---
    def _build_message(self, data: dict, include_source: bool = True) -> str:
        title = data.get('title_ru') or data.get('title') or ''
        text = data.get('content_ru') or data.get('description_ru') or ''
        source = data.get('source_name') or data.get('source') or data.get('source_link') or data.get('source_url') or ''
        parts = []
        if title:
            parts.append(title)
        if text:
            parts.append(text)
        if include_source and source:
            parts.append(f"Источник: {source}")
        return '\n\n'.join([p for p in parts if p]) or title or 'Новость'

    def _normalize_telegram_preview(self, raw) -> str | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            txt = raw.get('tg_preview') or raw.get('text') or raw.get('preview')
        elif isinstance(raw, (bytes, str)):
            txt = raw.decode('utf-8') if isinstance(raw, bytes) else raw
        else:
            txt = str(raw)
        if not txt:
            return None
        txt = txt.replace('\\n', '\n').strip()
        if txt.startswith('(') and txt.endswith(')'):
            inner = txt[1:-1].strip()
            if inner and not inner.endswith('.'):
                txt = inner
        return txt

    def _prepare_caption(self, message: str, max_caption: int = 1024) -> str:
        if len(message) <= max_caption:
            return message
        # Try to keep the last line (often source) and truncate the rest
        parts = message.split('\n')
        if len(parts) > 1:
            last = parts[-1]
            front = '\n'.join(parts[:-1])
            avail = max_caption - len(last) - 3
            if avail > 0:
                front_trunc = (front[:avail] + '...') if len(front) > avail else front
                return front_trunc + '\n' + last
            else:
                return last[:max_caption-3] + '...'
        return message[:max_caption-3] + '...'

    def _record_post(self, article_id: str, telegram_result, chat_id: str):
        post_record = {
            'article_id': article_id,
            'telegram_message': telegram_result.to_dict() if hasattr(telegram_result, 'to_dict') else None,
            'chat_id': chat_id,
            'created_at': datetime.utcnow().isoformat(),
        }

        pg = getattr(self, 'pg', None)
        if not pg:
            raise RuntimeError('Postgres client not available to record telegram post')

        # Record publication flag in articles_ru (no telegram_posts table used)
        conn, pooled = pg._get_conn()
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE article_id = %s",
                ('PUBLISHED', datetime.utcnow().isoformat(), datetime.utcnow().isoformat(), article_id),
            )
            conn.commit()
        finally:
            try:
                cur.close()
            except Exception:
                pass
            try:
                pg._put_conn(conn, pooled)
            except Exception:
                pass

    def _mark_article_published(self, doc_id: str, sent_message, error_str: str | None = None):
        try:
            update_fields = {
                'status': 'PUBLISHED',
                'published_at': datetime.utcnow().isoformat(),
                'telegram_publish_error': error_str,
            }
            pg = getattr(self, 'pg', None)
            if pg:
                try:
                    conn, pooled = pg._get_conn()
                    cur = conn.cursor()
                    try:
                        cur.execute("UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE article_id = %s",
                                    (update_fields['status'], update_fields['published_at'], update_fields['published_at'], doc_id))
                        try:
                            conn.commit()
                        except Exception:
                            pass
                    finally:
                        try:
                            cur.close()
                        except Exception:
                            pass
                        pg._put_conn(conn, pooled)
                except Exception:
                    print(f"[publisher] ⚠️ Failed to update articles_ru for {doc_id} via Postgres")
        except Exception as e:
            print(f"[publisher] ⚠️ Failed to update article doc {doc_id}: {e}")

    def _send_with_fallback(self, chat_id: str, image: str | None, message: str, data: dict) -> tuple:
        """Try to send a photo with caption, fall back to sending text. Returns (result, error_str)."""
        sent_message = None
        doc_error = None
        if image:
            try:
                caption = message
                max_caption = 1024
                if len(caption) > max_caption:
                    caption = self._prepare_caption(caption, max_caption=max_caption)
                sent_message = self._http_send_photo(chat_id, image, caption)
            except Exception as e:
                print(f"[publisher] ⚠️ Failed to send photo: {e}")
                doc_error = str(e)
                try:
                    sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
                except Exception as e2:
                    print(f"[publisher] ⚠️ Fallback text send failed: {e2}")
                    doc_error = f"{doc_error}; fallback_send_error: {e2}" if doc_error else str(e2)
        else:
            try:
                sent_message = self._http_send_message(chat_id, html.escape(message) if not isinstance(message, str) else message)
            except Exception as e:
                print(f"[publisher] ⚠️ sendMessage failed: {e}")
                doc_error = str(e)
        return sent_message, doc_error

    def publish_articles_from_articles_ru(self, max_to_publish: int | None = None) -> Dict:
        """Publishes up to `max_to_publish` (or config.max_articles_per_run) articles from `articles_ru` collection.

        When duplicates are encountered, the method continues to try other candidates
        until the desired number of publications is reached or the candidate pool is exhausted.
        """
        if max_to_publish is None:
            max_to_publish = self.config.max_articles_per_run

        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_token:
            err = 'Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        chat_id = self._get_chat_id()
        if not chat_id:
            err = 'Telegram chat id not configured (TELEGRAM_CHAT_ID missing and not in Firebase settings)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        try:
            # Prefer Postgres for articles_ru queries when available
            try:
                from workers.tools.pg_client import get_pg_client
                pg = get_pg_client()
            except Exception:
                pg = None

            pool_limit = max(self.config.max_articles_per_run * 10, 50)

            # Always use Postgres to fetch candidate translated articles
            rows = pg.fetch_translated_for_publish(limit=pool_limit, min_score=85)
            docs = []
            for r in rows:
                class RowWrapper:
                    def __init__(self, data):
                        self._d = data
                        self.id = data.get('article_id') or data.get('id')
                    def to_dict(self):
                        return self._d
                docs.append(RowWrapper(r))

            filtered = [d for d in docs if (d.to_dict() or {}).get('status') == 'TRANSLATED']

            def _created_key(doc):
                try:
                    v = (doc.to_dict() or {}).get('created_at')
                    if v is None:
                        return ''
                    if hasattr(v, 'isoformat'):
                        return v.isoformat()
                    if hasattr(v, 'seconds'):
                        return str(v.seconds)
                    return str(v)
                except Exception:
                    return ''

            # Sort candidates by creation and keep an expanded candidate list
            docs = sorted(filtered, key=_created_key)[: pool_limit]
        except Exception as e:
            err = f'Firestore query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            # stop if we've already published the requested maximum in this run
            if results['published'] >= max_to_publish:
                break
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                image = data.get('image_url') or data.get('image') or None

                # Use raw data['telegram_final'] as the message source (no fallbacks)
                try:
                    raw_preview = data.get('telegram_final')
                except Exception:
                    raw_preview = None
                final_preview = self._normalize_telegram_preview(raw_preview)
                if final_preview is None or final_preview.strip() == '':
                    print(f"[publisher] ❌ Article {article_id} has empty telegram_final")
                    results['errors'].append(f"empty_telegram_final:{article_id}")
                    continue
                # Before sending, compute embedding and save it to the article document
                try:
                    emb = self._compute_and_save_embedding_for_doc(doc)
                    # If embedding computed, perform deduplication check against recent published
                    try:
                        if emb and self._check_duplicate_and_mark(doc, emb):
                            # Already marked as DUBLICATED in the DB; skip sending and try next candidate
                            continue
                    except Exception:
                        pass
                except Exception:
                    pass

                message = final_preview
                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(doc.id, sent_message, doc_error)

                if sent_message:
                    results['published'] += 1
                    print(f"[publisher] ✅ Published article {article_id} to Telegram")
                    # If we've reached the requested maximum, stop attempting more
                    if results['published'] >= max_to_publish:
                        break
                else:
                    print(f"[publisher] ⚠️ Article {article_id} marked published but Telegram send failed. See 'telegram_publish_error' in doc.")
            except Exception as e:
                err = f"Error publishing doc {getattr(doc, 'id', '?')}: {e}"
                print(f"[publisher] ❌ {err}")
                results['errors'].append(err)

        return results

    def publish_oldest_translated_high_score(self) -> Dict:
        """Find the oldest article in `articles_ru` with status == 'TRANSLATED' and total_score > 80

        Publishes a single article (image first, then text+source) and marks it published.
        """
        results = {'published': 0, 'checked': 0, 'errors': []}

        if not self.telegram_token:
            err = 'Telegram bot not configured (TELEGRAM_BOT_TOKEN missing)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        chat_id = self._get_chat_id()
        if not chat_id:
            err = 'Telegram chat id not configured (TELEGRAM_CHAT_ID missing and not in Firebase settings)'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        try:
            pool_limit = 200
            pg = getattr(self, 'pg', None)
            if not pg:
                raise RuntimeError('Postgres client not available')
            rows = pg.fetch_translated_for_publish(limit=pool_limit, min_score=80)
            docs = []
            for r in rows:
                class RowWrapper:
                    def __init__(self, data):
                        self._d = data
                        self.id = data.get('article_id') or data.get('id')
                    def to_dict(self):
                        return self._d
                docs.append(RowWrapper(r))

            candidates = [d for d in docs if (d.to_dict() or {}).get('status') == 'TRANSLATED']
            candidates = sorted(candidates, key=lambda d: ((d.to_dict() or {}).get('created_at') and str((d.to_dict() or {}).get('created_at'))) or '')
            docs = candidates
        except Exception as e:
            err = f'PG query error: {e}'
            print(f"[publisher] ❌ {err}")
            results['errors'].append(err)
            return results

        results['checked'] = len(docs)

        for doc in docs:
            # stop if we've published one (this method intends to publish a single top candidate)
            if results['published'] >= 1:
                break
            try:
                data = doc.to_dict() or {}
                article_id = data.get('article_id') or doc.id
                image = data.get('image_url') or data.get('image') or None
                # Use raw data['telegram_final'] as the message source (no fallbacks)
                try:
                    raw_preview = data.get('telegram_final')
                except Exception:
                    raw_preview = None
                final_preview = self._normalize_telegram_preview(raw_preview)
                if final_preview is None or final_preview.strip() == '':
                    print(f"[publisher] ❌ Article {article_id} has empty telegram_final")
                    results['errors'].append(f"empty_telegram_final:{article_id}")
                    continue
                # compute embedding and save it to the article document
                try:
                    emb = self._compute_and_save_embedding_for_doc(doc)
                    try:
                        if emb and self._check_duplicate_and_mark(doc, emb):
                            # marked as duplicate, try next candidate
                            continue
                    except Exception:
                        pass
                except Exception:
                    pass

                message = final_preview
                sent_message, doc_error = self._send_with_fallback(chat_id, image, message, data)

                self._record_post(article_id, sent_message, chat_id)
                self._mark_article_published(doc.id, sent_message, doc_error)

                if sent_message:
                    results['published'] += 1
                    print(f"[publisher] ✅ Published article {article_id} to Telegram (TRANSLATED/high-score)")
                else:
                    print(f"[publisher] ⚠️ Article {article_id} marked published but Telegram send failed. See 'telegram_publish_error' in doc.")
            except Exception as e:
                err = f"Error publishing doc {getattr(doc, 'id', '?')}: {e}"
                print(f"[publisher] ❌ {err}")
                results['errors'].append(err)

        return results


def main():
    """Entry point for worker execution"""
    print("=" * 60)
    print("📢 Publisher Worker - Telegram Publication Handler")
    print("=" * 60)
    
    try:
        config = PublisherConfig.from_env()

        # Use configuration from environment (no CLI or new env overrides)
        worker = PublisherWorker(config)
        result = worker.publish_articles()
        

        print("\n" + "=" * 60)
        print("📊 RESULTS")
        print("=" * 60)
        print(f"Status: {result['status']}")
        print(f"Published: {result.get('published', 0)}")
        print(f"Total checked: {result.get('total_checked', 0)}")
        
        if result.get('errors'):
            print(f"\nErrors ({len(result['errors'])}):")
            for error in result['errors'][:5]:
                print(f"  • {error}")
        
        exit_code = 0 if result['status'] == 'success' else 1
        sys.exit(exit_code)
        
    except KeyboardInterrupt:
        print("\n⚠️  Interrupted by user")
        sys.exit(130)
    except Exception as e:
        print(f"\n❌ Critical error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
