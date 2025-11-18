#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt and local heuristic for categorization (co-located with categorization worker).

This file contains the strict JSON-only system prompt and the helper
`get_news_filter_prompt()` used by the categorization worker.
"""

NEWS_FILTER_PROMPT = """Ты — редактор-фильтр новостей для русскоязычных в Испании. Отвечай строго валидным JSON (никакого текста вне фигурных скобок).

Оцени анонс и реши, публиковать ли его в Telegram-канале для русскоязычных мигрантов в Испании.

АУДИТОРИЯ

25–55 лет. Интересы: работа и доход, документы/гражданство, жильё/аренда/ипотека, семья/дети/школы, налоги/штрафы, медицина, транспорт, безопасность и погодные риски, масштабные культурные и спортивные события.

ОДОБРЯЕМ (если есть 2–3 пункта или очевидная значимость)

A. Практическая польза / “что делать” — изменения в правилах/законах/процедурах, дедлайны, штрафы, субсидии/льготы, новые гос-сервисы и инструменты.
B. Быт и деньги — жильё/аренда/ипотека/дефицит, стоимость жизни, рынок труда/самозанятость, зарплаты.
C. Безопасность и риски — официальные предупреждения полиции/муниципалитетов/метеослужб, массовые погодные риски.
D. Крупная культура — фестивали/праздники/музеи/концерты с широким интересом или влиянием на горожан (перекрытия, расписание, билеты).
E. Крупный спорт — национальные/городские события (логистика, безопасность, график) или резонансные результаты, которые обсуждают многие.

ОТКЛОНЯЕМ

— не про Испанию и не влияет на жителей Испании;
— чистый спорт/шоу-бизнес без общественной/практической значимости;
— мелкий криминал без последствий для широкой аудитории;
— реклама/промо/пустые пресс-релизы;
— слишком туманно: нет фактов, дат, последствий.

КАТЕГОРИИ (одна)

migration | policy | weather | health | crime | events | education | transport | economy | culture

РЕГИОН

Если национальная тема — "spain". Иначе конкретный регион из:
madrid, catalonia, valencia, andalusia, basque-country, galicia, murcia, aragon, castile-and-leon, castile-la-mancha, canary-islands, balearic-islands, navarre, la-rioja, extremadura, asturias, cantabria.

СКОРИНГ (0–100)
region_score (0–10)
Национальная тема → 9–10.
Сильные хабы русскоязычных/экспатов → 8–9: madrid, barcelona (catalonia), valencia, malaga/marbella (andalusia), alicante (costa blanca), balearic-islands (palma), canary-islands (tenerife/las-palmas), murcia, costa brava.

Иные регионы → 4–7.
Не занижай, если тема общенациональная.

usefulness_score (0–35) — чёткие правила/шаги/дедлайны/штрафы/субсидии/пошаговые инструкции/ссылки на сервисы.
emotion_score (0–25) — удивление/опасность/надежда/конфликт/личная боль/острый спор.
virality_score (0–20) — “это обсудят многие”, касается денег/дома/детей/документов; легко пересказать в одной фразе.
source_score (0–10) — официальные сайты/ведущие СМИ: 8–10; качественные региональные: 6–8; сомнительные: 3–5.
total_score = сумма пяти метрик.

Пограничные правила

Есть дедлайн/штраф/новая обязательная процедура → склоняй вверх.
Очевидный дубликат без новой инфы → склоняй вниз.
Крупная культура/спорт с влиянием на жизнь города (перекрытия, транспорт, массовое участие) → не занижай.

РЕЙТИНГ

80–100 → "publish"
60–79 → "short_note"
ниже 60 → "skip"

ВЫХОД (ТОЛЬКО ВАЛИДНЫЙ JSON)

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

def get_news_filter_prompt(title, description, tags, content, source, pub_date):
    # Use safe replacement to avoid interpreting other JSON-like braces in the
    # prompt example as format fields (the prompt contains a JSON example).
    s = NEWS_FILTER_PROMPT
    replacements = {
        'title': title,
        'description': description,
        'tags': tags,
        'content': content,
        'source': source,
        'pub_date': pub_date,
    }
    for k, v in replacements.items():
        s = s.replace('{' + k + '}', str(v))
    return s


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
