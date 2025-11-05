#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОМПТ ДЛЯ ФИЛЬТРАЦИИ НОВОСТЕЙ
Система оценки интереса для ЦА с учетом региональных приоритетов
"""
 
NEWS_FILTER_PROMPT = """Ты редактор новостного Telegram-канала для русскоязычных мигрантов в Испании.

🎯 Твоя задача — оценить новость и решить, стоит ли публиковать её. 
Думай как мигрант: полезно ли это, затрагивает ли мою жизнь в Испании, стоит ли этим делиться?

---

## ЦЕЛЕВАЯ АУДИТОРИЯ:
- Русскоязычные мигранты 25–55 лет
- Интересы: работа, документы, жильё, семья, адаптация, налоги
- Ценности: практичность, достоверность, актуальность

---

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
    """Возвращает промпт для фильтрации новостей"""
    return NEWS_FILTER_PROMPT.format(
        title=title,
        description=description,
        tags=tags,
        content=content,
        source=source,
        pub_date=pub_date
    )

def validate_news_interest(news_data):
    """
    Валидирует новость по критериям интереса для ЦА
    """
    # Базовые проверки
    title = news_data.get('title', '')
    description = news_data.get('description', '')
    content = news_data.get('content', '')
    tags = news_data.get('tags', [])
    source = news_data.get('source', '')
    pub_date = news_data.get('pub_date', '')
    
    # Проверяем региональную релевантность
    priority_regions = ['мадрид', 'madrid', 'барселона', 'barcelona', 'bcn']
    high_priority_regions = ['малага', 'malaga', 'валенсия', 'valencia', 'аликанте', 'alicante']
    medium_priority_regions = ['марбейя', 'marbella', 'коста дель соль', 'costa del sol']
    
    # Проверяем во всех полях
    all_text = f"{title} {description} {' '.join(tags)} {content}".lower()
    
    has_priority_region = any(region in all_text for region in priority_regions)
    has_high_priority_region = any(region in all_text for region in high_priority_regions)
    has_medium_priority_region = any(region in all_text for region in medium_priority_regions)
    
    # Проверяем практическую пользу
    practical_keywords = ['документы', 'внж', 'паспорт', 'виза', 'разрешение', 'закон', 'правила', 'процедура', 'стоимость', 'цена', 'налог', 'работа', 'бизнес', 'жилье', 'аренда', 'покупка', 'приложение', 'система', 'изменения', 'новые правила', 'детский сад', 'образование', 'русский язык', 'русскоязычные', 'семьи', 'семей']
    has_practical_value = any(keyword in all_text for keyword in practical_keywords)
    
    # Проверяем срочность
    urgency_keywords = ['срочно', 'немедленно', 'сегодня', 'завтра', 'на этой неделе', 'в течение', 'срок', 'дедлайн', '1 сентября', 'с 1 сентября']
    has_urgency = any(keyword in all_text for keyword in urgency_keywords)
    
    # Проверяем масштаб
    scale_keywords = ['тысяч', 'миллион', 'все', 'каждый', 'многие', 'большинство', 'система', 'вся', 'весь', '30%', 'треть', 'треть всех']
    has_scale = any(keyword in all_text for keyword in scale_keywords)
    
    # Проверяем эмоциональность
    emotional_keywords = ['шок', 'драма', 'трагедия', 'кризис', 'катастрофа', 'сенсация', 'скандал', 'победа', 'успех', 'праздник', 'шокирующая', 'закрыли', 'закрытие', 'приятная новость', 'открылся', 'открытие', 'новый']
    has_emotions = any(keyword in all_text for keyword in emotional_keywords)
    
    # Проверяем виральность
    viral_keywords = ['спорно', 'противоречиво', 'разные мнения', 'обсуждение', 'дебаты', 'критика', 'поддержка', 'ужесточение', 'новые правила']
    has_viral_potential = any(keyword in all_text for keyword in viral_keywords)
    
    # Оценка по критериям
    regional_score = 0
    if has_priority_region:
        regional_score = 10
    elif has_high_priority_region:
        regional_score = 8
    elif has_medium_priority_region:
        regional_score = 6
    else:
        regional_score = 3
    
    surprise_score = 0
    if has_emotions:
        surprise_score += 15
    if has_viral_potential:
        surprise_score += 10
    
    importance_score = 0
    if has_practical_value:
        importance_score += 20
    if has_urgency:
        importance_score += 10
    if has_scale:
        importance_score += 5
    
    viral_score = 0
    if has_viral_potential:
        viral_score += 20
    if has_practical_value:
        viral_score += 10
    
    total_score = regional_score + surprise_score + importance_score + viral_score
    
    # Определяем рекомендацию
    if total_score >= 80:
        recommendation = "ПУБЛИКОВАТЬ"
        level = "высокий интерес"
    elif total_score >= 60:
        recommendation = "КРАТКАЯ ЗАМЕТКА"
        level = "средний интерес"
    else:
        recommendation = "НЕ ПУБЛИКОВАТЬ"
        level = "низкий интерес"
    
    return {
        'total_score': total_score,
        'regional_score': regional_score,
        'surprise_score': surprise_score,
        'importance_score': importance_score,
        'viral_score': viral_score,
        'recommendation': recommendation,
        'level': level,
        'analysis': {
            'has_priority_region': has_priority_region,
            'has_high_priority_region': has_high_priority_region,
            'has_medium_priority_region': has_medium_priority_region,
            'has_practical_value': has_practical_value,
            'has_urgency': has_urgency,
            'has_scale': has_scale,
            'has_emotions': has_emotions,
            'has_viral_potential': has_viral_potential
        }
    }

if __name__ == "__main__":
    print("🚀 ПРОМПТ ДЛЯ ФИЛЬТРАЦИИ НОВОСТЕЙ ГОТОВ К ИСПОЛЬЗОВАНИЮ!")
    print("Система оценки:")
    print("- Региональная релевантность: 0-10 баллов")
    print("- Удивление и эмоции: 0-25 баллов")
    print("- Важность информации: 0-35 баллов")
    print("- Виральность и делительность: 0-30 баллов")
    print("- Максимальный балл: 100")
    print("- Рекомендации: ПУБЛИКОВАТЬ (80-100), КРАТКАЯ ЗАМЕТКА (60-79), НЕ ПУБЛИКОВАТЬ (0-59)")
