#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для обновления окон публикаций в Firebase
Исправляет настройки согласно требованиям:
- 09:00 - 11:00 (утреннее)
- 12:00 - 14:00 (обеденное) 
- 16:00 - 18:00 (вечернее)
- 20:00 - 22:00 (ночное)
"""

import sys
import os
from datetime import datetime
import pytz

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from firebase_client import get_firebase_client

def update_publishing_windows():
    """Обновляет окна публикаций в Firebase"""
    try:
        print("🔄 Обновление окон публикаций в Firebase...")
        
        # Получаем клиент Firebase
        client = get_firebase_client()
        
        # Получаем текущие настройки
        current_settings = client.get_settings()
        print(f"📋 Текущие настройки загружены")
        
        # Новые окна публикаций
        new_publishing_windows = [
            {"start": "09:00", "end": "11:00"},    # Утреннее
            {"start": "12:00", "end": "14:00"},    # Обеденное
            {"start": "16:00", "end": "18:00"},    # Вечернее
            {"start": "20:00", "end": "22:00"}     # Ночное
        ]
        
        # Обновляем настройки
        current_settings['publishing_windows'] = new_publishing_windows
        
        # Также обновляем tg_slots_local для соответствия новым окнам
        current_settings['tg_slots_local'] = [
            "09:00", "10:00", "11:00",           # Утреннее окно
            "12:00", "13:00", "14:00",           # Обеденное окно
            "16:00", "17:00", "18:00",           # Вечернее окно
            "20:00", "21:00", "22:00"            # Ночное окно
        ]
        
        # Сохраняем обновленные настройки
        success = client.save_settings(current_settings)
        
        if success:
            print("✅ Окна публикаций успешно обновлены!")
            print("\n📅 Новые окна публикаций:")
            for i, window in enumerate(new_publishing_windows, 1):
                print(f"   {i}. {window['start']} - {window['end']}")
            
            print(f"\n⏰ Слоты для публикаций: {len(current_settings['tg_slots_local'])} часов")
            print(f"📊 Покрытие дня: 8/13 часов = 61.5%")
            
            return True
        else:
            print("❌ Ошибка сохранения настроек")
            return False
            
    except Exception as e:
        print(f"❌ Ошибка обновления окон публикаций: {e}")
        return False

def test_publishing_windows():
    """Тестирует новые окна публикаций"""
    try:
        print("\n🧪 Тестирование новых окон публикаций...")
        
        client = get_firebase_client()
        settings = client.get_settings()
        
        # Проверяем окна
        windows = settings.get('publishing_windows', [])
        print(f"📋 Загружено {len(windows)} окон публикаций:")
        
        for i, window in enumerate(windows, 1):
            print(f"   {i}. {window['start']} - {window['end']}")
        
        # Проверяем слоты
        slots = settings.get('tg_slots_local', [])
        print(f"\n⏰ Слоты для публикаций: {len(slots)} часов")
        print(f"   {', '.join(slots)}")
        
        # Тестируем текущее время
        madrid_tz = pytz.timezone('Europe/Madrid')
        current_time = datetime.now(madrid_tz)
        current_hour = current_time.hour
        current_time_str = current_time.strftime("%H:%M")
        
        print(f"\n🕐 Текущее время (Мадрид): {current_time_str}")
        print(f"   Час: {current_hour}")
        
        # Проверяем, в каком окне мы находимся
        from jobs_scheduler import PublishingWindow
        
        active_window = None
        for window_data in windows:
            window = PublishingWindow(
                start=window_data['start'],
                end=window_data['end']
            )
            if window.is_active(current_time):
                active_window = window
                break
        
        if active_window:
            print(f"✅ Текущее время входит в окно публикации: {active_window.start} - {active_window.end}")
        else:
            print(f"❌ Текущее время НЕ входит в окна публикации")
            
            # Показываем ближайшее окно
            for window_data in windows:
                window = PublishingWindow(
                    start=window_data['start'],
                    end=window_data['end']
                )
                start_hour = int(window.start.split(':')[0])
                if start_hour > current_hour:
                    print(f"   Следующее окно: {window.start} - {window.end}")
                    break
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        return False

def main():
    """Основная функция"""
    print("🚀 ОБНОВЛЕНИЕ ОКОН ПУБЛИКАЦИЙ")
    print("=" * 50)
    print("🎯 Цель: Исправить окна публикаций согласно требованиям")
    print("📅 Новые окна:")
    print("   • 09:00 - 11:00 (утреннее)")
    print("   • 12:00 - 14:00 (обеденное)")
    print("   • 16:00 - 18:00 (вечернее)")
    print("   • 20:00 - 22:00 (ночное)")
    print("=" * 50)
    
    # Обновляем настройки
    if update_publishing_windows():
        # Тестируем
        test_publishing_windows()
        
        print("\n" + "=" * 50)
        print("🎉 ОБНОВЛЕНИЕ ЗАВЕРШЕНО!")
        print("✅ Окна публикаций исправлены")
        print("✅ 17:00 теперь входит в вечернее окно (16:00-18:00)")
        print("✅ Покрытие дня: 8/13 часов = 61.5%")
        
    else:
        print("\n❌ ОБНОВЛЕНИЕ НЕ УДАЛОСЬ")
        print("Проверьте логи и попробуйте снова")

if __name__ == "__main__":
    main()




