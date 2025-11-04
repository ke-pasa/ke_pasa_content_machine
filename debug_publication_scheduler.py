#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ДИАГНОСТИКА ПЛАНИРОВЩИКА ПУБЛИКАЦИЙ
Проверяет, почему не происходят публикации в Telegram
"""

import os
from datetime import datetime
import pytz
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def debug_publication_scheduler():
    """Диагностика планировщика публикаций"""
    
    print("🔍 ДИАГНОСТИКА ПЛАНИРОВЩИКА ПУБЛИКАЦИЙ")
    print("=" * 60)
    
    try:
        from jobs_scheduler import PublicationSchedulerImproved
        from firebase_client import get_firebase_client
        
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        # Получаем настройки
        settings = scheduler._get_settings()
        
        print(f"✅ Планировщик создан успешно")
        print(f"✅ Настройки получены: {len(settings)} параметров")
        
        # Текущее время
        current_time = datetime.now(scheduler.madrid_tz)
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        print(f"\n⏰ ТЕКУЩЕЕ ВРЕМЯ:")
        print(f"   Время (Madrid): {current_time.strftime('%H:%M:%S')}")
        print(f"   Час: {current_hour}:00")
        print(f"   Минута: {current_minute}")
        
        # Проверяем почасовое время
        is_hourly_time = scheduler._is_hourly_publication_time()
        print(f"\n📅 ПРОВЕРКА ПОЧАСОВОГО ВРЕМЕНИ:")
        print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
        
        # Анализируем логику
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22]
        print(f"   Разрешенные часы: {allowed_hours}")
        print(f"   Текущий час разрешен: {'✅ ДА' if current_hour in allowed_hours else '❌ НЕТ'}")
        print(f"   ✅ УБРАНО ограничение по минутам (0-5)!")
        print(f"   ✅ Можно публиковать в любое время часа {current_hour}:00")
        
        # Проверяем блокировку
        can_publish = scheduler._can_publish_now(settings)
        print(f"\n🔒 ПРОВЕРКА БЛОКИРОВКИ:")
        print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
        
        # Проверяем последнее время публикации
        last_post_time = scheduler._get_last_post_time()
        if last_post_time:
            print(f"   Последняя публикация: {last_post_time.strftime('%H:%M:%S')}")
            
            # Проверяем интервал
            time_since_last = current_time - last_post_time
            min_interval = settings.get('min_post_interval_minutes', 60)
            print(f"   Время с последней публикации: {time_since_last}")
            print(f"   Минимальный интервал: {min_interval} минут")
            print(f"   Интервал соблюден: {'✅ ДА' if time_since_last.total_seconds() >= min_interval * 60 else '❌ НЕТ'}")
        else:
            print(f"   Последняя публикация: НЕТ (первый запуск)")
        
        # Проверяем блокировку по часам
        print(f"\n🔐 ПРОВЕРКА БЛОКИРОВКИ ПО ЧАСАМ:")
        print(f"   Последний час публикации: {scheduler._last_publication_hour}")
        print(f"   Блокировка активна: {'✅ ДА' if scheduler._publication_lock else '❌ НЕТ'}")
        
        # Проверяем статьи для публикации
        print(f"\n📰 ПРОВЕРКА СТАТЕЙ:")
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"   Доступных статей: {len(articles)}")
        
        if articles:
            print(f"   Примеры статей:")
            for i, article in enumerate(articles[:3]):
                title = article.get('title', 'Без заголовка')[:50]
                priority = article.get('priority', 0)
                print(f"     {i+1}. {title} (приоритет: {priority:.2f})")
        else:
            print(f"   ❌ Нет статей для публикации!")
        
        # Анализ проблемы
        print(f"\n🔍 АНАЛИЗ ПРОБЛЕМЫ:")
        
        if not is_hourly_time:
            if current_hour not in allowed_hours:
                print(f"   ❌ Текущий час {current_hour}:00 НЕ в списке разрешенных")
                next_allowed = [h for h in allowed_hours if h > current_hour]
                if next_allowed:
                    print(f"   ⏰ Следующий разрешенный час: {next_allowed[0]}:00")
        else:
            print(f"   ✅ Текущий час {current_hour}:00 разрешен для публикации")
            print(f"   ✅ Можно публиковать в любое время до {(current_hour + 1) % 24}:00")
        
        if not can_publish and is_hourly_time:
            if last_post_time and scheduler._last_publication_hour == current_hour:
                print(f"   ❌ Уже публиковали в этом часу ({current_hour}:00)")
            elif scheduler._publication_lock:
                print(f"   ❌ Активна блокировка публикации")
        
        if not articles:
            print(f"   ❌ Нет статей для публикации - проверьте фильтры")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        if current_hour in allowed_hours:
            if not can_publish:
                print(f"   • Время подходящее, но есть блокировка - проверьте настройки")
            else:
                print(f"   • Время подходящее и можно публиковать - проверьте статьи")
                print(f"   • Можно публиковать в любое время часа {current_hour}:00")
        else:
            print(f"   • Дождитесь разрешенного часа: {allowed_hours}")
        
        if not articles:
            print(f"   • Проверьте фильтры статей (exported_to_site=True, published=False)")
        
        print(f"\n🎯 СТАТУС:")
        if can_publish and articles:
            print(f"   ✅ Система готова к публикации!")
        elif can_publish and not articles:
            print(f"   ⚠️  Можно публиковать, но нет статей")
        elif not can_publish and is_hourly_time:
            print(f"   ⚠️  Время подходящее, но есть блокировка")
        else:
            print(f"   ❌ Сейчас не время для публикации")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_publication_scheduler()
