#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки расписания публикаций планировщика
Показывает, когда планировщик будет публиковать посты
"""

import pytz
from datetime import datetime, timedelta

def check_publication_schedule():
    """Проверяет расписание публикаций"""
    
    # Настройки планировщика
    madrid_tz = pytz.timezone('Europe/Madrid')
    allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22]
    
    print("📅 РАСПИСАНИЕ ПУБЛИКАЦИЙ В TELEGRAM")
    print("=" * 50)
    
    # Текущее время
    current_time = datetime.now(madrid_tz)
    current_hour = current_time.hour
    current_minute = current_time.minute
    
    print(f"🕐 Текущее время (Мадрид): {current_time.strftime('%H:%M:%S')}")
    print(f"   Час: {current_hour}, Минута: {current_minute}")
    print()
    
    # Проверяем текущий час
    if current_hour in allowed_hours:
        if current_minute <= 5:
            print(f"✅ СЕЙЧАС ВРЕМЯ ДЛЯ ПУБЛИКАЦИИ!")
            print(f"   Час {current_hour}:00 - {current_hour}:05")
        else:
            print(f"⏰ Текущий час {current_hour} разрешен, но не время публикации")
            print(f"   Публикация только в {current_hour}:00 - {current_hour}:05")
    else:
        print(f"❌ Текущий час {current_hour} НЕ разрешен для публикации")
    
    print()
    
    # Показываем все разрешенные часы
    print("📋 РАЗРЕШЕННЫЕ ЧАСЫ ПУБЛИКАЦИИ:")
    for hour in allowed_hours:
        status = "✅" if hour == current_hour else "  "
        print(f"   {status} {hour:02d}:00 - {hour:02d}:05")
    
    print()
    
    # Находим следующий час для публикации
    next_publication = None
    for hour in allowed_hours:
        if hour > current_hour or (hour == current_hour and current_minute < 5):
            next_publication = hour
            break
    
    if next_publication:
        if next_publication == current_hour:
            # Следующая публикация в текущем часе
            next_time = current_time.replace(minute=0, second=0, microsecond=0)
            time_until = next_time + timedelta(minutes=5) - current_time
            print(f"⏳ Следующая публикация: {next_publication:02d}:00 - {next_publication:02d}:05")
            print(f"   Осталось: {time_until.seconds // 60} мин {time_until.seconds % 60} сек")
        else:
            # Следующая публикация в будущем часе
            next_time = current_time.replace(hour=next_publication, minute=0, second=0, microsecond=0)
            time_until = next_time - current_time
            print(f"⏳ Следующая публикация: {next_publication:02d}:00 - {next_publication:02d}:05")
            print(f"   Осталось: {time_until.seconds // 3600} ч {(time_until.seconds % 3600) // 60} мин")
    else:
        # Следующая публикация завтра
        tomorrow = current_time + timedelta(days=1)
        next_time = tomorrow.replace(hour=allowed_hours[0], minute=0, second=0, microsecond=0)
        time_until = next_time - current_time
        print(f"⏳ Следующая публикация: завтра в {allowed_hours[0]:02d}:00 - {allowed_hours[0]:02d}:05")
        print(f"   Осталось: {time_until.seconds // 3600} ч {(time_until.seconds % 3600) // 60} мин")
    
    print()
    
    # Показываем логику работы планировщика
    print("🔧 ЛОГИКА РАБОТЫ ПЛАНИРОВЩИКА:")
    print("   1. Запускается каждый час")
    print("   2. Проверяет, подходит ли время для публикации")
    print("   3. Публикация разрешена только в разрешенные часы")
    print("   4. В каждом разрешенном часе - только первые 5 минут")
    print("   5. За час публикуется максимум 1 пост")
    print("   6. Срочные новости публикуются в любое время")
    
    print()
    
    # Показываем примеры
    print("📝 ПРИМЕРЫ ВРЕМЕНИ ПУБЛИКАЦИИ:")
    examples = [
        (9, 0, "✅ 9:00 - публикация разрешена"),
        (9, 3, "✅ 9:03 - публикация разрешена"),
        (9, 6, "❌ 9:06 - публикация запрещена"),
        (12, 0, "✅ 12:00 - публикация разрешена"),
        (15, 0, "❌ 15:00 - час не разрешен"),
        (20, 2, "✅ 20:02 - публикация разрешена"),
        (23, 0, "❌ 23:00 - час не разрешен")
    ]
    
    for hour, minute, status in examples:
        print(f"   {hour:02d}:{minute:02d} - {status}")

if __name__ == "__main__":
    check_publication_schedule()

