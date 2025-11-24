#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt and local heuristic for categorization (co-located with categorization worker).

This file contains the strict JSON-only system prompt and the helper
`get_news_filter_prompt()` used by the categorization worker.
"""

NEWS_FILTER_SYSTEM_PROMPT = """Ты — редактор-фильтр новостей для русскоязычных в Испании. Отвечай строго валидным JSON (никакого текста вне фигурных скобок).
Аудитория: 25–55 лет. Интересы: работа и доход, документы/гражданство, жильё/аренда/ипотека, семья/дети/школы, налоги/штрафы, медицина, транспорт, безопасность и погодные риски, масштабные культурные и спортивные события.
Одобряем: практическая польза / «что делать» (правила/законы/дедлайны/штрафы/льготы), бытовые/финансовые темы (жильё, рынок труда), безопасность/риски (официальные предупреждения/погода), крупные культурные и спортивные события с влиянием на жизнь города.
Отклоняем: материалы не про Испанию или без влияния на жителей Испании; реклама/промо; чистый шоу-бизнес/спорт без общественной значимости; мелкий криминал без последствий; туманные пресс-релизы без дат/фактов.
"""

NEWS_FILTER_USER_PROMPT = """Оцени анонс и реши, публиковать ли его в Telegram-канале для русскоязычных мигрантов в Испании.
Классификация/Правила/Шкалы:
- Категории (одна): migration | policy | weather | health | crime | events | education | transport | economy | culture
- Регион: if national -> "spain", else one of: madrid, catalonia, valencia, andalusia, basque-country, galicia, murcia, aragon, castile-and-leon, castile-la-mancha, canary-islands, balearic-islands, navarre, la-rioja, extremadura, asturias, cantabria.
- Scoring (0–100):
    region_score (0–10)
    usefulness_score (0–35)
    emotion_score (0–25)
    virality_score (0–20)
    source_score (0–10)
    total_score = сумма пяти метрик
Пограничные правила:
- Есть дедлайн/штраф/новая обязательная процедура → склоняй вверх.
- Очевидный дубликат без новой инфы → склоняй вниз.
- Крупная культура/спорт с влиянием на жизнь города → не занижай.

Рейтинг:
80–100 -> "publish"
60–79 -> "short_note"
<60 -> "skip"

ВЫХОД (ТОЛЬКО ВАЛИДНЫЙ JSON):
{
        "region_score": 0-10,
        "usefulness_score": 0-35,
        "emotion_score": 0-25,
        "virality_score": 0-20,
        "source_score": 0-10,
        "total_score": 0-100,
        "rating": "publish" | "short_note" | "skip",
        "category": "одна из категорий сверху",
        "comment": "1–2 предложения: почему это важно/обсуждаемо и чем полезно читателю"
}

ДАННЫЕ

Title: {title}
Description: {description}
Tags: {tags}
Content: {content}
Source: {source}
Publication Date: {pub_date}
Feed: {feed_name}
Region Hint (optional): {region_hint}
"""

def get_news_filter_prompt(title, description, tags, content, source, pub_date, feed_name='', region_hint=''):
    """Return a tuple (system_prompt, user_prompt).

    The system prompt contains role/audience and high-level rules.
    The user prompt contains the scoring rules and the data fields (placeholders).
    """
    # Fill placeholders in the user-facing prompt only (where data fields are present).
    s = NEWS_FILTER_USER_PROMPT
    replacements = {
        'title': title,
        'description': description,
        'tags': tags,
        'content': content,
        'source': source,
        'pub_date': pub_date,
        'feed_name': feed_name,
        'region_hint': region_hint,
    }
    for k, v in replacements.items():
        s = s.replace('{' + k + '}', str(v))
    # Return (system, user)
    return (NEWS_FILTER_SYSTEM_PROMPT, s)


def validate_news_interest(news_data):
    # Minimal local heuristic fallback (keeps existing behaviour).
    title = news_data.get('title', '')
    description = news_data.get('description', '')
    content = news_data.get('content', '')
    tags = news_data.get('tags', [])

    all_text = f"{title} {description} {' '.join(tags)} {content}".lower()
    score = 0
    # Very small heuristic example: boost if keywords exist
    practical_keywords = ['внж', 'виза', 'документы', 'работа', 'жилье', 'аренда', 'налог']
    if any(k in all_text for k in practical_keywords):
        score += 30
    if any(city in all_text for city in ['мадрид', 'барселона', 'валенсия', 'малага', 'аликант']):
        score += 10

    total = min(100, 40 + score)
    rating = 'publish' if total >= 80 else 'short_note' if total >= 60 else 'skip'
    return {
        'region_score': 8,
        'usefulness_score': min(35, score),
        'emotion_score': 0,
        'virality_score': 0,
        'source_score': 7,
        'total_score': total,
        'rating': rating,
        'category': 'general',
        'comment': ''
    }
