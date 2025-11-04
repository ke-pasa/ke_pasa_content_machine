#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для автоматической оценки и приоритизации новостных кластеров
Использует LLM для определения важности, срочности и чувствительности новостей
"""

import json
import logging
from typing import List, Dict, Any, Optional
import openai
from workers.tools.firebase_client import get_firebase_client


class NewsPrioritizer:
    """Класс для приоритизации новостных кластеров с помощью LLM"""

    def __init__(self, openai_client: openai.OpenAI, db=None):
        """
        Инициализация приоритизатора

        Args:
            openai_client: Клиент OpenAI
            db: Клиент Firebase (опционально)
        """
        self.openai_client = openai_client
        self.db = db or get_firebase_client()
        self.logger = logging.getLogger(__name__)

    def prioritize_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Приоритизирует список кластеров с помощью LLM

        Args:
            clusters: Список кластеров для оценки

        Returns:
            Список кластеров с добавленными полями приоритизации
        """
        if not clusters:
            self.logger.info("Нет кластеров для приоритизации")
            return []

        try:
            # Формируем промпт для LLM
            prompt = self._create_prioritization_prompt(clusters)
            
            # Вызываем LLM
            response = self._call_llm_for_prioritization(prompt)
            
            # Парсим ответ
            prioritized_clusters = self._parse_llm_response(response, clusters)
            
            self.logger.info(f"Приоритизировано {len(prioritized_clusters)} кластеров")
            return prioritized_clusters

        except Exception as e:
            self.logger.error(f"Ошибка приоритизации кластеров: {e}")
            # Возвращаем исходные кластеры с дефолтными значениями
            return self._add_default_prioritization(clusters)

    def _create_prioritization_prompt(self, clusters: List[Dict[str, Any]]) -> str:
        """
        Создает промпт для LLM на основе кластеров

        Args:
            clusters: Список кластеров

        Returns:
            Промпт для LLM
        """
        # Формируем JSON для входных данных
        input_data = []
        for cluster in clusters:
            cluster_data = {
                "topic_summary": cluster.get('topic_summary', ''),
                "combined_context": cluster.get('combined_context', ''),
                "sources": cluster.get('sources', [])
            }
            input_data.append(cluster_data)

        input_json = json.dumps(input_data, ensure_ascii=False, indent=2)

        prompt = f"""Ты — редактор и стратег новостного бота для русскоязычных мигрантов в Испании.

Твоя задача — определить, нужно ли публиковать новость из кластера, насколько она важна, является ли срочной, вечной, и какую чувствительность имеет.

Каждый кластер содержит одну тему и несколько источников с описаниями.

КРИТЕРИИ ОЦЕНКИ:

🔘 publish: true/false
true — если новость связана с жизнью мигрантов, Испанией, полезна, важна, актуальна.
false — если нерелевантна, старая, частная история без пользы, не связана с Испанией.

🔴 urgent: true/false
true, если важно опубликовать немедленно, даже вне расписания и лимитов:
катастрофы, землетрясения, шторма, экстренное изменение законов, массовые задержания, пожар, обрушение, отмена рейсов, массовые демонстрации.
false — если можно ждать.

🟢 evergreen: true/false
true — если материал будет актуален через недели или месяцы (инструкция, гайд, закон, справка).
false — если быстро устареет или связан с конкретной датой или событием.

🏷️ event_type (одно из):
"emergency", "weather_alert", "policy_change", "crime", "social_issue", "migration_tip", "local_event", "scam_alert", "economic_news", "health", "legal", "education", "transport", "entertainment"

📊 priority_score (0–100)
Оцени влияние темы на жизнь мигрантов, количество затронутых людей, важность.
Если событие локальное, но затрагивает много семей — высокий балл.
Если это частный случай — низкий балл.

📝 priority_reason
Кратко и по сути. Почему ты дал именно такую оценку? Не описывай очевидное.

🔐 sensitivity_level (одно из):
"normal" — нет деликатных тем.
"sensitive" — миграционные конфликты, протесты, политика, конфликты с властями.
"high" — насилие, смерть, трагедии, обвинения, суицид, расизм, детская опасность.

ВХОДНЫЕ ДАННЫЕ:
{input_json}

ИНСТРУКЦИИ:
- Обрабатывай все кластеры — не пропускай.
- Не используй markdown, только JSON-массив.
- Не пиши "Вот результат", не добавляй текст до или после JSON.
- Если возникают сомнения, оцени с точки зрения пользы для мигранта в Испании.

Верни массив объектов с полями: topic_summary, publish, urgent, evergreen, event_type, priority_score, priority_reason, sensitivity_level."""

        return prompt

    def _call_llm_for_prioritization(self, prompt: str) -> str:
        """
        Вызывает LLM для приоритизации

        Args:
            prompt: Промпт для LLM

        Returns:
            Ответ от LLM
        """
        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "Ты редактор новостного бота для русскоязычных мигрантов в Испании. Отвечай только JSON-массивом без дополнительного текста."},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                max_completion_tokens=800,
                temperature=1
            )
            
            return response.choices[0].message.content.strip()

        except Exception as e:
            self.logger.error(f"Ошибка вызова LLM: {e}")
            raise

    def _parse_llm_response(self, response: str, original_clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Парсит ответ LLM и объединяет с исходными кластерами

        Args:
            response: Ответ от LLM
            original_clusters: Исходные кластеры

        Returns:
            Список кластеров с добавленными полями приоритизации
        """
        try:
            # Убираем markdown обертки если есть
            response_clean = response.strip()
            if response_clean.startswith('```json'):
                response_clean = response_clean[7:]
            if response_clean.endswith('```'):
                response_clean = response_clean[:-3]
            response_clean = response_clean.strip()

            # Парсим JSON
            prioritized_data = json.loads(response_clean)
            
            if not isinstance(prioritized_data, list):
                raise ValueError("Ожидался JSON-массив")

            # Объединяем с исходными кластерами
            result = []
            for i, cluster in enumerate(original_clusters):
                if i < len(prioritized_data):
                    # Добавляем поля приоритизации к исходному кластеру
                    cluster_with_priority = cluster.copy()
                    priority_fields = prioritized_data[i]
                    
                    # Проверяем обязательные поля
                    required_fields = ['publish', 'urgent', 'evergreen', 'event_type', 'priority_score', 'priority_reason', 'sensitivity_level']
                    for field in required_fields:
                        if field in priority_fields:
                            cluster_with_priority[field] = priority_fields[field]
                        else:
                            # Дефолтные значения
                            cluster_with_priority[field] = self._get_default_value(field)
                    
                    result.append(cluster_with_priority)
                else:
                    # Если LLM вернул меньше результатов, добавляем дефолтные значения
                    cluster_with_defaults = self._add_default_prioritization([cluster])[0]
                    result.append(cluster_with_defaults)

            return result

        except json.JSONDecodeError as e:
            self.logger.error(f"Ошибка парсинга JSON от LLM: {e}")
            self.logger.error(f"Ответ LLM: {response}")
            return self._add_default_prioritization(original_clusters)
        
        except Exception as e:
            self.logger.error(f"Ошибка обработки ответа LLM: {e}")
            return self._add_default_prioritization(original_clusters)

    def _get_default_value(self, field: str) -> Any:
        """
        Возвращает дефолтное значение для поля приоритизации

        Args:
            field: Название поля

        Returns:
            Дефолтное значение
        """
        defaults = {
            'publish': True,
            'urgent': False,
            'evergreen': False,
            'event_type': 'local_event',
            'priority_score': 50,
            'priority_reason': 'Автоматическая оценка (ошибка LLM)',
            'sensitivity_level': 'normal'
        }
        return defaults.get(field, None)

    def _add_default_prioritization(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Добавляет дефолтные значения приоритизации к кластерам

        Args:
            clusters: Список кластеров

        Returns:
            Список кластеров с дефолтными значениями
        """
        result = []
        for cluster in clusters:
            cluster_with_defaults = cluster.copy()
            for field in ['publish', 'urgent', 'evergreen', 'event_type', 'priority_score', 'priority_reason', 'sensitivity_level']:
                if field not in cluster_with_defaults:
                    cluster_with_defaults[field] = self._get_default_value(field)
            result.append(cluster_with_defaults)
        return result

    def get_high_priority_clusters(self, clusters: List[Dict[str, Any]], min_score: int = 70) -> List[Dict[str, Any]]:
        """
        Возвращает кластеры с высоким приоритетом

        Args:
            clusters: Список кластеров
            min_score: Минимальный балл приоритета

        Returns:
            Список высокоприоритетных кластеров
        """
        return [cluster for cluster in clusters if cluster.get('priority_score', 0) >= min_score]

    def get_urgent_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Возвращает срочные кластеры

        Args:
            clusters: Список кластеров

        Returns:
            Список срочных кластеров
        """
        return [cluster for cluster in clusters if cluster.get('urgent', False)]

    def get_publishable_clusters(self, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Возвращает кластеры, рекомендованные к публикации

        Args:
            clusters: Список кластеров

        Returns:
            Список кластеров для публикации
        """
        return [cluster for cluster in clusters if cluster.get('publish', False)]


def create_prioritizer(openai_client: openai.OpenAI, db=None) -> NewsPrioritizer:
    """
    Создает экземпляр приоритизатора

    Args:
        openai_client: Клиент OpenAI
        db: Клиент Firebase (опционально)

    Returns:
        Экземпляр NewsPrioritizer
    """
    return NewsPrioritizer(openai_client, db)


def prioritize_articles(articles: List[Dict[str, Any]], openai_client: openai.OpenAI, db=None) -> List[Dict[str, Any]]:
    """
    Функция для приоритизации статей (обертка для совместимости)
    
    Args:
        articles: Список статей для приоритизации
        openai_client: Клиент OpenAI
        db: Клиент Firebase (опционально)
        
    Returns:
        Список статей с добавленными полями приоритизации
    """
    prioritizer = create_prioritizer(openai_client, db)
    return prioritizer.prioritize_clusters(articles)


if __name__ == "__main__":
    # Тестовый код
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    
    # Инициализация OpenAI
    openai_client = openai.OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
    
    # Создание приоритизатора
    prioritizer = create_prioritizer(openai_client)
    
    # Тестовые данные
    test_clusters = [
        {
            "topic_summary": "Пожар в общежитии мигрантов в Мадриде",
            "combined_context": "Вчера вечером произошел пожар в общежитии для мигрантов в районе Лавапьес. Пострадало 15 человек, 3 в критическом состоянии.",
            "sources": [
                {
                    "title": "Пожар в общежитии мигрантов",
                    "summary": "Крупный пожар в Мадриде",
                    "link": "https://example.com/fire"
                }
            ]
        },
        {
            "topic_summary": "Как правильно подавать документы на визу по оседлости в 2025 году",
            "combined_context": "Новые правила подачи документов на визу по оседлости вступили в силу с 1 января 2025 года.",
            "sources": [
                {
                    "title": "Новые правила виз",
                    "summary": "Изменения в процедуре",
                    "link": "https://example.com/visa"
                }
            ]
        }
    ]
    
    # Приоритизация
    prioritized = prioritizer.prioritize_clusters(test_clusters)
    
    print("Результат приоритизации:")
    for cluster in prioritized:
        print(f"Тема: {cluster['topic_summary']}")
        print(f"Публиковать: {cluster['publish']}")
        print(f"Срочно: {cluster['urgent']}")
        print(f"Приоритет: {cluster['priority_score']}")
        print(f"Тип: {cluster['event_type']}")
        print(f"Чувствительность: {cluster['sensitivity_level']}")
        print("---") 