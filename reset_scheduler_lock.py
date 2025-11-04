#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
СБРОС БЛОКИРОВКИ ПЛАНИРОВЩИКА
Снимает блокировку для принудительного тестирования
"""

from firebase_client import get_firebase_client
from jobs_scheduler import PublicationSchedulerImproved

def reset_scheduler_lock():
    """Сбрасывает блокировку планировщика"""
    
    print("🔓 СБРОС БЛОКИРОВКИ ПЛАНИРОВЩИКА")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        print(f"✅ Планировщик создан успешно")
        
        # Проверяем текущее состояние
        print(f"\n🔍 ТЕКУЩЕЕ СОСТОЯНИЕ:")
        print(f"   Последний час публикации: {scheduler._last_publication_hour}")
        print(f"   Блокировка активна: {'✅ ДА' if scheduler._publication_lock else '❌ НЕТ'}")
        
        # Сбрасываем блокировку
        scheduler._last_publication_hour = None
        scheduler._publication_lock = False
        
        print(f"\n🔓 БЛОКИРОВКА СБРОШЕНА:")
        print(f"   Последний час публикации: {scheduler._last_publication_hour}")
        print(f"   Блокировка активна: {'✅ ДА' if scheduler._publication_lock else '❌ НЕТ'}")
        
        # Проверяем настройки
        settings = scheduler._get_settings()
        print(f"\n📱 НАСТРОЙКИ TELEGRAM:")
        print(f"   Chat ID: {settings.get('telegram_chat_id', 'НЕ НАЙДЕН')}")
        print(f"   Bot Token: {'✅ УСТАНОВЛЕН' if settings.get('telegram_bot_token') else '❌ НЕ НАЙДЕН'}")
        
        # Проверяем время публикации
        is_hourly_time = scheduler._is_hourly_publication_time()
        can_publish = scheduler._can_publish_now(settings)
        
        print(f"\n⏰ ВРЕМЯ ПУБЛИКАЦИИ:")
        print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
        print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
        
        if is_hourly_time and can_publish:
            print(f"\n🚀 СИСТЕМА ГОТОВА К ПУБЛИКАЦИИ!")
            print(f"   Можно запустить планировщик")
        else:
            print(f"\n❌ Сейчас не время для публикации")
            print(f"   Проверьте разрешенные часы")
        
    except Exception as e:
        print(f"❌ Ошибка сброса блокировки: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reset_scheduler_lock()

