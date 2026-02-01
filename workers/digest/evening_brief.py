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
from workers.tools.digest_carousel_generator import DigestCarouselGenerator
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
            system_prompt = """
You create image prompts for evening news digest covers.

Your goal is a sophisticated editorial cover illustration with photographic depth,
used by modern international media (e.g. Meduza, NYT Opinion, The Economist, Bloomberg Weekend).

Create ONE visual prompt for DALL·E 3 in English.
Return ONLY the final image prompt.

GLOBAL STYLE RULES (ALWAYS APPLY):
- Editorial illustration with photographic realism (not a photo, not flat vector).
- Rich textures, depth, light and shadow, no hard outlines.
- Painterly or cinematic realism, never cartoon or comic.
- No flat vector style, no infographic look, no icons.
- No text, no logos, no symbols or obvious metaphors.
- No crowds, no close-up faces, no public figures.

REALISM GUARDRAILS:
- Avoid perfectly clean or idealized scenes.
- Allow subtle imperfections: uneven light, atmospheric haze, worn surfaces, slight asymmetry.
- The image should feel observed, not designed.

CONTENT LOGIC:
- The image represents the overall mood of the digest, not individual headlines.
- Spain or Southern Europe should be implied through architecture, landscape, light, or atmosphere — never through flags or symbols.
- Combine environment, economy, infrastructure, climate, or urban life subtly into one coherent scene.

COMPOSITION:
- Wide editorial cover composition.
- One dominant scene with layered background elements.
- Balanced but imperfect framing, no symmetry.

HUMAN PRESENCE RULES:
- Human presence is optional.
- If humans appear, avoid single isolated figures centered in the frame.
- Prefer indirect presence (shadows, partial figures, reflections, small groups in background).

LIGHT & COLOR:
- Natural editorial lighting.
- Muted, complex color palette with depth (Mediterranean tones allowed).
- Avoid high saturation and graphic contrast.

VARIATION DIRECTIVE:
- Each image should explore a different visual angle: interior vs exterior, ground level vs elevated view, open space vs dense environment.

STYLE ANCHORS:
- Choose 1–2 artistic anchors from: cinematic still realism, painterly editorial realism, atmospheric analog photography texture, modern editorial illustration with depth.
- Do not reuse the same combination repeatedly.

The final prompt must describe:
- setting
- atmosphere
- dominant visual elements
- light and color mood
- artistic style anchors
"""
            try:
                image_prompt = chat_completion(
                    client=client,
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": f"Digest preview:\n{first_lines}\n\nGenerate image prompt:"},
                    ],
                    max_tokens=100,
                    temperature=0.7,
                )
                if not image_prompt:
                    raise Exception("No image prompt generated")
                image_prompt = image_prompt.strip()
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


def _html_to_facebook_text(html: str) -> str:
    """Convert HTML to Facebook-compatible text with preserved URLs."""
    if not html:
        return ""
    import re
    # Preserve links in format: text (url)
    text = re.sub(r'<a href="(.*?)">(.*?)</a>', r'\2 (\1)', html)
    # Remove bold/italic tags
    text = re.sub(r'<b>(.*?)</b>', r'\1', text)
    text = re.sub(r'<i>(.*?)</i>', r'\1', text)
    # Remove any remaining HTML tags
    text = re.sub(r'<.*?>', '', text)
    # Decode HTML entities
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


def publish_content(content_dict: dict, channels: list, job_id: str = 'evening_brief', image_url: str = None):
    """Publish content to multiple platforms using platform-specific formats.
    
    Args:
        content_dict: Dict with 'telegram', 'facebook', 'reels_script' keys
        channels: List of Telegram channel IDs
        job_id: Job identifier
        image_url: Optional cover image URL
    """
    # Handle both old format (string) and new format (dict)
    if isinstance(content_dict, str):
        telegram_content = content_dict
        facebook_content = content_dict
    else:
        telegram_content = content_dict.get('telegram', '')
        facebook_content = content_dict.get('facebook', '')
        reels_script = content_dict.get('reels_script', '')
        if reels_script:
            logger.info(f"📹 Reels script generated:\n{reels_script[:200]}...")
    
    if not telegram_content:
        logger.warning("No content to publish")
        return {}
    
    telegram_token = os.getenv('TELEGRAM_BOT_TOKEN')
    if not telegram_token:
        logger.warning("⚠️ TELEGRAM_BOT_TOKEN not set")
    if image_url:
        logger.info(f'🖼️ Using digest cover image: {image_url}')
    
    # Convert telegram markdown to HTML for Telegram API
    html_content = _markdown_to_telegram_html(telegram_content)
    results = {}
    
    # Publish to Telegram channels
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
    
    # Publish to Facebook using Facebook-specific content
    try:
        fb_text = facebook_content if facebook_content else _html_to_facebook_text(html_content)
        fb_result = post_facebook(media_url=image_url, message=fb_text)
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
                                # Step 2: Try sending as regular message with media
                                try:
                                    if original_message.media:
                                        await client.send_message(target, original_message.text, file=original_message.media, link_preview=False)
                                    else:
                                        await client.send_message(target, original_message.text, link_preview=False)
                                    logger.info(f"✅ Sent as regular message to {target}")
                                except Exception as send_error:
                                    logger.warning(f"Failed to send regular message to {target}: {send_error}")
                                    # Step 3: Try sending without media
                                    try:
                                        await client.send_message(target, original_message.text, link_preview=False)
                                        logger.info(f"✅ Sent without media to {target}")
                                    except Exception as no_media_error:
                                        logger.warning(f"Failed to send without media to {target}: {no_media_error}")
                                        # Step 4: Try sending with media but without links
                                        try:
                                            import re
                                            text_no_links = re.sub(r'https?://\S+', '', original_message.text)
                                            if original_message.media:
                                                await client.send_message(target, text_no_links, file=original_message.media, link_preview=False)
                                            else:
                                                await client.send_message(target, text_no_links, link_preview=False)
                                            logger.info(f"✅ Sent without links to {target}")
                                        except Exception as final_error:
                                            logger.error(f"All send attempts failed for {target}: {final_error}")
                        # Pause 15 seconds between republish attempts
                        await asyncio.sleep(15)
                    for target in send_only_targets:
                        try:
                            await client.forward_messages(target, source_msg, source_chat)
                            logger.info(f"✅ Forwarded to restricted group {target}")
                        except Exception as forward_error:
                            logger.warning(f"Forward to restricted group {target} failed: {forward_error}")
                            if original_message and original_message.text:
                                # Step 2: Try sending as regular message with media
                                try:
                                    if original_message.media:
                                        await client.send_message(target, original_message.text, file=original_message.media, link_preview=False)
                                    else:
                                        await client.send_message(target, original_message.text, link_preview=False)
                                    logger.info(f"✅ Sent message to restricted group {target}")
                                except Exception as send_error:
                                    logger.warning(f"Failed to send to restricted group {target}: {send_error}")
                                    # Step 3: Try sending without media
                                    try:
                                        await client.send_message(target, original_message.text, link_preview=False)
                                        logger.info(f"✅ Sent without media to restricted group {target}")
                                    except Exception as no_media_error:
                                        logger.warning(f"Failed to send without media to restricted group {target}: {no_media_error}")
                                        # Step 4: Try sending with media but without links
                                        try:
                                            import re
                                            text_no_links = re.sub(r'https?://\S+', '', original_message.text)
                                            if original_message.media:
                                                await client.send_message(target, text_no_links, file=original_message.media, link_preview=False)
                                            else:
                                                await client.send_message(target, text_no_links, link_preview=False)
                                            logger.info(f"✅ Sent without links to restricted group {target}")
                                        except Exception as final_error:
                                            logger.error(f"All send attempts failed for restricted group {target}: {final_error}")
                        # Pause 15 seconds between republish attempts
                        await asyncio.sleep(15)
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
            SELECT total_score, telegram_final, description_ru, slug, image_url, title_ru
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
            # total_score, telegram_final, description_ru, slug, image_url, title_ru
            total_score = float(r[0]) if r[0] is not None else 0
            tg_final = r[1]
            desc = r[2]
            slug = r[3]
            image_url = r[4]  # image_url from articles_ru
            title_ru = r[5]   # title_ru from articles_ru

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
                "url": article_url,
                "title_ru": title_ru,  # Pass to OpenAI for carousel titles
                "image_url": image_url  # Pass to OpenAI - will be returned in carousel_items
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

        system_prompt = """Ты — редактор вечернего дайджеста новостей для разных платформ.

Твоя задача — создать контент на основе входных новостей для трёх форматов:
1. Telegram-пост (Markdown)
2. Facebook-пост (обычный текст)
3. Сценарий для Instagram/Facebook Reels на 30 секунд

Отбор и приоритет новостей:
- Используй НЕ БОЛЕЕ 5 новостей.
- Приоритизируй: 1) экономика и цены, 2) безопасность и контроль, 3) всё остальное.

=== ФОРМАТ TELEGRAM ===
- Общая длина поста — не более 700 символов.
- Каждая новость — не длиннее 140 символов (включая ссылку).
- Заголовок: **🌆 Вечерний дайджест. Испания**
- Каждая новость — один абзац, 1–2 коротких предложения, с пустой строкой между новостями.
- Эмодзи только как маркер перед новостью.
- Markdown-ссылка внутри текста: [ключевые слова](url)
- Используй ТОЛЬКО предоставленные URL из JSON.

=== ФОРМАТ FACEBOOK ===
- Заголовок: 🌆 Вечерний дайджест. Испания
- Каждая новость в формате:
  * Эмодзи + короткий текст новости (1-2 предложения)
  * Пустая строка
  * Полная ссылка на отдельной строке (https://...)
  * Пустая строка перед следующей новостью
- Без Markdown, только эмодзи и обычный текст.
- НЕ используй формат "текст (url)" — выводи ссылку на отдельной строке.
- Общая длина — не более 1200 символов.

=== СЦЕНАРИЙ ДЛЯ REELS (30 сек) ===
- Текст для озвучки видео на 30 секунд (для text-to-audio модели).
- ТОЛЬКО текст, который будет произносить голос, БЕЗ технических описаний и визуала.
- Структура:
  * Привлекающее внимание вступление (2-3 секунды)
  * Краткое изложение 3-4 главных новостей (по 5-7 секунд каждая)
  * Призыв подписаться на канал (2-3 секунды)
- Динамичный разговорный стиль, короткие предложения.
- Без ссылок, без эмодзи, только текст для озвучки.
- Общая длина текста: 60-80 слов (примерно 30 секунд речи).

=== КАРУСЕЛЬ ДЛЯ INSTAGRAM ===
- Выбери ТОП-5 новостей для карусели (те же, что использовал в digest).
- Для каждой новости верни: короткий заголовок (title_ru), URL и image_url.
- Заголовок должен быть коротким (максимум 80-100 символов) и понятным.
- Используй image_url из входных данных (не придумывай свои).

Содержание:
- Не переписывай заголовки буквально.
- Только факты из входных данных.
- Без аналитики и выводов.

ВЫВОД: Верни ТОЛЬКО валидный JSON. НЕ используй markdown блоки. НЕ добавляй пояснений. Начни ответ с символа "{" и закончи символом "}".

Пример формата ответа:
{"telegram": "текст в Markdown", "facebook": "текст для Facebook", "reels_script": "сценарий для видео", "carousel_items": [{"title_ru": "Заголовок новости 1", "url": "https://...", "image_url": "https://..."}]}"""

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
            model="gpt-5.2-chat",  # Прямо Azure deployment для мощной генерации
            messages=messages
        )

        if not response_text:
            logger.error("Failed to generate digest text from OpenAI")
            return None
        
        # Log the raw response to debug carousel issue
        logger.info(f"Raw OpenAI response: {response_text[:500]}...")
        
        # Parse JSON response
        try:
            # Remove markdown code blocks if present
            cleaned_response = response_text.strip()
            if cleaned_response.startswith('```'):
                cleaned_response = cleaned_response.split('\n', 1)[1]
                cleaned_response = cleaned_response.rsplit('```', 1)[0]
            
            parsed = json.loads(cleaned_response)
            telegram_content = parsed.get('telegram', '')
            facebook_content = parsed.get('facebook', '')
            reels_script = parsed.get('reels_script', '')
            carousel_items = parsed.get('carousel_items', [])
            
            # Debug carousel parsing
            logger.info(f"Parsed carousel_items: {len(carousel_items)} items")
            if carousel_items:
                for i, item in enumerate(carousel_items[:3]):  # Log first 3
                    logger.info(f"  Item {i+1}: title='{item.get('title_ru', '')}', has_image={bool(item.get('image_url'))}")
            else:
                logger.warning("No carousel_items found in OpenAI response")
        except Exception as e:
            logger.error(f"Failed to parse JSON response: {e}. Using response as telegram content.")
            telegram_content = response_text
            facebook_content = response_text
            reels_script = ""
            carousel_items = []
        
        # Add promo line to telegram and facebook
        promo_line_tg = "\n\nПодписывайтесь на наш канал: [Испания, ке паса](https://t.me/spain_kepasa)"
        promo_line_fb = "\n\nПодписывайтесь на наш канал: Испания, ке паса (https://t.me/spain_kepasa)"
        
        telegram_final = (telegram_content + promo_line_tg).strip()
        facebook_final = (facebook_content + promo_line_fb).strip() if facebook_content else ""

        # Generate cover image based on telegram content
        try:
            image_url = _generate_digest_image_for_brief(telegram_final, job_id="evening_brief")
        except Exception:
            image_url = None

        return {
            "telegram": telegram_final,
            "facebook": facebook_final,
            "reels_script": reels_script,
            "image_url": image_url,
            "carousel_items": carousel_items
        }

    except Exception as e:
        logger.error(f"Error generating evening brief: {e}")
        return None


def run_job(job: dict):
    """Full pipeline for evening brief: generate, save, publish, republish."""
    try:
        result = generate_digest()
        
        # Extract content from result
        if isinstance(result, dict):
            telegram_content = result.get('telegram', '')
            facebook_content = result.get('facebook', '')
            reels_script = result.get('reels_script', '')
            image_url = result.get('image_url')
            carousel_items_from_openai = result.get('carousel_items', [])
        else:
            telegram_content = result
            facebook_content = result
            reels_script = ''
            image_url = None
            carousel_items_from_openai = []
        
        if not telegram_content:
            logger.error("No content generated")
            return None
        
        # Respect dry-run: generate (and optionally save) but skip publishing
        dry_run = bool(job.get('dry_run', False))
        try:
            # Save telegram content as translation
            _maybe_save_translation(job, telegram_content)
        except Exception:
            logger.debug('Failed to save translation in run_job')
        
        if dry_run:
            logger.info("🧪 Dry-run enabled: skipping publish/republish")
            logger.info("\n" + "="*60)
            logger.info("📱 TELEGRAM CONTENT:")
            logger.info("="*60)
            logger.info(telegram_content)
            logger.info("\n" + "="*60)
            logger.info("📘 FACEBOOK CONTENT:")
            logger.info("="*60)
            logger.info(facebook_content)
            logger.info("\n" + "="*60)
            logger.info("📹 REELS SCRIPT:")
            logger.info("="*60)
            logger.info(reels_script)
            if image_url:
                logger.info("\n" + "="*60)
                logger.info(f"🖼️ IMAGE URL: {image_url}")
                logger.info("="*60)
            return {
                "telegram": telegram_content,
                "facebook": facebook_content,
                "reels_script": reels_script,
                "image_url": image_url,
                "published": False
            }

        channels = job.get('channels', [])
        content_dict = {
            'telegram': telegram_content,
            'facebook': facebook_content,
            'reels_script': reels_script
        }
        publish_results = publish_content(content_dict, channels, job_id=job.get('id', 'evening_brief'), image_url=image_url)
        
        # Generate Instagram carousel after publishing
        try:
            logger.info("📸 Generating Instagram carousel...")
            
            # OpenAI already returned carousel_items with image_url - no enrichment needed!
            carousel_data = [
                item for item in carousel_items_from_openai 
                if item.get('title_ru') and item.get('image_url')
            ]
            
            logger.info(f"Received {len(carousel_data)} carousel items from OpenAI")
            
            if len(carousel_data) >= 5 and image_url:
                # Initialize carousel generator
                carousel_gen = DigestCarouselGenerator(output_dir="output/instagram_carousel")
                
                # Download Telegram image to use as title slide
                import tempfile
                import requests
                from pathlib import Path
                
                # Create temp directory for title image
                temp_dir = Path("output/temp_digest")
                temp_dir.mkdir(parents=True, exist_ok=True)
                title_image_path = temp_dir / "telegram_title.jpg"
                
                # Download image from URL
                response = requests.get(image_url, timeout=15)
                response.raise_for_status()
                with open(title_image_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"Downloaded title image: {title_image_path}")
                
                # Generate carousel slides
                slides_data = carousel_gen.generate_carousel_slides(
                    title_image_path=str(title_image_path),
                    news_items=carousel_data,
                    digest_title="Испания, вечерний дайджест"
                )
                
                if slides_data:
                    logger.info(f"✅ Instagram carousel generated: {len(slides_data)} slides")
                    logger.info(f"Slides saved in: {carousel_gen.output_dir}")
                    for idx, slide in enumerate(slides_data, 1):
                        logger.info(f"  {idx}. {Path(slide['path']).name}")
                        logger.info(f"     Caption: {slide['caption'][:80]}...")
                else:
                    logger.warning("Failed to generate carousel slides")
                    
            else:
                logger.warning(f"Cannot generate carousel: found {len(carousel_data)} news items with images (need 5), image_url={bool(image_url)}")
                
        except Exception as e:
            logger.error(f"Failed to generate Instagram carousel: {e}", exc_info=True)
        
        # ВРЕМЕННО ЗАБЛОКИРОВАНО: репосты в другие группы
        # repub = job.get('republish', [])
        # if repub:
        #     # Use telegram content for republishing
        #     republish_content(telegram_content, repub, original_results=publish_results)
        
        return publish_results
    except Exception as e:
        logger.error(f"Error running evening brief job: {e}")
        return None
