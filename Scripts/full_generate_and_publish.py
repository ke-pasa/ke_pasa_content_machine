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
from datetime import datetime

# ensure repo root on sys.path
repo_root = Path(__file__).resolve().parent.parent
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from workers.tools.firebase_client import get_firebase_client
from workers.article_generator.translator import ArticleTranslator
from workers.article_generator.translator import _chat_completion as _translator_chat
from workers.article_generator.translator import _parse_json_from_text as _translator_parse_json
# Note: prompts moved to per-stage JSON files. Do not import stage eval constants here.
from workers.tools.telegram_helper import send_message, send_photo
from workers.article_generator.ArticleGenerator import ArticleGenerator


def load_article(db, article_id: str):
    doc = db.collection('articles').document(article_id).get()
    if not getattr(doc, 'exists', False):
        return None
    return doc.to_dict() or {}


def save_generated(db, doc_id: str, source: dict, translation_result: dict):
    now = datetime.utcnow().isoformat()

    editorial_result = translation_result.get('editorial_result') or {}
    stage1 = editorial_result.get('stage1') or {}
    stage2 = editorial_result.get('stage2') or {}
    stage3 = editorial_result.get('stage3') or {}
    stage4 = editorial_result.get('stage4') or {}
    publish_md = translation_result.get('publish_md')
    tg_preview = translation_result.get('tg_preview')
    stage6_telegram = translation_result.get('stage6_telegram') or {}

    title_ru = translation_result.get('title_ru') or stage4.get('title') or stage2.get('title')
    description_ru = translation_result.get('description_ru') or stage4.get('dek') or stage2.get('dek')
    content_ru = translation_result.get('content_ru') or stage4.get('body') or stage2.get('body') or stage1.get('explanation_ru')

    total_score = editorial_result.get('total_score') or translation_result.get('total_score') or stage3.get('total_score_percent')
    combined_flags = set()
    for flag_list in [stage2.get('flags') or [], stage4.get('flags') or [], translation_result.get('publish_flags') or [], translation_result.get('tg_flags') or [], stage6_telegram.get('flags') or []]:
        if isinstance(flag_list, list):
            combined_flags.update(flag_list)

    payload = {
        'article_id': doc_id,
        'source_url': source.get('link') or source.get('url'),
        'source_name': source.get('source') or source.get('source_name'),
        'image_url': source.get('image') or source.get('image_url') or None,
        'status': 'TRANSLATED',
        'total_score': total_score,
        'title_ru': title_ru,
        'description_ru': description_ru,
        'content_ru': content_ru,
        'stages': {
            'stage1': stage1,
            'stage2': stage2,
            'stage3': stage3,
            'stage4': stage4,
        },
        'publish_md': publish_md,
        'publish_flags': translation_result.get('publish_flags') or [],
        'telegram_preview': tg_preview,
        'telegram_flags': translation_result.get('tg_flags') or [],
        'telegram_final': stage6_telegram,
        'flags': sorted(list(combined_flags)),
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
            'publish_md': publish_md,
            'publish_flags': translation_result.get('publish_flags') or [],
            'telegram_preview': tg_preview,
            'telegram_flags': translation_result.get('tg_flags') or [],
            'status': 'TRANSLATED',
            'translated_at': now,
            'updated_at': now,
        }
        db.collection('articles').document(doc_id).set(update_payload, merge=True)
    except Exception:
        logging.exception('Failed to update original articles doc %s', doc_id)


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

    logger.info('Running full translator for %s', article_id)

    tr = translator.translate(title, description, content, metadata=metadata)
    if not tr or not isinstance(tr, dict):
        logger.error('Translator failed for %s', article_id)
        return 3

    # Print each stage for visibility with larger separators
    SEP = '\n' + '=' * 88 + '\n'
    SUBSEP = '\n' + '-' * 40 + '\n'

    def pretty_print_heading(title: str):
        print(SEP)
        print(f"*** {title} ***")
        print(SUBSEP)

    # initial text
    pretty_print_heading('НАЧАЛЬНЫЙ ТЕКСТ')
    print('Title:\n', title)
    print('\nDescription:\n', description)
    print('\nContent:\n', (content or '')[:2000])

    # Stage 1: structured analysis
    try:
        s1 = translator._stage1_translate(title, description, content, metadata)
    except Exception:
        s1 = None
    pretty_print_heading('СТРУКТУРНЫЙ АНАЛИЗ (stage1)')
    try:
        import json as _json
        print(_json.dumps(s1, ensure_ascii=False, indent=2))
    except Exception:
        print(s1)

    # Stage 2: human reportage
    try:
        s2 = translator._stage2_reporter(s1 or {}, metadata)
    except Exception:
        s2 = None
    pretty_print_heading('ЧЕЛОВЕЧЕСКИЙ РЕПОРТАЖ (stage2)')
    try:
        import json as _json
        print(_json.dumps(s2, ensure_ascii=False, indent=2))
    except Exception:
        print(s2)

    # Stage 3: editorial evaluation
    try:
        source_text = f"{title}\n\n{description}\n\n{content}"
        s3 = translator._stage3_edit_first(s1 or {}, s2 or {}, source_text, metadata)
    except Exception:
        s3 = None
    pretty_print_heading('ЭКСПЕРТНАЯ ОЦЕНКА (stage3)')
    try:
        import json as _json
        print(_json.dumps(s3, ensure_ascii=False, indent=2))
    except Exception:
        print(s3)

    # Stage 4: final article synthesis
    try:
        s4 = translator._stage4_edit_final(s1 or {}, s2 or {}, s3 or {}, source_text, metadata)
    except Exception:
        s4 = None
    pretty_print_heading('ФИНАЛЬНАЯ СТАТЬЯ (stage4)')
    try:
        import json as _json
        print(_json.dumps(s4, ensure_ascii=False, indent=2))
    except Exception:
        print(s4)

    # Stage 5: website markdown
    try:
        s5 = translator._stage5_publish_md(s4 or {}, metadata)
    except Exception:
        s5 = None
    pretty_print_heading('ВЕРСИЯ ДЛЯ САЙТА (stage5)')
    try:
        import json as _json
        print(_json.dumps(s5, ensure_ascii=False, indent=2))
    except Exception:
        print(s5)

    # Stage 6: Telegram preview
    try:
        s6 = translator._stage6_telegram(s4 or {}, metadata)
    except Exception:
        s6 = None
    pretty_print_heading('ТЕЛЕГРАММ ПРЕВЬЮ (stage6)')
    try:
        import json as _json
        print(_json.dumps(s6, ensure_ascii=False, indent=2))
    except Exception:
        print(s6)


    # Persist outputs
    save_generated(db, article_id, src, tr)

    # Send final preview via shared telegram helper
    try:
        # Determine final preview from stage6 or fallback to tg_preview
        stage6 = tr.get('stage6_telegram') or {}
        final_preview = stage6.get('tg_preview') or tr.get('tg_preview')

        if not final_preview:
            logger.warning('No telegram preview generated (stage5/stage4 missing)')
            sent = None
        else:
            chat_id = os.environ.get('TELEGRAM_CHAT_ID') or None
            if not chat_id:
                # Try firebase settings
                try:
                    client = get_firebase_client()
                    settings = client.get_settings()
                    chat_id = settings.get('telegram_chat_id')
                except Exception:
                    chat_id = None

            image = src.get('image') or src.get('image_url') or None

            if not os.environ.get('TELEGRAM_BOT_TOKEN') or not chat_id:
                logger.info('TELEGRAM_BOT_TOKEN or chat id not configured, printing final preview:')
                print(SEP)
                print('*** FINAL TELEGRAM PREVIEW ***')
                print(SUBSEP)
                print(final_preview)
                print(SEP)
                sent = None
            else:
                # Try sending photo with caption, fall back to text
                try:
                    if image:
                        caption = final_preview
                        max_caption = 1024
                        if len(caption) <= max_caption:
                            sent = send_photo(chat_id, image, caption=caption, token=os.environ.get('TELEGRAM_BOT_TOKEN'))
                        else:
                            sent = send_message(chat_id, final_preview, token=os.environ.get('TELEGRAM_BOT_TOKEN'))
                    else:
                        sent = send_message(chat_id, final_preview, token=os.environ.get('TELEGRAM_BOT_TOKEN'))
                except Exception:
                    logger.exception('Failed to send final preview for article %s', article_id)
                    sent = None

        # Record and mark published
        # Only record/mark published when a real Telegram send occurred
        if sent:
            try:
                # Determine chat id for record (env or firebase)
                recorded_chat_id = os.environ.get('TELEGRAM_CHAT_ID') or None
                if not recorded_chat_id:
                    try:
                        client = get_firebase_client()
                        settings = client.get_settings()
                        recorded_chat_id = settings.get('telegram_chat_id')
                    except Exception:
                        recorded_chat_id = None

                post_record = {
                    'article_id': article_id,
                    'telegram_message': sent.to_dict() if hasattr(sent, 'to_dict') else sent,
                    'chat_id': recorded_chat_id,
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

        else:
            logger.info('Article %s generated but not sent to Telegram (no token/chat or send failed). Not marking as published.', article_id)

    except Exception as e:
        logger.exception('Failed to prepare/send article %s: %s', article_id, e)
        return 4

    return 0


if __name__ == '__main__':
    import argparse, traceback

    p = argparse.ArgumentParser()
    p.add_argument('--article-id', required=True, help='Article id in `articles` to generate+publish')
    p.add_argument('--eval-only', action='store_true', help='Run translation evaluation only (no Firebase). Requires --source-text/--final-text or file variants')
    p.add_argument('--source-text-file', help='Path to file containing source Spanish text (used with --eval-only)')
    p.add_argument('--final-text-file', help='Path to file containing final Telegram Russian text (used with --eval-only)')
    p.add_argument('--source-text', help='Inline source Spanish text (used with --eval-only)')
    p.add_argument('--final-text', help='Inline final Telegram Russian text (used with --eval-only)')
    args = p.parse_args()

    try:
        # Support eval-only mode to run the STAGE_EVAL prompt locally without Firebase
        if getattr(args, 'eval_only', False):
            src_text = ''
            final_text = ''
            if args.source_text:
                src_text = args.source_text
            elif args.source_text_file:
                try:
                    with open(args.source_text_file, 'r', encoding='utf-8') as f:
                        src_text = f.read()
                except Exception as e:
                    print('Failed to read source text file:', e)
                    sys.exit(2)

            if args.final_text:
                final_text = args.final_text
            elif args.final_text_file:
                try:
                    with open(args.final_text_file, 'r', encoding='utf-8') as f:
                        final_text = f.read()
                except Exception as e:
                    print('Failed to read final text file:', e)
                    sys.exit(2)

            if not src_text or not final_text:
                print('For --eval-only please provide --source-text and --final-text (or their file variants).')
                sys.exit(2)

            # Build prompts using JSON-based prompt files
            from workers.article_generator.translator import _parse_json_from_text as _parse_json
            from workers.article_generator.prompts import _load_eval
            eval_prompts = _load_eval()
            messages = [
                {'role': 'system', 'content': eval_prompts.get('system', '')},
                {'role': 'user', 'content': eval_prompts.get('user', '').replace('<<SOURCE_TEXT_ES>>', src_text).replace('<<FINAL_TG_TEXT>>', final_text)},
            ]
            # Use translator client if available
            tr_client = None
            tr_model = None
            try:
                translator = ArticleTranslator()
                tr_client = translator.client
                tr_model = translator.model
            except Exception:
                tr_client = None
                tr_model = None

            raw_eval_text = None
            if tr_client and tr_model:
                try:
                    raw_eval_text = _translator_chat(tr_client, tr_model, messages, max_tokens=1200, temperature=0.0)
                except Exception:
                    raw_eval_text = None

            # If LLM call failed, print message and exit
            if not raw_eval_text:
                print('LLM call failed: ensure OPENAI_API_KEY is set and openai package is installed.')
                sys.exit(3)

            print('\n' + '=' * 88 + '\n')
            print('*** TRANSLATION EVALUATION (RAW) ***')
            print('\n' + '-' * 40 + '\n')
            print((raw_eval_text or '')[:4000])
            print('\n' + '=' * 88 + '\n')

            parsed = _translator_parse_json(raw_eval_text or '')
            if parsed is None:
                print('Failed to parse JSON from model response; raw output printed above.')
                sys.exit(0)
            import json as _json
            try:
                print(_json.dumps(parsed, ensure_ascii=False, indent=2))
            except Exception:
                print(parsed)

            sys.exit(0)
        else:
            rc = main(args.article_id)
            sys.exit(rc)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
