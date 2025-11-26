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

    # Stage 1 rough parse/translation
    try:
        s1 = translator._stage1_translate(title, description, content, metadata)
    except Exception:
        s1 = None
    pretty_print_heading('ГРУБЫЙ ПЕРЕВОД (stage1)')
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
    pretty_print_heading('РЕДАКТУРА / ПЕРЕВОД ДЛЯ САЙТА (stage2)')
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
    pretty_print_heading('PUBLISH (stage3)')
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
    pretty_print_heading('ТЕЛЕГРАММ (ГРУБАЯ ВЕРСИЯ) (stage4)')
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
    pretty_print_heading('ТЕЛЕГРАММ (ФИНАЛ) (stage5)')
    try:
        import json as _json
        print(_json.dumps(s5, ensure_ascii=False, indent=2))
    except Exception:
        print(s5)


    # Persist outputs
    save_generated(db, article_id, src, tr)

    # Send final preview via shared telegram helper
    try:
        # Determine final preview and image
        stage5 = tr.get('stage5_final') or None
        stage4 = tr.get('stage4_raw') or {'tg_preview': tr.get('tg_preview'), 'flags': tr.get('tg_flags') or []}
        final_preview = None
        if isinstance(stage5, dict):
            final_preview = stage5.get('tg_preview')
        if not final_preview and isinstance(stage4, dict):
            final_preview = stage4.get('tg_preview')
        if not final_preview:
            final_preview = tr.get('tg_preview')

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

    # Run a structured translation evaluation using LLM and save as a comment
    try:
        # Choose source Spanish text and final Telegram Russian text
        try:
            # Prefer original source fields in `src`
            source_text_es = src.get('content') or src.get('description') or src.get('title') or ''
        except Exception:
            source_text_es = src.get('content') or ''

        try:
            stage5 = tr.get('stage5_final') or None
            stage4 = tr.get('stage4_raw') or {'tg_preview': tr.get('tg_preview')}
            if isinstance(stage5, dict) and stage5.get('tg_preview'):
                final_tg_text = stage5.get('tg_preview')
            elif isinstance(stage4, dict) and stage4.get('tg_preview'):
                final_tg_text = stage4.get('tg_preview')
            else:
                final_tg_text = tr.get('translation_ru') or tr.get('content_ru') or ''
        except Exception:
            final_tg_text = tr.get('translation_ru') or tr.get('content_ru') or ''

        # Load evaluation prompts from JSON-based prompt files
        from workers.article_generator.prompts import _load_eval
        eval_prompts = _load_eval()
        system_prompt = eval_prompts.get('system', '')
        user_template = eval_prompts.get('user', '')
        user_prompt = user_template.replace('<<SOURCE_TEXT_ES>>', source_text_es or '').replace('<<FINAL_TG_TEXT>>', final_tg_text or '')

        messages = [
            {'role': 'system', 'content': system_prompt},
            {'role': 'user', 'content': user_prompt},
        ]

        # Call the model via translator's client
        try:
            raw_eval_text = _translator_chat(translator.client, translator.model, messages, max_tokens=1200, temperature=0.0)
        except Exception:
            raw_eval_text = None

        eval_json = None
        eval_text_snippet = (raw_eval_text or '')[:4000]
        print('\n' + '=' * 88 + '\n')
        print('*** TRANSLATION EVALUATION (RAW) ***')
        print('\n' + '-' * 40 + '\n')
        print(eval_text_snippet)
        print('\n' + '=' * 88 + '\n')

        # Try to parse JSON using translator helper
        try:
            parsed = _translator_parse_json(raw_eval_text or '')
            if isinstance(parsed, dict):
                eval_json = parsed
            else:
                # fallback: store raw text
                eval_json = {'raw': raw_eval_text or ''}
        except Exception:
            eval_json = {'raw': raw_eval_text or ''}

        # Save eval JSON into articles_ru
        try:
            db.collection('articles_ru').document(article_id).set({'translation_eval': eval_json, 'translation_eval_at': datetime.utcnow().isoformat()}, merge=True)
            logger.info('Saved structured translation evaluation for %s', article_id)
        except Exception:
            logger.exception('Failed to save structured translation evaluation for %s', article_id)

        # If we have a sent message record earlier, try to add a telegram_posts comment entry
        try:
            if sent:
                # recorded_chat_id and sent were added to telegram_posts earlier; try to record an eval comment
                comment_record = {
                    'article_id': article_id,
                    'kind': 'translation_eval',
                    'eval': eval_json,
                    'created_at': datetime.utcnow().isoformat(),
                }
                db.collection('telegram_post_comments').add(comment_record)
                # Also try to post eval as a Telegram reply to the sent message
                try:
                    # Determine message id and thread id from `sent` (could be dict or object)
                    msg_id = None
                    thread_id = None
                    try:
                        if hasattr(sent, 'message_id'):
                            msg_id = getattr(sent, 'message_id')
                        elif isinstance(sent, dict):
                            msg_id = sent.get('message_id') or (sent.get('message') or {}).get('message_id') or (sent.get('result') or {}).get('message_id')
                            # Telegram may include a 'message_thread_id' in some responses (forum topics)
                            thread_id = sent.get('message_thread_id') or (sent.get('message') or {}).get('message_thread_id') or (sent.get('result') or {}).get('message_thread_id')
                    except Exception:
                        msg_id = None
                        thread_id = None

                    eval_text_to_send = None
                    try:
                        import json as _json
                        eval_text_to_send = _json.dumps(eval_json, ensure_ascii=False, indent=2)
                    except Exception:
                        eval_text_to_send = str(eval_json)

                    # If thread_id exists or forum topic can be created, post eval via helper
                    try:
                        from workers.tools.telegram_helper import post_eval_comment
                        # post_eval_comment returns the telegram send result or an error dict or None
                        post_result = post_eval_comment(chat_id, eval_json, raw_text=raw_eval_text, sent=sent, token=os.environ.get('TELEGRAM_BOT_TOKEN'), max_len=1000)
                        # Record result or error into telegram_post_comments
                        try:
                            comment_record_update = {'post_result': post_result, 'post_result_at': datetime.utcnow().isoformat()}
                            # update the same comment record we added earlier (best-effort: add a separate doc if update fails)
                            db.collection('telegram_post_comments').add({**comment_record, **comment_record_update})
                        except Exception:
                            logger.exception('Failed to record telegram_post_comments post result for %s', article_id)
                    except Exception:
                        logger.exception('Failed to post eval to Telegram for %s', article_id)
                except Exception:
                    logger.exception('Failed to post eval as Telegram reply for %s', article_id)
        except Exception:
            logger.exception('Failed to save telegram post comment for %s', article_id)

    except Exception:
        logger.exception('Translation evaluation step failed for %s', article_id)

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
