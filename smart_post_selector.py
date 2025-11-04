#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Умный селектор постов для Telegram
Обеспечивает выбор лучших постов по рейтингу с тематическим разнообразием
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, Counter
import random


class SmartPostSelector:
    """Умный селектор постов для Telegram с тематическим разнообразием"""
    
    def __init__(self, settings: Dict[str, Any]):
        """
        Инициализация селектора
        
        Args:
            settings: Настройки системы
        """
        self.settings = settings
        self.daily_limit = settings.get('tg_daily_limit', 8)  # Увеличили до 8
        self.urgent_limit = settings.get('urgent_limit', 3)   # Лимит срочных постов
        self.category_cooldown = settings.get('category_cooldown_minutes', 90)
        self.diversity_weight = settings.get('diversity_weight', 0.3)
        self.time_spread_weight = settings.get('time_spread_weight', 0.2)
        
        # Категории для группировки
        self.category_groups = {
            'migration': ['migration', 'visa', 'residence'],
            'economy': ['economy', 'business', 'finance', 'tax'],
            'politics': ['politics', 'government', 'law'],
            'society': ['society', 'culture', 'education', 'health'],
            'weather': ['weather', 'climate', 'emergency'],
            'transport': ['transport', 'infrastructure', 'roads'],
            'real_estate': ['real_estate', 'property', 'housing'],
            'tourism': ['tourism', 'travel', 'events']
        }
        
        logging.info(f"SmartPostSelector инициализирован: лимит={self.daily_limit}, срочных={self.urgent_limit}")
    
    def _get_category_group(self, category: str) -> str:
        """
        Определяет группу категории для разнообразия
        
        Args:
            category: Категория статьи
            
        Returns:
            Группа категории
        """
        for group_name, categories in self.category_groups.items():
            if category.lower() in [cat.lower() for cat in categories]:
                return group_name
        
        return 'other'
    
    def _calculate_diversity_score(self, article: Dict[str, Any], 
                                 selected_categories: List[str], 
                                 selected_groups: List[str]) -> float:
        """
        Рассчитывает оценку разнообразия для статьи
        
        Args:
            article: Статья для оценки
            selected_categories: Уже выбранные категории
            selected_groups: Уже выбранные группы категорий
            
        Returns:
            Оценка разнообразия (0..1)
        """
        try:
            category = article.get('category', 'unknown').lower()
            group = self._get_category_group(category)
            
            # Штраф за повторение категории
            category_penalty = 0.0
            if category in selected_categories:
                category_penalty = 0.5
            
            # Штраф за повторение группы
            group_penalty = 0.0
            if group in selected_groups:
                group_penalty = 0.3
            
            # Бонус за новую группу
            group_bonus = 0.0
            if group not in selected_groups:
                group_bonus = 0.4
            
            # Бонус за редкую категорию
            category_frequency = Counter(selected_categories)
            if category in category_frequency:
                rarity_bonus = max(0, 0.2 - (category_frequency[category] * 0.1))
            else:
                rarity_bonus = 0.2
            
            diversity_score = 1.0 - category_penalty - group_penalty + group_bonus + rarity_bonus
            return max(0.0, min(1.0, diversity_score))
            
        except Exception as e:
            logging.warning(f"Ошибка расчета diversity_score: {e}")
            return 0.5
    
    def _calculate_time_spread_score(self, article: Dict[str, Any], 
                                   selected_times: List[str]) -> float:
        """
        Рассчитывает оценку распределения по времени
        
        Args:
            article: Статья для оценки
            selected_times: Уже выбранные времена
            
        Returns:
            Оценка распределения по времени (0..1)
        """
        try:
            # Если это первая статья, максимальный бонус
            if not selected_times:
                return 1.0
            
            # Анализируем распределение по времени дня
            morning_count = sum(1 for t in selected_times if '09' <= t[:2] <= '11')
            afternoon_count = sum(1 for t in selected_times if '14' <= t[:2] <= '16')
            evening_count = sum(1 for t in selected_times if '20' <= t[:2] <= '22')
            
            # Бонус за равномерное распределение
            time_counts = [morning_count, afternoon_count, evening_count]
            max_count = max(time_counts)
            min_count = min(time_counts)
            
            if max_count == 0:
                spread_score = 1.0
            else:
                spread_score = 1.0 - (max_count - min_count) / max_count
            
            return spread_score
            
        except Exception as e:
            logging.warning(f"Ошибка расчета time_spread_score: {e}")
            return 0.5
    
    def _calculate_final_selection_score(self, article: Dict[str, Any], 
                                       diversity_score: float, 
                                       time_spread_score: float) -> float:
        """
        Рассчитывает финальную оценку для выбора статьи
        
        Args:
            article: Статья для оценки
            diversity_score: Оценка разнообразия
            time_spread_score: Оценка распределения по времени
            
        Returns:
            Финальная оценка для выбора
        """
        try:
            # Базовый рейтинг статьи
            base_score = article.get('score', 0) / 100.0
            
            # Комбинированная оценка
            final_score = (
                (1.0 - self.diversity_weight - self.time_spread_weight) * base_score +
                self.diversity_weight * diversity_score +
                self.time_spread_weight * time_spread_score
            )
            
            return final_score
            
        except Exception as e:
            logging.warning(f"Ошибка расчета final_selection_score: {e}")
            return article.get('score', 50) / 100.0
    
    def select_posts_for_day(self, ranked_articles: List[Dict[str, Any]], 
                           available_slots: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Выбирает посты для публикации в течение дня
        
        Args:
            ranked_articles: Ранжированные статьи
            available_slots: Доступные временные слоты
            
        Returns:
            Словарь {slot_time: article} с выбранными постами
        """
        try:
            logging.info(f"Начинаю умный выбор постов: {len(ranked_articles)} статей, {len(available_slots)} слотов")
            
            # Разделяем на urgent и обычные
            urgent_articles = [a for a in ranked_articles if a.get('urgent', False)]
            normal_articles = [a for a in ranked_articles if not a.get('urgent', False)]
            
            logging.info(f"Найдено срочных: {len(urgent_articles)}, обычных: {len(normal_articles)}")
            
            # Результат выбора
            slot_assignments = {}
            selected_categories = []
            selected_groups = []
            selected_times = []
            
            # 1. Сначала размещаем urgent статьи (без лимитов)
            urgent_placed = 0
            for urgent in urgent_articles:
                if urgent_placed >= self.urgent_limit:
                    logging.info(f"Достигнут лимит срочных постов ({self.urgent_limit})")
                    break
                
                # Находим свободный слот
                for slot in available_slots:
                    if slot not in slot_assignments:
                        slot_assignments[slot] = urgent
                        selected_categories.append(urgent.get('category', 'unknown').lower())
                        selected_groups.append(self._get_category_group(urgent.get('category', 'unknown')))
                        selected_times.append(slot)
                        urgent_placed += 1
                        
                        logging.info(f"Urgent пост размещен в слот {slot}: {urgent.get('title', 'N/A')}")
                        break
            
            # 2. Затем размещаем обычные статьи с учетом разнообразия
            normal_placed = 0
            max_normal_posts = min(self.daily_limit - urgent_placed, len(available_slots) - urgent_placed)
            
            # Сортируем обычные статьи по финальной оценке выбора
            normal_with_scores = []
            for article in normal_articles:
                diversity_score = self._calculate_diversity_score(
                    article, selected_categories, selected_groups
                )
                time_spread_score = self._calculate_time_spread_score(
                    article, selected_times
                )
                final_score = self._calculate_final_selection_score(
                    article, diversity_score, time_spread_score
                )
                
                normal_with_scores.append({
                    'article': article,
                    'diversity_score': diversity_score,
                    'time_spread_score': time_spread_score,
                    'final_score': final_score
                })
            
            # Сортируем по финальной оценке
            normal_with_scores.sort(key=lambda x: x['final_score'], reverse=True)
            
            # Выбираем лучшие с учетом разнообразия
            for item in normal_with_scores:
                if normal_placed >= max_normal_posts:
                    break
                
                article = item['article']
                category = article.get('category', 'unknown').lower()
                group = self._get_category_group(category)
                
                # Проверяем cooldown категории (разрешаем повторения через 2-3 поста)
                if category != 'unknown' and category in selected_categories:
                    # Разрешаем повторение категории через 2-3 поста
                    category_count = selected_categories.count(category)
                    if category_count >= 3:  # Максимум 3 поста одной категории
                        continue
                
                # Находим свободный слот
                for slot in available_slots:
                    if slot not in slot_assignments:
                        slot_assignments[slot] = article
                        selected_categories.append(category)
                        selected_groups.append(group)
                        selected_times.append(slot)
                        normal_placed += 1
                        
                        logging.info(f"Пост размещен в слот {slot}: {article.get('title', 'N/A')} "
                                   f"(diversity={item['diversity_score']:.2f}, "
                                   f"time_spread={item['time_spread_score']:.2f}, "
                                   f"final={item['final_score']:.2f})")
                        break
            
            logging.info(f"Выбор завершен: {len(slot_assignments)} постов размещено "
                        f"(срочных: {urgent_placed}, обычных: {normal_placed})")
            
            return slot_assignments
            
        except Exception as e:
            logging.error(f"Ошибка умного выбора постов: {e}")
            return {}
    
    def get_selection_analytics(self, slot_assignments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Анализирует результаты выбора постов
        
        Args:
            slot_assignments: Результат выбора постов
            
        Returns:
            Аналитика выбора
        """
        try:
            if not slot_assignments:
                return {}
            
            # Статистика по типам
            urgent_count = sum(1 for a in slot_assignments.values() if a.get('urgent', False))
            normal_count = len(slot_assignments) - urgent_count
            
            # Статистика по категориям
            categories = [a.get('category', 'unknown') for a in slot_assignments.values()]
            category_counts = Counter(categories)
            
            # Статистика по группам категорий
            groups = [self._get_category_group(a.get('category', 'unknown')) for a in slot_assignments.values()]
            group_counts = Counter(groups)
            
            # Статистика по времени
            slots = list(slot_assignments.keys())
            morning_count = sum(1 for s in slots if '09' <= s[:2] <= '11')
            afternoon_count = sum(1 for s in slots if '14' <= s[:2] <= '16')
            evening_count = sum(1 for s in slots if '20' <= s[:2] <= '22')
            
            # Средний рейтинг
            scores = [a.get('score', 0) for a in slot_assignments.values()]
            avg_score = sum(scores) / len(scores) if scores else 0
            
            analytics = {
                'total_posts': len(slot_assignments),
                'urgent_posts': urgent_count,
                'normal_posts': normal_count,
                'category_distribution': dict(category_counts),
                'group_distribution': dict(group_counts),
                'time_distribution': {
                    'morning': morning_count,
                    'afternoon': afternoon_count,
                    'evening': evening_count
                },
                'average_score': round(avg_score, 1),
                'score_range': {
                    'min': min(scores) if scores else 0,
                    'max': max(scores) if scores else 0
                }
            }
            
            logging.info(f"Аналитика выбора: {analytics}")
            return analytics
            
        except Exception as e:
            logging.error(f"Ошибка анализа выбора: {e}")
            return {}
    
    def suggest_optimizations(self, analytics: Dict[str, Any]) -> List[str]:
        """
        Предлагает оптимизации на основе аналитики
        
        Args:
            analytics: Аналитика выбора
            
        Returns:
            Список предложений по оптимизации
        """
        try:
            suggestions = []
            
            # Проверяем разнообразие категорий
            category_dist = analytics.get('category_distribution', {})
            if len(category_dist) < 3:
                suggestions.append("Низкое разнообразие категорий - рассмотрите добавление статей других тем")
            
            # Проверяем распределение по времени
            time_dist = analytics.get('time_distribution', {})
            max_time_count = max(time_dist.values()) if time_dist else 0
            min_time_count = min(time_dist.values()) if time_dist else 0
            if max_time_count - min_time_count > 2:
                suggestions.append("Неравномерное распределение по времени - оптимизируйте временные слоты")
            
            # Проверяем средний рейтинг
            avg_score = analytics.get('average_score', 0)
            if avg_score < 70:
                suggestions.append("Низкий средний рейтинг - улучшите качество контента или настройте веса")
            
            # Проверяем количество постов
            total_posts = analytics.get('total_posts', 0)
            if total_posts < self.daily_limit * 0.7:
                suggestions.append(f"Недостаточно постов ({total_posts}/{self.daily_limit}) - увеличьте объем контента")
            
            return suggestions
            
        except Exception as e:
            logging.error(f"Ошибка генерации предложений: {e}")
            return ["Ошибка анализа - проверьте логи системы"]


def create_smart_post_selector(settings: Dict[str, Any]) -> SmartPostSelector:
    """
    Фабричная функция для создания SmartPostSelector
    
    Args:
        settings: Настройки системы
        
    Returns:
        Экземпляр SmartPostSelector
    """
    return SmartPostSelector(settings)
