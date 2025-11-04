#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Настройка свежей системы для полного автоматического цикла
"""

import os
from firebase_client import get_firebase_client

def clear_skipped_articles():
    """Очищает отклонённые статьи для повторной обработки"""
    print("🧹 Очищаем отклонённые статьи...")
    
    db = get_firebase_client().db
    
    # Очищаем коллекцию skipped_articles
    try:
        skipped_docs = list(db.collection('skipped_articles').stream())
        print(f"Найдено {len(skipped_docs)} отклонённых статей")
        
        for doc in skipped_docs:
            doc.reference.delete()
            
        print(f"✅ Удалено {len(skipped_docs)} отклонённых статей")
    except Exception as e:
        print(f"⚠️ Ошибка очистки skipped_articles: {e}")

def clear_old_tasks():
    """Очищает старые задачи"""
    print("🧹 Очищаем старые задачи...")
    
    db = get_firebase_client().db
    
    # Очищаем старые задачи
    try:
        old_tasks = list(db.collection('llm_tasks').stream())
        print(f"Найдено {len(old_tasks)} старых задач")
        
        for doc in old_tasks:
            doc.reference.delete()
            
        print(f"✅ Удалено {len(old_tasks)} старых задач")
    except Exception as e:
        print(f"⚠️ Ошибка очистки задач: {e}")

def create_test_feed():
    """Создаёт тестовый feed файл с несколькими RSS"""
    print("📝 Создаём тестовый feed файл...")
    
    test_feeds = [
        "https://www.20minutos.es/rss/",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/cultura/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/sociedad/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/opinion/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/ultimas-noticias/portada",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada"
    ]
    
    with open('test_feeds.txt', 'w', encoding='utf-8') as f:
        for feed in test_feeds:
            f.write(feed + '\n')
    
    print("✅ Создан test_feeds.txt")

def setup_environment():
    """Настраивает переменные окружения"""
    print("⚙️ Настраиваем переменные окружения...")
    
    env_vars = {
        'USE_OPENAI_BATCH': '1',
        'BYPASS_DB_CACHE': '1',  # Игнорируем кэш для тестирования
        'MIN_BATCH_SIZE': '3',   # Маленький размер для быстрого тестирования
        'BATCH_MAX_WAIT_SEC': '30',  # Быстрая отправка
        'RSS_MAX_ITEMS_PER_FEED': '5'  # Ограничиваем количество для теста
    }
    
    for key, value in env_vars.items():
        os.environ[key] = value
        print(f"  {key} = {value}")
    
    print("✅ Переменные окружения настроены")

def test_rss_parsing():
    """Тестирует RSS-парсинг"""
    print("🧪 Тестируем RSS-парсинг...")
    
    try:
        from rss_parser import RSSParser
        
        parser = RSSParser()
        parser.process_multiple_feeds('test_feeds.txt')
        
        print("✅ RSS-парсинг завершён")
    except Exception as e:
        print(f"❌ Ошибка RSS-парсинга: {e}")

def start_orchestrator():
    """Запускает оркестратор в фоне"""
    print("🚀 Запускаем оркестратор...")
    
    try:
        import subprocess
        import sys
        
        # Запускаем оркестратор в фоне
        process = subprocess.Popen(
            [sys.executable, 'batch_orchestrator.py'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        print(f"✅ Оркестратор запущен с PID {process.pid}")
        print("ℹ️  Оркестратор будет работать в фоне и обрабатывать задачи")
        
        return process
    except Exception as e:
        print(f"❌ Ошибка запуска оркестратора: {e}")
        return None

def main():
    print("🚀 Настройка свежей системы для автоматической работы...")
    
    # Шаг 1: Очищаем старые данные
    clear_skipped_articles()
    clear_old_tasks()
    
    # Шаг 2: Настраиваем окружение
    setup_environment()
    
    # Шаг 3: Создаём тестовые feeds
    create_test_feed()
    
    # Шаг 4: Тестируем RSS-парсинг
    test_rss_parsing()
    
    # Шаг 5: Запускаем оркестратор
    orchestrator_process = start_orchestrator()
    
    print("\n🎉 Система настроена и запущена!")
    print("\n📋 Что происходит дальше:")
    print("1. RSS-парсер создал задачи фильтрации")
    print("2. Оркестратор соберёт задачи в батчи и отправит в OpenAI")
    print("3. Результаты будут обработаны автоматически")
    print("4. Интересные статьи будут превращены в Telegram-посты")
    
    if orchestrator_process:
        print(f"\n🔍 Мониторинг:")
        print("- Логи оркестратора: см. вывод в консоли")
        print("- Состояние системы: python debug_system.py")
        print("- Остановка: Ctrl+C")
        
        try:
            # Ждём немного, чтобы показать начальные логи
            import time
            time.sleep(10)
            
            # Показываем первые логи
            try:
                stdout, stderr = orchestrator_process.communicate(timeout=1)
                if stdout:
                    print("\n📋 Логи оркестратора:")
                    print(stdout[:500] + "..." if len(stdout) > 500 else stdout)
            except subprocess.TimeoutExpired:
                pass
                
        except KeyboardInterrupt:
            print("\n🛑 Остановка системы...")
            orchestrator_process.terminate()

if __name__ == '__main__':
    main()

