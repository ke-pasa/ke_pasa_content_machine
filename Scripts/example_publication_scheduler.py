#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования модуля publication_scheduler.py
Демонстрирует основные возможности планировщика публикаций
"""

import os
import sys
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from workers.tools.pg_client import get_pg_client
from publication_scheduler import create_publication_scheduler


def create_sample_clusters() -> List[Dict[str, Any]]:
    """Создает примеры кластеров для демонстрации"""
    return [
        {
            'cluster_id': 'sample_urgent_1',
            'topic_summary': '🚨 СРОЧНО: Изменения в миграционном законодательстве',
            'publish': True,
            'urgent': True,
            'evergreen': True,
            'priority_score': 90,
            'priority_reason': 'Критически важные изменения для всех мигрантов',
            'event_type': 'policy_change',
            'sensitivity_level': 'sensitive',
            'combined_context': 'Правительство Испании объявило о новых правилах получения ВНЖ',
            'sources': ['https://example.com/policy_change_1'],
            'created_at': datetime.now().isoformat()
        },
        {
            'cluster_id': 'sample_high_priority_1',
            'topic_summary': '🏥 Важная информация о медицинском страховании',
            'publish': True,
            'urgent': False,
            'evergreen': True,
            'priority_score': 85,
            'priority_reason': 'Информация о медицинском обслуживании мигрантов',
            'event_type': 'health',
            'sensitivity_level': 'normal',
            'combined_context': 'Новые правила медицинского страхования для иностранцев',
            'sources': ['https://example.com/health_1'],
            'created_at': datetime.now().isoformat()
        },
        {
            'cluster_id': 'sample_normal_1',
            'topic_summary': '🎭 Фестиваль русской культуры в Барселоне',
            'publish': True,
            'urgent': False,
            'evergreen': False,
            'priority_score': 70,
            'priority_reason': 'Интересное культурное событие для русскоязычного сообщества',
            'event_type': 'local_event',
            'sensitivity_level': 'normal',
            'combined_context': 'Международный фестиваль русской культуры в Барселоне',
            'sources': ['https://example.com/culture_1'],
            'created_at': datetime.now().isoformat()
        },
        {
            'cluster_id': 'sample_digest_1',
            'topic_summary': '💡 Полезные советы: Как открыть банковский счет',
            'publish': True,
            'urgent': False,
            'evergreen': True,
            'priority_score': 60,
            'priority_reason': 'Практические советы для мигрантов',
            'event_type': 'migration_tip',
            'sensitivity_level': 'normal',
            'combined_context': 'Пошаговая инструкция по открытию банковского счета в Испании',
            'sources': ['https://example.com/tips_1'],
            'created_at': datetime.now().isoformat()
        },
        {
            'cluster_id': 'sample_low_priority_1',
            'topic_summary': '🍽️ Новый ресторан русской кухни в Мадриде',
            'publish': True,
            'urgent': False,
            'evergreen': False,
            'priority_score': 45,
            'priority_reason': 'Локальное событие',
            'event_type': 'local_event',
            'sensitivity_level': 'normal',
            'combined_context': 'Открытие нового ресторана русской кухни в центре Мадрида',
            'sources': ['https://example.com/restaurant_1'],
            'created_at': datetime.now().isoformat()
        }
    ]


def demonstrate_publication_scheduler():
    """Демонстрирует основные возможности планировщика"""
    print("🚀 Демонстрация модуля publication_scheduler.py")
    print("=" * 60)
    
    try:
        # Initialize Postgres-backed client (used by the scheduler for settings)
        pg_client = get_pg_client()
        print("✅ Postgres client initialized")
        
        # Create scheduler that expects a Firestore-like client; the scheduler
        # uses only get_settings/save operations which PG client implements.
        scheduler = create_publication_scheduler(pg_client)
        print("✅ Планировщик публикаций создан")
        
        # Получаем настройки
        settings = scheduler.get_settings()
        print(f"📋 Настройки публикации:")
        print(f"   Время публикаций: {settings['publishing_times']}")
        print(f"   Максимум статей на пост: {settings['max_articles_per_post']}")
        print(f"   Порог приоритета: {settings['priority_threshold']}")
        
        # Создаем примеры кластеров
        sample_clusters = create_sample_clusters()
        print(f"\n📦 Создано {len(sample_clusters)} примеров кластеров")
        
        # Демонстрируем срочную публикацию
        print("\n🔴 Демонстрация срочной публикации:")
        urgent_clusters = [c for c in sample_clusters if c.get('urgent', False)]
        
        for cluster in urgent_clusters:
            print(f"  📰 {cluster['topic_summary']}")
            print(f"     Приоритет: {cluster['priority_score']}/100")
            print(f"     Тип события: {cluster['event_type']}")
            
            job = scheduler.schedule_urgent(cluster)
            if job:
                print(f"     ✅ Запланирована срочная публикация: {job['job_id']}")
                print(f"        Время: {job['planned_at']}")
            else:
                print(f"     ❌ Ошибка планирования")
        
        # Демонстрируем планирование на завтра
        print("\n📅 Демонстрация планирования на завтра:")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        
        # Исключаем срочные кластеры
        regular_clusters = [c for c in sample_clusters if not c.get('urgent', False)]
        
        jobs = scheduler.schedule_publications(regular_clusters, tomorrow)
        print(f"Запланировано {len(jobs)} публикаций на {tomorrow}")
        
        for job in jobs:
            print(f"  📝 {job['type'].upper()}: {job['job_id']}")
            print(f"     Время: {job['planned_at']}")
            print(f"     Приоритет: {job['priority_score']}")
            print(f"     Статус: {job['status']}")
            
            if job['type'] == 'digest':
                cluster_count = len(job.get('cluster_ids', []))
                print(f"     Кластеров в дайджесте: {cluster_count}")
        
        # Демонстрируем получение запланированных jobs
        print("\n📋 Демонстрация получения запланированных jobs:")
        scheduled_jobs = scheduler.get_scheduled_jobs(tomorrow)
        print(f"Найдено {len(scheduled_jobs)} jobs на {tomorrow}")
        
        for job in scheduled_jobs:
            print(f"  📋 {job['job_id']}")
            print(f"     Тип: {job['type']}")
            print(f"     Статус: {job['status']}")
            print(f"     Срочная: {'Да' if job.get('urgent', False) else 'Нет'}")
        
        # Демонстрируем обновление статуса
        print("\n🔄 Демонстрация обновления статуса:")
        if scheduled_jobs:
            test_job = scheduled_jobs[0]
            job_id = test_job['job_id']
            
            print(f"  Обновляем статус job {job_id} на 'sent'")
            success = scheduler.update_job_status(job_id, 'sent')
            
            if success:
                print(f"  ✅ Статус успешно обновлен")
            else:
                print(f"  ❌ Ошибка обновления статуса")
        
        print("\n✅ Демонстрация завершена успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка в демонстрации: {e}")
        import traceback
        traceback.print_exc()


def demonstrate_cluster_filtering():
    """Демонстрирует фильтрацию кластеров"""
    print("\n🔍 Демонстрация фильтрации кластеров")
    print("-" * 40)
    
    try:
        pg_client = get_pg_client()
        scheduler = create_publication_scheduler(pg_client)
        settings = scheduler.get_settings()
        
        sample_clusters = create_sample_clusters()
        
        # Фильтруем кластеры
        publishable, urgent = scheduler._filter_clusters_for_publication(sample_clusters, settings)
        
        print(f"📊 Результаты фильтрации:")
        print(f"   Всего кластеров: {len(sample_clusters)}")
        print(f"   Публикуемые: {len(publishable)}")
        print(f"   Срочные: {len(urgent)}")
        
        print(f"\n📰 Публикуемые кластеры:")
        for cluster in publishable:
            print(f"  • {cluster['topic_summary']} (приоритет: {cluster['priority_score']})")
        
        print(f"\n🚨 Срочные кластеры:")
        for cluster in urgent:
            print(f"  • {cluster['topic_summary']} (приоритет: {cluster['priority_score']})")
        
    except Exception as e:
        print(f"❌ Ошибка в демонстрации фильтрации: {e}")


def demonstrate_slot_creation():
    """Демонстрирует создание слотов публикации"""
    print("\n⏰ Демонстрация создания слотов публикации")
    print("-" * 40)
    
    try:
        pg_client = get_pg_client()
        scheduler = create_publication_scheduler(pg_client)
        settings = scheduler.get_settings()
        
        # Создаем слоты на завтра
        tomorrow = datetime.now() + timedelta(days=1)
        slots = scheduler._create_publication_slots(tomorrow, settings)
        
        print(f"📅 Слоты публикации на {tomorrow.strftime('%Y-%m-%d')}:")
        for slot in slots:
            print(f"  🕐 {slot.time} - {slot.datetime.strftime('%Y-%m-%d %H:%M')}")
            print(f"     Максимум статей: {slot.max_articles}")
            print(f"     Доступно слотов: {slot.available_slots}")
        
    except Exception as e:
        print(f"❌ Ошибка в демонстрации слотов: {e}")


if __name__ == "__main__":
    # Настраиваем логирование
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Запускаем демонстрации
    demonstrate_publication_scheduler()
    demonstrate_cluster_filtering()
    demonstrate_slot_creation()
    
    print("\n🎉 Все демонстрации завершены!") 