#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Улучшенный селектор постов для Telegram
Оценивает ВСЕ статьи и выбирает лучшие по рейтингу
"""

import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict, Counter
import random

class ImprovedPostSelector:
    """Улучшенный селектор постов - оценивает все статьи и выбирает лучшие"""
    
    def __init__(self, settings: Dict[str, Any]):
        """
        Инициализация улучшенного селектора
        
        Args:
            settings: Настройки системы
        """
        self.settings = settings
        self.daily_limit = settings.get('tg_daily_limit', 8)
        self.urgent_limit = settings.get('urgent_limit', 3)
        self.category_cooldown = settings.get('category_cooldown_minutes', 90)
        
        # НОВЫЕ НАСТРОЙКИ: Приоритет качества над разнообразием
        self.quality_weight = settings.get('quality_weight', 0.7)      # 70% - качество
        self.diversity_weight = settings.get('diversity_weight', 0.2)  # 20% - разнообразие
        self.time_spread_weight = settings.get('time_spread_weight', 0.1)  # 10% - время
        
        # Категории для группировки
        self.category_groups = {
            'migration': ['migration', 'visa', 'residence'],
            'economy': ['economy', 'business', 'finance', 'tax'],
            'politics': ['politics', 'government', 'law', 'policy'],
            'society': ['society', 'culture', 'education', 'health'],
            'weather': ['weather', 'climate', 'emergency'],
            'transport': ['transport', 'infrastructure', 'roads'],
            'real_estate': ['real_estate', 'property', 'housing'],
            'tourism': ['tourism', 'travel', 'events'],
            'crime': ['crime', 'police', 'safety'],
            'general': ['general']
        }
        
        logging.info(f"ImprovedPostSelector инициализирован: лимит={self.daily_limit}, "
                    f"качество={self.quality_weight}, разнообразие={self.diversity_weight}")
    
    def _get_category_group(self, category: str) -> str:
        """Определяет группу категории для разнообразия"""
        for group_name, categories in self.category_groups.items():
            if category.lower() in [cat.lower() for cat in categories]:
                return group_name
        return 'other'
    
    def _calculate_quality_score(self, article: Dict[str, Any]) -> float:
        """
        Рассчитывает оценку качества статьи (главный критерий)
        """
        try:
            # Базовый рейтинг (0-100)
            base_score = article.get('score', 0) / 100.0
            
            # Дополнительные факторы качества
            quality_bonus = 0.0
            
            # Бонус за высокий рейтинг
            if base_score > 0.8:  # > 80
                quality_bonus = 0.2
            elif base_score > 0.6:  # > 60
                quality_bonus = 0.1
            elif base_score > 0.4:  # > 40
                quality_bonus = 0.05
            
            # Бонус за срочность
            if article.get('urgent', False):
                quality_bonus += 0.1
            
            # Бонус за свежесть (не старше 7 дней)
            created_at = article.get('created_at')
            if created_at:
                try:
                    if hasattr(created_at, 'timestamp'):
                        days_old = (datetime.now(timezone.utc) - created_at).days
                        if days_old <= 1:
                            quality_bonus += 0.1
                        elif days_old <= 3:
                            quality_bonus += 0.05
                    else:
                        # Если created_at - строка или другой формат
                        quality_bonus += 0.05
                except:
                    pass
            
            final_quality = min(1.0, base_score + quality_bonus)
            return final_quality
            
        except Exception as e:
            logging.warning(f"Ошибка расчета quality_score: {e}")
            return article.get('score', 50) / 100.0
    
    def _calculate_diversity_score(self, article: Dict[str, Any], 
                                 selected_categories: List[str], 
                                 selected_groups: List[str]) -> float:
        """
        Рассчитывает оценку разнообразия (вторичный критерий)
        """
        try:
            category = article.get('category', 'unknown').lower()
            group = self._get_category_group(category)
            
            # Штраф за повторение категории
            category_penalty = 0.0
            if category in selected_categories:
                category_penalty = 0.3
            
            # Штраф за повторение группы
            group_penalty = 0.0
            if group in selected_groups:
                group_penalty = 0.2
            
            # Бонус за новую группу
            group_bonus = 0.0
            if group not in selected_groups:
                group_bonus = 0.3
            
            # Бонус за редкую категорию
            category_frequency = Counter(selected_categories)
            if category in category_frequency:
                rarity_bonus = max(0, 0.2 - (category_frequency[category] * 0.05))
            else:
                rarity_bonus = 0.2
            
            diversity_score = 1.0 - category_penalty - group_penalty + group_bonus + rarity_bonus
            return max(0.0, min(1.0, diversity_score))
            
        except Exception as e:
            logging.warning(f"Ошибка расчета diversity_score: {e}")
            return 0.5
    
    def _calculate_time_spread_score(self, article: Dict[str, Any], 
                                   selected_times: List[str]) -> float:
        """Рассчитывает оценку распределения по времени"""
        try:
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
    
    def _calculate_final_score(self, article: Dict[str, Any], 
                             quality_score: float,
                             diversity_score: float, 
                             time_spread_score: float) -> float:
        """
        Рассчитывает финальную оценку с приоритетом качества
        """
        try:
            # НОВАЯ ФОРМУЛА: Приоритет качества
            final_score = (
                self.quality_weight * quality_score +
                self.diversity_weight * diversity_score +
                self.time_spread_weight * time_spread_score
            )
            
            return final_score
            
        except Exception as e:
            logging.warning(f"Ошибка расчета final_score: {e}")
            return quality_score  # Fallback на качество
    
    def select_posts_for_day(self, all_articles: List[Dict[str, Any]], 
                           available_slots: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Выбирает посты для публикации, оценивая ВСЕ статьи
        
        Args:
            all_articles: ВСЕ статьи для оценки (не только топ-15)
            available_slots: Доступные временные слоты
            
        Returns:
            Словарь {slot_time: article} с выбранными постами
        """
        try:
            logging.info(f"Начинаю улучшенный выбор постов: {len(all_articles)} статей, {len(available_slots)} слотов")
            
            # Разделяем на urgent и обычные
            urgent_articles = [a for a in all_articles if a.get('urgent', False)]
            normal_articles = [a for a in all_articles if not a.get('urgent', False)]
            
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
                        
                        logging.info(f"🚨 Urgent пост размещен в слот {slot}: {urgent.get('title', 'N/A')}")
                        break
            
            # 2. Оцениваем ВСЕ обычные статьи
            normal_with_scores = []
            for article in normal_articles:
                # Рассчитываем все оценки
                quality_score = self._calculate_quality_score(article)
                diversity_score = self._calculate_diversity_score(
                    article, selected_categories, selected_groups
                )
                time_spread_score = self._calculate_time_spread_score(
                    article, selected_times
                )
                final_score = self._calculate_final_score(
                    article, quality_score, diversity_score, time_spread_score
                )
                
                normal_with_scores.append({
                    'article': article,
                    'quality_score': quality_score,
                    'diversity_score': diversity_score,
                    'time_spread_score': time_spread_score,
                    'final_score': final_score
                })
            
            # Сортируем по финальной оценке (лучшие первые)
            normal_with_scores.sort(key=lambda x: x['final_score'], reverse=True)
            
            logging.info(f"Оценено {len(normal_with_scores)} обычных статей")
            if normal_with_scores:
                best_score = normal_with_scores[0]['final_score']
                worst_score = normal_with_scores[-1]['final_score']
                logging.info(f"Диапазон оценок: {best_score:.3f} - {worst_score:.3f}")
            
            # 3. Выбираем лучшие статьи для оставшихся слотов
            normal_placed = 0
            max_normal_posts = min(self.daily_limit - urgent_placed, len(available_slots) - urgent_placed)
            
            for item in normal_with_scores:
                if normal_placed >= max_normal_posts:
                    break
                
                article = item['article']
                category = article.get('category', 'unknown').lower()
                group = self._get_category_group(category)
                
                # Проверяем cooldown категории (мягче)
                if category in selected_categories:
                    last_index = len(selected_categories) - 1 - selected_categories[::-1].index(category)
                    if last_index >= 0:
                        # Если статья очень качественная, игнорируем cooldown
                        if item['quality_score'] > 0.8:
                            logging.info(f"Игнорируем cooldown для качественной статьи: {article.get('title', 'N/A')}")
                        else:
                            continue
                
                # Находим свободный слот
                for slot in available_slots:
                    if slot not in slot_assignments:
                        slot_assignments[slot] = article
                        selected_categories.append(category)
                        selected_groups.append(group)
                        selected_times.append(slot)
                        normal_placed += 1
                        
                        logging.info(f"📝 Пост размещен в слот {slot}: {article.get('title', 'N/A')} "
                                   f"(качество={item['quality_score']:.3f}, "
                                   f"разнообразие={item['diversity_score']:.3f}, "
                                   f"финальная={item['final_score']:.3f})")
                        break
            
            logging.info(f"Выбор завершен: {len(slot_assignments)} постов размещено "
                        f"(срочных: {urgent_placed}, обычных: {normal_placed})")
            
            return slot_assignments
            
        except Exception as e:
            logging.error(f"Ошибка улучшенного выбора постов: {e}")
            return {}
    
    def get_selection_analytics(self, slot_assignments: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """Анализирует результаты выбора постов"""
        try:
            if not slot_assignments:
                return {}
            
            # Собираем статистику
            total_posts = len(slot_assignments)
            categories = [a.get('category', 'unknown').lower() for a in slot_assignments.values()]
            category_distribution = Counter(categories)
            
            # Оценки качества
            quality_scores = []
            for article in slot_assignments.values():
                if 'score' in article:
                    quality_scores.append(article['score'])
            
            analytics = {
                'total_posts': total_posts,
                'category_distribution': dict(category_distribution),
                'unique_categories': len(category_distribution),
                'average_quality': sum(quality_scores) / len(quality_scores) if quality_scores else 0,
                'min_quality': min(quality_scores) if quality_scores else 0,
                'max_quality': max(quality_scores) if quality_scores else 0
            }
            
            return analytics
            
        except Exception as e:
            logging.error(f"Ошибка аналитики выбора: {e}")
            return {}
    
    def suggest_optimizations(self, analytics: Dict[str, Any]) -> List[str]:
        """Предлагает оптимизации на основе аналитики"""
        suggestions = []
        
        try:
            if not analytics:
                return suggestions
            
            total_posts = analytics.get('total_posts', 0)
            unique_categories = analytics.get('unique_categories', 0)
            average_quality = analytics.get('average_quality', 0)
            
            # Анализ разнообразия
            if unique_categories < 3:
                suggestions.append(f"Низкое разнообразие категорий ({unique_categories}) - рассмотрите добавление статей других тем")
            
            # Анализ качества
            if average_quality < 60:
                suggestions.append(f"Низкий средний рейтинг ({average_quality:.1f}) - улучшите качество контента или настройте веса")
            
            # Анализ количества
            if total_posts < 4:
                suggestions.append(f"Недостаточно постов ({total_posts}) - увеличьте объем контента")
            
            return suggestions
            
        except Exception as e:
            logging.error(f"Ошибка предложений оптимизации: {e}")
            return []

def create_improved_post_selector(settings: Dict[str, Any]) -> ImprovedPostSelector:
    """Создает улучшенный селектор постов"""
    return ImprovedPostSelector(settings)







