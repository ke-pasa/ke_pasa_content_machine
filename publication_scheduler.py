#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для планирования публикаций на основе приоритезированных кластеров
Создает и управляет очередью публикаций в коллекции jobs
"""

import os
import json
import logging
from datetime import datetime, timedelta, time
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import pytz
from workers.tools.firebase_client import FirebaseClient, COLLECTIONS


@dataclass
class PublicationSlot:
    """Слот для публикации"""
    time: str  # HH:MM
    datetime: datetime
    max_articles: int
    used_articles: int = 0
    scheduled_clusters: List[str] = None
    
    def __post_init__(self):
        if self.scheduled_clusters is None:
            self.scheduled_clusters = []
    
    @property
    def available_slots(self) -> int:
        """Количество доступных слотов"""
        return self.max_articles - self.used_articles


class PublicationScheduler:
    """Класс для планирования публикаций на основе приоритезированных кластеров"""
    
    def __init__(self, firebase_client: FirebaseClient, timezone: str = "Europe/Madrid"):
        """
        Инициализация планировщика публикаций
        
        Args:
            firebase_client: Клиент Firebase
            timezone: Часовой пояс (по умолчанию Madrid)
        """
        self.firebase_client = firebase_client
        self.timezone = pytz.timezone(timezone)
        self.logger = logging.getLogger(__name__)
        
        # Настройки по умолчанию
        self.default_settings = {
            'publishing_times': ['09:00', '14:00', '20:00'],
            'max_articles_per_post': 2,
            'priority_threshold': 60,
            'telegram_chat_id': '@spain_kepasa'  # Добавляем дефолтный chat_id
        }
    
    def get_settings(self) -> Dict[str, Any]:
        """Получает настройки из Firebase"""
        try:
            settings = self.firebase_client.get_settings()
            return {
                'publishing_times': settings.get('publishing_times', self.default_settings['publishing_times']),
                'max_articles_per_post': settings.get('max_articles_per_post', self.default_settings['max_articles_per_post']),
                'priority_threshold': settings.get('priority_threshold', self.default_settings['priority_threshold']),
                'telegram_chat_id': settings.get('telegram_chat_id', self.default_settings['telegram_chat_id'])
            }
        except Exception as e:
            # Не логируем предупреждение для telegram_chat_id, так как это нормально
            if 'telegram_chat_id' not in str(e):
                self.logger.warning(f"Ошибка получения настроек, используем дефолтные: {e}")
            return self.default_settings
    
    def _create_publication_slots(self, date: datetime, settings: Dict[str, Any]) -> List[PublicationSlot]:
        """
        Создает слоты для публикаций на указанную дату
        
        Args:
            date: Дата для создания слотов
            settings: Настройки публикации
            
        Returns:
            Список слотов публикации
        """
        slots = []
        publishing_times = settings['publishing_times']
        max_articles = settings['max_articles_per_post']
        
        for time_str in publishing_times:
            # Парсим время
            hour, minute = map(int, time_str.split(':'))
            
            # Создаем datetime в указанном часовом поясе
            # Преобразуем date в datetime
            slot_datetime = datetime.combine(date, time.min).replace(hour=hour, minute=minute, second=0, microsecond=0)
            # Проверяем, есть ли уже часовой пояс
            if slot_datetime.tzinfo is None:
                slot_datetime = self.timezone.localize(slot_datetime)
            else:
                slot_datetime = slot_datetime.astimezone(self.timezone)
            
            slot = PublicationSlot(
                time=time_str,
                datetime=slot_datetime,
                max_articles=max_articles
            )
            slots.append(slot)
        
        return slots
    
    def _filter_clusters_for_publication(self, clusters: List[Dict[str, Any]], settings: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """
        Фильтрует кластеры для публикации
        
        Args:
            clusters: Список кластеров
            settings: Настройки публикации
            
        Returns:
            Кортеж (публикуемые кластеры, срочные кластеры)
        """
        threshold = settings['priority_threshold']
        
        # Отделяем срочные кластеры
        urgent_clusters = [
            cluster for cluster in clusters 
            if cluster.get('urgent', False) and cluster.get('publish', False)
        ]
        
        # Отбираем обычные кластеры для публикации
        publishable_clusters = [
            cluster for cluster in clusters 
            if (cluster.get('publish', False) and 
                cluster.get('priority_score', 0) >= threshold and
                not cluster.get('urgent', False))
        ]
        
        # Сортируем по приоритету (убывание)
        publishable_clusters.sort(key=lambda x: x.get('priority_score', 0), reverse=True)
        
        return publishable_clusters, urgent_clusters
    
    def _check_duplicate_jobs(self, cluster_ids: List[str], date: datetime) -> List[str]:
        """
        Проверяет существующие jobs для кластеров на указанную дату
        
        Args:
            cluster_ids: Список ID кластеров
            date: Дата для проверки
            
        Returns:
            Список ID кластеров, для которых уже есть jobs
        """
        if not self.firebase_client.db:
            return []
        
        try:
            # Получаем jobs на указанную дату
            start_date = datetime.combine(date, time.min)
            end_date = start_date + timedelta(days=1)
            
            jobs_ref = self.firebase_client.db.collection(COLLECTIONS['JOBS'])
            query = jobs_ref.where('planned_at', '>=', start_date.isoformat()).where('planned_at', '<', end_date.isoformat())
            
            existing_jobs = query.stream()
            existing_cluster_ids = set()
            
            for job in existing_jobs:
                job_data = job.to_dict()
                if job_data.get('cluster_id'):
                    existing_cluster_ids.add(job_data['cluster_id'])
            
            return list(existing_cluster_ids)
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки дубликатов jobs: {e}")
            return []
    
    def _create_job_id(self, cluster_id: str, planned_datetime: datetime, job_type: str = "post") -> str:
        """
        Создает уникальный ID для job
        
        Args:
            cluster_id: ID кластера
            planned_datetime: Запланированное время
            job_type: Тип job (post, digest, urgent_post)
            
        Returns:
            Уникальный ID job
        """
        date_str = planned_datetime.strftime('%Y-%m-%d_%H-%M')
        return f"{job_type}_{cluster_id}_{date_str}"
    
    def _save_job(self, job_data: Dict[str, Any]) -> bool:
        """
        Сохраняет job в Firebase
        
        Args:
            job_data: Данные job
            
        Returns:
            True если сохранение прошло успешно
        """
        if not self.firebase_client.db:
            self.logger.error("Firebase не инициализирован")
            return False
        
        try:
            job_id = job_data['job_id']
            doc_ref = self.firebase_client.db.collection(COLLECTIONS['JOBS']).document(job_id)
            doc_ref.set(job_data)
            
            self.logger.info(f"Job сохранен: {job_id}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка сохранения job: {e}")
            return False
    
    def schedule_urgent(self, cluster: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Создает и возвращает job для срочной публикации (немедленно)
        
        Args:
            cluster: Кластер для срочной публикации
            
        Returns:
            Job для срочной публикации или None при ошибке
        """
        try:
            cluster_id = cluster.get('cluster_id')
            if not cluster_id:
                self.logger.error("Отсутствует cluster_id в кластере")
                return None
            
            # Создаем job для немедленной публикации
            now = datetime.now(self.timezone)
            job_id = self._create_job_id(cluster_id, now, "urgent_post")
            
            job_data = {
                'job_id': job_id,
                'cluster_id': cluster_id,
                'planned_at': now.isoformat(),
                'channel': 'telegram',
                'urgent': True,
                'status': 'scheduled',
                'priority_score': cluster.get('priority_score', 0),
                'event_type': cluster.get('event_type', 'emergency'),
                'created_at': now.isoformat(),
                'type': 'post',
                'sensitivity_level': cluster.get('sensitivity_level', 'normal')
            }
            
            # Сохраняем job
            if self._save_job(job_data):
                self.logger.info(f"Срочная публикация запланирована: {cluster_id}")
                return job_data
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка планирования срочной публикации: {e}")
            return None
    
    def create_digest_job(self, unused_clusters: List[Dict[str, Any]], date: datetime) -> Optional[Dict[str, Any]]:
        """
        Создает дайджест-публикацию, если есть интересные кластеры, не попавшие в Telegram
        
        Args:
            unused_clusters: Список неиспользованных кластеров
            date: Дата для дайджеста
            
        Returns:
            Job для дайджеста или None
        """
        if not unused_clusters:
            return None
        
        try:
            # Отбираем 3-5 интересных кластеров для дайджеста
            interesting_clusters = [
                cluster for cluster in unused_clusters
                if cluster.get('priority_score', 0) >= 40  # Минимальный порог для дайджеста
            ]
            
            if not interesting_clusters:
                return None
            
            # Сортируем по приоритету и берем до 5
            interesting_clusters.sort(key=lambda x: x.get('priority_score', 0), reverse=True)
            digest_clusters = interesting_clusters[:5]
            
            # Создаем время для дайджеста (21:30)
            digest_time = date.replace(hour=21, minute=30, second=0, microsecond=0)
            digest_time = self.timezone.localize(digest_time)
            
            # Создаем job для дайджеста
            job_id = f"digest_{date.strftime('%Y-%m-%d')}"
            
            job_data = {
                'job_id': job_id,
                'cluster_ids': [c.get('cluster_id') for c in digest_clusters],
                'planned_at': digest_time.isoformat(),
                'channel': 'telegram',
                'urgent': False,
                'status': 'scheduled',
                'priority_score': max(c.get('priority_score', 0) for c in digest_clusters),
                'event_type': 'digest',
                'created_at': datetime.now(self.timezone).isoformat(),
                'type': 'digest',
                'digest_clusters': digest_clusters
            }
            
            # Сохраняем job
            if self._save_job(job_data):
                self.logger.info(f"Дайджест запланирован на {digest_time.strftime('%Y-%m-%d %H:%M')}")
                return job_data
            else:
                return None
                
        except Exception as e:
            self.logger.error(f"Ошибка создания дайджеста: {e}")
            return None
    
    def schedule_publications(self, clusters: List[Dict[str, Any]], date: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Создает jobs на день — включая срочные, обычные, дайджест
        
        Args:
            clusters: Список кластеров для планирования
            date: Дата для планирования (YYYY-MM-DD), если None - сегодня
            
        Returns:
            Список созданных jobs
        """
        try:
            # Определяем дату
            if date:
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
                target_datetime = datetime.combine(target_date, datetime.min.time())
                # Добавляем часовой пояс
                target_datetime = self.timezone.localize(target_datetime)
            else:
                target_datetime = datetime.now(self.timezone).replace(hour=0, minute=0, second=0, microsecond=0)
            
            # Получаем настройки
            settings = self.get_settings()
            
            # Фильтруем кластеры
            publishable_clusters, urgent_clusters = self._filter_clusters_for_publication(clusters, settings)
            
            # Создаем слоты публикации
            slots = self._create_publication_slots(target_datetime, settings)
            
            # Проверяем существующие jobs
            existing_cluster_ids = self._check_duplicate_jobs(
                [c.get('cluster_id') for c in clusters if c.get('cluster_id')], 
                target_datetime
            )
            
            created_jobs = []
            used_cluster_ids = set()
            
            # 1. Планируем срочные публикации
            for urgent_cluster in urgent_clusters:
                cluster_id = urgent_cluster.get('cluster_id')
                if cluster_id and cluster_id not in existing_cluster_ids:
                    job = self.schedule_urgent(urgent_cluster)
                    if job:
                        created_jobs.append(job)
                        used_cluster_ids.add(cluster_id)
            
            # 2. Планируем обычные публикации по слотам
            cluster_index = 0
            
            for slot in slots:
                while slot.available_slots > 0 and cluster_index < len(publishable_clusters):
                    cluster = publishable_clusters[cluster_index]
                    cluster_id = cluster.get('cluster_id')
                    
                    # Пропускаем уже использованные или существующие
                    if (cluster_id in used_cluster_ids or 
                        cluster_id in existing_cluster_ids or
                        not cluster_id):
                        cluster_index += 1
                        continue
                    
                    # Проверяем ограничения
                    if not self._can_schedule_cluster(cluster, slot, created_jobs):
                        cluster_index += 1
                        continue
                    
                    # Создаем job
                    job_id = self._create_job_id(cluster_id, slot.datetime, "post")
                    
                    job_data = {
                        'job_id': job_id,
                        'cluster_id': cluster_id,
                        'planned_at': slot.datetime.isoformat(),
                        'channel': 'telegram',
                        'urgent': False,
                        'status': 'scheduled',
                        'priority_score': cluster.get('priority_score', 0),
                        'event_type': cluster.get('event_type', 'local_event'),
                        'created_at': datetime.now(self.timezone).isoformat(),
                        'type': 'post',
                        'sensitivity_level': cluster.get('sensitivity_level', 'normal')
                    }
                    
                    if self._save_job(job_data):
                        created_jobs.append(job_data)
                        used_cluster_ids.add(cluster_id)
                        slot.used_articles += 1
                        slot.scheduled_clusters.append(cluster_id)
                    
                    cluster_index += 1
            
            # 3. Создаем дайджест из неиспользованных кластеров
            unused_clusters = [
                cluster for cluster in clusters
                if (cluster.get('cluster_id') and 
                    cluster.get('cluster_id') not in used_cluster_ids and
                    cluster.get('cluster_id') not in existing_cluster_ids)
            ]
            
            digest_job = self.create_digest_job(unused_clusters, target_datetime)
            if digest_job:
                created_jobs.append(digest_job)
            
            self.logger.info(f"Запланировано {len(created_jobs)} публикаций на {target_datetime.strftime('%Y-%m-%d')}")
            return created_jobs
            
        except Exception as e:
            self.logger.error(f"Ошибка планирования публикаций: {e}")
            return []
    
    def _can_schedule_cluster(self, cluster: Dict[str, Any], slot: PublicationSlot, existing_jobs: List[Dict[str, Any]]) -> bool:
        """
        Проверяет, можно ли запланировать кластер в данный слот
        
        Args:
            cluster: Кластер для проверки
            slot: Слот публикации
            existing_jobs: Существующие jobs
            
        Returns:
            True если можно запланировать
        """
        # Проверяем чувствительность
        sensitivity = cluster.get('sensitivity_level', 'normal')
        if sensitivity == 'high':
            # Проверяем, нет ли уже high sensitivity в этом слоте
            for job in existing_jobs:
                if (job.get('planned_at', '').startswith(slot.datetime.strftime('%Y-%m-%d')) and
                    job.get('sensitivity_level') == 'high'):
                    return False
        
        # Проверяем event_type (избегаем повторов)
        event_type = cluster.get('event_type', 'local_event')
        for job in existing_jobs:
            if (job.get('planned_at', '').startswith(slot.datetime.strftime('%Y-%m-%d')) and
                job.get('event_type') == event_type):
                return False
        
        return True
    
    def get_scheduled_jobs(self, date: Optional[str] = None, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Получает запланированные jobs
        
        Args:
            date: Дата для фильтрации (YYYY-MM-DD)
            status: Статус для фильтрации
            
        Returns:
            Список jobs
        """
        if not self.firebase_client.db:
            return []
        
        try:
            jobs_ref = self.firebase_client.db.collection(COLLECTIONS['JOBS'])
            query = jobs_ref
            
            # Фильтруем по дате
            if date:
                target_date = datetime.strptime(date, '%Y-%m-%d').date()
                start_datetime = datetime.combine(target_date, datetime.min.time())
                end_datetime = start_datetime + timedelta(days=1)
                
                query = query.where('planned_at', '>=', start_datetime.isoformat()).where('planned_at', '<', end_datetime.isoformat())
            
            # Фильтруем по статусу
            if status:
                query = query.where('status', '==', status)
            
            jobs = query.stream()
            return [job.to_dict() for job in jobs]
            
        except Exception as e:
            self.logger.error(f"Ошибка получения jobs: {e}")
            return []
    
    def update_job_status(self, job_id: str, status: str) -> bool:
        """
        Обновляет статус job
        
        Args:
            job_id: ID job
            status: Новый статус
            
        Returns:
            True если обновление прошло успешно
        """
        if not self.firebase_client.db:
            return False
        
        try:
            job_ref = self.firebase_client.db.collection(COLLECTIONS['JOBS']).document(job_id)
            job_ref.update({
                'status': status,
                'updated_at': datetime.now(self.timezone).isoformat()
            })
            
            self.logger.info(f"Статус job {job_id} обновлен на {status}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка обновления статуса job {job_id}: {e}")
            return False


def create_publication_scheduler(firebase_client: FirebaseClient, timezone: str = "Europe/Madrid") -> PublicationScheduler:
    """
    Фабричная функция для создания планировщика публикаций
    
    Args:
        firebase_client: Клиент Firebase
        timezone: Часовой пояс
        
    Returns:
        Экземпляр PublicationScheduler
    """
    return PublicationScheduler(firebase_client, timezone) 