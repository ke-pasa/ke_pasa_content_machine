#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для запуска тестов системы "Испания, ¿qué pasa?"
Позволяет выбрать тип тестирования и запустить соответствующие тесты
"""

import os
import sys
import subprocess
import argparse
from datetime import datetime

def print_banner():
    """Выводит баннер системы"""
    print("=" * 80)
    print("🔍 СИСТЕМА ТЕСТИРОВАНИЯ 'Испания, ¿qué pasa?'")
    print("=" * 80)
    print("📋 Доступные типы тестирования:")
    print("   1. minimal    - Минимальные тесты (быстро, без внешних API)")
    print("   2. full       - Полные тесты (медленно, с проверкой всех компонентов)")
    print("   3. quick      - Быстрые тесты (проверка основных функций)")
    print("   4. all        - Все тесты последовательно")
    print("=" * 80)

def run_test(test_type: str):
    """Запускает тест указанного типа"""
    print(f"🚀 Запуск тестирования типа: {test_type}")
    print(f"⏱️  Время начала: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("-" * 60)
    
    if test_type == "minimal":
        result = subprocess.run([sys.executable, "test_system_final.py"], 
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
    elif test_type == "full":
        result = subprocess.run([sys.executable, "test_full_system_integration.py"], 
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
    elif test_type == "quick":
        result = subprocess.run([sys.executable, "test_system_final.py"], 
                              capture_output=True, text=True, encoding='utf-8', errors='replace')
    elif test_type == "all":
        print("🔄 Запуск всех тестов последовательно...")
        
        # Минимальные тесты
        print("\n📋 1. Минимальные тесты:")
        result1 = subprocess.run([sys.executable, "test_system_final.py"], 
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(result1.stdout)
        if result1.stderr:
            print("Ошибки:", result1.stderr)
        
        # Полные тесты
        print("\n📋 2. Полные тесты:")
        result2 = subprocess.run([sys.executable, "test_full_system_integration.py"], 
                               capture_output=True, text=True, encoding='utf-8', errors='replace')
        print(result2.stdout)
        if result2.stderr:
            print("Ошибки:", result2.stderr)
        
        # Определяем общий результат
        if result1.returncode == 0 and result2.returncode == 0:
            result = type('Result', (), {'returncode': 0, 'stdout': 'Все тесты пройдены', 'stderr': ''})()
        else:
            result = type('Result', (), {'returncode': 1, 'stdout': 'Есть ошибки', 'stderr': ''})()
    else:
        print(f"❌ Неизвестный тип тестирования: {test_type}")
        return False
    
    # Выводим результат
    print(result.stdout)
    if result.stderr:
        print("Ошибки:", result.stderr)
    
    print("-" * 60)
    print(f"⏱️  Время окончания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    if result.returncode == 0:
        print("✅ Тестирование завершено успешно!")
        return True
    else:
        print("❌ Тестирование завершено с ошибками!")
        return False

def check_environment():
    """Проверяет окружение перед запуском тестов"""
    print("🔍 Проверка окружения...")
    
    # Проверка Python версии
    python_version = sys.version_info
    if python_version.major == 3 and python_version.minor >= 8:
        print(f"✅ Python версия: {python_version.major}.{python_version.minor}.{python_version.micro}")
    else:
        print(f"❌ Требуется Python 3.8+, текущая версия: {python_version.major}.{python_version.minor}")
        return False
    
    # Проверка основных файлов
    required_files = [
        'test_system_windows.py',
        'test_full_system_integration.py',
        'rss_parser.py',
        'feeds.txt'
    ]
    
    missing_files = []
    for file_path in required_files:
        if os.path.exists(file_path):
            print(f"✅ Файл найден: {file_path}")
        else:
            missing_files.append(file_path)
            print(f"❌ Файл не найден: {file_path}")
    
    if missing_files:
        print(f"❌ Отсутствуют файлы: {', '.join(missing_files)}")
        return False
    
    print("✅ Окружение готово к тестированию")
    return True

def main():
    """Главная функция"""
    parser = argparse.ArgumentParser(description='Запуск тестов системы')
    parser.add_argument('--type', '-t', 
                       choices=['minimal', 'full', 'quick', 'all'],
                       default='minimal',
                       help='Тип тестирования (по умолчанию: minimal)')
    parser.add_argument('--check-env', '-c', 
                       action='store_true',
                       help='Только проверить окружение')
    
    args = parser.parse_args()
    
    print_banner()
    
    if args.check_env:
        if check_environment():
            print("✅ Окружение готово к работе!")
            sys.exit(0)
        else:
            print("❌ Проблемы с окружением!")
            sys.exit(1)
    
    # Проверка окружения
    if not check_environment():
        print("❌ Окружение не готово к тестированию!")
        sys.exit(1)
    
    # Запуск тестов
    success = run_test(args.type)
    
    if success:
        print("\n🎉 Все тесты пройдены успешно!")
        sys.exit(0)
    else:
        print("\n💥 Обнаружены проблемы в системе!")
        print("📋 Проверьте логи для получения подробной информации:")
        print("   - system_test.log (для полных тестов)")
        print("   - minimal_test.log (для минимальных тестов)")
        sys.exit(1)

if __name__ == "__main__":
    main() 