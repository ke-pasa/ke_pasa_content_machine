#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для исправления окон публикации в Firebase
Добавляет промежуточные окна для покрытия всего дня
"""

from workers.tools.firebase_client import get_firebase_client
import json

def check_current_windows():
    """Проверяет текущие окна публикации"""
    print("🔍 ПРОВЕРКА ТЕКУЩИХ ОКОН ПУБЛИКАЦИИ")
    print("=" * 50)
    
    try:
        firebase_client = get_firebase_client()
        settings = firebase_client.get_settings()
        
        current_windows = settings.get('publishing_windows', [])
        
        print(f"📊 Текущие окна публикации: {len(current_windows)}")
        
        if current_windows:
            for i, window in enumerate(current_windows, 1):
                start = window.get('start', 'НЕТ')
                end = window.get('end', 'НЕТ')
                print(f"   {i}. {start} - {end}")
        else:
            print("   ❌ Окна публикации не настроены!")
        
        # Анализируем покрытие дня
        print(f"\n📅 АНАЛИЗ ПОКРЫТИЯ ДНЯ:")
        
        if current_windows:
            # Сортируем окна по времени начала
            sorted_windows = sorted(current_windows, key=lambda x: x.get('start', '00:00'))
            
            # Проверяем промежутки
            for i in range(len(sorted_windows) - 1):
                current_end = sorted_windows[i].get('end', '00:00')
                next_start = sorted_windows[i + 1].get('start', '00:00')
                
                if current_end < next_start:
                    print(f"   ⚠️  Промежуток: {current_end} - {next_start}")
                else:
                    print(f"   ✅ Перекрытие: {current_end} - {next_start}")
            
            # Проверяем начало и конец дня
            first_start = sorted_windows[0].get('start', '00:00')
            last_end = sorted_windows[-1].get('end', '00:00')
            
            if first_start > '09:00':
                print(f"   ⚠️  Позднее начало дня: {first_start}")
            else:
                print(f"   ✅ Раннее начало дня: {first_start}")
            
            if last_end < '22:00':
                print(f"   ⚠️  Ранний конец дня: {last_end}")
            else:
                print(f"   ✅ Поздний конец дня: {last_end}")
        else:
            print("   ❌ Нет окон для анализа")
        
        return current_windows
        
    except Exception as e:
        print(f"❌ Ошибка при проверке окон: {e}")
        return []

def create_optimized_windows():
    """Создает оптимизированные окна публикации"""
    print(f"\n🚀 СОЗДАНИЕ ОПТИМИЗИРОВАННЫХ ОКОН ПУБЛИКАЦИИ")
    print("=" * 50)
    
    # Новые окна для лучшего покрытия дня
    optimized_windows = [
        {"start": "09:00", "end": "11:00"},    # Утреннее окно
        {"start": "12:00", "end": "14:00"},    # Обеденное окно (НОВОЕ!)
        {"start": "16:00", "end": "18:00"},    # Вечернее окно (НОВОЕ!)
        {"start": "20:00", "end": "22:00"}     # Ночное окно
    ]
    
    print("📋 Новые окна публикации:")
    for i, window in enumerate(optimized_windows, 1):
        start = window['start']
        end = window['end']
        print(f"   {i}. {start} - {end}")
    
    # Анализируем покрытие
    print(f"\n📅 АНАЛИЗ ПОКРЫТИЯ:")
    
    # Проверяем промежутки
    for i in range(len(optimized_windows) - 1):
        current_end = optimized_windows[i]['end']
        next_start = optimized_windows[i + 1]['start']
        
        if current_end < next_start:
            gap_hours = int(next_start.split(':')[0]) - int(current_end.split(':')[0])
            print(f"   ✅ Промежуток {current_end} - {next_start} ({gap_hours} ч) - нормально")
        else:
            print(f"   ❌ Перекрытие {current_end} - {next_start}")
    
    # Проверяем общее покрытие
    total_hours = 0
    for window in optimized_windows:
        start_hour = int(window['start'].split(':')[0])
        end_hour = int(window['end'].split(':')[0])
        total_hours += (end_hour - start_hour)
    
    print(f"   📊 Общее покрытие: {total_hours} часов в день")
    print(f"   📊 Покрытие с 9:00 до 22:00: {total_hours}/13 = {(total_hours/13)*100:.1f}%")
    
    return optimized_windows

def update_publishing_windows():
    """Обновляет окна публикации в Firebase"""
    print(f"\n🔧 ОБНОВЛЕНИЕ ОКОН ПУБЛИКАЦИИ В FIREBASE")
    print("=" * 50)
    
    try:
        firebase_client = get_firebase_client()
        
        # Получаем текущие настройки
        current_settings = firebase_client.get_settings()
        
        # Создаем новые окна
        new_windows = create_optimized_windows()
        
        # Обновляем настройки
        updated_settings = current_settings.copy()
        updated_settings['publishing_windows'] = new_windows
        
        # Добавляем дополнительные настройки для лучшей работы
        updated_settings.update({
            'max_articles_per_window': 2,           # Максимум 2 статьи в окне
            'min_post_interval_minutes': 30,        # Минимум 30 минут между постами
            'enable_urgent_publications': True,     # Включить срочные публикации
            'urgent_override_windows': True,        # Срочные статьи вне окон
            'max_daily_posts': 8,                   # Максимум 8 постов в день
            'window_cooldown_minutes': 15           # 15 минут отдыха между окнами
        })
        
        # Сохраняем в Firebase
        success = firebase_client.save_settings(updated_settings)
        
        if success:
            print("✅ Окна публикации успешно обновлены!")
            print(f"📋 Новые настройки:")
            for key, value in updated_settings.items():
                if key == 'publishing_windows':
                    print(f"   {key}: {len(value)} окон")
                    for i, window in enumerate(value, 1):
                        print(f"     {i}. {window['start']} - {window['end']}")
                else:
                    print(f"   {key}: {value}")
        else:
            print("❌ Ошибка при сохранении настроек")
        
        return success
        
    except Exception as e:
        print(f"❌ Ошибка при обновлении окон: {e}")
        return False

def test_publishing_windows():
    """Тестирует новые окна публикации"""
    print(f"\n🧪 ТЕСТИРОВАНИЕ НОВЫХ ОКОН ПУБЛИКАЦИИ")
    print("=" * 50)
    
    try:
        firebase_client = get_firebase_client()
        settings = firebase_client.get_settings()
        
        windows = settings.get('publishing_windows', [])
        
        if not windows:
            print("❌ Окна публикации не найдены!")
            return
        
        print("📋 Текущие окна:")
        for i, window in enumerate(windows, 1):
            start = window.get('start', '00:00')
            end = window.get('end', '00:00')
            print(f"   {i}. {start} - {end}")
        
        # Тестируем разные времена
        test_times = [
            ("08:30", "До первого окна"),
            ("10:00", "В первом окне"),
            ("12:30", "В обеденном окне"),
            ("15:00", "Между окнами"),
            ("17:00", "В вечернем окне"),
            ("21:00", "В ночном окне"),
            ("23:00", "После всех окон")
        ]
        
        print(f"\n🕐 ТЕСТИРОВАНИЕ ВРЕМЕНИ:")
        
        for time_str, description in test_times:
            # Простая проверка - находим активное окно
            active_window = None
            for window in windows:
                start = window.get('start', '00:00')
                end = window.get('end', '00:00')
                
                if start <= time_str <= end:
                    active_window = window
                    break
            
            if active_window:
                print(f"   🟢 {time_str} ({description}): Активно окно {active_window['start']}-{active_window['end']}")
            else:
                print(f"   🔴 {time_str} ({description}): Нет активных окон")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
        return False

if __name__ == "__main__":
    print("🎯 ИСПРАВЛЕНИЕ ОКОН ПУБЛИКАЦИИ В FIREBASE")
    print("=" * 60)
    
    # Проверяем текущее состояние
    current_windows = check_current_windows()
    
    # Создаем оптимизированные окна
    new_windows = create_optimized_windows()
    
    # Спрашиваем пользователя
    print(f"\n🚀 Найдено {len(current_windows)} текущих окон")
    print(f"💡 Предлагается {len(new_windows)} новых окон")
    
    response = input("\nХотите обновить окна публикации? (y/n): ")
    if response.lower() in ['y', 'yes', 'да']:
        # Обновляем окна
        if update_publishing_windows():
            # Тестируем новые окна
            test_publishing_windows()
            print(f"\n🎉 Обновление завершено успешно!")
        else:
            print(f"\n❌ Ошибка при обновлении!")
    else:
        print("❌ Обновление отменено пользователем")





