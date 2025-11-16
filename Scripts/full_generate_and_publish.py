"""Full generation pipeline for a single article: stage1..stage5 then publish.

Usage: run from repo root in venv
  python Scripts/full_generate_and_publish.py --article-id <ID>

This script:
- loads the article from `articles` collection
- runs the full translator pipeline via `ArticleTranslator.translate`
- saves generated outputs into `articles_ru` (stages.editorial/publish/telegram/telegram_final)
- updates the original `articles` document with translation fields
- sends the final Telegram preview using `PublisherWorker` HTTP helpers
"""
from __future__ import annotations

import sys
from pathlib import Path
import logging
import os
from datetime import datetime

# ensure repo root on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from workers.tools.firebase_client import get_firebase_client
from workers.article_generator.translator import ArticleTranslator
from workers.publisher.worker import PublisherWorker


def load_article(db, article_id: str):
    doc = db.collection('articles').document(article_id).get()
    if not getattr(doc, 'exists', False):
        return None
    return doc.to_dict() or {}


def save_generated(db, doc_id: str, source: dict, translation_result: dict):
    now = datetime.utcnow().isoformat()

    stage2 = translation_result.get('editorial_result') or None
    stage3 = {'publish_md': translation_result.get('publish_md'), 'flags': translation_result.get('publish_flags') or []}
    stage4 = translation_result.get('stage4_raw') or {'tg_preview': translation_result.get('tg_preview'), 'flags': translation_result.get('tg_flags') or []}
    stage5 = translation_result.get('stage5_final') or None

    title_ru = translation_result.get('title_ru') or (stage2 or {}).get('title_ru')
    description_ru = translation_result.get('description_ru') or (stage2 or {}).get('description_ru')
    content_ru = translation_result.get('content_ru') or (stage2 or {}).get('content_ru') or translation_result.get('translation_ru')

    payload = {
        'article_id': doc_id,
        'source_url': source.get('link') or source.get('url'),
        'source_name': source.get('source') or source.get('source_name'),
        'image_url': source.get('image') or source.get('image_url') or None,
        'status': 'TRANSLATED',
        'title_ru': title_ru,
        'description_ru': description_ru,
        'content_ru': content_ru,
        'stages': {
            'editorial': stage2,
            'publish': stage3,
            'telegram': stage4,
            'telegram_final': stage5,
        },
        'telegram_preview': (stage5 or {}).get('tg_preview') if stage5 else (stage4 or {}).get('tg_preview'),
        'telegram_flags': (stage5 or {}).get('flags') or (stage4 or {}).get('flags') or [],
        'updated_at': now,
        'created_at': now,
    }

    try:
        db.collection('articles_ru').document(doc_id).set(payload, merge=True)
    except Exception:
        logging.exception('Failed to save generated article to articles_ru %s', doc_id)

    # update original article document
    try:
        update_payload = {
            'title_ru': title_ru,
            'description_ru': description_ru,
            'content_ru': content_ru,
            'publish_md': translation_result.get('publish_md'),
            'publish_flags': translation_result.get('publish_flags'),
            'telegram_preview': (stage5 or {}).get('tg_preview') if stage5 else (stage4 or {}).get('tg_preview'),
            'telegram_flags': (stage5 or {}).get('flags') or (stage4 or {}).get('flags') or [],
            'status': 'TRANSLATED',
            'translated_at': now,
            'updated_at': now,
        }
        db.collection('articles').document(doc_id).set(update_payload, merge=True)
    except Exception:
        logging.exception('Failed to update original articles doc %s', doc_id)


def send_final_preview(pub: PublisherWorker, article_doc: dict, translation_result: dict) -> dict | None:
    # Determine final preview and image
    stage5 = translation_result.get('stage5_final') or None
    stage4 = translation_result.get('stage4_raw') or {'tg_preview': translation_result.get('tg_preview'), 'flags': translation_result.get('tg_flags') or []}
    # Prefer explicit stage5, then stage4, then any top-level tg_preview
    final_preview = None
    if isinstance(stage5, dict):
        final_preview = stage5.get('tg_preview')
    if not final_preview and isinstance(stage4, dict):
        final_preview = stage4.get('tg_preview')
    if not final_preview:
        final_preview = translation_result.get('tg_preview')

    if not final_preview:
        logging.warning('No telegram preview generated (stage5/stage4 missing)')
        return None

    image = article_doc.get('image') or article_doc.get('image_url') or None

    # If no telegram token/chat configured, print the preview instead of sending
    if not pub.telegram_token:
        logging.info('TELEGRAM_BOT_TOKEN not configured, printing final preview:')
        print('\n--- FINAL TELEGRAM PREVIEW ---\n')
        print(final_preview)
        print('\n--- END PREVIEW ---\n')
        return None

    chat_id = pub._get_chat_id()
    if not chat_id:
        raise RuntimeError('Telegram chat id not configured')

    # Try sending photo with caption if present and fits; otherwise text
    try:
        if image:
            caption = final_preview
            max_caption = 1024
            if len(caption) <= max_caption:
                return pub._http_send_photo(chat_id, image, caption)
            else:
                return pub._http_send_message(chat_id, final_preview)
        else:
            return pub._http_send_message(chat_id, final_preview)
    except Exception:
        logging.exception('Failed to send final preview for article')
        raise


def main(article_id: str):
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger('full_generate_and_publish')

    fb = get_firebase_client()
    db = fb.db

    src = load_article(db, article_id)
    if not src:
        logger.error('Article %s not found in articles', article_id)
        return 2

    title = src.get('title', '') or ''
    description = src.get('description', '') or ''
    content = src.get('content', '') or ''

    # Include total_score if present in source so translator can decide whether
    # to run the telegram preview stage. If missing, default to 100 to force
    # generation during ad-hoc full runs.
    try:
        total_score_val = float(src.get('total_score')) if src.get('total_score') is not None else 100.0
    except Exception:
        total_score_val = 100.0
    metadata = {
        'url': src.get('link') or src.get('url') or src.get('source'),
        'doc_id': article_id,
        'total_score': total_score_val,
    }

    translator = ArticleTranslator()
    logger.info('Running full translator for %s', article_id)
    # Run translation pipeline
    tr = translator.translate(title, description, content, metadata=metadata)
    if not tr or not isinstance(tr, dict):
        logger.error('Translator failed for %s', article_id)
        return 3

    # Print each stage for visibility
    print('\n--- начальный текст ---\n')
    print('Title:\n', title)
    print('\nDescription:\n', description)
    print('\nContent:\n', (content or '')[:2000])

    # Stage 1 rough parse/translation
    try:
        s1 = translator._stage1_translate(title, description, content, metadata)
    except Exception:
        s1 = None
    print('\n--- Грубый перевод (stage1) ---\n')
    try:
        import json as _json
        print(_json.dumps(s1, ensure_ascii=False, indent=2))
    except Exception:
        print(s1)

    # Stage 2 editorial
    try:
        s2 = translator._stage2_edit(s1 or {}, metadata)
    except Exception:
        s2 = None
    print('\n--- Редактура / перевод для сайта (stage2) ---\n')
    try:
        import json as _json
        print(_json.dumps(s2, ensure_ascii=False, indent=2))
    except Exception:
        print(s2)

    # Stage 3 publish
    try:
        s3 = translator._stage3_publish(s2 or {}, metadata)
    except Exception:
        s3 = None
    print('\n--- Publish (stage3) ---\n')
    try:
        import json as _json
        print(_json.dumps(s3, ensure_ascii=False, indent=2))
    except Exception:
        print(s3)

    # Stage 4 telegram rough
    try:
        s4 = None
        if metadata.get('total_score', 0) >= 80 and metadata.get('url'):
            s4 = translator._stage4_telegram(s2 or {}, metadata)
    except Exception:
        s4 = None
    print('\n--- Телеграмм (грубая версия) (stage4) ---\n')
    try:
        import json as _json
        print(_json.dumps(s4, ensure_ascii=False, indent=2))
    except Exception:
        print(s4)

    # Stage 5 final
    try:
        s5 = None
        if isinstance(s4, dict) and s4.get('tg_preview'):
            s5 = translator._stage5_finalize(s4, metadata)
    except Exception:
        s5 = None
    print('\n--- Телеграмм (финал) (stage5) ---\n')
    try:
        import json as _json
        print(_json.dumps(s5, ensure_ascii=False, indent=2))
    except Exception:
        print(s5)


    # Persist outputs
    save_generated(db, article_id, src, tr)

    # Create publisher and send final preview. Use HTTP helpers to avoid potential httpx/async issues.
    saved_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    try:
        # Temporarily remove token when instantiating to avoid Bot creation side-effects; we'll use HTTP calls below.
        if 'TELEGRAM_BOT_TOKEN' in os.environ:
            del os.environ['TELEGRAM_BOT_TOKEN']
        pub = PublisherWorker()
    finally:
        if saved_token is not None:
            os.environ['TELEGRAM_BOT_TOKEN'] = saved_token

    pub.telegram_token = saved_token
    pub.telegram_bot = None

    try:
        sent = send_final_preview(pub, src, tr)
    except Exception as e:
        logger.exception('Failed to send article %s: %s', article_id, e)
        return 4

    # Record and mark published
    # Only record/mark published when a real Telegram send occurred
    if sent:
        try:
            post_record = {
                'article_id': article_id,
                'telegram_message': sent.to_dict() if hasattr(sent, 'to_dict') else sent,
                'chat_id': pub._get_chat_id(),
                'created_at': datetime.utcnow().isoformat(),
            }
            db.collection('telegram_posts').add(post_record)
        except Exception:
            logger.exception('Failed to record telegram_posts for %s', article_id)

        try:
            db.collection('articles_ru').document(article_id).set({'published_to_telegram': True, 'published_to_telegram_at': datetime.utcnow().isoformat(), 'status': 'PUBLISHED'}, merge=True)
        except Exception:
            logger.exception('Failed to mark articles_ru %s as published', article_id)

        try:
            art_doc = db.collection('articles').document(article_id)
            if art_doc.get().exists:
                db.collection('articles').document(article_id).set({'status': 'PUBLISHED'}, merge=True)
        except Exception:
            logger.exception('Failed to update articles %s status', article_id)

        logger.info('Article %s generated and published', article_id)
        return 0
    else:
        logger.info('Article %s generated but not sent to Telegram (no token/chat or send failed). Not marking as published.', article_id)
        return 0


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
