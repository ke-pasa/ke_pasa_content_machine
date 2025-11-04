#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для генерации контента на основе кластеров
Генерирует статьи для сайта и Telegram-посты с использованием OpenAI
"""

import os
import json
import time
import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Union
from pathlib import Path
from openai import OpenAI
from slugify import slugify
from workers.tools.firebase_client import FirebaseClient


def _get_openai_client() -> Optional[OpenAI]:
    """
    Создает и возвращает OpenAI клиент
    
    Returns:
        OpenAI клиент или None если API ключ не найден
    """
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        logging.warning("OPENAI_API_KEY не найден в переменных окружения")
        return None
    
    try:
        return OpenAI(api_key=api_key)
    except Exception as e:
        logging.error(f"Ошибка инициализации OpenAI клиента: {e}")
        return None


def _extract_json_from_response(response_text: str) -> Optional[Dict[str, Any]]:
    """
    Извлекает JSON из ответа LLM
    
    Args:
        response_text: Текст ответа от LLM
        
    Returns:
        Словарь с данными или None при ошибке
    """
    try:
        # Ищем JSON в ответе (может быть обернут в markdown)
        json_start = response_text.find('{')
        json_end = response_text.rfind('}') + 1
        if json_start != -1 and json_end > json_start:
            json_str = response_text[json_start:json_end]
            return json.loads(json_str)
        else:
            logging.warning(f"JSON не найден в ответе: {response_text[:200]}...")
            return None
    except json.JSONDecodeError as e:
        logging.error(f"Ошибка парсинга JSON: {e}")
        return None


def _is_valid_image_url(url: str) -> bool:
    """
    Простейшая валидация URL изображения для использования в статье/экспорте
    """
    if not url or not isinstance(url, str):
        return False
    url_lower = url.lower().strip()
    if not (url_lower.startswith('http://') or url_lower.startswith('https://')):
        return False
    # Проверяем расширение файла
    image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
    if not any(ext in url_lower for ext in image_extensions):
        return False
    # Исключаем явные не-картинки
    non_image_patterns = ['/ads/', '/banner/', '/logo/', '/icon/']
    if any(p in url_lower for p in non_image_patterns):
        return False
    return True


def generate_article(cluster: Dict[str, Any], as_markdown: bool = False) -> Union[Dict[str, Any], str]:
    """
    Генерирует статью для сайта на основе кластера.
    Использует OpenAI (gpt-5-mini) с улучшенным промптом для русскоязычных мигрантов.
    
    Args:
        cluster: Словарь с данными кластера
        as_markdown: Если True, возвращает Markdown с frontmatter, иначе JSON
        
    Returns:
        Словарь с сгенерированной статьей или Markdown строка
    """
    openai_client = _get_openai_client()
    if not openai_client:
        logging.error("OpenAI клиент не инициализирован")
        return None
    
    # Извлекаем данные из кластера
    topic_summary = cluster.get('topic_summary', '')
    combined_context = cluster.get('combined_context', '')
    sources = cluster.get('sources', [])
    
    if not topic_summary or not combined_context:
        logging.error("Недостаточно данных в кластере для генерации статьи")
        return None
    
    # ОГРАНИЧИВАЕМ РАЗМЕР combined_context для предотвращения превышения лимита токенов
    # OpenAI gpt-5-mini имеет лимит 128,000 токенов
    # Оставляем запас для системного промпта и других частей
    MAX_CONTEXT_LENGTH = 400000  # ~100,000 токенов (с запасом)
    
    if len(combined_context) > MAX_CONTEXT_LENGTH:
        logging.warning(f"⚠️ combined_context слишком длинный ({len(combined_context)} символов), обрезаю до {MAX_CONTEXT_LENGTH}")
        # Обрезаем до максимальной длины, сохраняя начало
        combined_context = combined_context[:MAX_CONTEXT_LENGTH] + "\n\n[Текст обрезан из-за ограничений длины]"
    
    logging.info(f"📄 Размер combined_context: {len(combined_context)} символов (~{len(combined_context) * 0.25:.0f} токенов)")
    
    # Получаем изображение из первого источника
    image_url = ""
    if sources and len(sources) > 0:
        image_url = sources[0].get('image', '')
    
    if as_markdown:
        # Промпт для Markdown формата (оставляем как есть для совместимости)
        prompt = f"""Ты опытный журналист, который пишет для русскоязычных мигрантов в Испании. Твои читатели — обычные люди, которые хотят понимать, что происходит вокруг них, без лишних сложностей.

**🎯 КЛЮЧЕВОЕ ТРЕБОВАНИЕ:**
1. **ИСПОЛЬЗУЙ ПОЛНЫЙ ТЕКСТ СТАТЬИ** - не ограничивайся только заголовком и кратким описанием! В поле "Контекст" содержится полный текст новости - используй ВСЕ детали, цифры, имена, места, цитаты из него.

2. **ОБЯЗАТЕЛЬНО объясняй каждый незнакомый термин** простыми словами! Например:
   - "Педро Санчес (премьер-министр Испании)"
   - "Андалусия (самый большой регион Испании на юге)"
   - "Севилья (столица Андалусии, красивый город с богатой историей)"
   - "Partido Popular (основная оппозиционная партия в Испании)"

3. **ВКЛЮЧАЙ КОНКРЕТНЫЕ ДЕТАЛИ** из полного текста: точные даты, цифры, имена людей, названия организаций, адреса, цитаты.

4. **НЕ ПРИДУМЫВАЙ ИНФОРМАЦИЮ** - используй только то, что есть в предоставленном тексте.

По-дружески знакомь читателя с такими деталями, добавляя интересные факты и заметки для лучшего понимания контекста.

**Как писать:**
- Простыми словами, как будто объясняешь другу за чашкой кофе
- Избегай канцеляризмов и официальных оборотов
- Используй короткие предложения и абзацы
- Добавляй личные местоимения (мы, вы, они)
- Пиши так, будто ты сам заинтересован в теме
- Находи интригу даже в сухих новостях
- Используй метафоры, вопросы, риторические приемы
- Добавляй разговорные фразы и эмоциональные маркеры

**Структура текста:**
- Начни с захватывающего вступления (почему это важно именно для мигрантов)
- Объясни ситуацию простыми словами
- Добавь контекст — что это значит для обычных людей
- Используй подзаголовки для структурирования
- Заверши практическим выводом или вопросом

**Чего избегать:**
- Сложных терминов без объяснения
- Длинных предложений с множественными придаточными
- Шаблонных фраз типа "следует отметить", "необходимо подчеркнуть"
- Излишне формального тона
- Машинных оборотов речи

**Что добавить:**
- Конкретные примеры и цифры
- Мнения экспертов или очевидцев
- Практические советы для читателей
- Эмоциональную окраску, где уместно
- Местный контекст и особенности Испании
- Разговорные фразы и естественные переходы
- Интересные факты о людях, местах, событиях

**📏 ТРЕБОВАНИЯ К ДЛИНЕ:**
- Минимальная длина статьи: 800-1200 слов
- Каждый раздел должен содержать минимум 3-4 абзаца
- Не допускай поверхностного описания - раскрывай тему глубоко

**Стиль:**
Пиши в стиле Meduza, The Village, Tinkoff Journal — живо, с характером, но без потери информативности.

**⚠️ SEO и структура:**
- Используй ключевые слова (keywords) — от 3 до 5, одно слово в каждом (только существительные, в нижнем регистре)
- Поле `tags` также должно содержать 1-словные значения
- Поле `category`: выбери одну из — [migration, policy, weather, health, crime, events, education, transport, economy]
- Поле `slug`: генерация URL-дружественной версии заголовка (латиницей, через тире)

**📍 Регион:**
Определи, о каком регионе Испании идёт речь. Используй информацию из заголовка, текста и источников. 
Доступные регионы: Andalusia, Catalonia, Madrid, Valencia, Galicia, Castile and León, Basque Country, Castile-La Mancha, Canary Islands, Murcia, Aragon, Extremadura, Balearic Islands, Asturias, Navarre, Cantabria, La Rioja, Ceuta, Melilla.
Верни это в поле "region" в правильном формате (с заглавной буквы). Если неясно — укажи "region": "unknown".

**⚠️ Выводи статью в формате Markdown с frontmatter (между `---`)**

---

**Материал для обработки:**

Тема: {topic_summary}
Контекст: {combined_context}
Изображение: {image_url if image_url else "Не указано"}

---

Создай статью в формате Markdown с YAML frontmatter:

---
title: "Готовый заголовок"
description: "Краткое описание статьи"
pubDate: "2025-01-03"
author: "Авто-редакция"
tags: [миграция, жильё, налоги]
keywords: [миграция, жильё, налоги]
category: "policy"
slug: "kak-iskat-kvartiru-v-barcelone"
image: "https://example.com/image.jpg"
region: "catalonia"
---

## Подзаголовок

Основной текст статьи...

Пиши так, чтобы читатель не догадался, что текст написан ИИ."""
    else:
        # НОВЫЙ ПРОМПТ: редакторский, живой русский, строгий JSON по заданной схеме
        category_hint = cluster.get('category_hint', '')
        region_hint = cluster.get('region_hint', '')
        urgent = cluster.get('urgent', False)
        prompt = f"""Ты опытный русскоязычный журналист, который пишет для мигрантов в Испании. Твоя задача - создавать интересные, понятные и естественные по языку статьи.

ВАЖНО: Пиши ТОЛЬКО на русском языке, как будто ты русский человек, а не переводчик. Избегай дословных переводов с испанского!

## ТРЕБОВАНИЯ К ЯЗЫКУ:
- Используй ЖИВОЙ, РАЗГОВОРНЫЙ русский язык
- НЕ используй технические термины без объяснения
- Объясняй географические названия и местные особенности
- Избегай фраз типа "призыв к осторожности", "охотничьи интересы" - это звучит неестественно
- Пиши так, как говорят обычные русские люди

## ЗАПРЕЩЕННЫЕ ФРАЗЫ (замени на естественные):
❌ "восстановить свои жизни" → ✅ "вернуться к нормальной жизни"
❌ "имели знания в этой области" → ✅ "были специалистами" или "разбирались в деле"
❌ "это значит, что" → ✅ "это означает" или просто убирай
❌ "важно отметить" → ✅ "стоит помнить" или убирай
❌ "следует подчеркнуть" → ✅ "нужно сказать" или убирай
❌ "молодые человек" → ✅ "молодой человек"
❌ "shocking" → ✅ "шокирующий" или "потрясающий"

## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ:
1. **Практическая информация**: Если речь о мероприятии, музее, достопримечательности - обязательно добавь:
   - Ссылку на официальный сайт (если есть в исходных данных)
   - Информацию о билетах и ценах
   - Адрес и как добраться
   - Контакты для бронирования
2. **Изображение**: В поле image верни URL изображения из источника, если он дан (image_hint). Если image_hint пуст, оставь поле image пустым. НИЧЕГО НЕ ВЫДУМЫВАЙ.

2. **Географические пояснения**: Всегда объясняй, где находится место:
   - "В Антекере, на юге Испании, в провинции Малага"
   - "В Галисии, на северо-западе Испании"

3. **Естественные переходы**: Избегай повторяющихся фраз, используй разнообразие:
   - "Кроме того", "Также", "При этом", "В то же время"

## ОБЪЁМ И ГЛУБИНА БЕЗ ВОДЫ:
- Если во входных данных мало фактов — 400–700 слов, без растягивания.
- Если фактов/деталей много — 900–1400 слов, раскрой тему глубже, но не добавляй воду. Включай все значимые цифры, даты, имена, места и пояснения из входа.

## СТРУКТУРА СТАТЬИ:
1. **Заголовок** - живой, интересный, без канцеляризмов
2. **Вступление** - объясни, что происходит простыми словами
3. **Основная часть** - разбивай на логичные разделы с понятными заголовками
4. **Практические советы** - что делать читателю в этой ситуации
5. **Заключение** - краткий итог и что дальше

## ПРИМЕРЫ ПРАВИЛЬНЫХ ФРАЗ:
✅ "Власти призывают быть осторожными" (вместо "призыв к осторожности")
✅ "Пожар начался из-за охотников" (вместо "охотничьи интересы")
✅ "Горы Пиренеи на севере Испании" (вместо просто "Пиренеи")
✅ "Жилой район" (вместо "урбанизация")
✅ "Природный парк" (вместо "экопарк")
✅ "Вернуться к нормальной жизни" (вместо "восстановить жизни")
✅ "Были специалистами" (вместо "имели знания в области")

## ИСХОДНЫЕ ДАННЫЕ:
Тема: {cluster['topic_summary']}
Контекст: {cluster['combined_context']}
image_hint: {image_url if image_url else ""}
Категория: {cluster.get('category_hint', 'general')}
Регион: {cluster.get('region_hint', 'spain')}
Срочность: {cluster.get('urgent', False)}

## ЗАДАЧА:
Создай интересную, понятную статью на живом русском языке. Объясни все термины, географические названия и местные особенности. Добавь практическую информацию (ссылки, контакты, цены) если она есть в исходных данных. Статья должна быть полезна русскоязычным мигрантам в Испании.

ВЫХОД (СТРОГО ОДИН JSON, без Markdown‑ограждений):
{{
  "facts": {{
    "what": "",
    "where_when": "",
    "numbers": [],
    "actors": [],
    "terms": [],
    "unknowns": "",
    "image_url": ""
  }},
  "primary_keyword": "",
  "secondary_keywords": ["","",""],
  "region_normalized": "",
  "category_final": "",
  "outline": {{ "h2": [ {{ "text": "", "h3": ["",""] }} ] }},
  "title": "",
  "description": "",
  "content": "Markdown с H2/H3 из outline",
  "tags": ["","",""],
  "keywords": ["","",""],
  "category": "",
  "region": "",
  "slug": "",
  "pubDate": "YYYY-MM-DD",
  "author": "Авто-редакция",
  "image": "",
  "meta_title": "",
  "meta_description": "",
  "seo_audit": {{
    "primary_in_title": true,
    "primary_in_h2": true,
    "region_in_title_or_h2": true,
    "has_numbers_or_dates": true,
    "no_keyword_stuffing": true,
    "outline_quality_note": ""
  }}
}}"""
    
    max_retries = 2
    for attempt in range(max_retries):
        try:
            if as_markdown:
                response = openai_client.chat.completions.create(
                    model="gpt-5-mini",
                    messages=[
                        {"role": "system", "content": "Ты журналист для русскоязычных мигрантов в Испании. КРИТИЧЕСКИ ВАЖНО: ВСЕГДА ПИШИ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ! Пиши простым, понятным языком. Отвечай в формате Markdown с YAML frontmatter."},
                        {"role": "user", "content": prompt}
                    ],
                    max_completion_tokens=3000,  # Увеличили с 1400 до 3000 для более детальных статей
                    temperature=1  # GPT-5-mini поддерживает только temperature=1
                )
                
                result_text = response.choices[0].message.content.strip()
                
                # Проверяем, что результат содержит frontmatter
                if result_text.startswith('---') and '---' in result_text[3:]:
                    logging.info(f"✅ Markdown статья сгенерирована")
                    return result_text
                else:
                    logging.warning(f"Неверный формат Markdown: {result_text[:200]}...")
                    if attempt < max_retries - 1:
                        time.sleep(2)
                        continue
                    else:
                        # Генерируем fallback Markdown
                        return _generate_fallback_markdown(cluster)
            else:
                response = openai_client.chat.completions.create(
                    model="gpt-5-mini",
                    messages=[
                        {"role": "system", "content": "Ты новостной редактор для русскоязычных мигрантов в Испании. КРИТИЧЕСКИ ВАЖНО: ВСЕГДА ПИШИ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ! Выводи строго один JSON-объект без Markdown и пояснений."},
                        {"role": "user", "content": prompt}
                    ],
                    response_format={"type": "json_object"},
                    max_completion_tokens=5000,  # Увеличили с 3600 до 5000 для более детальных статей
                    temperature=1  # GPT-5-mini поддерживает только temperature=1
                )
                
                result_text = response.choices[0].message.content.strip()
                article_data = _extract_json_from_response(result_text)
                
                if article_data:
                    # Проверяем обязательные поля
                    required_fields = ['title', 'description', 'content', 'tags']
                    if all(field in article_data for field in required_fields):
                        # Добавляем недостающие поля с значениями по умолчанию
                        if 'pubDate' not in article_data:
                            article_data['pubDate'] = datetime.now().strftime('%Y-%m-%d')
                        if 'author' not in article_data:
                            article_data['author'] = "Авто-редакция"
                        # Картинка: используем image из ответа, если валиден; иначе берем image_hint; иначе пусто
                        candidate_image = article_data.get('image', '')
                        if _is_valid_image_url(candidate_image):
                            article_data['image'] = candidate_image
                        elif _is_valid_image_url(image_url):
                            article_data['image'] = image_url
                        else:
                            article_data['image'] = ""
                        if 'slug' not in article_data:
                            article_data['slug'] = slugify(article_data['title'], max_length=50)
                        if 'category' not in article_data:
                            article_data['category'] = "policy"
                        if 'meta_title' not in article_data:
                            article_data['meta_title'] = article_data['title'][:60]
                        if 'meta_description' not in article_data:
                            article_data['meta_description'] = article_data['description'][:160]
                        if 'meta_keywords' not in article_data:
                            article_data['meta_keywords'] = article_data['tags']
                        if 'region' not in article_data:
                            article_data['region'] = "Spain"
                        
                        logging.info(f"✅ Статья сгенерирована: {article_data['title']}")
                        return article_data
                    else:
                        logging.warning(f"Неполный JSON ответ: {article_data}")
                        return None
                else:
                    if attempt < max_retries - 1:
                        logging.warning(f"Попытка {attempt + 1} не удалась, повторяю...")
                        time.sleep(2)
                        continue
                    else:
                        logging.error(f"Не удалось обработать JSON после {max_retries} попыток")
                        return None
                    
        except Exception as e:
            error_msg = str(e).lower()
            if 'rate limit' in error_msg or 'timeout' in error_msg:
                if attempt < max_retries - 1:
                    logging.warning(f"Rate limit/timeout (попытка {attempt + 1}): {e}")
                    time.sleep(2)
                    continue
                else:
                    logging.error(f"Rate limit/timeout после {max_retries} попыток: {e}")
                    return None
            else:
                logging.error(f"Ошибка OpenAI API: {e}")
                return None
    
    return None


def _generate_fallback_markdown(cluster: Dict[str, Any]) -> str:
    """
    Генерирует fallback Markdown статью без использования LLM
    
    Args:
        cluster: Словарь с данными кластера
        
    Returns:
        Простая Markdown статья с frontmatter
    """
    topic_summary = cluster.get('topic_summary', 'Новость')
    combined_context = cluster.get('combined_context', '')
    sources = cluster.get('sources', [])
    
    # Получаем изображение из первого источника
    image_url = ""
    if sources and len(sources) > 0:
        image_url = sources[0].get('image', '')
    
    # Генерируем slug из topic_summary
    slug = slugify(topic_summary, max_length=50)
    
    # Определяем категорию на основе ключевых слов
    category = "policy"
    if any(word in topic_summary.lower() for word in ['миграция', 'виза', 'иммиграция']):
        category = "migration"
    elif any(word in topic_summary.lower() for word in ['экономика', 'финансы', 'деньги', 'банк']):
        category = "economy"
    elif any(word in topic_summary.lower() for word in ['погода', 'температура', 'дождь', 'солнце', 'жара']):
        category = "weather"
    elif any(word in topic_summary.lower() for word in ['здоровье', 'медицина', 'больница', 'врач']):
        category = "health"
    elif any(word in topic_summary.lower() for word in ['преступление', 'полиция', 'арест', 'суд']):
        category = "crime"
    elif any(word in topic_summary.lower() for word in ['событие', 'праздник', 'фестиваль', 'концерт']):
        category = "events"
    elif any(word in topic_summary.lower() for word in ['образование', 'школа', 'университет', 'учеба']):
        category = "education"
    elif any(word in topic_summary.lower() for word in ['транспорт', 'метро', 'автобус', 'поезд']):
        category = "transport"
    
    # Определяем регион на основе ключевых слов
    region = "Spain"  # По умолчанию общий регион Испания
    topic_lower = topic_summary.lower()
    
    # Сначала проверяем конкретные регионы
    if any(word in topic_lower for word in ['барселона', 'каталония', 'catalonia', 'cataluña', 'каталон']):
        region = "Catalonia"
    elif any(word in topic_lower for word in ['мадрид', 'madrid']):
        region = "Madrid"
    elif any(word in topic_lower for word in ['валенсия', 'valencia', 'валенсий']):
        region = "Valencia"
    elif any(word in topic_lower for word in ['андалусия', 'andalusia', 'севилья', 'sevilla', 'малага', 'malaga', 'кордова', 'cordoba', 'гранада', 'granada', 'андалусий']):
        region = "Andalusia"
    elif any(word in topic_lower for word in ['мурсия', 'murcia', 'мурсий']):
        region = "Murcia"
    elif any(word in topic_lower for word in ['баск', 'basque', 'бильбао', 'bilbao', 'витория', 'vitoria', 'сан-себастьян', 'san sebastian']):
        region = "Basque Country"
    elif any(word in topic_lower for word in ['галисия', 'galicia', 'ла-корунья', 'la coruña', 'а-корунья', 'a coruña', 'виго', 'vigo', 'сантьяго', 'santiago', 'галисий']):
        region = "Galicia"
    elif any(word in topic_lower for word in ['кастилия-ла-манча', 'castile-la mancha', 'толедо', 'toledo', 'альбасете', 'albacete', 'куэнка', 'cuenca']):
        region = "Castile-La Mancha"
    elif any(word in topic_lower for word in ['кастилия', 'castile', 'леон', 'leon', 'саламанка', 'salamanca', 'бургос', 'burgos', 'вальядолид', 'valladolid', 'кастиль']):
        region = "Castile and León"
    elif any(word in topic_lower for word in ['канарские', 'canary', 'тенерифе', 'tenerife', 'гран-канария', 'gran canaria', 'лас-пальмас', 'las palmas', 'канар']):
        region = "Canary Islands"
    elif any(word in topic_lower for word in ['арагон', 'aragon', 'сарагоса', 'zaragoza', 'уэска', 'huesca', 'теруэль', 'teruel', 'арагон']):
        region = "Aragon"
    elif any(word in topic_lower for word in ['эстремадура', 'extremadura', 'бадахос', 'badajoz', 'касерес', 'caceres', 'мерida', 'merida', 'эстремадур']):
        region = "Extremadura"
    elif any(word in topic_lower for word in ['балеарские', 'balearic', 'майорка', 'mallorca', 'менорка', 'menorca', 'ибиса', 'ibiza', 'пальма', 'palma', 'балеар']):
        region = "Balearic Islands"
    elif any(word in topic_lower for word in ['астурия', 'asturias', 'овьедо', 'oviedo', 'хихон', 'gijon', 'астурий']):
        region = "Asturias"
    elif any(word in topic_lower for word in ['наварра', 'navarre', 'памплона', 'pamplona', 'наварр']):
        region = "Navarre"
    elif any(word in topic_lower for word in ['кантабрия', 'cantabria', 'сантандер', 'santander', 'кантабрий']):
        region = "Cantabria"
    elif any(word in topic_lower for word in ['риоха', 'rioja', 'логроньо', 'logroño', 'риох']):
        region = "La Rioja"
    elif any(word in topic_lower for word in ['сеута', 'ceuta', 'сеут']):
        region = "Ceuta"
    elif any(word in topic_lower for word in ['мелилья', 'melilla', 'мелиль']):
        region = "Melilla"
    # Если не найден конкретный регион, остается "Spain" (общий регион)
    
    # Извлекаем ключевые слова из topic_summary
    keywords = [word.lower() for word in topic_summary.split() if len(word) > 3][:5]
    if not keywords:
        keywords = ["новости", "испания", "миграция"]
    
    markdown_content = f"""---
title: "{topic_summary}"
description: "{combined_context[:160] if combined_context else 'Описание новости'}"
pubDate: "{datetime.now().strftime('%Y-%m-%d')}"
author: "Авто-редакция"
tags: {keywords}
keywords: {keywords}
category: "{category}"
slug: "{slug}"
image: "{image_url}"
region: "{region}"
---

## {topic_summary}

{combined_context if combined_context else 'Подробности новости будут добавлены позже.'}

### Что это значит для мигрантов?

Эта новость может повлиять на жизнь русскоязычных мигрантов в Испании. Рекомендуем следить за развитием событий.

### Источники

Информация получена из проверенных источников и официальных заявлений."""
    
    return markdown_content


def generate_article_url(article: Dict[str, Any], website_dir: str = "spain-news-portal") -> str:
    """
    Генерирует правильную ссылку на статью на основе экспортированного файла
    
    Args:
        article: Словарь с данными статьи
        website_dir: Директория сайта
        
    Returns:
        URL статьи на сайте
    """
    try:
        # Определяем коллекцию на основе категории
        category = article.get('category', 'policy').lower()
        collection_mapping = {
            'migration': 'news',
            'policy': 'news',
            'weather': 'news',
            'health': 'news',
            'crime': 'news',
            'events': 'news',
            'education': 'news',
            'transport': 'news',
            'economy': 'news'
        }
        collection = collection_mapping.get(category, 'news')
        
        # Получаем slug из статьи или генерируем из заголовка
        title = article.get('title', '')
        slug = article.get('slug', slugify(title, max_length=50))
        
        # Проверяем, существует ли файл с точным slug
        file_path = Path(website_dir) / "src" / "content" / collection / f"{slug}.md"
        
        if file_path.exists():
            # Файл существует, используем правильную ссылку
            result_url = f"https://spain-que-pasa.com/{collection}/{slug}/"
            logging.info(f"Генерируем URL: collection={collection}, slug={repr(slug)}, result={repr(result_url)}")
            return result_url
        else:
            # Ищем файл по slug в имени файла (может быть с временной меткой)
            collection_dir = Path(website_dir) / "src" / "content" / collection
            if collection_dir.exists():
                # Сортируем файлы по времени создания (новые сначала)
                files = sorted(collection_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
                
                # Сначала ищем файл, который содержит наш slug в имени
                for file in files:
                    if slug in file.stem:
                        file_slug = file.stem.strip()  # Убираем лишние пробелы и переносы строк
                        return f"https://spain-que-pasa.com/{collection}/{file_slug}/"
                
                # Если не нашли по slug, ищем по заголовку статьи
                for file in files:
                    try:
                        with open(file, 'r', encoding='utf-8') as f:
                            content = f.read()
                            # Ищем заголовок в frontmatter или в тексте
                            if title in content or any(word in content for word in title.split()[:3]):
                                # Нашли файл с этим заголовком
                                file_slug = file.stem.strip()  # Убираем лишние пробелы и переносы строк
                                return f"https://spain-que-pasa.com/{collection}/{file_slug}/"
                    except Exception:
                        continue
                
                # Если не нашли по заголовку, берем самый новый файл
                if files:
                    newest_file = files[0]
                    file_slug = newest_file.stem.strip()  # Убираем лишние пробелы и переносы строк
                    return f"https://spain-que-pasa.com/{collection}/{file_slug}/"
            
            # Файл не найден, используем fallback
            logging.warning(f"Файл статьи не найден для заголовка: {title}")
            return f"https://spain-que-pasa.com/{collection}/{slug}/"
            
    except Exception as e:
        logging.error(f"Ошибка генерации URL: {e}")
        # Fallback ссылка
        title = article.get('title', '')
        slug = slugify(title, max_length=50)
        return f"https://spain-que-pasa.com/news/{slug}/"


def update_telegram_post_with_correct_link(article: Dict[str, Any], website_dir: str = "spain-news-portal") -> str:
    """
    Обновляет Telegram-пост с правильной ссылкой на статью
    
    Args:
        article: Словарь с данными статьи
        website_dir: Директория сайта
        
    Returns:
        Обновленный Telegram-пост
    """
    telegram_post = article.get('telegram_post', '')
    if not telegram_post:
        return telegram_post
    
    # Генерируем правильную ссылку
    correct_url = generate_article_url(article, website_dir)
    
    # Заменяем старые ссылки на правильную
    # Ищем ссылки вида https://spain-que-pasa.com/news/.../
    old_link_pattern = r'https://spain-que-pasa\.com/[^/\s]+/[^/\s]+/'
    telegram_post = re.sub(old_link_pattern, correct_url, telegram_post)
    
    # Если ссылки не было, добавляем в конец
    if 'https://spain-que-pasa.com/' not in telegram_post:
        # Находим последний абзац и добавляем ссылку
        lines = telegram_post.split('\n')
        if lines and not lines[-1].strip().startswith('🔗'):
            telegram_post += f"\n\n🔗 {correct_url}"
    
    return telegram_post


def generate_telegram_post(article: Dict[str, Any]) -> str:
    """
    Генерирует Telegram-пост в Markdown (до 1000 символов) на основе готовой статьи.
    Использует тот же промпт, что был в generate_telegram_post() в rss_parser.py.
    
    Args:
        article: Словарь с данными статьи
        
    Returns:
        Готовый Telegram-пост в формате Markdown
    """
    # Добавляем логирование для отладки
    logging.info(f"🔍 Генерирую Telegram-пост для статьи:")
    logging.info(f"   - ID: {article.get('article_id', 'N/A')}")
    logging.info(f"   - Заголовок: {article.get('title', 'N/A')[:100]}...")
    logging.info(f"   - Описание: {article.get('description', 'N/A')[:100]}...")
    logging.info(f"   - Длина контента: {len(article.get('content', ''))}")
    logging.info(f"   - Теги: {article.get('tags', [])}")
    
    openai_client = _get_openai_client()
    if not openai_client:
        logging.error("OpenAI клиент не инициализирован")
        return _generate_fallback_post(article)
    
    try:
        # Генерируем правильную ссылку на статью
        article_url = generate_article_url(article)
        
        prompt = f"""Ты пишешь посты для Telegram-канала, где публикуются новости для русскоязычных мигрантов в Испании.

**📏 СТРОГОЕ ТРЕБОВАНИЕ ПО ДЛИНЕ:**
Пост ДОЛЖЕН быть ровно до 1000 символов включительно. Не больше! Если не помещается - сокращай, но сохраняй суть.

На основе следующей ГОТОВОЙ СТАТЬИ НА РУССКОМ ЯЗЫКЕ создай информативный, живой и цепляющий Telegram-пост, который:

✅ Полностью передаёт суть и смысл статьи  
✅ Даёт читателю ясную картину ситуации  
✅ Интересно и легко читается  
✅ СТРОГО до 1000 символов  
✅ Написан живо, но без "воды", канцелярита или сухости  
✅ Содержит в конце ссылку на полную статью  
✅ Завершается вопросом или призывом к обсуждению  

**🎨 ФОРМАТИРОВАНИЕ:**
- **Заголовок** выделяй жирным: **Название статьи**
- **Ключевые моменты** в тексте тоже выделяй жирным: **важная информация**
- Используй emoji умеренно и по делу

**Стиль написания:**
- Простыми словами, как будто рассказываешь другу
- Находи интригу даже в сухих новостях
- Используй метафоры и вопросы для вовлечения
- Добавляй разговорные фразы и эмоциональные маркеры
- Избегай машинных оборотов речи
- Пиши в стиле Meduza, The Village, Tinkoff Journal

---

Формат:

1. **🧲 Заголовок** (жирным, в одну строку)
2. **🧾 Краткий и насыщенный текст** (2-4 абзаца), в котором:
   - изложена суть статьи
   - включены важные детали, причины, последствия
   - интересные или спорные моменты
   - ключевые моменты выделены **жирным**
3. **🔗 Ссылка на полную статью**: {article_url}
4. **💬 ОБЯЗАТЕЛЬНО заверши вопросом или призывом к обсуждению!** Например:
   - "Что думаете об этих изменениях?"
   - "Как эти новости повлияют на ваши планы?"
   - "Поделитесь своим опытом в комментариях!"

**📝 АЛЬТЕРНАТИВА ДЛЯ ДЛИННЫХ ПОСТОВ:**
Если тема очень интересная и не помещается в 1000 символов, можешь закончить фразой:
"📖 Продолжение в комментариях 👇"

---

Статья (уже на русском языке):

Title: {article.get('title', '')}
Description: {article.get('description', '')}
Tags: {article.get('tags', [])}
Content: {article.get('content', '')}

---

✏️ Верни только Telegram-пост в Markdown. Не добавляй пояснений. Не используй хэштеги. Не пиши от лица ИИ.
Ссылка в конце: {article_url}

**ПОМНИ: СТРОГО до 1000 символов!**"""
        
        response = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты эксперт по созданию Telegram-постов для русскоязычных мигрантов в Испании. Создавай информативные, живые и цепляющие посты СТРОГО до 1000 символов с жирным форматированием."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=400,
            temperature=1
        )
        
        # Добавляем детальное логирование для отладки
        logging.info(f"🔍 OpenAI ответ получен:")
        logging.info(f"   - Модель: {response.model}")
        logging.info(f"   - Использовано токенов: {response.usage.total_tokens if response.usage else 'N/A'}")
        logging.info(f"   - Количество выборов: {len(response.choices)}")
        
        if response.choices and len(response.choices) > 0:
            choice = response.choices[0]
            logging.info(f"   - Первый выбор:")
            logging.info(f"     - Финиш причина: {choice.finish_reason}")
            logging.info(f"     - Индекс: {choice.index}")
            logging.info(f"     - Сообщение роль: {choice.message.role}")
            logging.info(f"     - Длина контента: {len(choice.message.content) if choice.message.content else 0}")
            
            if choice.message.content:
                logging.info(f"     - Первые 100 символов: {choice.message.content[:100]}...")
            else:
                logging.warning("⚠️ OpenAI вернул пустой контент!")
        else:
            logging.error("❌ OpenAI не вернул выборов")
        
        telegram_post = response.choices[0].message.content.strip() if response.choices and response.choices[0].message.content else ""
        
        # Проверяем длину поста
        post_length = len(telegram_post)
        logging.info(f"✅ Telegram-пост сгенерирован ({post_length} символов)")
        
        # Проверяем, что пост не пустой
        if not telegram_post or post_length == 0:
            logging.error("❌ OpenAI вернул пустой пост, используем fallback")
            return _generate_fallback_post(article)
        
        # Если пост длиннее 1000 символов, НЕ обрезаем - убираем картинку
        if post_length > 1000:
            logging.warning(f"Пост превышает лимит в 1000 символов ({post_length}), но НЕ обрезаем - убираем картинку")
            # Здесь можно добавить логику для уведомления о необходимости убрать картинку
            # Пост публикуется целиком без картинки
        
        return telegram_post
        
    except Exception as e:
        logging.error(f"Ошибка при генерации Telegram-поста: {e}")
        return _generate_fallback_post(article)


def _generate_fallback_post(article: Dict[str, Any]) -> str:
    """
    Генерирует fallback Telegram-пост без использования LLM
    
    Args:
        article: Словарь с данными статьи
        
    Returns:
        Простой Telegram-пост
    """
    title = article.get('title', 'Новость')
    description = article.get('description', '')
    content = article.get('content', '')
    
    # Генерируем правильную ссылку
    article_url = generate_article_url(article)
    
    # Создаем простой пост
    post = f"**{title}**\n\n"
    
    # Добавляем описание или начало контента
    if description:
        post += f"{description}\n\n"
    elif content:
        # Берем первые 200 символов контента
        content_preview = content[:200].strip()
        if len(content_preview) == 200:
            content_preview = content_preview.rsplit(' ', 1)[0] + "..."
        post += f"{content_preview}\n\n"
    
    post += f"🔗 [Читать полную статью]({article_url})\n"
    post += "💬 Поделитесь своим мнением в комментариях!"
    
    # Проверяем длину
    if len(post) > 1000:
        # Сокращаем до 1000 символов
        post = post[:997] + "..."
    
    return post


def generate_and_save_content(cluster: Dict[str, Any], client: FirebaseClient) -> Optional[str]:
    """
    Генерирует статью и Telegram-пост, сохраняет в Firebase в коллекцию 'articles'.
    Сначала экспортирует статью на сайт, потом генерирует Telegram-пост с правильной ссылкой.
    Добавляет поля:
      - cluster_id, priority_score, urgent
      - telegram_post
      - source_link (из cluster["sources"][0]["link"])

    Args:
        cluster: Словарь с данными кластера
        client: Firebase клиент
        
    Returns:
        ID созданной статьи или None при ошибке
    """
    if not client:
        logging.error("Firebase клиент не передан")
        return None
    
    # Проверяем дубликат
    sources = cluster.get('sources', [])
    if not sources:
        logging.error("Кластер не содержит источников")
        return None
    
    source_link = sources[0].get('link', '')
    if not source_link:
        logging.error("Первый источник не содержит ссылки")
        return None
    
    # Генерируем статью
    article = generate_article(cluster)
    if not article:
        logging.error("Не удалось сгенерировать статью")
        return None
    
    # Проверяем дубликат по ссылке и заголовку
    if client.is_duplicate_article(source_link, article['title']):
        logging.info(f"Статья уже существует: {article['title']}")
        return None
    
    # Добавляем дополнительные поля
    article.update({
        'cluster_id': cluster.get('cluster_id', ''),
        'priority_score': cluster.get('priority_score', 0),
        'urgent': cluster.get('urgent', False),
        'source_link': source_link,
        'link': source_link,  # Добавляем link для совместимости с Firebase
        'created_at': datetime.now().isoformat()
    })
    
    # Сохраняем в Firebase
    if client.save_article(article):
        logging.info(f"✅ Статья сохранена в Firebase: {article['title']}")
        
        # Сначала экспортируем статью на сайт
        try:
            from article_exporter import ArticleExporter
            exporter = ArticleExporter(client)
            if exporter.save_article(article):
                logging.info(f"✅ Статья экспортирована на сайт: {article['title']}")
            else:
                logging.warning(f"⚠️  Не удалось экспортировать статью на сайт: {article['title']}")
        except Exception as e:
            logging.error(f"❌ Ошибка экспорта статьи на сайт: {e}")
        
        # Теперь генерируем Telegram-пост с правильной ссылкой и сразу сохраняем
        # Telegram-посты теперь генерируются только для выбранных лучших статей
        # в jobs_scheduler.py через telegram_post_generator.py
        client.update_article(article)
        
        # Возвращаем ID статьи (хеш из ссылки и заголовка)
        import hashlib
        content_hash = hashlib.md5(f"{source_link}{article['title']}".encode()).hexdigest()
        return content_hash
    else:
        logging.error("Не удалось сохранить статью в Firebase")
        return None 


def generate_article_from_news(article_data: Dict[str, Any], firebase_client) -> Optional[str]:
    """
    Генерирует статью напрямую из новости (без кластеризации)
    
    Args:
        article_data: Данные новости для генерации статьи
        firebase_client: Клиент Firebase
        
    Returns:
        ID сгенерированной статьи или None при ошибке
    """
    try:
        # Создаем промпт для генерации статьи
        prompt = f"""Создай информативную статью на русском языке для русскоязычных мигрантов в Испании.

Исходная новость:
Заголовок: {article_data['title']}
Ссылка: {article_data['link']}
Содержание: {article_data['content']}

Требования:
- Пиши ТОЛЬКО на русском языке
- Создай структурированную статью с заголовками
- Добавь практические советы и объяснения
- Адаптируй под русскоязычных мигрантов в Испании
- Сохрани важную информацию из исходной новости
- Добавь полезные детали и контекст

Формат: Markdown с YAML frontmatter"""

        # Генерируем статью
        logging.info(f"Генерирую статью для: {article_data.get('title', 'Без заголовка')}")
        article_content = generate_article_content(prompt, as_markdown=True)
        
        if not article_content:
            logging.error("Не удалось сгенерировать содержимое статьи даже через fallback")
            return None
        
        logging.info(f"Статья сгенерирована успешно, длина: {len(article_content)} символов")
        
        # Создаем структуру статьи для сайта
        article_doc = {
            'title': article_data['title'],
            'content': article_content,
            'summary': article_data['summary'],
            'source_link': article_data['link'],
            'source_article_id': article_data.get('source_article_id'),
            'image': article_data.get('image', ''),
            'priority_score': article_data.get('priority_score', 0),
            'urgent': article_data.get('urgent', False),
            'category': 'general',  # Можно добавить определение категории
            'tags': [],  # Можно добавить автоматические теги
            'created_at': datetime.now(timezone.utc).isoformat(),
            'exported_to_site': True,
            'published': False,
            'daily_priority_score': 0
        }
        
        # Сохраняем в Firebase
        articles_ref = firebase_client.db.collection('generated_articles')
        doc_ref = articles_ref.add(article_doc)
        
        logging.info(f"Статья успешно сгенерирована и сохранена: {doc_ref[1].id}")
        return doc_ref[1].id
        
    except Exception as e:
        logging.error(f"Ошибка генерации статьи из новости: {e}")
        return None


def generate_article_content(prompt: str, as_markdown: bool = True) -> Optional[str]:
    """
    Генерирует содержимое статьи по промпту
    
    Args:
        prompt: Промпт для генерации
        as_markdown: Генерировать в формате Markdown
        
    Returns:
        Сгенерированное содержимое или None при ошибке
    """
    try:
        openai_client = _get_openai_client()
        if not openai_client:
            logging.error("OpenAI клиент не инициализирован")
            return None
        
        response = openai_client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты журналист для русскоязычных мигрантов в Испании. КРИТИЧЕСКИ ВАЖНО: ВСЕГДА ПИШИ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ! Пиши простым, понятным языком. Отвечай в формате Markdown с YAML frontmatter."},
                {"role": "user", "content": prompt}
            ],
            max_completion_tokens=3000,
            temperature=1
        )
        
        generated_content = response.choices[0].message.content.strip()
        
        if not generated_content:
            logging.error("OpenAI вернул пустой ответ")
            # Пробуем fallback генерацию
            return _generate_fallback_article(prompt)
        
        return generated_content
        
    except Exception as e:
        logging.error(f"Ошибка генерации содержимого статьи: {e}")
        # Пробуем fallback генерацию при ошибке
        return _generate_fallback_article(prompt)


def _generate_fallback_article(prompt: str) -> str:
    """
    Fallback генерация статьи без использования OpenAI
    
    Args:
        prompt: Промпт для генерации
        
    Returns:
        Простая статья в формате Markdown
    """
    try:
        # Извлекаем ключевую информацию из промпта
        lines = prompt.split('\n')
        title = ""
        content = ""
        
        for line in lines:
            if 'Заголовок:' in line:
                title = line.split('Заголовок:')[1].strip()
            elif 'Содержание:' in line:
                content = line.split('Содержание:')[1].strip()
                break
        
        if not title:
            title = "Важная новость для мигрантов в Испании"
        
        if not content:
            content = "Информация о важном событии, которое может повлиять на жизнь русскоязычных мигрантов в Испании."
        
        # Создаем простую статью
        fallback_article = f"""---
title: "{title}"
description: "Важная информация для русскоязычных мигрантов в Испании"
pubDate: "{datetime.now().strftime('%Y-%m-%d')}"
author: "Авто-редакция"
tags: [миграция, испания, новости]
category: "news"
---

# {title}

{content}

## Что это значит для мигрантов?

Эта новость может повлиять на вашу жизнь в Испании. Рекомендуем внимательно изучить детали и при необходимости обратиться к специалистам.

## Полезные ссылки

- [Официальный сайт правительства Испании](https://www.lamoncloa.gob.es/)
- [Информация для иностранцев](https://extranjeros.inclusion.gob.es/)

---
*Статья сгенерирована автоматически на основе важной новости.*"""
        
        logging.info("Использована fallback генерация статьи")
        return fallback_article
        
    except Exception as e:
        logging.error(f"Ошибка fallback генерации: {e}")
        # Возвращаем минимальную статью
        return f"""---
title: "Важная новость"
description: "Информация для мигрантов в Испании"
pubDate: "{datetime.now().strftime('%Y-%m-%d')}"
author: "Авто-редакция"
tags: [новости, испания]
category: "news"
---

# Важная новость

Произошло важное событие, которое может повлиять на жизнь мигрантов в Испании. Рекомендуем следить за развитием ситуации.

---
*Статья сгенерирована автоматически.*""" 