#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки функции генерации Telegram-поста
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser

def test_telegram_post_generation():
    """Тестирует генерацию Telegram-поста"""
    
    # Создаем экземпляр парсера
    parser = RSSParser()
    
    # Тестовая статья
    test_article = {
        "title": "Новые правила получения визы в Испании в 2025 году",
        "description": "Испанское правительство объявило о значительных изменениях в процедуре получения виз для иностранцев. Новые правила вступят в силу с 1 января 2025 года и затронут как туристические, так и рабочие визы.",
        "content": """
        Министерство иностранных дел Испании объявило о введении новых правил получения виз, которые вступят в силу с 1 января 2025 года. Изменения направлены на упрощение процедуры для квалифицированных специалистов и ужесточение контроля для туристических виз.

        Основные изменения включают:
        - Упрощенная процедура для высококвалифицированных специалистов
        - Увеличение срока рассмотрения заявлений на туристические визы
        - Новые требования к финансовой обеспеченности
        - Обязательное медицинское страхование для всех типов виз

        По словам министра иностранных дел, новые правила помогут привлечь в страну больше квалифицированных специалистов, особенно в сфере IT и медицины. При этом ужесточение требований к туристическим визам направлено на борьбу с нелегальной миграцией.

        Эксперты отмечают, что изменения могут значительно повлиять на поток мигрантов из России и других стран СНГ. Особенно это касается тех, кто планирует работать в Испании по высококвалифицированным специальностям.
        """,
        "tags": ["виза", "миграция", "Испания", "2025", "новые правила"],
        "slug": "visa-changes-2025"
    }
    
    print("🧪 Тестирование генерации Telegram-поста")
    print("=" * 60)
    
    # Генерируем Telegram-пост
    try:
        telegram_post = parser.generate_telegram_post(test_article)
        
        print("✅ Telegram-пост успешно сгенерирован!")
        print(f"📏 Длина поста: {len(telegram_post)} символов")
        print("\n📱 СГЕНЕРИРОВАННЫЙ ПОСТ:")
        print("-" * 40)
        print(telegram_post)
        print("-" * 40)
        
        # Проверяем ограничения
        if len(telegram_post) <= 1000:
            print("✅ Длина поста соответствует ограничениям Telegram")
        else:
            print("⚠️  Пост превышает лимит в 1000 символов")
        
        # Проверяем наличие обязательных элементов
        checks = [
            ("🧲", "Заголовок с эмодзи"),
            ("🧾", "Основной текст"),
            ("🔗", "Ссылка на статью"),
            ("💬", "Призыв к обсуждению"),
            ("https://example.com/news/visa-changes-2025/", "Правильная ссылка")
        ]
        
        print("\n🔍 Проверка элементов поста:")
        for element, description in checks:
            if element in telegram_post:
                print(f"✅ {description}")
            else:
                print(f"❌ {description} - не найден")
        
    except Exception as e:
        print(f"❌ Ошибка при генерации поста: {e}")

def test_fallback_post():
    """Тестирует fallback-функцию без OpenAI"""
    
    print("\n🧪 Тестирование fallback-функции (без OpenAI)")
    print("=" * 60)
    
    # Создаем парсер без OpenAI
    parser = RSSParser()
    parser.openai_client = None  # Отключаем OpenAI
    
    test_article = {
        "title": "Тестовая статья",
        "description": "Это тестовое описание статьи для проверки fallback-функции генерации Telegram-поста.",
        "content": "Полный текст статьи...",
        "tags": ["тест"],
        "slug": "test-article"
    }
    
    try:
        telegram_post = parser.generate_telegram_post(test_article)
        
        print("✅ Fallback-пост успешно сгенерирован!")
        print(f"📏 Длина поста: {len(telegram_post)} символов")
        print("\n📱 FALLBACK ПОСТ:")
        print("-" * 40)
        print(telegram_post)
        print("-" * 40)
        
    except Exception as e:
        print(f"❌ Ошибка при генерации fallback-поста: {e}")

if __name__ == "__main__":
    print("🚀 Запуск тестов генерации Telegram-поста")
    print("=" * 60)
    
    # Тест с OpenAI
    test_telegram_post_generation()
    
    # Тест без OpenAI
    test_fallback_post()
    
    print("\n✅ Тестирование завершено!") 