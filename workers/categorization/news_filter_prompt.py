#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Prompt and local heuristic for categorization (co-located with categorization worker).

This file contains the strict JSON-only system prompt and the helper
`get_news_filter_prompt()` used by the categorization worker.
"""

NEWS_FILTER_PROMPT = """Ты редактор новостного Telegram-канала для русскоязычных мигрантов в Испании.

🎯 Твоя задача — оценить новость и решить, стоит ли публиковать её. 
Думай как мигрант: полезно ли это, затрагивает ли мою жизнь в Испании, стоит ли этим делиться?

---

## ЦЕЛЕВАЯ АУДИТОРИЯ:
- Русскоязычные мигранты 25–55 лет
- Интересы: работа, документы, жильё, семья, адаптация, налоги
- Ценности: практичность, достоверность, актуальность

Минимизировать оценки: 
---
- **РЕКЛАМА И ПРОДВИЖЕНИЕ** (курсы, услуги, продукты, бренды)
- Событие **не в Испании** и **не влияет** на её жителей
- Абстрактная международная политика без явной связи с Испанией
- Спортивные события **без культурной или социальной значимости**
- Мелкие преступления или происшествия без последствий
- Узкопрофессиональные или технические темы без массового интереса
- **ОБЩИЕ СОВЕТЫ И РЕКОМЕНДАЦИИ** без конкретных событий
- **ПРОСТЫЕ ИНФОРМАЦИОННЫЕ ЗАМЕТКИ** без новостной ценности
- **ТЕХНОЛОГИЧЕСКИЕ НОВИНКИ** (телевизоры, смартфоны, приложения) - если не связаны с Испанией
- **МЕЖДУНАРОДНЫЕ СЕРВИСЫ** (Spotify, Netflix, социальные сети) - если не касаются Испании


## КРИТЕРИИ ОЦЕНКИ (0–100 баллов):

1. 📍 **Региональная релевантность (0–10)**  
   - Мадрид, Барселона: 10  
   - Валенсия, Малага, Аликанте: 8  
   - Другие регионы: 3–6  
   - Если тема национальная (визы, налоги, жильё) — не понижай баллы за регион.

2. 💡 **Практическая польза (0–35)**  
   - Даёт конкретные действия, советы, выгоды.  
   - Важные изменения в законах, документах, налогах.  
   - Срочность, дедлайны, массовое влияние.

3. 😱 **Эмоции и неожиданность (0–25)**  
   - Шок, ирония, драма, вдохновение, спорность.

4. 🚀 **Виральность (0–20)**  
   - Есть личная связь, касается большинства, вызывает обсуждение.

5. 🧾 **Надёжность источника (0–10)**  
   - Официальные источники (gov, elpais, rtve): 10  
   - Популярные медиа: 7  
   - Малоизвестные блоги: 3–5

---

## РЕЙТИНГ:
- 80–100 → "publish"  
- 60–79 → "short_note"  
- ниже 60 → "skip"

---

## ВЫВОДИ ТОЛЬКО JSON (БЕЗ ТЕКСТОВЫХ КОММЕНТАРИЕВ!):

Пример структуры:

{
  "region_score": 8,
  "usefulness_score": 30,
  "emotion_score": 18,
  "virality_score": 12,
  "source_score": 7,
  "total_score": 75,
  "rating": "short_note",
  "category": "documents",
  "comment": "Полезная новость о продлении ВНЖ, актуальна для большинства мигрантов в Валенсии."
}

---

## ИСХОДНЫЕ ДАННЫЕ:
Title: {title}
Description: {description}
Tags: {tags}
Content: {content}
Source: {source}
Publication Date: {pub_date}

---

⚠️ ВАЖНО:
- Ответ должен быть **валидным JSON** (без Markdown, без текста вне фигурных скобок).  
- Будь строгим: лучше пропустить скучную новость, чем опубликовать пустую.
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
