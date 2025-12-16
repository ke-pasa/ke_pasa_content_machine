import uuid
import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import importlib

from .news_filter_prompt import get_news_filter_prompt
from workers.tools.openai_client import parse_json_from_text
from workers.tools.constants import MIN_ARTICLE_SCORE, SHORT_NOTE_THRESHOLD, PUBLISH_THRESHOLD
import os
import json as _json


def _get_openai_client():
    try:
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'get_openai_client'):
            return worker_mod.get_openai_client()
    except Exception:
        pass
    from workers.tools.openai_client import get_openai_client as _go
    return _go()


def _chat_completion(client, model, messages, max_tokens=600, temperature=0):
    """Wrapper that returns (text, usage_dict) tuple."""
    try:
        # Call responses API directly to get usage info
        req_kwargs = {
            'model': model,
            'input': messages,  # Note: Responses API uses 'input', not 'messages'
            'max_output_tokens': max_tokens,
            'stream': False,
        }
        
        # Only GPT-4o models support temperature
        if model.startswith('gpt-4') or model.startswith('gpt-3'):
            req_kwargs['temperature'] = temperature
        
        resp = client.responses.create(**req_kwargs)
        
        # Extract text
        text = getattr(resp, 'output_text', None)
        if text and isinstance(text, str):
            text = text.strip()
        
        # Extract usage
        usage_dict = None
        try:
            usage = getattr(resp, 'usage', None)
            if usage:
                prompt_tokens = getattr(usage, 'prompt_tokens', 0) or getattr(usage, 'input_tokens', 0)
                completion_tokens = getattr(usage, 'completion_tokens', 0) or getattr(usage, 'output_tokens', 0)
                total_tokens = getattr(usage, 'total_tokens', 0) or (prompt_tokens + completion_tokens)
                usage_dict = {
                    'prompt_tokens': prompt_tokens,
                    'completion_tokens': completion_tokens,
                    'total_tokens': total_tokens
                }
        except Exception:
            pass
        
        return (text, usage_dict)
    except Exception:
        # Fallback to standard chat_completion
        from workers.tools.openai_client import chat_completion as _cc
        text = _cc(client, model, messages, max_tokens=max_tokens, temperature=temperature)
        return (text, None)


def _parse_json_from_text(text: str):
    try:
        worker_mod = importlib.import_module('workers.categorization.worker')
        if hasattr(worker_mod, 'parse_json_from_text'):
            return worker_mod.parse_json_from_text(text)
    except Exception:
        pass
    return parse_json_from_text(text)


from .config import CategorizationConfig


class CategorizationWorker:
    """Categorization worker with paginated reads from Postgres via `workers.tools.pg_client`.

    This worker was migrated away from Firestore and now uses the `PGClient` adapter
    exposed by `workers.tools.pg_client.get_pg_client()`. The code still defensively
    handles Firestore-like objects for backward compatibility, but reads/writes use Postgres.
    """

    def __init__(self, config: CategorizationConfig = None, batch_size: int = None):
        self.config = config or CategorizationConfig.from_env()
        self.logger = logging.getLogger('workers.categorization')

        if batch_size is not None:
            try:
                self.config.batch_size = int(batch_size)
            except Exception:
                self.config.batch_size = 10
        else:
            self.config.batch_size = int(getattr(self.config, 'batch_size', 10) or 10)

        from workers.tools.pg_client import get_pg_client
        self.pg = get_pg_client()
        self.instance_id = str(uuid.uuid4())[:8]
        self.embedding_model =  'text-embedding-3-small'
        self.similarity_threshold = 0.65


    def _deduplicate_by_topic(self, topic_id: int):
        """
        Deduplicate articles within a given topic.
        1. If any article in the topic is 'TRANSLATED', mark all others (non-TRANSLATED) as 'DEDUPLICATED'.
        2. If none are 'TRANSLATED', keep the one with the highest total_score and mark others as 'DEDUPLICATED'.
        """
        if not topic_id:
            return

        try:
            t_articles = self.pg.get_articles_by_topic(topic_id)
            if len(t_articles) <= 1:
                return

            has_translated = any(a.get('status') == 'TRANSLATED' for a in t_articles)
            dedup_ids = []

            if has_translated:
                # If at least one is TRANSLATED, mark all others (non-TRANSLATED) as DEDUPLICATED
                dedup_ids = [str(a['id']) for a in t_articles if a.get('status') != 'TRANSLATED']
            else:
                # No TRANSLATED. Find max total_score.
                def get_score(x):
                    try:
                        return float(x.get('total_score') or 0)
                    except Exception:
                        return 0.0
                
                # Sort descending by score. First one stays, others become DEDUPLICATED.
                sorted_arts = sorted(t_articles, key=get_score, reverse=True)

                if len(sorted_arts) > 1:
                    dedup_ids = [str(a['id']) for a in sorted_arts[1:]]

            if dedup_ids:
                updated_count = self.pg.set_articles_status(dedup_ids, 'DEDUPLICATED')
                self.logger.info(f"Deduplicated {updated_count} articles in topic {topic_id}: {dedup_ids}")

        except Exception as ex:
            self.logger.warning(f"Error in deduplication logic for topic {topic_id}: {ex}")

    def _extract_embedding(self, client, text: str) -> tuple:
        """Extract embedding from text using OpenAI API.
        
        Returns:
            tuple: (embedding_vector, error_message)
        """
        if not client or not text:
            return None, "No client or text provided"
        # Try a couple of times on transient failures and be defensive about response shape
        max_attempts = 2
        for attempt in range(max_attempts):
            try:
                resp = client.embeddings.create(model=self.embedding_model, input=[text])
                self._log_embedding_usage(resp)

                # Normalize data extraction for both dict-like and object-like responses
                if isinstance(resp, dict):
                    data = resp.get('data')
                else:
                    data = getattr(resp, 'data', None)

                if data and isinstance(data, list) and len(data) > 0:
                    first = data[0]
                    if isinstance(first, dict):
                        emb = first.get('embedding') or first.get('vector')
                    else:
                        emb = getattr(first, 'embedding', None) or getattr(first, 'vector', None)

                    if emb:
                        return emb, None

                    resp_summary = None
                    try:
                        if isinstance(resp, dict):
                            resp_summary = {k: (v if k != 'data' else f'<data len={len(data)}>') for k, v in resp.items()}
                        else:
                            resp_summary = str(resp)
                    except Exception:
                        resp_summary = '<unserializable response>'

                    err_msg = f"Missing embedding field in response data (model={self.embedding_model}) - {resp_summary}"
                    # If final attempt, return error
                    if attempt == max_attempts - 1:
                        return None, err_msg
                    # otherwise retry
                else:
                    # No data array present; try to surface any error info
                    err_info = None
                    if isinstance(resp, dict):
                        err_info = resp.get('error') or resp.get('message')
                    else:
                        err_info = getattr(resp, 'error', None)

                    resp_str = None
                    try:
                        resp_str = str(resp)[:600]
                    except Exception:
                        resp_str = '<unserializable response>'

                    err_msg = f"No embedding data in response (model={self.embedding_model})"
                    if err_info:
                        err_msg += f": {err_info}"
                    else:
                        err_msg += f" - resp_summary={resp_str}"

                    if attempt == max_attempts - 1:
                        return None, err_msg

                # short backoff before retrying
                time.sleep(0.5)
            except Exception as e:
                if attempt == max_attempts - 1:
                    return None, str(e)
                time.sleep(0.5)

    def _log_embedding_usage(self, resp):
        """Log embedding API usage if available."""
        try:
            usage = getattr(resp, 'usage', None) or (resp.get('usage') if isinstance(resp, dict) else None)
            if usage:
                prompt_tokens = usage.get('prompt_tokens') or usage.get('input_tokens') or 0
                total_tokens = usage.get('total_tokens') or usage.get('total', prompt_tokens)
                self.logger.info(f'OpenAI embeddings usage: prompt={prompt_tokens} total={total_tokens}')
        except Exception:
            pass

    def _find_similar_topic(self, embedding: list) -> tuple:
        """Find most similar topic using pgvector.
        
        Returns:
            tuple: (topic_id, similarity, error_message)
        """
        if not embedding:
            return None, 0.0, "No embedding provided"
        
        try:
            conn, pooled = self.pg._get_conn()
            cur = conn.cursor()
            try:
                emb_text = _json.dumps(embedding, ensure_ascii=False)
                cur.execute(
                    """
                    SELECT t.id, 1 - (t.emb <=> %s::vector) as similarity
                    FROM public.topic t
                    WHERE t.emb IS NOT NULL
                    ORDER BY t.emb <=> %s::vector
                    LIMIT 1
                    """,
                    (emb_text, emb_text)
                )
                row = cur.fetchone()
                if row and row[0] is not None:
                    topic_id = int(row[0])
                    similarity = float(row[1]) if row[1] is not None else 0.0
                    try:
                        self.logger.info(
                            "Embedding similarity: topic_id=%s similarity=%.4f" % (topic_id, similarity)
                        )
                    except Exception:
                        pass
                    return topic_id, similarity, None
                try:
                    self.logger.info("Embedding similarity: no topic match found")
                except Exception:
                    pass
                return None, 0.0, None
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self.pg._put_conn(conn, pooled)
        except Exception as e:
            return None, 0.0, str(e)

    def _store_topic_embedding(self, topic_id: int, embedding: list) -> bool:
        """Store embedding for a topic in the database.
        
        Returns:
            bool: True if successful, False otherwise
        """
        if not topic_id or not embedding:
            return False
        
        try:
            conn, pooled = self.pg._get_conn()
            cur = conn.cursor()
            try:
                emb_text = _json.dumps(embedding, ensure_ascii=False)
                # Try vector type first
                try:
                    cur.execute("UPDATE public.topic SET emb = %s::vector WHERE id = %s", (emb_text, topic_id))
                    conn.commit()
                    preview = (emb_text[:200] + '...') if len(emb_text) > 200 else emb_text
                    self.logger.info(f"Stored topic embedding for topic {topic_id} as vector (preview={preview})")
                    return True
                except Exception as ve:
                    # Vector cast failed; log the reason and fallback to jsonb
                    self.logger.debug(f"Vector update failed for topic {topic_id}: {ve}")
                    try:
                        cur.execute("ALTER TABLE public.topic ADD COLUMN IF NOT EXISTS emb jsonb")
                    except Exception:
                        pass
                    try:
                        cur.execute("UPDATE public.topic SET emb = %s::jsonb WHERE id = %s", (emb_text, topic_id))
                        conn.commit()
                        preview = (emb_text[:200] + '...') if len(emb_text) > 200 else emb_text
                        self.logger.info(f"Stored topic embedding for topic {topic_id} as jsonb (preview={preview})")
                        return True
                    except Exception as je:
                        # Fallback update failed too
                        self.logger.warning(f"JSONB update failed for topic {topic_id}: {je}")
                        conn.rollback()
                        return False
            finally:
                try:
                    cur.close()
                except Exception:
                    pass
                self.pg._put_conn(conn, pooled)
        except Exception as e:
            self.logger.warning(f"Failed to store embedding for topic {topic_id}: {e}")
            return False

    def _match_or_create_topic(self, client, title: str, doc_id: str, score: float, description: str = '', lock=None, recent_topics=None) -> int:
        """Match article to existing topic or create new one.
        
        Returns:
            int: topic_id or None
        """
        self.logger.debug(f"_match_or_create_topic start: doc_id={doc_id} title_present={bool(title)} score={score}")
        if not title:
            if score >= MIN_ARTICLE_SCORE:
                self.logger.warning(f"Skipping topic creation for {doc_id}: Missing title")
            return None
        
        # Extract embedding for title + description (prefer richer context)
        combo_text = title or ''
        try:
            if description:
                combo_text = f"{title}\n\n{description}"
        except Exception:
            combo_text = title or ''

        embedding, err = self._extract_embedding(client, combo_text)
        if err:
            self.logger.warning(f"Error computing embedding for topic match: {err}")
            return None
        
        if not embedding:
            self.logger.warning(f"Embedding empty for doc {doc_id}; skipping topic match")
            return None

        try:
            emb_len = len(embedding) if hasattr(embedding, '__len__') else 'unknown'
            self.logger.info(
                f"Embedding ready for doc {doc_id}: topic_score={score:.2f} vector_len={emb_len}"
            )
        except Exception:
            pass
        
        # Search for similar topic
        topic_id, similarity, err = self._find_similar_topic(embedding)
        if err:
            self.logger.warning(f"Error finding similar topic: {err}")
        
        # Use existing topic if similarity is high enough
        if topic_id and similarity >= self.similarity_threshold:
            self.logger.info(
                f"Topic decision for doc {doc_id}: reuse topic {topic_id} (sim={similarity:.3f} >= threshold={self.similarity_threshold:.3f})"
            )
            return topic_id
        
        if topic_id:
            self.logger.info(
                f"Topic decision for doc {doc_id}: candidate {topic_id} below threshold (sim={similarity:.3f} < threshold={self.similarity_threshold:.3f}), creating new"
            )
        
        # Create new topic
        self.logger.debug(f"Creating new topic for doc {doc_id} title='{title}'")
        new_topic_id = self.pg.create_topic(title)
        if not new_topic_id:
            self.logger.warning(f"Failed to create topic for article {doc_id} (title='{title}')")
            return None

        self.logger.info(f"Created topic {new_topic_id} for article {doc_id} (score={score})")

        try:
            stored = self._store_topic_embedding(new_topic_id, embedding)
            if not stored:
                self.logger.warning(f"Embedding not stored for topic {new_topic_id}")
            else:
                try:
                    self.logger.info(f"Topic decision for doc {doc_id}: embedding persisted for topic {new_topic_id}")
                except Exception:
                    pass
        except Exception as e:
            self.logger.warning(f"Error storing embedding for topic {new_topic_id}: {e}")

        return new_topic_id

    def _call_llm_categorization(self, client, model: str, doc_id: str, title: str, description: str, tags: list, content: str, source: str, pub_date: str, feed_name: str, region_hint: str) -> dict:
        """Call LLM for article categorization.
        
        Returns:
            dict: interest_result with LLM response or error info
        """
        system_prompt, user_prompt = get_news_filter_prompt(
            title, description, tags, content, source, pub_date, 
            feed_name=feed_name, region_hint=region_hint
        )

        if not client:
            self.logger.warning(f'No LLM client available for article {doc_id}')
            return None

        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            result = _chat_completion(client, model, messages, max_tokens=1200, temperature=0)

            # Handle tuple return (text, usage) or just text
            if isinstance(result, tuple):
                text, usage = result
            else:
                text, usage = result, None

            # Save raw model response for debugging (both text and structured if available)
            try:
                raw_dir = Path(__file__).parent.parent.parent / 'logs' / 'openai_raw'
                raw_dir.mkdir(parents=True, exist_ok=True)
                raw_file = raw_dir / f"{doc_id or 'unknown'}_{int(time.time())}.json"
                raw_payload = {
                    'doc_id': doc_id,
                    'model': model,
                    'messages': messages,
                    'raw_text': text,
                    '_usage': usage,
                    'raw_result_repr': repr(result)
                }
                with raw_file.open('w', encoding='utf-8') as rf:
                    rf.write(json.dumps(raw_payload, ensure_ascii=False, indent=2))
                try:
                    self.logger.info(f'Saved raw LLM response to {raw_file}')
                except Exception:
                    pass
            except Exception:
                pass

            parsed = _parse_json_from_text(text or '')

            if parsed:
                # Add usage info if available
                if usage and isinstance(parsed, dict):
                    parsed['_usage'] = usage
                return parsed
            
            # Preserve raw model output for debugging
            self.logger.warning(f'LLM returned invalid JSON for article {doc_id}; saving raw output')
            print('\n--- RAW MODEL OUTPUT START ---')
            print(text)
            print('--- RAW MODEL OUTPUT END ---\n')
            return {'raw_model_output': text}
            
        except Exception:
            self.logger.exception(f'Error while calling LLM for article {doc_id}')
            return None

    def _extract_interest_fields(self, interest_result: dict) -> dict:
        """Extract standard fields from LLM interest result."""
        if not isinstance(interest_result, dict):
            return {}
        # If the model returned a `scores` object, compute total_score from its components.
        total = None
        try:
            # Prefer explicit total fields if present
            total = interest_result.get('total_score') or interest_result.get('total')
            if total is None and isinstance(interest_result.get('scores'), dict):
                s = interest_result.get('scores') or {}
                # Sum known score components defensively
                comps = [
                    s.get('region_score'),
                    s.get('source_score'),
                    s.get('editorial_value'),
                    s.get('expat_relevance_bonus'),
                    s.get('urgency_score')
                ]
                total_sum = 0
                any_numeric = False
                for v in comps:
                    try:
                        if v is None:
                            continue
                        nv = float(v)
                        total_sum += nv
                        any_numeric = True
                    except Exception:
                        continue
                if any_numeric:
                    total = total_sum
        except Exception:
            total = None

        return {
            'total_score': total,
            'rating': interest_result.get('rating') or interest_result.get('recommendation'),
            'short_note': interest_result.get('short_analysis') or interest_result.get('short_note'),
            'category': interest_result.get('category'),
            'comment': interest_result.get('comment') or interest_result.get('commentary'),
            'newsletter': interest_result.get('newsletter'),
        }

    def categorize_new_articles(self) -> Dict:
        results = {'processed': 0, 'errors': []}
        table_data = []  # List to collect table rows

        score_buckets = {
            f'>={PUBLISH_THRESHOLD}': 0,
            f'{SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}': 0,
            f'<{SHORT_NOTE_THRESHOLD}': 0
        }

        try:
            requested_total = int(self.config.batch_size)
            if requested_total <= 0:
                return {'status': 'success', 'processed': 0}

            chunk_size = 30
            processed_total = 0
            last_snapshot = None

            while processed_total < requested_total:
                limit_for_query = min(chunk_size, requested_total - processed_total)

                try:
                    # last_snapshot is a cursor dict with 'created_at' and 'id'
                    docs = self.pg.fetch_articles_new(limit=limit_for_query, last_cursor=last_snapshot, status='NEW', hours_ago=24)
                except Exception as e:
                    return {'status': 'error', 'message': str(e)}

                if not docs:
                    break

                model = 'gpt-4o-mini'
                client = _get_openai_client()

                chunk_results = {'processed': 0, 'errors': []}

                def _process_doc(doc):
                    try:
                        doc_id = doc.get('id')
                        data = doc

                        title = data.get('title', '')
                        description = data.get('description', '') or ''
                        content = (data.get('content', '') or '')[:500]
                        tags = data.get('tags', []) or data.get('categories', []) or []
                        source = data.get('source', '') or data.get('link', '') or ''
                        pub_date = data.get('pub_date', '') or ''

                        feed_name = data.get('feed_name', '') or data.get('feed', '') or ''
                        region_hint = data.get('region_hint', '') or ''
                        
                        record_start = time.perf_counter()
                        
                        # Call LLM for categorization
                        interest_result = self._call_llm_categorization(
                            client, model, doc_id, title, description, tags, 
                            content, source, pub_date, feed_name, region_hint
                        )
                        
                        record_end = time.perf_counter()
                        processing_time_ms = int((record_end - record_start) * 1000)
                        
                        # Extract fields from LLM response
                        fields = self._extract_interest_fields(interest_result)
                        total_score = fields.get('total_score')
                        rating = fields.get('rating')
                        short_note = fields.get('short_note')
                        category_field = fields.get('category')
                        comment_field = fields.get('comment')
                        newsletter_field = fields.get('newsletter')

                        status_field = 'CATEGORIZED'
                        score_val = float(total_score) if total_score is not None else 0.0
                        if score_val < MIN_ARTICLE_SCORE:
                            try:
                                self.logger.info(
                                    f"Article {doc_id} has total_score={score_val:.2f} < threshold {MIN_ARTICLE_SCORE}; topic assignment disabled"
                                )
                            except Exception:
                                pass
                            status_field = 'SKIPPED'
                        else:
                            try:
                                self.logger.info(
                                    f"Article {doc_id} has total_score={score_val:.2f} >= threshold {MIN_ARTICLE_SCORE}; attempting topic match"
                                )
                            except Exception:
                                pass

                        # Topic assignment via embedding similarity
                        topic_id_val = None
                        if score_val >= MIN_ARTICLE_SCORE:
                            try:
                                    topic_id_val = self._match_or_create_topic(client, title, doc_id, score_val, description=description)
                            except Exception as e:
                                self.logger.exception(f"Error creating topic for {doc_id}: {e}")

                        update_payload = {
                            'interest': interest_result,
                            'status': status_field,
                            'total_score': total_score,
                            'rating': rating,
                            'short_note': short_note,
                            'category': category_field,
                            'comment': comment_field,
                            'newsletter': newsletter_field,
                            'topic_id': topic_id_val,
                            'categorized_at': datetime.now(timezone.utc).isoformat(),
                            'updated_at': datetime.now(timezone.utc).isoformat(),
                        }

                        try:
                            ok = self.pg.save_article_categorization(doc_id, update_payload)
                            if ok:
                                save_status = 'ok'
                                result_line = f"[categorization] ✅ Article {doc_id} categorized"
                                chunk_results['processed'] += 1
                            else:
                                err = f"Postgres save returned no rows updated for {doc_id}"
                                save_status = {'error': err}
                                result_line = f"[categorization] ❌ {err}"
                                chunk_results['errors'].append(err)
                        except Exception as e:
                            err = f"Save error for {doc_id}: {e}"
                            save_status = {'error': str(e)}
                            result_line = f"[categorization] ❌ {err}"
                            chunk_results['errors'].append(err)

                        # Logic to deduplicate by topic
                        if topic_id_val:
                            self._deduplicate_by_topic(topic_id_val)

                        # logging
                        try:
                            log_dir = Path(__file__).parent.parent.parent / 'logs'
                            log_dir.mkdir(parents=True, exist_ok=True)
                            log_file = log_dir / 'categorization.jsonl'
                            log_entry = {
                                'doc_id': doc_id,
                                'input': {
                                    'title': title,
                                    'description': description,
                                    'tags': tags,
                                    'source': source,
                                    'pub_date': pub_date
                                },
                                'interest': interest_result,
                                'save_status': save_status,
                                'processing_time_ms': processing_time_ms,
                                'model': model,
                                'timestamp': datetime.now(timezone.utc).isoformat()
                            }
                            with log_file.open('a', encoding='utf-8') as f:
                                f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')
                            try:
                                # Emit a concise machine-readable summary to the logger (console)
                                summary = {
                                    'doc_id': doc_id,
                                    'total_score': total_score,
                                    'rating': rating,
                                    'short_note': short_note,
                                    'processing_time_ms': processing_time_ms,
                                    'save_status': save_status,
                                    'timestamp': datetime.now(timezone.utc).isoformat()
                                }
                                try:
                                    _log = logging.getLogger('workers.categorization')
                                    _log.info(json.dumps(summary, ensure_ascii=False))
                                except Exception:
                                    pass
                            except Exception:
                                pass
                        except Exception:
                            pass

                        # Update per-run score buckets (thread-safe)
                        try:
                            ts = None
                            if isinstance(interest_result, dict):
                                ts = interest_result.get('total_score') or interest_result.get('total')
                            # Fall back to update_payload total_score
                            if ts is None:
                                ts = update_payload.get('total_score')

                            if ts is not None:
                                try:
                                    val = float(ts)
                                except Exception:
                                    val = None
                                if val is not None:
                                    if val >= PUBLISH_THRESHOLD:
                                        score_buckets[f'>={PUBLISH_THRESHOLD}'] += 1
                                    elif val >= SHORT_NOTE_THRESHOLD:
                                        score_buckets[f'{SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}'] += 1
                                    else:
                                        score_buckets[f'<{SHORT_NOTE_THRESHOLD}'] += 1

                        except Exception:
                            pass

                        # Collect data for summary table
                        try:
                            # Check if this document was deduplicated
                            is_duplicated = False
                            if topic_id_val:
                                try:
                                    t_articles = self.pg.get_articles_by_topic(topic_id_val)
                                    for art in t_articles:
                                        if str(art.get('id')) == str(doc_id) and art.get('status') == 'DEDUPLICATED':
                                            is_duplicated = True
                                            break
                                except Exception:
                                    pass
                            
                            # Get token count from interest_result
                            tokens = None
                            if isinstance(interest_result, dict):
                                # Check _usage first (added by our code), then fallback to other fields
                                usage_dict = interest_result.get('_usage')
                                if usage_dict and isinstance(usage_dict, dict):
                                    tokens = usage_dict.get('total_tokens')
                                if tokens is None:
                                    tokens = interest_result.get('usage', {}).get('total_tokens') or interest_result.get('total_tokens')
                            
                            table_data.append({
                                'score': score_val,
                                'link': source,
                                'doc_id': doc_id,
                                'tokens': tokens,
                                'topic_id': topic_id_val,
                                'is_duplicated': is_duplicated
                            })
                        except Exception:
                            pass

                    except Exception as e:
                        err = f"Processing error for doc {getattr(doc, 'id', '?')}: {e}"
                        chunk_results['errors'].append(err)

                # Execute sequentially (single-threaded)
                for d in docs:
                    _process_doc(d)

                # aggregate chunk results
                results['processed'] += chunk_results['processed']
                results['errors'].extend(chunk_results['errors'])
                processed_total += chunk_results['processed']

                # If we've processed enough, break early
                if processed_total >= requested_total:
                    break

                try:
                    last_row = docs[-1]
                    # pg.fetch_articles_new returns normalized rows with created_at and id
                    if isinstance(last_row, dict):
                        last_snapshot = {'created_at': last_row.get('created_at'), 'id': last_row.get('id')}
                    else:
                        last_snapshot = last_row
                except Exception:
                    last_snapshot = None

                if len(docs) < limit_for_query:
                    break

            # After successful processing, print detailed score buckets summary
            try:
                import datetime as dt_mod
                print(f'\n📊 Detailed scoring summary for this run ({datetime.now().strftime("%Y-%m-%d %H:%M:%S")}):')
                print(f"   Total processed: {results.get('processed', 0)}")
                print(f"   >={PUBLISH_THRESHOLD}: {score_buckets.get(f'>={PUBLISH_THRESHOLD}', 0)}")
                print(f"   {SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}: {score_buckets.get(f'{SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}', 0)}")
                print(f"   <{SHORT_NOTE_THRESHOLD}: {score_buckets.get(f'<{SHORT_NOTE_THRESHOLD}', 0)}")
            except Exception:
                pass

            # Print detailed results table
            try:
                if table_data:
                    print("\n" + "="*120)
                    print(f"{'Score':<8} {'Link':<40} {'Doc ID':<35} {'Tokens':<8} {'Topic':<8} {'Duplicated':<10}")
                    print("="*120)
                    for row in table_data:
                        score = f"{row['score']:.1f}" if row['score'] is not None else "N/A"
                        link = (row['link'][:37] + "...") if row['link'] and len(row['link']) > 40 else (row['link'] or "N/A")
                        doc_id = row['doc_id'][:32] + "..." if row['doc_id'] and len(row['doc_id']) > 35 else (row['doc_id'] or "N/A")
                        tokens = str(row['tokens']) if row['tokens'] is not None else "N/A"
                        topic_id = str(row['topic_id']) if row['topic_id'] is not None else "N/A"
                        is_dup = "Yes" if row['is_duplicated'] else "No"
                        print(f"{score:<8} {link:<40} {doc_id:<35} {tokens:<8} {topic_id:<8} {is_dup:<10}")
                    print("="*120 + "\n")
            except Exception as ex:
                self.logger.warning(f"Error printing table: {ex}")

            return {'status': 'success', **results}

        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    def get_statistics(self) -> Dict:
        try:
            conn = self.pg._conn
            cur = conn.cursor()

            def column_exists(col_name: str) -> bool:
                cur.execute("SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_schema='public' AND table_name='articles' AND column_name=%s)", (col_name,))
                return bool(cur.fetchone()[0])

            from workers.tools.constants import SHORT_NOTE_THRESHOLD, PUBLISH_THRESHOLD
            stats = {
                'total': 0,
                'urgent': 0,
                'by_priority': {'high': 0, 'medium': 0, 'low': 0},
                'by_category': {},
                'score_buckets': {f'>={PUBLISH_THRESHOLD}': 0, f'{SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}': 0, f'<{SHORT_NOTE_THRESHOLD}': 0}
            }

            # Total
            cur.execute('SELECT COUNT(*) FROM public.articles')
            stats['total'] = int(cur.fetchone()[0] or 0)

            # Urgent
            if column_exists('urgent'):
                cur.execute('SELECT COUNT(*) FROM public.articles WHERE urgent = TRUE')
                stats['urgent'] = int(cur.fetchone()[0] or 0)

            if column_exists('priority_score'):
                cur.execute("SELECT SUM(CASE WHEN COALESCE(priority_score,0) >= 8 THEN 1 ELSE 0 END), SUM(CASE WHEN COALESCE(priority_score,0) >=5 AND COALESCE(priority_score,0) < 8 THEN 1 ELSE 0 END), SUM(CASE WHEN COALESCE(priority_score,0) < 5 THEN 1 ELSE 0 END) FROM public.articles")
                row = cur.fetchone() or (0, 0, 0)
                stats['by_priority']['high'] = int(row[0] or 0)
                stats['by_priority']['medium'] = int(row[1] or 0)
                stats['by_priority']['low'] = int(row[2] or 0)

            # Categories aggregation
            if column_exists('categories'):
                try:
                    cur.execute("SELECT elem, COUNT(*) FROM public.articles, jsonb_array_elements_text(COALESCE(categories, '[]'::jsonb)) AS elem GROUP BY elem")
                    for cat, cnt in cur.fetchall():
                        stats['by_category'][cat] = int(cnt or 0)
                except Exception:
                    pass

            # Score buckets based on total_score column (fallback to 0 when NULL)
            if column_exists('total_score'):
                cur.execute(
                    "SELECT SUM(CASE WHEN total_score >= %s THEN 1 ELSE 0 END), SUM(CASE WHEN total_score >= %s AND total_score < %s THEN 1 ELSE 0 END), SUM(CASE WHEN total_score < %s THEN 1 ELSE 0 END) FROM public.articles WHERE total_score IS NOT NULL",
                    (PUBLISH_THRESHOLD, SHORT_NOTE_THRESHOLD, PUBLISH_THRESHOLD, SHORT_NOTE_THRESHOLD)
                )
                row = cur.fetchone() or (0, 0, 0)
                stats['score_buckets'][f'>={PUBLISH_THRESHOLD}'] = int(row[0] or 0)
                stats['score_buckets'][f'{SHORT_NOTE_THRESHOLD}-{PUBLISH_THRESHOLD - 1}'] = int(row[1] or 0)
                stats['score_buckets'][f'<{SHORT_NOTE_THRESHOLD}'] = int(row[2] or 0)

            try:
                cur.close()
            except Exception:
                pass

            return stats
        except Exception:
            return {}

    def _process_single_doc(self, doc) -> Dict:
        """Process a single normalized row or Firestore-like doc and return a dict with result info."""
        try:
            doc_id = doc.get('id')
            data = doc

            title = data.get('title', '')
            description = data.get('description', '') or ''
            content = (data.get('content', '') or '')[:500]
            tags = data.get('tags', []) or data.get('categories', []) or []
            source = data.get('source', '') or data.get('link', '') or ''
            pub_date = data.get('pub_date', '') or ''
            feed_name = data.get('feed_name', '') or data.get('feed', '') or ''
            region_hint = data.get('region_hint', '') or ''
            
            client = _get_openai_client()
            model = 'gpt-4o-mini'

            # Call LLM for categorization
            interest_result = self._call_llm_categorization(
                client, model, doc_id, title, description, tags, 
                content, source, pub_date, feed_name, region_hint
            )

            # Extract fields from LLM response
            fields = self._extract_interest_fields(interest_result)
            total_score = fields.get('total_score')
            rating = fields.get('rating')
            short_note = fields.get('short_note')
            category_field = fields.get('category')
            comment_field = fields.get('comment')
            publish_on_site = interest_result.get('publish_on_site') if isinstance(interest_result, dict) else None
            publish_on_social = interest_result.get('publish_on_social') if isinstance(interest_result, dict) else None
            newsletter_field = fields.get('newsletter')

            # Determine status
            status_field = 'CATEGORIZED'
            score_val = float(total_score) if total_score is not None else 0.0
            if score_val < MIN_ARTICLE_SCORE:
                try:
                    self.logger.info(
                        f"Article {doc_id} has total_score={score_val:.2f} < threshold {MIN_ARTICLE_SCORE}; topic assignment disabled"
                    )
                except Exception:
                    pass
                status_field = 'SKIPPED'
            else:
                try:
                    self.logger.info(
                        f"Article {doc_id} has total_score={score_val:.2f} >= threshold {MIN_ARTICLE_SCORE}; attempting topic match"
                    )
                except Exception:
                    pass

            # Topic assignment via embedding similarity (no lock needed for single doc)
            topic_id_val = None
            if score_val >= MIN_ARTICLE_SCORE:
                try:
                    # Create a dummy lock and recent_topics list for single-doc processing
                    import threading
                    lock = threading.Lock()
                    recent_topics = []
                    try:
                        recent_topics = self.pg.get_recent_topics(hours=48)
                    except Exception:
                        pass
                    
                    topic_id_val = self._match_or_create_topic(client, title, doc_id, score_val, description=description, lock=lock, recent_topics=recent_topics)
                except Exception as e:
                    self.logger.exception(f"Error creating topic for {doc_id}: {e}")

            update_payload = {
                'interest': interest_result,
                'status': status_field,
                'total_score': total_score,
                'rating': rating,
                'short_note': short_note,
                'category': category_field,
                'comment': comment_field,
                'publish_on_site': publish_on_site,
                'publish_on_social': publish_on_social,
                'newsletter': newsletter_field,
                'topic_id': topic_id_val,
                'categorized_at': datetime.now(timezone.utc).isoformat(),
                'updated_at': datetime.now(timezone.utc).isoformat(),
            }

            ok = self.pg.save_article_categorization(doc_id, update_payload)

            # Deduplicate by topic
            if topic_id_val:
                self._deduplicate_by_topic(topic_id_val)

            return {'doc_id': doc_id, 'ok': ok, 'payload': update_payload}
        except Exception as e:
            return {'doc_id': getattr(doc, 'id', None), 'ok': False, 'error': str(e)}

    def categorize_article_by_id(self, article_id: str) -> Dict:
        try:
            row = self.pg.fetch_article_by_id(article_id)
            if not row:
                return {'status': 'error', 'message': f'Article {article_id} not found'}
            res = self._process_single_doc(row)
            if res.get('ok'):
                return {'status': 'success', 'processed': 1, 'doc_id': article_id}
            else:
                return {'status': 'error', 'message': res.get('error', 'save_failed')}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}
