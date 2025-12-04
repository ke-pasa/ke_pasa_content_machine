"""Full generation pipeline for a single article: translate and optionally publish.

This script is PG-first and will raise exceptions if Postgres operations fail.

Usage:
    python Scripts/full_generate.py --article-id <ID>
"""

from __future__ import annotations

import sys
from pathlib import Path
import logging
import os
import json
from datetime import datetime, timezone

repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=repo_root / '.env')
except Exception:
    pass

from workers.tools.pg_client import get_pg_client
from workers.article_generator.translator import ArticleTranslator
from workers.tools.telegram_helper import send_message, send_photo
from workers.article_generator.ArticleGenerator import ArticleGenerator


def load_article_pg(article_id: str) -> dict:
    pg = get_pg_client()
    if not pg:
        raise RuntimeError('Postgres client not available')
    rec = pg.fetch_article_by_id(article_id)
    return rec


def save_generated_pg(doc_id: str, source: dict, translation_result: dict):
    ag = ArticleGenerator()
    ag._save_generated_article(doc_id=doc_id, source=source, total_score=translation_result.get('total_score') or 0.0, translation_result=translation_result, status='TRANSLATED')


def main(article_id: str):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('full_generate')

    src = load_article_pg(article_id)
    if not src:
        logger.error('Article %s not found', article_id)
        return 2

    title = src.get('title', '') or ''
    description = src.get('description', '') or ''
    content = src.get('content', '') or ''

    translator = ArticleTranslator()
    generator = ArticleGenerator(translator=translator)

    try:
        url = src.get('link') or src.get('url')
        if url:
            fetched = generator._fetch_article_content(url)
            if fetched and len(fetched) > len(content):
                content = fetched

        tr = translator.translate(title, description, content, metadata={'doc_id': article_id, 'url': url, 'total_score': src.get('total_score')})
        if not tr:
            logger.error('Translation failed for %s', article_id)
            return 3

        save_generated_pg(article_id, src, tr)

        final_preview = (tr.get('stage6_telegram') or {}).get('tg_preview') or tr.get('tg_preview')
        if not final_preview:
            logger.info('No telegram preview generated for %s', article_id)
            return 0

        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        token = os.environ.get('TELEGRAM_BOT_TOKEN')
        if not token or not chat_id:
            logger.info('Missing TELEGRAM config, printing preview')
            print(final_preview)
            return 0

        sent = None
        try:
            image = src.get('image') or src.get('image_url')
            if image:
                caption = final_preview
                if len(caption) <= 1024:
                    sent = send_photo(chat_id, image, caption=caption, token=token)
                else:
                    sent = send_message(chat_id, final_preview, token=token)
            else:
                sent = send_message(chat_id, final_preview, token=token)
        except Exception:
            logger.exception('Failed to send preview for %s', article_id)
            sent = None

        if sent:
            pg = get_pg_client()
            if not pg:
                raise RuntimeError('Postgres client not available to record telegram post')

            post = {'article_id': article_id, 'telegram_message': sent.to_dict() if hasattr(sent, 'to_dict') else (sent if isinstance(sent, dict) else {'repr': repr(sent)}), 'chat_id': chat_id, 'created_at': datetime.now(timezone.utc).isoformat()}

            conn, pooled = pg._get_conn()
            try:
                cur = conn.cursor()
                try:
                    cur.execute('UPDATE public.articles_ru SET status = %s, published_to_telegram = %s, published_at = %s, updated_at = %s WHERE article_id = %s', ('PUBLISHED', True, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), article_id))
                    conn.commit()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
            finally:
                try:
                    pg._put_conn(conn, pooled)
                except Exception:
                    pass

            # update articles_ru status
            conn, pooled = pg._get_conn()
            try:
                cur = conn.cursor()
                try:
                    cur.execute('UPDATE public.articles_ru SET status = %s, published_to_telegram = %s, published_at = %s, updated_at = %s WHERE article_id = %s', ('PUBLISHED', True, datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), article_id))
                    conn.commit()
                finally:
                    try:
                        cur.close()
                    except Exception:
                        pass
            finally:
                try:
                    pg._put_conn(conn, pooled)
                except Exception:
                    pass

        return 0
    except Exception:
        logger.exception('Failed full generate for %s', article_id)
        return 4


if __name__ == '__main__':
    import argparse, traceback

    p = argparse.ArgumentParser()
    p.add_argument('--article-id', required=True, help='Article id in `articles` to generate+publish')
    args = p.parse_args()

    try:
        rc = main(args.article_id)
        sys.exit(rc)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
