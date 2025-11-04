#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Система кластеризации новостных анонсов
2-этапный пайплайн с использованием OpenAI API
"""

import json
import os
import hashlib
import re
from typing import List, Dict, Any, Optional, Tuple
from collections import defaultdict
from datetime import datetime
import openai
from firebase_client import get_firebase_client


class NewsCluster:
    """Класс для представления кластера новостей"""
    
    def __init__(self, topic_summary: str, sources: List[Dict], combined_context: str = ""):
        self.cluster_id = f"cluster_{hash(topic_summary) % 1000000}"
        self.topic_summary = topic_summary
        self.sources = sources
        self.combined_context = combined_context
        self.created_at = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'cluster_id': self.cluster_id,
            'topic_summary': self.topic_summary,
            'sources': self.sources,
            'combined_context': self.combined_context,
            'created_at': self.created_at
        }
    
    def __str__(self) -> str:
        return f"Кластер '{self.topic_summary}' ({len(self.sources)} источников)"


class KeywordGrouper:
    """Предварительная группировка анонсов по ключевым словам"""
    
    def __init__(self):
        # Ключевые слова для группировки по темам
        self.topic_keywords = {
            'миграция_внж': [
                'внж', 'вид на жительство', 'резиденция', 'миграция', 'иностранцы', 
                'документы', 'разрешение', 'продление', 'загранпаспорт', 'виза'
            ],
            'налоги_финансы': [
                'налоги', 'налоговая', 'финансы', 'бюджет', 'экономика', 'банк', 
                'кредит', 'ипотека', 'пенсия', 'страховка', 'бизнес', 'предприниматели'
            ],
            'здравоохранение': [
                'медицина', 'здоровье', 'больница', 'врач', 'лечение', 'страховка', 
                'аптека', 'вакцина', 'эпидемия', 'пандемия', 'covid'
            ],
            'образование': [
                'образование', 'школа', 'университет', 'курсы', 'язык', 'испанский', 
                'обучение', 'студенты', 'учителя', 'диплом', 'сертификат'
            ],
            'недвижимость': [
                'недвижимость', 'жилье', 'квартира', 'дом', 'аренда', 'покупка', 
                'ипотека', 'цены', 'рынок', 'агентство', 'строительство'
            ],
            'транспорт': [
                'транспорт', 'автобус', 'метро', 'поезд', 'автомобиль', 'водительские права', 
                'дороги', 'парковка', 'общественный транспорт', 'такси'
            ],
            'культура_развлечения': [
                'культура', 'фестиваль', 'концерт', 'выставка', 'музей', 'театр', 
                'кино', 'ресторан', 'кафе', 'развлечения', 'досуг'
            ],
            'погода_климат': [
                'погода', 'климат', 'температура', 'дождь', 'жара', 'холод', 
                'сезон', 'метеорология', 'прогноз', 'стихия'
            ],
            'политика_законы': [
                'политика', 'правительство', 'законы', 'выборы', 'парламент', 
                'министерство', 'реформа', 'законопроект', 'голосование'
            ],
            'работа_карьера': [
                'работа', 'карьера', 'зарплата', 'трудоустройство', 'вакансии', 
                'компания', 'офис', 'удаленная работа', 'профессия'
            ]
        }
        
        # Географические ключевые слова
        self.geo_keywords = {
            'мадрид': ['мадрид', 'madrid', 'столица', 'центральная испания'],
            'барселона': ['барселона', 'barcelona', 'каталония', 'cataluña'],
            'валенсия': ['валенсия', 'valencia', 'валенсийское сообщество'],
            'севилья': ['севилья', 'sevilla', 'андалусия', 'andalucía'],
            'малага': ['малага', 'málaga', 'коста дель соль'],
            'бильбао': ['бильбао', 'bilbao', 'баскония', 'país vasco'],
            'сарагоса': ['сарагоса', 'zaragoza', 'арагон', 'aragon'],
            'мурсия': ['мурсия', 'murcia', 'мурсийский регион'],
            'пальма': ['пальма', 'palma', 'майорка', 'mallorca', 'балеарские острова'],
            'лас_пальмас': ['лас пальмас', 'las palmas', 'канарские острова']
        }
        
        # Временные ключевые слова
        self.time_keywords = {
            'срочно': ['срочно', 'немедленно', 'экстренно', 'критично', 'важно'],
            'сегодня': ['сегодня', 'вчера', 'завтра', 'на этой неделе'],
            'месяц': ['в этом месяце', 'в прошлом месяце', 'ежемесячно'],
            'год': ['в этом году', 'в прошлом году', 'ежегодно', '2025', '2024']
        }
    
    def extract_keywords(self, text: str) -> List[str]:
        """Извлекает ключевые слова из текста"""
        if not text:
            return []
        
        # Приводим к нижнему регистру и убираем пунктуацию
        text = re.sub(r'[^\w\s]', ' ', text.lower())
        words = text.split()
        
        # Фильтруем короткие слова и стоп-слова
        stop_words = {'и', 'в', 'на', 'с', 'по', 'для', 'от', 'до', 'из', 'за', 'о', 'об', 'а', 'но', 'или', 'что', 'как', 'где', 'когда', 'почему'}
        keywords = [word for word in words if len(word) > 2 and word not in stop_words]
        
        return keywords
    
    def calculate_topic_score(self, announcement: Dict[str, Any]) -> Dict[str, float]:
        """Вычисляет оценку принадлежности к каждой теме"""
        text = f"{announcement.get('title', '')} {announcement.get('summary', '')}"
        keywords = self.extract_keywords(text)
        
        scores = {}
        for topic, topic_keywords in self.topic_keywords.items():
            score = 0
            for keyword in keywords:
                if any(tk in keyword or keyword in tk for tk in topic_keywords):
                    score += 1
            # Нормализуем по длине ключевых слов темы
            scores[topic] = score / len(topic_keywords) if topic_keywords else 0
        
        return scores
    
    def calculate_geo_score(self, announcement: Dict[str, Any]) -> Dict[str, float]:
        """Вычисляет оценку географической принадлежности"""
        text = f"{announcement.get('title', '')} {announcement.get('summary', '')}"
        keywords = self.extract_keywords(text)
        
        scores = {}
        for region, region_keywords in self.geo_keywords.items():
            score = 0
            for keyword in keywords:
                if any(rk in keyword or keyword in rk for rk in region_keywords):
                    score += 1
            scores[region] = score / len(region_keywords) if region_keywords else 0
        
        return scores
    
    def calculate_time_score(self, announcement: Dict[str, Any]) -> Dict[str, float]:
        """Вычисляет оценку временной срочности"""
        text = f"{announcement.get('title', '')} {announcement.get('summary', '')}"
        keywords = self.extract_keywords(text)
        
        scores = {}
        for time_category, time_keywords in self.time_keywords.items():
            score = 0
            for keyword in keywords:
                if any(tk in keyword or keyword in tk for tk in time_keywords):
                    score += 1
            scores[time_category] = score / len(time_keywords) if time_keywords else 0
        
        return scores
    
    def group_announcements(self, announcements: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Группирует анонсы по ключевым словам
        
        Args:
            announcements: Список анонсов для группировки
            
        Returns:
            Словарь групп анонсов
        """
        print(f"🔍 Предварительная группировка {len(announcements)} анонсов по ключевым словам...")
        
        # Вычисляем оценки для каждого анонса
        announcement_scores = []
        for announcement in announcements:
            topic_scores = self.calculate_topic_score(announcement)
            geo_scores = self.calculate_geo_score(announcement)
            time_scores = self.calculate_time_score(announcement)
            
            # Находим лучшую тему
            best_topic = max(topic_scores.items(), key=lambda x: x[1])
            best_geo = max(geo_scores.items(), key=lambda x: x[1]) if any(geo_scores.values()) else ('общие', 0)
            best_time = max(time_scores.items(), key=lambda x: x[1]) if any(time_scores.values()) else ('обычные', 0)
            
            announcement_scores.append({
                'announcement': announcement,
                'topic': best_topic[0],
                'topic_score': best_topic[1],
                'geo': best_geo[0],
                'geo_score': best_geo[1],
                'time': best_time[0],
                'time_score': best_time[1],
                'total_score': best_topic[1] + best_geo[1] + best_time[1]
            })
        
        # Группируем по основной теме
        groups = defaultdict(list)
        ungrouped = []
        
        for scored_announcement in announcement_scores:
            if scored_announcement['topic_score'] > 0.1:  # Минимальный порог
                group_key = f"{scored_announcement['topic']}_{scored_announcement['geo']}"
                groups[group_key].append(scored_announcement['announcement'])
            else:
                ungrouped.append(scored_announcement['announcement'])
        
        # Добавляем негруппированные анонсы в отдельную группу
        if ungrouped:
            groups['разное_общие'] = ungrouped
        
        # Выводим статистику группировки
        print(f"✅ Создано {len(groups)} предварительных групп:")
        for group_name, group_announcements in groups.items():
            print(f"   📁 {group_name}: {len(group_announcements)} анонсов")
        
        return dict(groups)


class NewsClusteringPipeline:
    """Упрощенный пайплайн кластеризации новостей с предварительной группировкой"""
    
    def __init__(self, openai_client: openai.OpenAI, db=None):
        self.openai_client = openai_client
        self.db_client = db or get_firebase_client()
        self.db = self.db_client.db  # Firestore клиент для прямых запросов
        self.batch_size = 75  # Увеличиваем размер батча для лучшего качества кластеризации
        self.use_batch = False  # Всегда используем прямые запросы
        
        # Инициализируем группировщик по ключевым словам
        self.keyword_grouper = KeywordGrouper()
        
        # Кэшируем системный промпт для кластеризации
        self._clustering_system_prompt = self._create_clustering_system_prompt()
        self._clustering_messages = [
            {"role": "system", "content": self._clustering_system_prompt}
        ]
        print("✅ Системный промпт кластеризации кэширован")
        print(f"✅ Размер батча: {self.batch_size} анонсов")
        print("✅ Предварительная группировка по ключевым словам включена")
    
    def _create_clustering_system_prompt(self) -> str:
        """Создает оптимизированный системный промпт для финальной кластеризации"""
        return """Ты эксперт по кластеризации новостей для русскоязычных мигрантов в Испании.

**ЗАДАЧА:**
Создай финальные кластеры новостей по смыслу для последующей генерации статей. Это последний этап кластеризации - создавай сразу готовые группы.

**ПРАВИЛА КЛАСТЕРИЗАЦИИ:**

🎯 **ОБЪЕДИНЯЙ новости, если они:**
- Рассказывают об одном событии с разных ракурсов
- Касаются одной темы (налоги, погода, миграция, культура)
- Происходят в одном регионе/городе Испании
- Связаны временной последовательностью (причина → следствие)
- Дополняют друг друга деталями

🔍 **РАЗДЕЛЯЙ новости, если они:**
- О разных событиях одной тематики
- Происходят в разных регионах без связи
- Имеют разное время (прошлое vs настоящее)
- Касаются разных аспектов жизни

**КРИТЕРИИ КАЧЕСТВА ФИНАЛЬНОГО КЛАСТЕРА:**
- Минимум 2 новости в кластере (снижено для небольших групп)
- Максимум 8 новостей в кластере (для читаемости)
- Логическая связь между новостями
- Потенциал для создания интересной статьи
- Готовность к генерации контента (без дополнительной обработки)

**ФОРМАТ ОТВЕТА:**
Строго в JSON формате, массив объектов кластеров:

```json
[
  {
    "topic_summary": "Краткое описание темы кластера (1-2 предложения)",
    "sources": [
      {
        "title": "Заголовок новости",
        "link": "Ссылка на источник",
        "summary": "Краткое описание"
      }
    ],
    "combined_context": "Объединенный контекст всех новостей (3-5 предложений)"
  }
]
```

**ВАЖНО:**
- Создавай кластеры высокого качества
- Избегай слишком больших или слишком маленьких кластеров
- Фокусируйся на новостях, важных для мигрантов в Испании
- Каждый кластер должен иметь потенциал для интересной статьи
- Учитывай, что новости уже предварительно сгруппированы по темам"""
    
    def cluster_announcements(self, announcements: List[Dict[str, Any]]) -> List[NewsCluster]:
        """
        Кластеризация анонсов с предварительной группировкой по ключевым словам
        
        Args:
            announcements: Список анонсов для кластеризации
            
        Returns:
            Список кластеров
        """
        if not announcements:
            print("⚠️  Нет анонсов для кластеризации")
            return []
        
        print(f"🚀 Начинаю кластеризацию {len(announcements)} анонсов...")
        
        # Этап 1: Предварительная группировка по ключевым словам
        print("\n📊 ЭТАП 1: Предварительная группировка по ключевым словам")
        pre_groups = self.keyword_grouper.group_announcements(announcements)
        
        all_clusters = []
        
        # Этап 2: LLM-кластеризация внутри каждой предварительной группы (финальная)
        print("\n🤖 ЭТАП 2: LLM-кластеризация внутри групп (создание финальных кластеров)")
        
        for group_name, group_announcements in pre_groups.items():
            if len(group_announcements) < 2:  # Снижаем минимальный размер с 3 до 2
                print(f"   ⚠️  Группа '{group_name}' слишком мала ({len(group_announcements)} анонсов), пропускаю")
                continue
            
            print(f"\n   🔍 Обрабатываю группу '{group_name}' ({len(group_announcements)} анонсов)")
            
            # Разбиваем группу на батчи если она слишком большая
            if len(group_announcements) > self.batch_size:
                print(f"      📦 Разбиваю на батчи по {self.batch_size} анонсов...")
                batches = [group_announcements[i:i + self.batch_size] 
                          for i in range(0, len(group_announcements), self.batch_size)]
                
                for i, batch in enumerate(batches, 1):
                    print(f"      🔄 Батч {i}/{len(batches)} ({len(batch)} анонсов)")
                    batch_clusters = self._cluster_batch(batch)
                    all_clusters.extend(batch_clusters)
            else:
                # Обрабатываем всю группу как один батч
                batch_clusters = self._cluster_batch(group_announcements)
                all_clusters.extend(batch_clusters)
        
        # Упрощенная кластеризация: убираем этап объединения похожих кластеров
        # Кластеризация сразу создает финальные группы
        print(f"\n✅ Кластеризация завершена: создано {len(all_clusters)} кластеров")
        return all_clusters
    
    def _cluster_batch(self, batch: List[Dict[str, Any]]) -> List[NewsCluster]:
        """
        Финальная кластеризация одного батча анонсов с использованием кэшированного промпта
        
        Args:
            batch: Список анонсов (до 75 штук)
            
        Returns:
            Список финальных кластеров для этого батча
        """
        # Подготавливаем данные для LLM
        announcements_text = self._format_announcements_for_llm(batch)
        
        # Используем кэшированный системный промпт + только данные анонсов
        user_message = f"""Создай финальные кластеры для следующих {len(batch)} новостных анонсов:

{announcements_text}

Создай готовые кластеры для последующей генерации статей. Это финальный этап кластеризации."""
        
        try:
            # Используем кэшированный системный промпт
            messages = self._clustering_messages + [{"role": "user", "content": user_message}]
            
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=messages,
                response_format={"type": "json_object"},
                max_completion_tokens=2000,  # Увеличиваем для лучшего качества
                temperature=1
            )
            
            result = response.choices[0].message.content.strip()
            
            # Парсим JSON (убираем markdown-разметку если есть)
            try:
                # Убираем markdown-разметку если есть
                clean_result = result.strip()
                if clean_result.startswith('```json'):
                    clean_result = clean_result[7:]
                if clean_result.endswith('```'):
                    clean_result = clean_result[:-3]
                clean_result = clean_result.strip()
                
                clusters_data = json.loads(clean_result)
                clusters = []
                
                # LLM может вернуть объект с ключом 'clusters' или массив напрямую
                if isinstance(clusters_data, dict) and 'clusters' in clusters_data:
                    clusters_list = clusters_data['clusters']
                elif isinstance(clusters_data, list):
                    clusters_list = clusters_data
                else:
                    clusters_list = []
                
                for cluster_data in clusters_list:
                    if isinstance(cluster_data, dict) and 'topic_summary' in cluster_data:
                        cluster = NewsCluster(
                            topic_summary=cluster_data['topic_summary'],
                            sources=cluster_data.get('sources', []),
                            combined_context=cluster_data.get('combined_context', '')
                        )
                        clusters.append(cluster)
                
                print(f"   ✅ Создано {len(clusters)} кластеров")
                return clusters
                
            except json.JSONDecodeError as e:
                print(f"   ⚠️ Ошибка парсинга JSON: {e}")
                print(f"   Ответ LLM: {result[:200]}...")
                return self._fallback_clustering(batch)
                
        except Exception as e:
            print(f"   ⚠️ Ошибка при обращении к OpenAI API: {e}")
            return self._fallback_clustering(batch)
    
    def _merge_similar_clusters(self, clusters: List[NewsCluster]) -> List[NewsCluster]:
        """
        Объединение похожих кластеров с использованием кэшированного промпта
        
        Args:
            clusters: Список кластеров для объединения
            
        Returns:
            Список объединенных кластеров
        """
        if len(clusters) <= 1:
            return clusters
        
        # Подготавливаем данные для LLM
        clusters_text = self._format_clusters_for_merging(clusters)
        
        # Используем кэшированный системный промпт + только данные кластеров
        user_message = f"""Проанализируй следующие кластеры и объедини похожие:

{clusters_text}

Объединяй только те кластеры, которые действительно относятся к одному событию или теме."""
        
        try:
            # Используем кэшированный системный промпт
            messages = self._clustering_messages + [{"role": "user", "content": user_message}]
            
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=messages,
                response_format={"type": "json_object"},
                max_completion_tokens=2000,  # Увеличиваем для лучшего качества
                temperature=1
            )
            
            result = response.choices[0].message.content.strip()
            
            try:
                # Убираем markdown-разметку если есть
                clean_result = result.strip()
                if clean_result.startswith('```json'):
                    clean_result = clean_result[7:]
                if clean_result.endswith('```'):
                    clean_result = clean_result[:-3]
                clean_result = clean_result.strip()
                
                merged_data = json.loads(clean_result)
                merged_clusters = []
                
                # LLM может вернуть объект с ключом 'clusters' или массив напрямую
                if isinstance(merged_data, dict) and 'clusters' in merged_data:
                    clusters_list = merged_data['clusters']
                elif isinstance(merged_data, list):
                    clusters_list = merged_data
                else:
                    clusters_list = []
                
                for cluster_data in clusters_list:
                    if isinstance(cluster_data, dict) and 'topic_summary' in cluster_data:
                        cluster = NewsCluster(
                            topic_summary=cluster_data['topic_summary'],
                            sources=cluster_data.get('sources', []),
                            combined_context=cluster_data.get('combined_context', '')
                        )
                        merged_clusters.append(cluster)
                
                # Если объединение не дало результата, возвращаем исходные кластеры
                if len(merged_clusters) == 0:
                    print(f"   ⚠️ LLM не смог объединить кластеры, оставляем исходные: {len(clusters)}")
                    return clusters
                
                print(f"   ✅ Объединено в {len(merged_clusters)} кластеров")
                return merged_clusters
                
            except json.JSONDecodeError as e:
                print(f"   ⚠️ Ошибка парсинга JSON при объединении: {e}")
                return clusters
                
        except Exception as e:
            print(f"   ⚠️ Ошибка при объединении кластеров: {e}")
            return clusters
    
    def _format_announcements_for_llm(self, announcements: List[Dict[str, Any]]) -> str:
        """Форматирует анонсы для отправки в LLM"""
        formatted = []
        
        for i, ann in enumerate(announcements, 1):
            title = ann.get('title', 'Без заголовка')
            summary = ann.get('summary', 'Без описания')
            link = ann.get('link', '')
            date = ann.get('date', '')
            tags = ', '.join(ann.get('tags', []))
            
            formatted.append(f"""АНОНС {i}:
Заголовок: {title}
Описание: {summary}
Ссылка: {link}
Дата: {date}
Теги: {tags}
---""")
        
        return '\n'.join(formatted)
    
    def _format_clusters_for_merging(self, clusters: List[NewsCluster]) -> str:
        """Форматирует кластеры для анализа слияния"""
        formatted = []
        
        for i, cluster in enumerate(clusters, 1):
            sources_text = '\n'.join([
                f"  - {source.get('title', 'Без заголовка')} ({source.get('link', '')})"
                for source in cluster.sources[:3]  # Показываем первые 3 источника
            ])
            
            formatted.append(f"""КЛАСТЕР {i}:
Тема: {cluster.topic_summary}
Источники ({len(cluster.sources)}):
{sources_text}
Контекст: {cluster.combined_context[:200]}...
---""")
        
        return '\n'.join(formatted)
    
    def _fallback_clustering(self, batch: List[Dict[str, Any]]) -> List[NewsCluster]:
        """
        Fallback-кластеризация при ошибках LLM
        Создает отдельный кластер для каждого анонса
        """
        print("   🔄 Используем fallback-кластеризацию")
        clusters = []
        
        for ann in batch:
            cluster = NewsCluster(
                topic_summary=ann.get('title', 'Без заголовка'),
                sources=[{
                    'title': ann.get('title', ''),
                    'link': ann.get('link', ''),
                    'summary': ann.get('summary', '')
                }],
                combined_context=ann.get('summary', '')
            )
            clusters.append(cluster)
        
        return clusters
    
    def _save_clusters_to_firebase(self, clusters: List[NewsCluster]):
        """Сохраняет кластеры в Firebase"""
        try:
            for cluster in clusters:
                cluster_dict = cluster.to_dict()
                success = self.db_client.save_cluster(cluster_dict)
                
                if success:
                    print(f"   💾 Сохранен кластер: {cluster.topic_summary}")
                else:
                    print(f"   ⚠️ Ошибка сохранения кластера: {cluster.topic_summary}")
                    
        except Exception as e:
            print(f"   ⚠️ Ошибка сохранения в Firebase: {e}")
    
    def get_unpublished_clusters(self, limit: int = 10) -> List[NewsCluster]:
        """
        Получает неопубликованные кластеры из Firebase
        
        Args:
            limit: Максимальное количество кластеров
            
        Returns:
            Список неопубликованных кластеров
        """
        try:
            clusters_data = self.db.get_unpublished_clusters(limit)
            clusters = []
            
            for data in clusters_data:
                cluster = NewsCluster(
                    topic_summary=data['topic_summary'],
                    sources=data['sources'],
                    combined_context=data['combined_context']
                )
                cluster.cluster_id = data['cluster_id']
                cluster.created_at = data['created_at']
                cluster.published = data['published']
                clusters.append(cluster)
            
            return clusters
            
        except Exception as e:
            print(f"⚠️ Ошибка получения кластеров из Firebase: {e}")
            return []
    
    def mark_cluster_as_published(self, cluster_id: str):
        """Отмечает кластер как опубликованный"""
        try:
            success = self.db.mark_cluster_as_published(cluster_id)
            if success:
                print(f"✅ Кластер {cluster_id} отмечен как опубликованный")
            else:
                print(f"⚠️ Ошибка отметки кластера {cluster_id} как опубликованного")
                
        except Exception as e:
            print(f"⚠️ Ошибка обновления статуса кластера: {e}")


def create_clustering_pipeline(openai_client: openai.OpenAI, db=None) -> NewsClusteringPipeline:
    """
    Фабричная функция для создания пайплайна кластеризации
    
    Args:
        openai_client: Клиент OpenAI
        db: Клиент Firebase (опционально)
        
    Returns:
        Экземпляр пайплайна кластеризации
    """
    return NewsClusteringPipeline(openai_client, db) 