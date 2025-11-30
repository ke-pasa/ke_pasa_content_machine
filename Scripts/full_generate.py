"""Full generation pipeline for a single article: stage1..stage6 then publish.

Usage: run from repo root in venv
  python Scripts/full_generate_and_publish.py --article-id <ID>

This script:
- loads the article from `articles` collection
- runs the full translator pipeline via `ArticleTranslator.translate`
- saves generated outputs into `articles_ru` (stages.stage1/stage2/stage3/stage4, publish_md, telegram_preview, telegram_final)
- updates the original `articles` document with translation fields
- sends the final Telegram preview using `PublisherWorker` HTTP helpers

New 6-stage architecture:
- stage1: structured analysis (explanation_ru, facts_raw, actors)
- stage2: human reportage (title, dek, body, facts, entities)
- stage3: editorial evaluation (scores, rewrite_focus_points, detected_issues)
- stage4: final article synthesis (title, dek, body, facts, entities)
- stage5: website markdown with YAML frontmatter
- stage6: Telegram preview with HTML markup
"""
from __future__ import annotations

import sys
from pathlib import Path
import logging
import os
from datetime import datetime, timezone

# ensure repo root on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

# Load .env from repo root for developer convenience (best-effort)
try:
    from dotenv import load_dotenv
    load_dotenv(dotenv_path=repo_root / '.env')
except Exception:
    pass

# Ensure articles directory exists (so generated markdown can be saved locally)
try:
    articles_dir = repo_root / 'articles'
    articles_dir.mkdir(parents=True, exist_ok=True)
    logging.getLogger(__name__).info('Ensured articles directory exists at %s', str(articles_dir))
except Exception:
    logging.getLogger(__name__).exception('Failed to ensure articles directory exists')

from workers.tools.firebase_client import get_firebase_client
from workers.article_generator.translator import ArticleTranslator
from workers.tools.telegram_helper import send_message, send_photo
from workers.article_generator.ArticleGenerator import ArticleGenerator


def load_article(db, article_id: str):
    doc = db.collection('articles').document(article_id).get()
    if not getattr(doc, 'exists', False):
        return None
    return doc.to_dict() or {}


def save_generated(db, doc_id: str, source: dict, translation_result: dict):
    """Save generated article to articles_ru and update original articles document."""
    # Compute total_score for ArticleGenerator
    editorial_result = translation_result.get('editorial_result') or {}
    stage3 = editorial_result.get('stage3') or {}
    total_score = editorial_result.get('total_score') or translation_result.get('total_score') or stage3.get('total_score_percent') or 0.0

    # Delegate articles_ru persisting to ArticleGenerator (includes telegram_final.tg_preview population)
    ag = ArticleGenerator()
    try:
        ag._save_generated_article(
            doc_id=doc_id,
            source=source,
            total_score=total_score,
            translation_result=translation_result,
            status='TRANSLATED',
            metadata={'worker_name': 'full_generate'}
        )
    except Exception:
        logging.exception('Failed to save generated article via ArticleGenerator for %s', doc_id)

    # Update original article document with basic translation fields
    try:
        now = datetime.now(timezone.utc).isoformat()
        update_payload = {
            'title_ru': translation_result.get('title_ru'),
            'description_ru': translation_result.get('description_ru'),
            'content_ru': translation_result.get('content_ru'),
            'status': 'TRANSLATED',
            'translated_at': now,
            'updated_at': now,
        }
        db.collection('articles').document(doc_id).set(update_payload, merge=True)
    except Exception:
        logging.exception('Failed to update original articles doc %s', doc_id)


def main(article_id: str):
    import json
    
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

    try:
        total_score_val = float(src.get('total_score')) if src.get('total_score') is not None else 100.0
    except Exception:
        total_score_val = 50.0
    metadata = {
        'url': src.get('link') or src.get('url') or src.get('source'),
        'image_url': src.get('image') or src.get('image_url') or None,
        'doc_id': article_id,
        'total_score': total_score_val,
    }

    translator = ArticleTranslator()
    # Try to fetch the full article content (prefer full text over preview)
    try:
        generator = ArticleGenerator(translator=translator)
        fetched_full = None
        try:
            url = metadata.get('url')
            if url:
                fetched_full = generator._fetch_article_content(url)
        except Exception:
            fetched_full = None

        if fetched_full and len(fetched_full) > len(content):
            logger.info('Using fetched full article text for %s (fetched %d chars vs stored %d)', article_id, len(fetched_full), len(content))
            content = fetched_full
            metadata['fetched_content'] = fetched_full
            metadata['content_source'] = 'fetched'
        else:
            metadata['fetched_content'] = fetched_full
            metadata['content_source'] = 'stored'
    except Exception:
        logger.exception('Failed to fetch full article content for %s', article_id)

    logger.info('Running full translator for %s (total_score=%.1f, url=%s)', article_id, metadata.get('total_score', 0), metadata.get('url', 'N/A')[:50] if metadata.get('url') else 'N/A')

    tr = translator.translate(title, description, content, metadata=metadata)
    if not tr or not isinstance(tr, dict):
        logger.error('Translator failed for %s', article_id)
        return 3

    # Print each stage for visibility with larger separators
    SEP = '\n' + '=' * 88 + '\n'
    SUBSEP = '\n' + '-' * 40 + '\n'

    def pretty_print_heading(title_text: str):
        print(SEP)
        print(f"*** {title_text} ***")
        print(SUBSEP)

    # Extract stages from tr (translator.translate already ran all stages internally)
    editorial_result = tr.get('editorial_result') or {}
    s1 = editorial_result.get('stage1') or {}
    s2 = editorial_result.get('stage2') or {}
    s3 = editorial_result.get('stage3') or {}
    s4 = editorial_result.get('stage4') or {}
    s5 = {'publish_md': tr.get('publish_md')}
    s6 = tr.get('stage6_telegram') or {}

    # initial text
    pretty_print_heading('НАЧАЛЬНЫЙ ТЕКСТ')
    print('Title:\n', title)
    print('\nDescription:\n', description)
    print('\nContent:\n', (content or '')[:2000])

    # Stage 1: structured analysis
    pretty_print_heading('СТРУКТУРНЫЙ АНАЛИЗ (stage1)')
    try:
        print(json.dumps(s1, ensure_ascii=False, indent=2))
    except Exception:
        print(s1)

    # Stage 2: human reportage
    pretty_print_heading('ЧЕЛОВЕЧЕСКИЙ РЕПОРТАЖ (stage2)')
    try:
        print(json.dumps(s2, ensure_ascii=False, indent=2))
    except Exception:
        print(s2)

    # Stage 3: editorial evaluation
    pretty_print_heading('ЭКСПЕРТНАЯ ОЦЕНКА (stage3)')
    try:
        print(json.dumps(s3, ensure_ascii=False, indent=2))
    except Exception:
        print(s3)

    # Stage 4: final article synthesis
    pretty_print_heading('ФИНАЛЬНАЯ СТАТЬЯ (stage4)')
    try:
        print(json.dumps(s4, ensure_ascii=False, indent=2))
    except Exception:
        print(s4)

    # Stage 5: website markdown
    pretty_print_heading('ВЕРСИЯ ДЛЯ САЙТА (stage5)')
    try:
        print(json.dumps(s5, ensure_ascii=False, indent=2))
    except Exception:
        print(s5)

    # Stage 6: Telegram preview
    pretty_print_heading('ТЕЛЕГРАММ ПРЕВЬЮ (stage6)')
    if not s6 or s6 == {}:
        score = metadata.get('total_score', 0)
        url = metadata.get('url', 'N/A')
        print(f"⚠️  Stage6 не был сгенерирован!")
        print(f"   Требования: total_score >= 80 и наличие URL")
        print(f"   Текущие значения: total_score={score}, url={url[:80] if url and url != 'N/A' else url}")
        if score < 80:
            print(f"   ❌ Оценка {score} ниже порога 80")
        if not url or url == 'N/A':
            print(f"   ❌ URL отсутствует")
    try:
        print(json.dumps(s6, ensure_ascii=False, indent=2))
    except Exception:
        print(s6)

    # Persist outputs
    save_generated(db, article_id, src, tr)

    # Determine final preview from stage6 or fallback to tg_preview
    try:
        stage6 = tr.get('stage6_telegram') or {}
        final_preview = stage6.get('tg_preview') or tr.get('tg_preview')

        if not final_preview:
            logger.warning('No telegram preview generated (stage5/stage4 missing)')
            return 0

        # Resolve chat id from env or firebase settings
        chat_id = os.environ.get('TELEGRAM_CHAT_ID') or None
        if not chat_id:
            try:
                client = get_firebase_client()
                settings = client.get_settings()
                chat_id = settings.get('telegram_chat_id')
            except Exception:
                chat_id = None

        token = os.environ.get('TELEGRAM_BOT_TOKEN')

        # If no token or chat id, print preview for manual send and do not mark published
        if not token or not chat_id:
            logger.info('TELEGRAM_BOT_TOKEN or chat id not configured, printing final preview:')
            print(SEP)
            print('*** FINAL TELEGRAM PREVIEW ***')
            print(SUBSEP)
            print(final_preview)
            print(SEP)
            return 0

        # Perform send: try photo with caption first, fallback to text
        sent = None
        image = src.get('image') or src.get('image_url') or None
        try:
            if image:
                caption = final_preview
                max_caption = 1024
                if len(caption) <= max_caption:
                    sent = send_photo(chat_id, image, caption=caption, token=token)
                else:
                    sent = send_message(chat_id, final_preview, token=token)
            else:
                sent = send_message(chat_id, final_preview, token=token)
        except Exception:
            logger.exception('Failed to send final preview for article %s', article_id)
            sent = None

        # If send succeeded, record and mark published
        if sent:
            try:
                # Normalize sent to serializable structure
                try:
                    if hasattr(sent, 'to_dict'):
                        sent_serializable = sent.to_dict()
                    elif isinstance(sent, dict):
                        sent_serializable = sent
                    else:
                        sent_serializable = {'repr': repr(sent)}
                except Exception:
                    sent_serializable = {'repr': repr(sent)}

                post_record = {
                    'article_id': article_id,
                    'telegram_message': sent_serializable,
                    'chat_id': chat_id,
                    'created_at': datetime.now(timezone.utc).isoformat(),
                }
                db.collection('telegram_posts').add(post_record)
            except Exception:
                logger.exception('Failed to record telegram_posts for %s', article_id)

            try:
                db.collection('articles_ru').document(article_id).set({'published_to_telegram': True, 'published_to_telegram_at': datetime.now(timezone.utc).isoformat(), 'status': 'PUBLISHED'}, merge=True)
            except Exception:
                logger.exception('Failed to mark articles_ru %s as published', article_id)

            try:
                db.collection('articles').document(article_id).set({'status': 'PUBLISHED'}, merge=True)
            except Exception:
                logger.exception('Failed to update articles %s status', article_id)

            logger.info('Article %s generated and published', article_id)

        else:
            logger.info('Article %s generated but Telegram send failed; not marking as published.', article_id)

    except Exception as e:
        logger.exception('Failed to prepare/send article %s: %s', article_id, e)
        return 4

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
