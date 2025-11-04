#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Централизованный клиент для работы с Firebase Firestore
Фиксированная структура коллекций для новостного ИИ-бота
"""

import os
import json
import hashlib
from datetime import datetime
from typing import Dict, List, Any, Optional
import firebase_admin
from firebase_admin import credentials, firestore
from firebase_admin import firestore as firestore_types

# Константы для названий коллекций
COLLECTIONS = {
    'CLUSTERS': 'clusters',
    'ARTICLES': 'articles', 
    'PUBLISHED': 'published',
    'SOURCES': 'sources',
    'SKIPPED': 'skipped',
    'JOBS': 'jobs',
    'LOG': 'log',
    'SETTINGS': 'settings'
}

# Кэш для настроек
_settings_cache = None
_settings_cache_time = None
_settings_cache_ttl = 300  # 5 минут


class FirebaseClient:
    """Централизованный клиент для работы с Firebase Firestore"""
    
    def __init__(self, credentials_path: str = 'firebase_key.json'):
        """
        Инициализация Firebase клиента
        
        Args:
            credentials_path: Путь к файлу с ключами Firebase
        """
        self.db = None
        self._init_firebase(credentials_path)
    
    def _init_firebase(self, credentials_path: str):
        """Инициализация подключения к Firebase"""
        try:
            if not os.path.exists(credentials_path):
                raise FileNotFoundError(f"Файл {credentials_path} не найден")
            
            # Проверяем, не инициализирован ли уже Firebase
            if not firebase_admin._apps:
                cred = credentials.Certificate(credentials_path)
                firebase_admin.initialize_app(cred)
            
            self.db = firestore.client()
            self._log_event("Firebase клиент инициализирован успешно", "info")
            
        except Exception as e:
            self._log_event(f"Ошибка инициализации Firebase: {e}", "error")
            raise
    
    def _log_event(self, message: str, level: str = "info"):
        """Логирование событий в коллекцию log"""
        try:
            if os.getenv('FIREBASE_LOG_DISABLED', '0') == '1':
                return
        except Exception:
            pass
        if not self.db:
            print(f"[{level.upper()}] {message}")
            return
        
        try:
            log_data = {
                'message': message,
                'level': level,
                'timestamp': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            
            self.db.collection(COLLECTIONS['LOG']).add(log_data)
            
        except Exception as e:
            print(f"Ошибка логирования: {e}")
            print(f"[{level.upper()}] {message}")
    
    def save_cluster(self, cluster: Dict[str, Any]) -> bool:
        """
        Сохраняет кластер в Firebase
        
        Args:
            cluster: Словарь с данными кластера
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return False
        
        try:
            # Проверяем обязательные поля
            required_fields = ['cluster_id', 'topic_summary', 'sources']
            for field in required_fields:
                if field not in cluster:
                    raise ValueError(f"Отсутствует обязательное поле: {field}")
            
            # Добавляем временные метки
            cluster['created_at'] = firestore_types.SERVER_TIMESTAMP
            cluster['updated_at'] = firestore_types.SERVER_TIMESTAMP
            
            # Сохраняем в коллекцию clusters
            doc_ref = self.db.collection(COLLECTIONS['CLUSTERS']).document(cluster['cluster_id'])
            doc_ref.set(cluster, merge=True)
            
            self._log_event(f"Кластер сохранен: {cluster['cluster_id']}", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка сохранения кластера: {e}", "error")
            return False
    
    def get_unpublished_clusters(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Получает неопубликованные кластеры
        
        Args:
            limit: Максимальное количество кластеров
            
        Returns:
            Список кластеров
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return []
        
        try:
            clusters_ref = self.db.collection(COLLECTIONS['CLUSTERS'])
            query = clusters_ref.where('published', '==', False).order_by('created_at', direction=firestore_types.Query.DESCENDING).limit(limit)
            
            docs = query.stream()
            clusters = []
            
            for doc in docs:
                cluster_data = doc.to_dict()
                cluster_data['doc_id'] = doc.id
                clusters.append(cluster_data)
            
            self._log_event(f"Получено {len(clusters)} неопубликованных кластеров", "info")
            return clusters
            
        except Exception as e:
            self._log_event(f"Ошибка получения кластеров: {e}", "error")
            return []
    
    def mark_cluster_as_published(self, cluster_id: str) -> bool:
        """
        Отмечает кластер как опубликованный
        
        Args:
            cluster_id: ID кластера
            
        Returns:
            True если операция прошла успешно
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return False
        
        try:
            # Обновляем статус кластера
            cluster_ref = self.db.collection(COLLECTIONS['CLUSTERS']).document(cluster_id)
            cluster_ref.update({
                'published': True,
                'published_at': firestore_types.SERVER_TIMESTAMP,
                'updated_at': firestore_types.SERVER_TIMESTAMP
            })
            
            # Добавляем запись в коллекцию published
            published_data = {
                'cluster_id': cluster_id,
                'published_at': firestore_types.SERVER_TIMESTAMP,
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            self.db.collection(COLLECTIONS['PUBLISHED']).add(published_data)
            
            self._log_event(f"Кластер отмечен как опубликованный: {cluster_id}", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка отметки кластера как опубликованного: {e}", "error")
            return False
    
    def is_duplicate_source(self, link: str) -> bool:
        """
        Проверяет, есть ли источник с такой ссылкой
        
        Args:
            link: URL источника
            
        Returns:
            True если источник уже существует
        """
        if not self.db:
            return False
        
        try:
            sources_ref = self.db.collection(COLLECTIONS['SOURCES'])
            query = sources_ref.where('link', '==', link).limit(1)
            docs = list(query.stream())
            
            return len(docs) > 0
            
        except Exception as e:
            self._log_event(f"Ошибка проверки дубликата источника: {e}", "error")
            return False
    
    def is_duplicate_hash(self, hash_value: str) -> bool:
        """
        Проверяет, есть ли источник с таким хешем
        
        Args:
            hash_value: Хеш источника
            
        Returns:
            True если источник уже существует
        """
        if not self.db:
            return False
        
        try:
            sources_ref = self.db.collection(COLLECTIONS['SOURCES'])
            query = sources_ref.where('hash', '==', hash_value).limit(1)
            docs = list(query.stream())
            
            return len(docs) > 0
            
        except Exception as e:
            self._log_event(f"Ошибка проверки дубликата хеша: {e}", "error")
            return False
    
    def save_source_hash(self, link: str, title: str = "", summary: str = "", source_id: str = "", feed_url: str = "") -> bool:
        """
        Сохраняет хеш источника для предотвращения дубликатов
        
        Args:
            link: URL источника
            title: Заголовок
            summary: Описание
            source_id: ID источника
            feed_url: URL RSS-ленты
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return False
        
        try:
            # Создаем хеш из title + summary
            content_for_hash = f"{title}{summary}".strip()
            if not content_for_hash:
                content_for_hash = link
            
            hash_value = hashlib.md5(content_for_hash.encode()).hexdigest()
            
            # Проверяем дубликаты
            if self.is_duplicate_hash(hash_value):
                self._log_event(f"Источник с таким хешем уже существует: {hash_value[:8]}...", "info")
                return True
            
            # Сохраняем источник
            source_data = {
                'link': link,
                'hash': hash_value,
                'title': title,
                'summary': summary,
                'source_id': source_id,
                'feed_url': feed_url,
                'parsed_at': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }
            
            self.db.collection(COLLECTIONS['SOURCES']).add(source_data)
            
            self._log_event(f"Источник сохранен: {hash_value[:8]}...", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка сохранения источника: {e}", "error")
            return False
    
    def get_settings(self) -> Dict[str, Any]:
        """
        Получает настройки из Firebase с кэшированием
        
        Returns:
            Словарь с настройками
            
        Raises:
            Exception: Если отсутствуют критические настройки
        """
        global _settings_cache, _settings_cache_time
        
        # Проверяем кэш
        if (_settings_cache and _settings_cache_time and 
            (datetime.now() - _settings_cache_time).seconds < _settings_cache_ttl):
            return _settings_cache
        
        if not self.db:
            raise Exception("Firebase не инициализирован")
        
        try:
            settings_ref = self.db.collection(COLLECTIONS['SETTINGS']).document('main')
            doc = settings_ref.get()
            
            if not doc.exists:
                # Создаем настройки по умолчанию
                default_settings = {
                    'cluster_batch_size': 20,
                    'llm_model': 'gpt-4o-mini',
                    'publishing_times': ['09:00', '14:00', '20:00'],
                    'publishing_windows': [
                        {"start": "09:00", "end": "11:00"},
                        {"start": "12:00", "end": "14:00"},
                        {"start": "16:00", "end": "18:00"},
                        {"start": "20:00", "end": "22:00"}
                    ],
                    'max_articles_per_post': 2,
                    'rss_check_interval_minutes': 30,
                    'telegram_chat_id': '',
                    'openai_api_key': '',
                    'created_at': firestore_types.SERVER_TIMESTAMP,
                    'updated_at': firestore_types.SERVER_TIMESTAMP
                }
                
                settings_ref.set(default_settings)
                settings = default_settings
                self._log_event("Созданы настройки по умолчанию", "info")
            else:
                settings = doc.to_dict()
            
            # Проверяем критические настройки
            critical_settings = ['llm_model', 'telegram_chat_id']
            missing_settings = [s for s in critical_settings if not settings.get(s)]
            
            if missing_settings:
                raise Exception(f"Отсутствуют критические настройки: {', '.join(missing_settings)}")
            
            # Обновляем кэш
            _settings_cache = settings
            _settings_cache_time = datetime.now()
            
            self._log_event("Настройки загружены из Firebase", "info")
            return settings
            
        except Exception as e:
            self._log_event(f"Ошибка получения настроек: {e}", "error")
            raise
    
    def save_settings(self, settings: Dict[str, Any]) -> bool:
        """
        Сохраняет настройки в Firebase
        
        Args:
            settings: Словарь с настройками
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return False
        
        try:
            # Добавляем временные метки
            settings['updated_at'] = firestore_types.SERVER_TIMESTAMP
            
            # Сохраняем в коллекцию settings
            settings_ref = self.db.collection(COLLECTIONS['SETTINGS']).document('main')
            settings_ref.set(settings, merge=True)
            
            # Сбрасываем кэш
            global _settings_cache, _settings_cache_time
            _settings_cache = None
            _settings_cache_time = None
            
            self._log_event("Настройки успешно обновлены", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка сохранения настроек: {e}", "error")
            return False
    
    def log_event(self, message: str, level: str = "info") -> None:
        """
        Логирует событие в Firebase
        
        Args:
            message: Сообщение для логирования
            level: Уровень логирования (info, warning, error)
        """
        self._log_event(message, level)
    
    def save_article(self, article: Dict[str, Any]) -> bool:
        """
        Сохраняет статью в Firebase
        
        Args:
            article: Словарь с данными статьи
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.db:
            self._log_event("Firebase не инициализирован", "error")
            return False
        
        try:
            # Создаем уникальный ID для статьи
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            content_hash = hashlib.md5(f"{article_link}{article_title}".encode()).hexdigest()
            
            # Добавляем временные метки
            article['created_at'] = firestore_types.SERVER_TIMESTAMP
            article['updated_at'] = firestore_types.SERVER_TIMESTAMP
            
            # Сохраняем в коллекцию articles
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(content_hash)
            doc_ref.set(article, merge=True)
            
            self._log_event(f"Статья сохранена: {content_hash[:8]}...", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка сохранения статьи: {e}", "error")
            return False
    
    def is_duplicate_article(self, link: str, title: str) -> bool:
        """
        Проверяет, есть ли статья с такой ссылкой и заголовком
        
        Args:
            link: URL статьи
            title: Заголовок статьи
            
        Returns:
            True если статья уже существует
        """
        if not self.db:
            return False
        
        try:
            content_hash = hashlib.md5(f"{link}{title}".encode()).hexdigest()
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(content_hash)
            doc = doc_ref.get()
            
            return doc.exists
            
        except Exception as e:
            self._log_event(f"Ошибка проверки дубликата статьи: {e}", "error")
            return False

    def is_duplicate_by_link(self, link: str) -> bool:
        """
        Быстрая проверка существования статьи по полю link (раннее отсечение до LLM)
        """
        if not self.db:
            return False
        try:
            docs = list(self.db.collection(COLLECTIONS['ARTICLES']).where('link', '==', link).limit(1).stream())
            return len(docs) > 0
        except Exception as e:
            self._log_event(f"Ошибка проверки дубликата по ссылке: {e}", "error")
            return False

    def mark_skipped(self, link: str, title: str, summary: str, reason: str) -> None:
        """
        Помечает источник как пропущенный (неинтересный) с возможностью TTL-кэша
        """
        if not self.db:
            return
        try:
            key = f"{link}|{title}|{(summary or '')[:400]}"
            summary_hash = hashlib.md5(key.encode()).hexdigest()
            doc_ref = self.db.collection(COLLECTIONS['SKIPPED']).document(summary_hash)
            doc_ref.set({
                'link': link,
                'title': title,
                'summary_hash': summary_hash,
                'reason': reason,
                'skipped_at': datetime.now().isoformat(),
                'created_at': firestore_types.SERVER_TIMESTAMP
            }, merge=True)
        except Exception as e:
            self._log_event(f"Ошибка сохранения SKIPPED: {e}", "error")

    def was_skipped_recently(self, link: str, title: str, summary: str, ttl_days: int = 7) -> bool:
        """
        Проверяет, отклонялся ли источник недавно (для пропуска повторной LLM-фильтрации)
        """
        if not self.db:
            return False
        try:
            import datetime as dt
            key = f"{link}|{title}|{(summary or '')[:400]}"
            summary_hash = hashlib.md5(key.encode()).hexdigest()
            doc = self.db.collection(COLLECTIONS['SKIPPED']).document(summary_hash).get()
            if not doc.exists:
                return False
            data = doc.to_dict() or {}
            skipped_at = data.get('skipped_at')
            if not skipped_at:
                return True
            t = dt.datetime.fromisoformat(skipped_at)
            return (dt.datetime.now() - t).days < ttl_days
        except Exception as e:
            self._log_event(f"Ошибка проверки SKIPPED: {e}", "error")
            return False
    
    def get_article(self, article_id: str) -> Optional[Dict[str, Any]]:
        """
        Получает статью по ID
        
        Args:
            article_id: ID статьи (хеш)
            
        Returns:
            Словарь с данными статьи или None если не найдена
        """
        if not self.db:
            return None
        
        try:
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(article_id)
            doc = doc_ref.get()
            
            if doc.exists:
                return doc.to_dict()
            else:
                return None
                
        except Exception as e:
            self._log_event(f"Ошибка получения статьи: {e}", "error")
            return None
    
    def update_article(self, article: Dict[str, Any]) -> bool:
        """
        Обновляет существующую статью в Firebase
        
        Args:
            article: Словарь с данными статьи
            
        Returns:
            True если обновление прошло успешно
        """
        if not self.db:
            return False
        
        try:
            # Создаем уникальный ID для статьи
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            content_hash = hashlib.md5(f"{article_link}{article_title}".encode()).hexdigest()
            
            # Добавляем временные метки
            article['updated_at'] = firestore_types.SERVER_TIMESTAMP
            
            # Обновляем в коллекции articles
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(content_hash)
            doc_ref.set(article, merge=True)
            
            self._log_event(f"Статья обновлена: {content_hash[:8]}...", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка обновления статьи: {e}", "error")
            return False
    
    def save_article_ranking(self, article_id: str, ranking: dict) -> bool:
        """
        Сохраняет рейтинг статьи в подполе 'ranking'
        
        Args:
            article_id: ID статьи
            ranking: Словарь с данными рейтинга
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.db:
            return False
        
        try:
            # Получаем ссылку на документ статьи
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(article_id)
            
            # Обновляем только поле ranking
            doc_ref.update({
                'ranking': ranking,
                'ranking_updated_at': firestore_types.SERVER_TIMESTAMP
            })
            
            self._log_event(f"Рейтинг сохранен для статьи {article_id[:8]}...", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка сохранения рейтинга для статьи {article_id}: {e}", "error")
            return False
    
    def update_article_field(self, article_id: str, field_name: str, field_value: Any) -> bool:
        """
        Обновляет конкретное поле статьи в Firebase
        
        Args:
            article_id: ID статьи
            field_name: Название поля для обновления
            field_value: Новое значение поля
            
        Returns:
            True если обновление прошло успешно
        """
        if not self.db:
            return False
        
        try:
            # Получаем ссылку на документ статьи
            doc_ref = self.db.collection(COLLECTIONS['ARTICLES']).document(article_id)
            
            # Обновляем только указанное поле
            doc_ref.update({
                field_name: field_value,
                'updated_at': firestore_types.SERVER_TIMESTAMP
            })
            
            self._log_event(f"Поле {field_name} обновлено для статьи {article_id[:8]}...", "info")
            return True
            
        except Exception as e:
            self._log_event(f"Ошибка обновления поля {field_name} для статьи {article_id}: {e}", "error")
            return False


# Глобальный экземпляр клиента
_firebase_client = None


def get_firebase_client() -> FirebaseClient:
    """
    Получает глобальный экземпляр Firebase клиента
    
    Returns:
        Экземпляр FirebaseClient
    """
    global _firebase_client
    
    if _firebase_client is None:
        _firebase_client = FirebaseClient()
    
    return _firebase_client


def reset_firebase_client():
    """Сбрасывает глобальный экземпляр клиента (для тестов)"""
    global _firebase_client
    _firebase_client = None 