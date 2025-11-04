#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для ранжирования статей для публикации в Telegram
Включает LLM-оценку, расчет рейтингов и выбор лучших постов
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
import math


def compute_recency_score(published_at: datetime, half_life_hours: int = 6) -> float:
    """
    Экспоненциальное затухание: 1.0 в первые часы, потом плавно вниз (0..1).
    
    Args:
        published_at: Время публикации статьи
        half_life_hours: Время полураспада в часах (по умолчанию 6)
        
    Returns:
        Оценка актуальности от 0 до 1
    """
    try:
        # Убеждаемся что published_at имеет timezone
        if published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)
        
        now = datetime.now(timezone.utc)
        hours_ago = (now - published_at).total_seconds() / 3600
        
        if hours_ago <= 0:
            return 1.0
        
        # Экспоненциальное затухание
        score = math.exp(-hours_ago * math.log(2) / half_life_hours)
        return max(0.0, min(1.0, score))
        
    except Exception as e:
        logging.warning(f"Ошибка расчета recency_score: {e}")
        return 0.5


def estimate_snackability_len(content: str) -> float:
    """
    Грубая оценка: можно ли упаковать в 900–1000 символов (0..1).
    
    Args:
        content: Содержимое статьи
        
    Returns:
        Оценка "закусочности" от 0 до 1
    """
    try:
        if not content:
            return 0.5
        
        # Убираем HTML теги и лишние пробелы
        clean_content = content.replace('<', ' <').replace('>', '> ')
        words = clean_content.split()
        
        # Оценка на основе количества слов
        word_count = len(words)
        
        if word_count <= 150:  # Легко упаковать
            return 1.0
        elif word_count <= 300:  # Средняя сложность
            return 0.7
        elif word_count <= 500:  # Сложно, но возможно
            return 0.4
        else:  # Очень сложно
            return 0.1
            
    except Exception as e:
        logging.warning(f"Ошибка оценки snackability: {e}")
        return 0.5


def llm_quick_assess(openai_client, article: dict) -> dict:
    """
    LLM-оценка статьи для Telegram поста.
    
    Args:
        openai_client: OpenAI клиент
        article: Словарь с данными статьи
        
    Returns:
        Словарь с оценками и метаданными
    """
    try:
        # Формируем промпт
        system_prompt = """Ты редактор телеграм-новостей. Оцени пригодность материала для короткого, ёмкого поста. Строго JSON."""

        user_prompt = f"""Статья (русский текст):

TITLE: {article.get('title', 'N/A')}
DESCRIPTION: {article.get('description', 'N/A')}
CATEGORY: {article.get('category', 'N/A')}
PRIORITY_SCORE: {article.get('priority_score', 0)}    # 0..100
URGENT: {article.get('urgent', False)}                    # true/false

СУТЬ (первые 1200 символов контента):
{article.get('content', '')[:1200]}

Оцени по шкале 0..1:
- usefulness: практическая польза для жизни в Испании (деньги/правила/безопасность/что делать).
- emotional_hook: вызывает интерес, эмоцию, спор, риск, конфликт, «что делать сейчас».
- can_fit_1000: true/false — можно ли уложить читаемую суть в 900–1000 символов.
- bullets: дай 2–4 предельно коротких тезиса по сути (не более 12 слов каждый).

Ответ ТОЛЬКО JSON:
{{ "usefulness":0.0, "emotional_hook":0.0, "can_fit_1000":true, "bullets":["...","..."] }}"""

        # Вызываем LLM (синхронная версия)
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            response_format={"type": "json_object"},
            max_tokens=200,
            temperature=0.2
        )
        
        # Парсим ответ
        content = response.choices[0].message.content
        result = json.loads(content)
        
        # Валидируем результат
        required_fields = ['usefulness', 'emotional_hook', 'can_fit_1000', 'bullets']
        for field in required_fields:
            if field not in result:
                raise ValueError(f"Отсутствует поле: {field}")
        
        # Нормализуем значения
        result['usefulness'] = max(0.0, min(1.0, float(result['usefulness'])))
        result['emotional_hook'] = max(0.0, min(1.0, float(result['emotional_hook'])))
        result['can_fit_1000'] = bool(result['can_fit_1000'])
        result['bullets'] = list(result.get('bullets', []))
        
        logging.info(f"LLM оценка для статьи '{article.get('title', 'N/A')}': {result}")
        return result
        
    except Exception as e:
        logging.error(f"Ошибка LLM оценки статьи: {e}")
        # Возвращаем значения по умолчанию
        return {
            "usefulness": 0.5,
            "emotional_hook": 0.5,
            "can_fit_1000": True,
            "bullets": []
        }


def simple_score(article: dict, assess: dict) -> float:
    """
    Итоговый балл (0..100), без регионов/источников.
    
    Args:
        article: Словарь с данными статьи
        assess: Словарь с LLM-оценкой
        
    Returns:
        Финальный рейтинг от 0 до 100
    """
    try:
        # Базовые компоненты
        priority_score_raw = article.get('priority_score', 0)
        if isinstance(priority_score_raw, str):
            try:
                priority_score = float(priority_score_raw) / 100.0
            except (ValueError, TypeError):
                priority_score = 0.0
        else:
            priority_score = float(priority_score_raw or 0) / 100.0  # Нормализуем к 0..1
        usefulness = float(assess.get('usefulness', 0.5))
        emotional_hook = float(assess.get('emotional_hook', 0.5))
        
        # Recency score
        published_at_str = article.get('created_at') or article.get('published_date')
        if published_at_str:
            try:
                if isinstance(published_at_str, str):
                    if published_at_str.strip():
                        published_at = datetime.fromisoformat(published_at_str.replace('Z', '+00:00'))
                    else:
                        published_at = datetime.now(timezone.utc)
                else:
                    # Это уже datetime объект
                    published_at = published_at_str
                recency = compute_recency_score(published_at)
            except:
                recency = 0.5
        else:
            recency = 0.5
        
        # Snackability
        snack = 1.0 if assess.get('can_fit_1000', True) else 0.5
        
        # Веса компонентов
        weights = {
            'priority': 0.40,
            'usefulness': 0.25,
            'emotional': 0.20,
            'recency': 0.10,
            'snack': 0.05
        }
        
        # Расчет финального рейтинга
        score = (
            weights['priority'] * priority_score +
            weights['usefulness'] * usefulness +
            weights['emotional'] * emotional_hook +
            weights['recency'] * recency +
            weights['snack'] * snack
        ) * 100
        
        return max(0.0, min(100.0, score))
        
    except Exception as e:
        logging.error(f"Ошибка расчета simple_score: {e}")
        return 50.0


def rank_for_telegram(openai_client, firebase_client, articles: List[dict], settings: dict) -> List[dict]:
    """
    Ранжирует статьи для публикации в Telegram.
    
    Args:
        openai_client: OpenAI клиент
        firebase_client: Firebase клиент
        articles: Список статей для ранжирования
        settings: Настройки ранжирования
        
    Returns:
        Список статей с рейтингами
    """
    try:
        logging.info(f"Начинаю ранжирование {len(articles)} статей для Telegram")
        
        ranked_articles = []
        
        for article in articles:
            try:
                # LLM-оценка
                assess = llm_quick_assess(openai_client, article)
                
                # Расчет рейтинга
                score = simple_score(article, assess)
                
                # Формируем данные для сохранения
                ranking_data = {
                    "score": score,
                    "components": {
                        "priority": float(article.get('priority_score', 0) or 0) / 100.0 if not isinstance(article.get('priority_score'), str) else float(article.get('priority_score', 0)) / 100.0,
                        "usefulness": assess.get('usefulness', 0.5),
                        "emotional": assess.get('emotional_hook', 0.5),
                        "recency": compute_recency_score(
                            datetime.fromisoformat(article.get('created_at', '').replace('Z', '+00:00'))
                            if article.get('created_at') and isinstance(article.get('created_at'), str) and article.get('created_at').strip() else datetime.now(timezone.utc)
                        ),
                        "snack": 1.0 if assess.get('can_fit_1000', True) else 0.5
                    },
                    "urgent_effective": article.get('urgent', False),
                    "assess": assess,
                    "decided_at": datetime.now(timezone.utc)
                }
                
                # Сохраняем рейтинг в Firebase
                article_id = article.get('id') or article.get('article_id')
                if article_id and firebase_client:
                    try:
                        firebase_client.save_article_ranking(article_id, ranking_data)
                        logging.info(f"Рейтинг сохранен для статьи {article_id}: {score:.1f}")
                    except Exception as e:
                        logging.warning(f"Не удалось сохранить рейтинг для статьи {article_id}: {e}")
                
                # Добавляем рейтинг к статье
                article['ranking'] = ranking_data
                article['score'] = score
                
                # Формируем результат для возврата
                result_article = {
                    'id': article_id,
                    'score': score,
                    'urgent': article.get('urgent', False),
                    'ranking': ranking_data,
                    'bullets': assess.get('bullets', []),
                    'can_fit_1000': assess.get('can_fit_1000', True),
                    'title': article.get('title', ''),
                    'category': article.get('category', ''),
                    'content': article.get('content', '')
                }
                
                ranked_articles.append(result_article)
                
            except Exception as e:
                logging.error(f"Ошибка ранжирования статьи '{article.get('title', 'N/A')}': {e}")
                continue
        
        # Сортируем по рейтингу (убывание)
        ranked_articles.sort(key=lambda x: x['score'], reverse=True)
        
        logging.info(f"Ранжирование завершено: {len(ranked_articles)} статей обработано")
        return ranked_articles
        
    except Exception as e:
        logging.error(f"Критическая ошибка ранжирования: {e}")
        return []


def filter_articles_by_category_cooldown(articles: List[dict], cooldown_minutes: int = 90) -> List[dict]:
    """
    Фильтрует статьи по cooldown категорий.
    
    Args:
        articles: Список статей
        cooldown_minutes: Время cooldown в минутах
        
    Returns:
        Отфильтрованный список статей
    """
    try:
        if not articles:
            return []
        
        filtered = []
        category_last_used = {}
        
        for article in articles:
            category = article.get('category', 'unknown')
            current_time = datetime.now(timezone.utc)
            
            # Проверяем cooldown
            if category in category_last_used:
                time_diff = (current_time - category_last_used[category]).total_seconds() / 60
                if time_diff < cooldown_minutes:
                    logging.info(f"Статья '{article.get('title', 'N/A')}' пропущена из-за cooldown категории {category}")
                    continue
            
            # Обновляем время последнего использования категории
            category_last_used[category] = current_time
            filtered.append(article)
        
        return filtered
        
    except Exception as e:
        logging.error(f"Ошибка фильтрации по cooldown категорий: {e}")
        return articles


def select_articles_for_slots(ranked_articles: List[dict], settings: dict) -> Dict[str, dict]:
    """
    Выбирает статьи для временных слотов.
    
    Args:
        ranked_articles: Ранжированные статьи
        settings: Настройки публикации
        
    Returns:
        Словарь {slot_time: article}
    """
    try:
        slots = settings.get('tg_slots_local', [])
        daily_limit = settings.get('tg_daily_limit', 6)
        topk = settings.get('rank_topk_llm', 12)
        
        # Берем топ статьи
        top_articles = ranked_articles[:topk]
        
        # Разделяем на urgent и обычные
        urgent_articles = [a for a in top_articles if a.get('urgent', False)]
        normal_articles = [a for a in top_articles if not a.get('urgent', False)]
        
        # Urgent статьи публикуем сразу
        slot_assignments = {}
        used_articles = set()
        
        # Сначала размещаем urgent статьи
        for urgent in urgent_articles:
            if len(slot_assignments) < len(slots):
                # Находим свободный слот
                for slot in slots:
                    if slot not in slot_assignments:
                        slot_assignments[slot] = urgent
                        used_articles.add(urgent['id'])
                        logging.info(f"Urgent статья назначена на слот {slot}: {urgent['title']}")
                        break
        
        # Затем размещаем обычные статьи
        normal_available = [a for a in normal_articles if a['id'] not in used_articles]
        normal_available = filter_articles_by_category_cooldown(normal_available)
        
        for article in normal_available:
            if len(slot_assignments) >= daily_limit:
                break
                
            # Находим свободный слот
            for slot in slots:
                if slot not in slot_assignments:
                    slot_assignments[slot] = article
                    used_articles.add(article['id'])
                    logging.info(f"Статья назначена на слот {slot}: {article['title']}")
                    break
        
        logging.info(f"Выбрано {len(slot_assignments)} статей для {len(slots)} слотов")
        return slot_assignments
        
    except Exception as e:
        logging.error(f"Ошибка выбора статей для слотов: {e}")
        return {}
