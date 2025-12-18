
import json
import logging
import datetime
from workers.tools.pg_client import get_pg_client
from workers.tools.openai_client import get_openai_client, chat_completion

logger = logging.getLogger(__name__)

def generate_digest() -> str:
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
            SELECT total_score, telegram_final, description_ru   
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
            # total_score, telegram_final, description_ru
            total_score = float(r[0]) if r[0] is not None else 0
            tg_final = r[1]
            desc = r[2]

            # Normalize telegram_final
            final_text = ""
            if isinstance(tg_final, dict):
                final_text = tg_final.get('tg_preview') or tg_final.get('text') or ""
            elif isinstance(tg_final, str):
                final_text = tg_final
            
            # Fallback to description if telegram_final is empty (unlikely for published)
            if not final_text:
                final_text = desc

            news_items.append({
                "total_score": total_score,
                "text": final_text
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
- Не выводи полные URL.
- Используй ровно ОДНУ Markdown-ссылку внутри текста новости.
- Ссылка должна быть встроена в 1–3 ключевых слова из текста.

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
            return "Error: Failed to generate digest text from OpenAI"
        promo_line = "\n\nПодписывайтесь на наш канал: [Испания, ке паса](https://t.me/spain_kepasa)"

        try:
            return (response_text + promo_line).strip()
        except Exception:
            return response_text

    except Exception as e:
        logger.error(f"Error generating evening brief: {e}")
        return f"Error: {e}"
