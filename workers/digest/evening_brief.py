import json
import logging
import datetime
import time
import os
from pathlib import Path
from workers.tools.pg_client import get_pg_client
from workers.tools.openai_client import get_openai_client, chat_completion
from workers.article_generator.image_generator import ImageGenerator
from workers.tools.telegram_helper import send_message, send_photo
from workers.tools.facebook_helper import post_facebook
from telethon import TelegramClient
from telethon.tl.types import Channel, Chat

logger = logging.getLogger(__name__)

def _generate_digest_image_for_brief(content: str, job_id: str = "evening_brief") -> str:
    """Generate a cover image for the evening brief and return local file path or URL.

    Uses DALL-E 3 (Azure or OpenAI) with a minimalist editorial illustration style.
    Returns None on failure.
    """
    try:
        image_gen = ImageGenerator(model="dall-e-3")
    except Exception as e:
        logger.warning(f"Failed to initialize ImageGenerator: {e}")
        return None

    try:
        first_lines = "\n".join((content or "").split("\n")[:5])
        client = get_openai_client()
        if client:
            system_prompt = (
                "You create image prompts for news digest covers. Your goal is a high-end, minimalist "
                "editorial illustration in the style of The New Yorker or Meduza.\n\n"
                "Create a 1-sentence visual prompt for DALL-E 3. \n\n"
                "STYLE RULES:\n"
                "- Minimalist vector-style editorial illustration.\n"
                "- Clean lines, limited sophisticated color palette (e.g., muted blue, deep ochre, slate grey).\n"
                "- Conceptual and metaphor-driven imagery related to Spanish news (infrastructure, heat, bureaucracy, or Mediterranean landscape).\n"
                "- No text, no logos, no complex crowd scenes.\n"
                "- Composition: bold, central focus, lots of negative space.\n\n"
                "Return ONLY the image prompt in English."
            )
            try:
                resp = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Digest preview:\n{first_lines}\n\nGenerate image prompt:"},
                    ],
                    max_tokens=100,
                    temperature=0.7,
                )
                image_prompt = resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"Failed to generate image prompt: {e}")
                image_prompt = (
                    "minimalist vector-style editorial illustration, Spanish news digest theme, clean lines, "
                    "muted blue and ochre palette, central focus, negative space, The New Yorker style"
                )
        else:
            image_prompt = (
                "clean minimal comic-style illustration, Que Pasa brand vibe, Spanish news digest theme, colorful but professional"
            )

        # Generate image
        logger.info(f"Generating evening brief cover image with prompt: {image_prompt[:100]}...")
        if image_gen.use_azure:
            image_url = image_gen._generate_with_azure_dalle(image_prompt)
        else:
            resp = image_gen.client.images.generate(
                model="dall-e-3",
                prompt=image_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
            )
            if resp.data and len(resp.data) > 0:
                image_url = resp.data[0].url
            else:
                logger.warning("No image generated")
                return None

        if not image_url:
            return None

        # Save and return local path preferred
        doc_id = f"digest_{job_id}_{int(time.time())}"
        local_path = image_gen._download_and_save_image(image_url, doc_id)
        if local_path:
            try:
                project_root = Path(__file__).resolve().parent.parent.parent
                fs_path = project_root / local_path
                if fs_path.exists():
                    logger.info(f"✅ Evening brief cover image generated (saved locally): {fs_path}")
                    return str(fs_path)
            except Exception:
                pass
            web_url = f"https://ke-pasa.es/images/news/{doc_id}.jpg"
            logger.info(f"✅ Evening brief cover image generated: {web_url}")
            return web_url

        return image_url
    except Exception as e:
        logger.exception(f"Failed to generate evening brief image: {e}")
        return None


def _markdown_to_telegram_html(text: str) -> str:
    if not text:
        return ""
    import re
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    text = re.sub(r'^#+\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
    text = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', text)
    text = re.sub(r'\*(.+?)\*', r'<i>\1</i>', text)
    text = re.sub(r'\[(.+?)\]\((.+?)\)', r'<a href="\2">\1</a>', text)
    text = re.sub(r'^\s*\*\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
    return text


def _html_to_plain_text(html: str) -> str:
    if not html:
        return ""
    import re
    text = re.sub(r'<b>(.*?)</b>', r'\1', html)
    text = re.sub(r'<i>(.*?)</i>', r'\1', text)
    text = re.sub(r'<a href="(.*?)">(.*?)</a>', r'\2', text)
    text = re.sub(r'<.*?>', '', text)
    text = text.replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')
    return text.strip()


def _maybe_save_translation(job: dict, content: str):
    if not content:
        return None
    try:
        save_flag = bool(job.get('save_translations', False))
    except Exception:
        save_flag = False
    if not save_flag:
        save_flag = os.getenv('SAVE_TRANSLATIONS', 'false').lower() in ('1', 'true', 'yes')
    if not save_flag:
        return None

    out_dir = os.getenv('SAVE_TRANSLATIONS_DIR')
    out_path = Path(out_dir) if out_dir else Path(__file__).parent / 'translations'
    try:
        out_path.mkdir(parents=True, exist_ok=True)
        gi = out_path / '.gitignore'
        if not gi.exists():
            gi.write_text("*\n!.gitignore\n", encoding='utf-8')
        job_id = job.get('id', 'unknown')
        ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        filename = out_path / f"{job_id}_{ts}.md"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(content)
        logger.info(f"💾 Saved translation for job '{job_id}' -> {filename}")
        return str(filename)
    except Exception as e:
        logger.error(f"Failed to save translation file: {e}")
        return None


def publish_content(content: str, channels: list, job_id: str = 'evening_brief', image_url: str = None):
    if not content:
        logger.warning("No content to publish")
        return {}
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not telegram_token:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set")
    if image_url:
        logger.info(f'🖼️ Using digest cover image: {image_url}')
    html_content = _markdown_to_telegram_html(content)
    results = {}
    for channel in channels:
        try:
            logger.info(f"Sending digest to {channel}...")
            if image_url:
                res = send_photo(chat_id=channel, photo_url=image_url, caption=html_content, token=telegram_token, parse_mode='HTML')
                logger.info(f"✅ Sent digest with image to {channel}")
            else:
                res = send_message(channel, html_content, token=telegram_token, parse_mode='HTML')
                logger.info(f"✅ Sent text-only digest to {channel}")
            results[channel] = res
        except Exception as e:
            results[channel] = None
            logger.error(f"❌ Failed to send to {channel}: {e}")
    try:
        plain_text = _html_to_plain_text(html_content)
        fb_result = post_facebook(message=plain_text, image_url=image_url)
        results['facebook'] = fb_result
    except Exception as e:
        logger.error(f"❌ Error posting to Facebook: {e}")
        results['facebook'] = None
    return results


def republish_content(content: str, republish_channels: list, original_results: dict = None):
    if not republish_channels:
        return
    api_id = os.getenv('TELETHON_API_ID')
    api_hash = os.getenv('TELETHON_API_HASH')
    session_name = os.getenv('TELETHON_SESSION', 'republish_session')
    if not api_id or not api_hash:
        logger.warning("Telethon credentials not set; skipping republish")
        return
    try:
        api_id_int = int(api_id)
    except Exception:
        logger.error("Invalid TELETHON_API_ID")
        return

    source_msg = None
    source_chat = None
    if original_results:
        for ch, res in (original_results or {}).items():
            if not res:
                continue
            try:
                msg_id = res.get('message_id') or (res.get('message') or {}).get('message_id')
            except Exception:
                msg_id = None
            try:
                chat_info = res.get('chat') or res.get('sender_chat') or {}
                chat_id = chat_info.get('id') if isinstance(chat_info, dict) else None
                if not chat_id:
                    chat_id = chat_info.get('username') if isinstance(chat_info, dict) else None
            except Exception:
                chat_id = None
            if msg_id and chat_id:
                source_msg = int(msg_id)
                source_chat = chat_id
                break
    if not source_msg or not source_chat:
        logger.warning("No source message available to forward; skipping republish")
        return

    try:
        import asyncio

        async def _forward_async():
            async with TelegramClient(session_name, api_id_int, api_hash) as client:
                try:
                    authorized = await client.is_user_authorized()
                    if not authorized:
                        logger.warning("Telethon client not authorized; skipping republish")
                        return
                    exclude_usernames = set(['spain_kepasa'])
                    targets = []
                    send_only_targets = []
                    async for dialog in client.iter_dialogs():
                        ent = dialog.entity
                        uname = getattr(ent, 'username', None)
                        is_group = False
                        if isinstance(ent, Channel):
                            is_group = not getattr(ent, 'broadcast', False)
                        elif isinstance(ent, Chat):
                            is_group = True
                        if not is_group:
                            continue
                        if uname and uname in exclude_usernames:
                            continue
                        can_send = True
                        if isinstance(ent, Channel):
                            banned_rights = getattr(ent, 'banned_rights', None)
                            if banned_rights and getattr(banned_rights, 'send_messages', False):
                                can_send = False
                        target_id = f"@{uname}" if uname else ent.id
                        if can_send:
                            targets.append(target_id)
                        else:
                            send_only_targets.append(target_id)
                    original_message = None
                    try:
                        original_message = await client.get_messages(source_chat, ids=source_msg)
                    except Exception as e:
                        logger.warning(f"Could not fetch original message: {e}")
                    for target in targets:
                        try:
                            await client.forward_messages(target, source_msg, source_chat)
                            logger.info(f"✅ Forwarded to {target}")
                        except Exception as forward_error:
                            logger.error(f"Failed to forward to {target}: {forward_error}")
                            if original_message and original_message.text:
                                try:
                                    await client.send_message(target, original_message.text, link_preview=False)
                                    logger.info(f"✅ Sent as regular message to {target}")
                                except Exception as send_error:
                                    logger.error(f"Failed to send regular message to {target}: {send_error}")
                    for target in send_only_targets:
                        try:
                            await client.forward_messages(target, source_msg, source_chat)
                            logger.info(f"✅ Forwarded to restricted group {target}")
                        except Exception as forward_error:
                            logger.warning(f"Forward to restricted group {target} failed: {forward_error}")
                            if original_message and original_message.text:
                                try:
                                    await client.send_message(target, original_message.text, link_preview=False)
                                    logger.info(f"✅ Sent message to restricted group {target}")
                                except Exception as send_error:
                                    logger.error(f"Cannot send to restricted group {target}: {send_error}")
                except Exception as e:
                    logger.error(f"Telethon forward error: {e}")
        asyncio.run(_forward_async())
    except Exception as e:
        logger.error(f"Telethon error: {e}")


def generate_digest() -> dict:
    """
    Generates the evening brief digest using OpenAI.
    1. Fetches relevant articles from Postgres.
    2. Sends them to GPT-4o-mini with the specific prompt.
    3. Returns the generated Markdown.
    """
    try:
        # 1. Fetch articles
        pg = get_pg_client()
        conn, pooled = pg._get_conn()
        cur = conn.cursor()
        
        sql = """
            SELECT total_score, telegram_final, description_ru, slug 
            FROM articles_ru
            WHERE published_at > now() - INTERVAL '1 day'
              AND status = 'PUBLISHED'
            ORDER BY total_score DESC;
        """
        
        cur.execute(sql)
        rows = cur.fetchall()
        
        # Release connection back
        try:
            cur.close()
            pg._put_conn(conn, pooled)
        except Exception:
            pass

        if not rows:
            logger.info("No articles found for evening brief")
            return "No news today."

        # 2. Pack result into JSON
        news_items = []
        for r in rows:
            # total_score, telegram_final, description_ru, slug
            total_score = float(r[0]) if r[0] is not None else 0
            tg_final = r[1]
            desc = r[2]
            slug = r[3]

            # Normalize telegram_final
            final_text = ""
            if isinstance(tg_final, dict):
                final_text = tg_final.get('tg_preview') or tg_final.get('text') or ""
            elif isinstance(tg_final, str):
                final_text = tg_final
            
            # Fallback to description if telegram_final is empty (unlikely for published)
            if not final_text:
                final_text = desc

            # Generate article URL from slug
            article_url = f"https://ke-pasa.es/news/{slug}/" if slug else ""

            news_items.append({
                "total_score": total_score,
                "text": final_text,
                "url": article_url
            })

        news_json = json.dumps(news_items, ensure_ascii=False, indent=2)

        # 3. Call OpenAI
        client = get_openai_client()
        if not client:
            return "Error: OpenAI client not available"

        # Generate dynamic date in Russian
        months = [
            "", "января", "февраля", "марта", "апреля", "мая", "июня",
            "июля", "августа", "сентября", "октября", "ноября", "декабря"
        ]
        now = datetime.datetime.now()
        date_str = f"{now.day} {months[now.month]} {now.year}"

        system_prompt = """Ты — редактор вечернего Telegram-канала.

Твоя задача — формировать ОДИН короткий Telegram-пост в формате вечернего дайджеста на основе входных новостей.

КРИТИЧЕСКИ ВАЖНО:
- Ответ должен быть выведен СТРОГО в формате Markdown, совместимом с Telegram.
- Общая длина поста — не более 700 символов.

Отбор и приоритет:
- Используй НЕ БОЛЕЕ 5 новостей.
- Приоритизируй новости в следующем порядке:
  1) экономика и цены,
  2) безопасность и контроль,
  3) всё остальное.
- Если новостей больше — отбрасывай менее важные.

Ограничение длины:
- КАЖДАЯ новость (включая встроенную ссылку) должна быть не длиннее 140 символов.

Формат:
- Заголовок: **🌆 Вечерний дайджест. Испания**
- Каждая новость — один абзац, 1–2 коротких предложения.
- Пустая строка между новостями.
- Используй эмодзи только как маркер перед новостью.
- Не используй категории, подзаголовки и списки.

Ссылки:
- ОБЯЗАТЕЛЬНО используй предоставленную ссылку (поле url) для каждой новости.
- Не выводи полные URL.
- Используй ровно ОДНУ Markdown-ссылку внутри текста новости в формате [текст](url).
- Ссылка должна быть встроена в 1–3 ключевых слова из текста.
- Используй ТОЛЬКО предоставленные URL из JSON, не придумывай свои.

Содержание:
- Не переписывай заголовки буквально.
- Не добавляй факты, которых нет во входных данных.
- Без аналитики, выводов и итогов.

Выводи ТОЛЬКО готовый текст Telegram-поста в Markdown."""

        user_prompt_content = f"""Сформируй вечернюю Telegram-заметку.

Дата: {date_str}
Регион: Испания

Новости (JSON):
{news_json}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt_content}
        ]

        logger.info(f"Generating digest from {len(news_items)} items...")
        response_text = chat_completion(
            client=client,
            model="gpt-5.1",
            messages=messages
        )

        if not response_text:
            return {"content": "Error: Failed to generate digest text from OpenAI", "image_url": None}
        promo_line = "\n\nПодписывайтесь на наш канал: [Испания, ке паса](https://t.me/spain_kepasa)"

        try:
            final_text = (response_text + promo_line).strip()
        except Exception:
            final_text = response_text

        # Generate cover image as part of the evening digest
        try:
            image_url = _generate_digest_image_for_brief(final_text, job_id="evening_brief")
        except Exception:
            image_url = None

        return {"content": final_text, "image_url": image_url}

    except Exception as e:
        logger.error(f"Error generating evening brief: {e}")
        return {"content": f"Error: {e}", "image_url": None}


def run_job(job: dict):
    """Full pipeline for evening brief: generate, save, publish, republish."""
    try:
        result = generate_digest()
        content = result.get('content') if isinstance(result, dict) else result
        image_url = result.get('image_url') if isinstance(result, dict) else None
        if not content:
            logger.error("No content generated")
            return None
        # Respect dry-run: generate (and optionally save) but skip publishing
        dry_run = bool(job.get('dry_run', False))
        try:
            _maybe_save_translation(job, content)
        except Exception:
            logger.debug('Failed to save translation in run_job')
        if dry_run:
            logger.info("🧪 Dry-run enabled: skipping publish/republish")
            return {"content": content, "image_url": image_url, "published": False}

        channels = job.get('channels', [])
        publish_results = publish_content(content, channels, job_id=job.get('id', 'evening_brief'), image_url=image_url)
        repub = job.get('republish', [])
        if repub:
            republish_content(content, repub, original_results=publish_results)
        return publish_results
    except Exception as e:
        logger.error(f"Error running evening brief job: {e}")
        return None
