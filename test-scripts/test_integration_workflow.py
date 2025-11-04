#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест полной интеграции: RSS → LLM → Firebase → Telegram
Проверяет весь workflow от парсинга RSS до отправки в Telegram
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser


def test_complete_workflow():
    """
    Тестирует полный workflow обработки статей
    """
    print("🚀 ТЕСТ ПОЛНОЙ ИНТЕГРАЦИИ RSS → LLM → Firebase → Telegram")
    print("=" * 80)
    
    # Создаем экземпляр парсера
    rss_parser = RSSParser()
    
    # Тестовая статья
    test_article = {
        "title": "Новые правила для получения визы в Испании в 2025 году",
        "description": "Министерство иностранных дел Испании объявило о важных изменениях в процедуре получения виз для иностранных граждан. Новые правила вступят в силу с 1 января 2025 года и затронут все типы виз, включая туристические, студенческие и рабочие.",
        "content": """
        Министерство иностранных дел Испании объявило о важных изменениях в процедуре получения виз для иностранных граждан. Новые правила вступят в силу с 1 января 2025 года и затронут все типы виз, включая туристические, студенческие и рабочие.

        Основные изменения включают:
        - Упрощение процедуры подачи документов
        - Сокращение сроков рассмотрения заявлений
        - Новые требования к финансовой обеспеченности
        - Изменения в списке необходимых документов

        По словам министра иностранных дел, эти изменения направлены на привлечение квалифицированных специалистов и упрощение процесса легализации для иностранных граждан, желающих жить и работать в Испании.

        Эксперты отмечают, что новые правила особенно выгодны для граждан стран, не входящих в ЕС, включая Россию, Украину и другие постсоветские государства.
        """,
        "tags": ["виза", "иммиграция", "2025", "новые правила"],
        "slug": "nuevas-reglas-visa-espana-2025",
        "link": "https://example.com/news/nuevas-reglas-visa-espana-2025/",
        "published": "2025-01-15T10:00:00Z"
    }
    
    print("1️⃣ Тестируем генерацию Telegram-поста...")
    telegram_post = rss_parser.generate_telegram_post(test_article)
    
    if telegram_post:
        print("✅ Telegram-пост сгенерирован успешно")
        print(f"📏 Длина поста: {len(telegram_post)} символов")
        print("\n📱 СОДЕРЖИМОЕ ПОСТА:")
        print("-" * 40)
        print(telegram_post)
        print("-" * 40)
        
        # Добавляем пост к статье
        test_article['telegram_post'] = telegram_post
        
        print("\n2️⃣ Тестируем отправку в Telegram (симуляция)...")
        
        # Проверяем наличие необходимых переменных окружения
        bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        
        if bot_token and chat_id:
            print("✅ Переменные окружения настроены")
            print(f"🤖 Bot Token: {bot_token[:10]}...")
            print(f"💬 Chat ID: {chat_id}")
            
            # Спрашиваем пользователя, хочет ли он отправить реальный пост
            print("\n⚠️  ВНИМАНИЕ: Это отправит реальный пост в Telegram!")
            response = input("Отправить пост? (y/N): ").strip().lower()
            
            if response == 'y':
                success = rss_parser.send_telegram_post(test_article)
                if success:
                    print("✅ Пост успешно отправлен в Telegram!")
                else:
                    print("❌ Ошибка при отправке поста")
            else:
                print("📝 Отправка пропущена")
        else:
            print("⚠️  Переменные окружения не настроены:")
            if not bot_token:
                print("   - TELEGRAM_BOT_TOKEN не установлен")
            if not chat_id:
                print("   - TELEGRAM_CHAT_ID не установлен")
            print("\n💡 Для настройки добавьте в .env файл:")
            print("   TELEGRAM_BOT_TOKEN=your_bot_token_here")
            print("   TELEGRAM_CHAT_ID=your_chat_id_here")
    else:
        print("❌ Ошибка при генерации Telegram-поста")


def test_workflow_with_firebase():
    """
    Тестирует workflow с сохранением в Firebase
    """
    print("\n" + "=" * 80)
    print("🔥 ТЕСТ ИНТЕГРАЦИИ С FIREBASE")
    print("=" * 80)
    
    rss_parser = RSSParser()
    
    # Проверяем подключение к Firebase
    if not rss_parser.db:
        print("❌ Firebase не настроен")
        return
    
    # Тестовая статья с переводом
    test_article = {
        "title": "Испанская экономика показывает рост в 2025 году",
        "description": "По данным Национального института статистики, ВВП Испании вырос на 2.8% в первом квартале 2025 года.",
        "content": "Подробный анализ экономических показателей Испании...",
        "tags": ["экономика", "ВВП", "рост", "2025"],
        "slug": "economia-espana-crecimiento-2025",
        "link": "https://example.com/news/economia-espana-crecimiento-2025/",
        "published": "2025-01-15T12:00:00Z"
    }
    
    translated_article = {
        "title": "Испанская экономика показывает рост в 2025 году",
        "description": "По данным Национального института статистики, ВВП Испании вырос на 2.8% в первом квартале 2025 года.",
        "tags": ["экономика", "ВВП", "рост", "2025"]
    }
    
    print("1️⃣ Сохраняем статью в Firebase...")
    if rss_parser.save_to_firebase(test_article, translated_article):
        print("✅ Статья сохранена в Firebase")
        
        print("2️⃣ Генерируем Telegram-пост...")
        telegram_post = rss_parser.generate_telegram_post(test_article)
        
        if telegram_post:
            print("✅ Telegram-пост сгенерирован")
            test_article['telegram_post'] = telegram_post
            
            print("3️⃣ Готово к отправке в Telegram!")
            print(f"📊 Статья: {test_article['title']}")
            print(f"📱 Telegram-пост: {len(telegram_post)} символов")
        else:
            print("❌ Ошибка при генерации Telegram-поста")
    else:
        print("❌ Ошибка при сохранении в Firebase")


def show_usage_examples():
    """
    Показывает примеры использования
    """
    print("\n" + "=" * 80)
    print("📖 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ")
    print("=" * 80)
    
    print("\n1️⃣ Запуск с генерацией Telegram-постов:")
    print("   python rss_parser.py --send-telegram")
    
    print("\n2️⃣ Запуск с отображением всех статей:")
    print("   python rss_parser.py --send-telegram --display-all")
    
    print("\n3️⃣ Обработка одной RSS-ленты:")
    print("   python rss_parser.py https://example.com/rss.xml --send-telegram")
    
    print("\n4️⃣ Использование в коде:")
    print("""
   from rss_parser import RSSParser
   
   rss_parser = RSSParser()
   
   # Обработка статей
   articles = rss_parser.process_multiple_feeds()
   
   # Отправка в Telegram
   for article in articles:
       if article.get('telegram_post'):
           rss_parser.send_telegram_post(article)
   """)


if __name__ == "__main__":
    try:
        test_complete_workflow()
        test_workflow_with_firebase()
        show_usage_examples()
        
        print("\n" + "=" * 80)
        print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc() 