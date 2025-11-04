#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОВЕРКА СЛЕДУЮЩЕГО ВРЕМЕНИ ПУБЛИКАЦИИ
Показывает, когда будет следующая возможность публикации
"""

from workers.tools.firebase_client import get_firebase_client
from jobs_scheduler import PublicationSchedulerImproved
from datetime import datetime, timedelta
import pytz

def check_next_publication_time():
    """Проверяет следующее время публикации"""
    
    print("🔍 ПРОВЕРКА СЛЕДУЮЩЕГО ВРЕМЕНИ ПУБЛИКАЦИИ")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        print(f"✅ Планировщик создан успешно")
        
        # Текущее время
        madrid_tz = pytz.timezone('Europe/Madrid')
        current_time = datetime.now(madrid_tz)
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        print(f"\n⏰ ТЕКУЩЕЕ ВРЕМЯ:")
        print(f"   Время: {current_time.strftime('%H:%M:%S')}")
        print(f"   Час: {current_hour}:00")
        print(f"   Минута: {current_minute}")
        
        # Разрешенные часы
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22, 23]
        
        print(f"\n📅 РАЗРЕШЕННЫЕ ЧАСЫ:")
        print(f"   Часы: {allowed_hours}")
        print(f"   Текущий час разрешен: {'✅ ДА' if current_hour in allowed_hours else '❌ НЕТ'}")
        
        # Следующий разрешенный час
        next_allowed_hours = [h for h in allowed_hours if h > current_hour]
        if next_allowed_hours:
            next_hour = next_allowed_hours[0]
            print(f"   Следующий разрешенный час: {next_hour}:00")
            
            # Время до следующего часа
            if next_hour == 23:
                # Следующий час - завтра в 09:00
                tomorrow = current_time + timedelta(days=1)
                next_time = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)
                time_until = next_time - current_time
                print(f"   Время до следующей публикации: {time_until}")
                print(f"   Следующая публикация: завтра в 09:00")
            else:
                # Следующий час - сегодня
                next_time = current_time.replace(hour=next_hour, minute=0, second=0, microsecond=0)
                time_until = next_time - current_time
                print(f"   Время до следующей публикации: {time_until}")
                print(f"   Следующая публикация: сегодня в {next_hour}:00")
        else:
            print(f"   Следующий разрешенный час: завтра в 09:00")
        
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
            print(f"   Можно опубликовать 1 пост в часе {current_hour}:00")
        elif is_hourly_time and not can_publish:
            print(f"\n⚠️  Время подходящее, но есть блокировка")
            print(f"   Дождитесь следующего разрешенного часа")
        else:
            print(f"\n❌ Сейчас не время для публикации")
            print(f"   Дождитесь разрешенного часа")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        if current_hour in allowed_hours:
            if can_publish:
                print(f"   • Сейчас можно публиковать в часе {current_hour}:00")
                print(f"   • Запустите планировщик для публикации")
            else:
                print(f"   • Время подходящее, но есть блокировка")
                print(f"   • Дождитесь следующего разрешенного часа")
        else:
            print(f"   • Текущий час {current_hour}:00 НЕ в списке разрешенных")
            if next_allowed_hours:
                print(f"   • Следующая возможность: {next_allowed_hours[0]}:00")
            else:
                print(f"   • Следующая возможность: завтра в 09:00")
        
    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_next_publication_time()

