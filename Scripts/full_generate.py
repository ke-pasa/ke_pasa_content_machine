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
from workers.article_generator.image_generator import ImageGenerator


def load_article_pg(article_id: str) -> dict:
    pg = get_pg_client()
    if not pg:
        raise RuntimeError('Postgres client not available')
    rec = pg.fetch_article_by_id(article_id)
    return rec


def save_generated_pg(doc_id: str, source: dict, translation_result: dict):
    ag = ArticleGenerator()
    # total_score comes from the source article, not from translation_result
    total_score = source.get('total_score', 0.0)
    try:
        total_score = float(total_score)
    except (ValueError, TypeError):
        total_score = 0.0
    ag._save_generated_article(doc_id=doc_id, source=source, total_score=total_score, translation_result=translation_result, status='TRANSLATED')


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
    
    image_generation_enabled = os.environ.get('ARTICLE_GENERATOR_ENABLE_IMAGES', 'false').strip().lower() in ('1', 'true', 'yes', 'on')
    if image_generation_enabled:
        try:
            image_gen = ImageGenerator(model=os.environ.get('ARTICLE_GENERATOR_IMAGE_MODEL', 'gpt-image-1'))
            logger.info('Image generator initialized')
        except Exception as e:
            logger.warning(f'Failed to initialize image generator: {e}')
            image_gen = None
    else:
        logger.info('Article image generation disabled (ARTICLE_GENERATOR_ENABLE_IMAGES=false)')
        image_gen = None

    try:
        url = src.get('link') or src.get('url')
        # Propagate SAVE_TRANSLATIONS into translator as save_stages flag
        save_stages_flag = os.environ.get('SAVE_TRANSLATIONS', 'false').lower() in ('1', 'true', 'yes')
        tr = translator.translate(
            title,
            description,
            content,
            metadata={
                'doc_id': article_id,
                'url': url,
                'total_score': src.get('total_score'),
                'save_stages': save_stages_flag,
            }
        )
        if not tr:
            logger.error('Translation failed for %s', article_id)
            return 3

        logger.info('Translation completed for %s. Keys in result: %s', article_id, list(tr.keys()))
        logger.info('Article metadata: total_score=%.1f, url=%s', src.get('total_score', 0.0), url)

        # Generate image if missing
        image_url = src.get('image')
        if image_gen and (not image_url or not image_url.strip()):
            logger.info('🎨 Generating image for article %s (no existing image)', article_id)
            try:
                generated_image_path = image_gen.generate_image_for_article(
                    doc_id=article_id,
                    title=title,
                    description=description,
                    content=content,
                    existing_image_url=image_url
                )
                if generated_image_path:
                    src['image'] = generated_image_path
                    logger.info('✅ Generated and saved image: %s', generated_image_path)
            except Exception as img_err:
                logger.warning('⚠️ Image generation failed for %s: %s', article_id, img_err)

        save_generated_pg(article_id, src, tr)

        final_preview = (tr.get('stage6_telegram') or {}).get('tg_preview') or tr.get('tg_preview')
        if not final_preview:
            logger.warning('No telegram preview generated for %s', article_id)
            logger.info('Translation result has stage6_telegram: %s, tg_preview: %s', 
                       bool(tr.get('stage6_telegram')), bool(tr.get('tg_preview')))
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
                logger.info('Attempting to send photo with caption (len=%d) to chat %s', len(caption), chat_id)
                if len(caption) <= 1024:
                    sent = send_photo(chat_id, image, caption=caption, token=token)
                    logger.info('Photo sent successfully: %s', sent)
                else:
                    logger.info('Caption too long, sending as text message instead')
                    sent = send_message(chat_id, final_preview, token=token)
                    logger.info('Message sent successfully: %s', sent)
            else:
                logger.info('No image found, sending text message to chat %s', chat_id)
                sent = send_message(chat_id, final_preview, token=token)
                logger.info('Message sent successfully: %s', sent)
        except Exception as e:
            logger.exception('Failed to send preview for %s: %s', article_id, str(e))
            sent = None


        if sent:
            logger.info('Message sent successfully, updating article status to PUBLISHED')
            pg = get_pg_client()
            if not pg:
                raise RuntimeError('Postgres client not available to record telegram post')

            post = {'article_id': article_id, 'telegram_message': sent.to_dict() if hasattr(sent, 'to_dict') else (sent if isinstance(sent, dict) else {'repr': repr(sent)}), 'chat_id': chat_id, 'created_at': datetime.now(timezone.utc).isoformat()}

            conn, pooled = pg._get_conn()
            try:
                cur = conn.cursor()
                try:
                    cur.execute('UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE article_id = %s', ('PUBLISHED', datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), article_id))
                    conn.commit()
                    logger.info('Article %s status updated to PUBLISHED', article_id)
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
                    cur.execute('UPDATE public.articles_ru SET status = %s, published_at = %s, updated_at = %s WHERE article_id = %s', ('PUBLISHED', datetime.now(timezone.utc).isoformat(), datetime.now(timezone.utc).isoformat(), article_id))
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
        else:
            logger.warning('Message was not sent for article %s - skipping status update', article_id)

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
