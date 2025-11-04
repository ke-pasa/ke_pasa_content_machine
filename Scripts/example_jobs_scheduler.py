#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования модуля jobs_scheduler.py
Демонстрирует различные сценарии работы планировщика публикаций
"""

import os
import json
from datetime import datetime, timedelta
import pytz
from jobs_scheduler import PublicationScheduler, PublishingWindow
from firebase_client import get_firebase_client


def create_sample_article(article_id: str, title: str, urgent: bool = False, priority_score: float = 0.8) -> dict:
    """Создает образец статьи для тестирования"""
    return {
        'article_id': article_id,
        'title': title,
        'description': f'Описание статьи "{title}"',
        'content': f'Полный текст статьи "{title}" для тестирования планировщика публикаций.',
        'telegram_post': f'📰 **{title}**\n\nКраткое описание новости для Telegram-канала.\n\n#новости #испания',
        'priority_score': priority_score,
        'urgent': urgent,
        'cluster_id': f'cluster_{article_id}',
        'image': 'https://example.com/image.jpg',
        'created_at': datetime.now(pytz.timezone('Europe/Madrid')).isoformat(),
        'published': False
    }


def demonstrate_basic_usage():
    """Демонстрация базового использования планировщика"""
    print("🚀 Демонстрация базового использования планировщика")
    print("=" * 60)
    
    try:
        # Создаем планировщик
        scheduler = PublicationScheduler()
        
        # Запускаем планировщик
        results = scheduler.run()
        
        print(f"📊 Результаты выполнения:")
        print(f"   Всего статей проверено: {results['total_articles_checked']}")
        print(f"   Опубликовано: {results['articles_published']}")
        print(f"   Срочных: {results['urgent_published']}")
        print(f"   Обычных: {results['regular_published']}")
        print(f"   Пропущено (вне окна): {results['skipped_outside_window']}")
        print(f"   Пропущено (интервал): {results['skipped_interval']}")
        print(f"   Пропущено (лимит): {results['skipped_limit']}")
        
        if results['errors']:
            print(f"\n❌ Ошибки ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"   - {error}")
        else:
            print("\n✅ Ошибок нет")
            
    except Exception as e:
        print(f"❌ Ошибка при запуске планировщика: {e}")


def demonstrate_publishing_windows():
    """Демонстрация работы с окнами публикации"""
    print("\n🕐 Демонстрация работы с окнами публикации")
    print("=" * 60)
    
    # Создаем окна публикации
    windows = [
        PublishingWindow("09:00", "11:00"),
        PublishingWindow("14:00", "16:00"),
        PublishingWindow("20:00", "22:00")
    ]
    
    # Проверяем активность окон в разное время
    test_times = [
        ("08:30", "До первого окна"),
        ("10:00", "В первом окне"),
        ("12:00", "Между окнами"),
        ("15:00", "Во втором окне"),
        ("23:00", "После всех окон")
    ]
    
    for time_str, description in test_times:
        test_time = datetime.strptime(f"2024-01-15 {time_str}", "%Y-%m-%d %H:%M")
        test_time = pytz.timezone('Europe/Madrid').localize(test_time)
        
        active_windows = [w for w in windows if w.is_active(test_time)]
        
        if active_windows:
            window_info = f"{active_windows[0].start}-{active_windows[0].end}"
            print(f"🟢 {time_str} ({description}): Активно окно {window_info}")
        else:
            print(f"🔴 {time_str} ({description}): Нет активных окон")


def demonstrate_settings_management():
    """Демонстрация управления настройками"""
    print("\n⚙️ Демонстрация управления настройками")
    print("=" * 60)
    
    try:
        client = get_firebase_client()
        
        # Пример настроек
        sample_settings = {
            "publishing_windows": [
                {"start": "09:00", "end": "11:00"},
                {"start": "14:00", "end": "16:00"},
                {"start": "20:00", "end": "22:00"}
            ],
            "max_articles_per_window": 2,
            "min_post_interval_minutes": 30,
            "telegram_chat_id": "@your_channel",
            "llm_model": "gpt-4o-mini"
        }
        
        print("📋 Пример настроек планировщика:")
        print(json.dumps(sample_settings, indent=2, ensure_ascii=False))
        
        # Получаем текущие настройки
        current_settings = client.get_settings()
        print(f"\n📊 Текущие настройки в Firebase:")
        print(f"   Окон публикации: {len(current_settings.get('publishing_windows', []))}")
        print(f"   Максимум статей в окне: {current_settings.get('max_articles_per_window', 'не задано')}")
        print(f"   Интервал между постами: {current_settings.get('min_post_interval_minutes', 'не задано')} мин")
        print(f"   Telegram чат: {current_settings.get('telegram_chat_id', 'не задано')}")
        
    except Exception as e:
        print(f"❌ Ошибка при работе с настройками: {e}")


def demonstrate_urgent_publications():
    """Демонстрация работы с срочными публикациями"""
    print("\n🚨 Демонстрация работы с срочными публикациями")
    print("=" * 60)
    
    try:
        scheduler = PublicationScheduler()
        
        # Создаем тестовые статьи
        test_articles = [
            create_sample_article("urgent_1", "СРОЧНО: Важная новость", urgent=True, priority_score=0.95),
            create_sample_article("regular_1", "Обычная новость", urgent=False, priority_score=0.8),
            create_sample_article("urgent_2", "Еще одна срочная новость", urgent=True, priority_score=0.9)
        ]
        
        print("📰 Тестовые статьи:")
        for article in test_articles:
            urgent_mark = "🚨" if article['urgent'] else "📄"
            print(f"   {urgent_mark} {article['title']} (приоритет: {article['priority_score']})")
        
        print("\n💡 Срочные статьи публикуются:")
        print("   ✅ В любое время (вне окон)")
        print("   ✅ Без ограничений по интервалу")
        print("   ✅ Без ограничений по лимиту окна")
        print("   ✅ С наивысшим приоритетом")
        
    except Exception as e:
        print(f"❌ Ошибка при демонстрации срочных публикаций: {e}")


def demonstrate_interval_management():
    """Демонстрация управления интервалами между публикациями"""
    print("\n⏱️ Демонстрация управления интервалами")
    print("=" * 60)
    
    try:
        scheduler = PublicationScheduler()
        
        # Получаем настройки
        settings = scheduler._get_settings()
        min_interval = settings.get('min_post_interval_minutes', 30)
        
        print(f"📋 Текущий минимальный интервал: {min_interval} минут")
        
        # Симулируем проверку интервала
        current_time = datetime.now(pytz.timezone('Europe/Madrid'))
        
        # Примеры разных интервалов
        intervals = [15, 30, 45, 60]
        
        for interval_minutes in intervals:
            last_post_time = current_time - timedelta(minutes=interval_minutes)
            time_since_last = current_time - last_post_time
            
            if time_since_last < timedelta(minutes=min_interval):
                status = "❌ Слишком рано"
            else:
                status = "✅ Можно публиковать"
            
            print(f"   {interval_minutes:2d} мин назад: {status}")
        
    except Exception as e:
        print(f"❌ Ошибка при демонстрации интервалов: {e}")


def demonstrate_error_handling():
    """Демонстрация обработки ошибок"""
    print("\n🛡️ Демонстрация обработки ошибок")
    print("=" * 60)
    
    print("🔍 Планировщик обрабатывает следующие ошибки:")
    print("   ❌ Отсутствие TELEGRAM_BOT_TOKEN")
    print("   ❌ Отсутствие TELEGRAM_CHAT_ID")
    print("   ❌ Ошибки подключения к Firebase")
    print("   ❌ Ошибки Telegram API")
    print("   ❌ Отсутствие telegram_post в статье")
    print("   ❌ Ошибки обновления статуса публикации")
    
    print("\n💡 Стратегии обработки:")
    print("   ✅ Логирование всех ошибок")
    print("   ✅ Продолжение работы при ошибках отдельных статей")
    print("   ✅ Fallback настройки при недоступности Firebase")
    print("   ✅ Graceful degradation при отсутствии Telegram")


def demonstrate_integration_workflow():
    """Демонстрация полного рабочего процесса"""
    print("\n🔄 Демонстрация полного рабочего процесса")
    print("=" * 60)
    
    print("📋 Полный цикл работы планировщика:")
    print("   1. 🔍 Получение настроек из Firebase")
    print("   2. 📰 Поиск неопубликованных статей")
    print("   3. 🕐 Проверка текущего окна публикации")
    print("   4. ⏱️ Проверка интервала с последней публикацией")
    print("   5. 📊 Проверка лимита публикаций в окне")
    print("   6. 🚨 Обработка срочных статей (вне очереди)")
    print("   7. 📤 Отправка в Telegram")
    print("   8. ✅ Обновление статуса публикации")
    print("   9. 📝 Логирование результатов")
    
    print("\n🎯 Интеграция с другими модулями:")
    print("   🔗 firebase_client.py - работа с базой данных")
    print("   🔗 content_generator.py - генерация контента")
    print("   🔗 publication_scheduler.py - планирование слотов")
    print("   🔗 rss_parser.py - парсинг новостей")


def main():
    """Основная функция демонстрации"""
    print("🎯 Демонстрация модуля jobs_scheduler.py")
    print("=" * 80)
    
    # Проверяем наличие необходимых переменных окружения
    required_env_vars = ['TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    
    if missing_vars:
        print(f"⚠️  Отсутствуют переменные окружения: {', '.join(missing_vars)}")
        print("   Демонстрация будет ограниченной")
        print()
    
    # Запускаем демонстрации
    demonstrate_publishing_windows()
    demonstrate_settings_management()
    demonstrate_urgent_publications()
    demonstrate_interval_management()
    demonstrate_error_handling()
    demonstrate_integration_workflow()
    
    print("\n" + "=" * 80)
    print("🎉 Демонстрация завершена!")
    print("\n💡 Для запуска планировщика используйте:")
    print("   python jobs_scheduler.py --run")
    print("   python jobs_scheduler.py --test")
    print("\n📚 Для настройки cron-задачи:")
    print("   */15 * * * * cd /path/to/project && python jobs_scheduler.py --run")


if __name__ == "__main__":
    main() 