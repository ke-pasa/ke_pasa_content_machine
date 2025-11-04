#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Главный скрипт для исправления всех проблем с системой
1. Исправляет поле summary в статьях
2. Настраивает окна публикации
3. Тестирует систему
"""

import os
import sys
from datetime import datetime
import pytz

def main():
    """Главная функция исправления"""
    print("🚀 ИСПРАВЛЕНИЕ ВСЕХ ПРОБЛЕМ С СИСТЕМОЙ")
    print("=" * 60)
    print(f"⏰ Время запуска: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # Проверяем наличие необходимых модулей
    try:
        from check_summary_field import check_summary_field, fix_summary_field
        from fix_publishing_windows import check_current_windows, update_publishing_windows, test_publishing_windows
        print("✅ Все модули загружены успешно")
    except ImportError as e:
        print(f"❌ Ошибка импорта модулей: {e}")
        print("   Убедитесь, что все скрипты находятся в одной папке")
        return
    
    # Шаг 1: Проверяем поле summary
    print(f"\n🔍 ШАГ 1: ПРОВЕРКА ПОЛЯ SUMMARY")
    print("-" * 40)
    
    stats = check_summary_field()
    if not stats:
        print("❌ Не удалось проверить поле summary")
        return
    
    # Шаг 2: Исправляем поле summary если нужно
    if stats['without_summary'] > 0:
        print(f"\n🔧 ШАГ 2: ИСПРАВЛЕНИЕ ПОЛЯ SUMMARY")
        print("-" * 40)
        
        response = input(f"Найдено {stats['without_summary']} статей без summary. Исправить? (y/n): ")
        if response.lower() in ['y', 'yes', 'да']:
            fixed_count = fix_summary_field()
            print(f"✅ Исправлено {fixed_count} статей!")
        else:
            print("❌ Исправление summary отменено")
    else:
        print("✅ Все статьи имеют поле summary!")
    
    # Шаг 3: Проверяем окна публикации
    print(f"\n🔍 ШАГ 3: ПРОВЕРКА ОКОН ПУБЛИКАЦИИ")
    print("-" * 40)
    
    current_windows = check_current_windows()
    
    # Шаг 4: Обновляем окна публикации
    print(f"\n🔧 ШАГ 4: ОБНОВЛЕНИЕ ОКОН ПУБЛИКАЦИИ")
    print("-" * 40)
    
    response = input("Обновить окна публикации для лучшего покрытия дня? (y/n): ")
    if response.lower() in ['y', 'yes', 'да']:
        if update_publishing_windows():
            print("✅ Окна публикации обновлены!")
            
            # Тестируем новые окна
            print(f"\n🧪 ШАГ 5: ТЕСТИРОВАНИЕ НОВЫХ ОКОН")
            print("-" * 40)
            test_publishing_windows()
        else:
            print("❌ Ошибка при обновлении окон публикации")
    else:
        print("❌ Обновление окон отменено")
    
    # Шаг 5: Финальная проверка
    print(f"\n🔍 ШАГ 5: ФИНАЛЬНАЯ ПРОВЕРКА")
    print("-" * 40)
    
    # Проверяем summary еще раз
    print("📊 Проверяем поле summary...")
    final_stats = check_summary_field()
    
    # Проверяем окна публикации
    print("\n📊 Проверяем окна публикации...")
    final_windows = check_current_windows()
    
    # Итоговый отчет
    print(f"\n🎉 ИТОГОВЫЙ ОТЧЕТ")
    print("=" * 40)
    
    if final_stats:
        print(f"📋 Статьи:")
        print(f"   ✅ Полные: {final_stats['complete']}")
        print(f"   ❌ Без summary: {final_stats['without_summary']}")
        print(f"   ❌ Без title: {final_stats['without_title']}")
        print(f"   ❌ Без link: {final_stats['without_link']}")
    
    if final_windows:
        print(f"📅 Окна публикации: {len(final_windows)}")
        for i, window in enumerate(final_windows, 1):
            start = window.get('start', 'НЕТ')
            end = window.get('end', 'НЕТ')
            print(f"   {i}. {start} - {end}")
    
    # Рекомендации
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    print("-" * 40)
    
    if final_stats and final_stats['without_summary'] > 0:
        print("⚠️  Все еще есть статьи без summary:")
        print("   - Запустите скрипт check_summary_field.py для детального анализа")
        print("   - Проверьте процесс парсинга RSS")
    
    if final_windows and len(final_windows) >= 4:
        print("✅ Окна публикации настроены оптимально")
        print("   - Система должна публиковать статьи в течение дня")
    else:
        print("⚠️  Окна публикации требуют настройки")
        print("   - Запустите скрипт fix_publishing_windows.py")
    
    print(f"\n🚀 Следующие шаги:")
    print("   1. Перезапустите оркестратор")
    print("   2. Мониторьте логи на предмет ошибок")
    print("   3. Проверьте публикации в Telegram")
    
    print(f"\n🎯 Исправление завершено!")
    print(f"⏰ Время завершения: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print(f"\n❌ Исправление прервано пользователем")
    except Exception as e:
        print(f"\n❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()
