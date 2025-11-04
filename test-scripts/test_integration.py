#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример интеграции функции генерации Telegram-поста в цепочку обработки статей
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser

def simulate_article_processing_pipeline():
    """
    Симулирует полную цепочку обработки статьи:
    1. Получение статьи
    2. Сохранение в Firebase
    3. Генерация Telegram-поста
    4. Подготовка к отправке в Telegram
    """
    
    print("🚀 Симуляция полной цепочки обработки статьи")
    print("=" * 60)
    
    # Создаем экземпляр парсера
    parser = RSSParser()
    
    # Симулируем обработанную статью (после process_article)
    processed_article = {
        "title": "Испания упрощает получение гражданства для IT-специалистов",
        "description": "Новая программа привлечения высококвалифицированных специалистов в сфере технологий включает упрощенную процедуру получения испанского гражданства.",
        "content": """
        Министерство труда и социальной экономики Испании объявило о запуске новой программы привлечения IT-специалистов из-за рубежа. Программа "Tech Talent Spain" направлена на решение нехватки квалифицированных кадров в технологическом секторе.

        Основные преимущества программы:
        - Ускоренная процедура получения рабочей визы (до 10 дней)
        - Упрощенное получение вида на жительство
        - Возможность получения гражданства через 2 года вместо стандартных 10 лет
        - Налоговые льготы для IT-компаний, нанимающих иностранных специалистов

        Программа распространяется на специалистов в области:
        - Разработки программного обеспечения
        - Искусственного интеллекта и машинного обучения
        - Кибербезопасности
        - Аналитики данных
        - DevOps и облачных технологий

        По оценкам правительства, программа поможет привлечь в страну до 50,000 IT-специалистов в течение следующих 5 лет. Это должно значительно укрепить позиции Испании на международном рынке технологий.

        Эксперты отмечают, что новая программа особенно привлекательна для специалистов из России, Украины и других стран СНГ, где наблюдается высокий уровень подготовки IT-кадров.
        """,
        "tags": ["IT", "гражданство", "виза", "миграция", "технологии", "Испания"],
        "slug": "tech-talent-spain-citizenship",
        "link": "https://example.com/news/tech-talent-spain-citizenship/",
        "published": "2025-01-15T10:30:00Z",
        "image": "https://example.com/images/tech-talent.jpg",
        "category": "миграция",
        "feed_title": "Испанские новости"
    }
    
    print("📰 Обработанная статья:")
    print(f"   Заголовок: {processed_article['title']}")
    print(f"   Категория: {processed_article['category']}")
    print(f"   Теги: {', '.join(processed_article['tags'])}")
    print()
    
    # Шаг 1: Сохранение в Firebase
    print("💾 Шаг 1: Сохранение в Firebase")
    print("-" * 40)
    
    # Создаем оригинальную статью для Firebase
    original_article = {
        "title": "Spain Simplifies Citizenship Process for IT Specialists",
        "description": "New program to attract high-skilled technology professionals includes simplified Spanish citizenship procedure.",
        "link": processed_article["link"],
        "published": processed_article["published"],
        "image": processed_article["image"],
        "category": processed_article["category"],
        "feed_title": processed_article["feed_title"]
    }
    
    firebase_success = parser.save_to_firebase(original_article, processed_article)
    
    if firebase_success:
        print("✅ Статья успешно сохранена в Firebase")
    else:
        print("⚠️  Ошибка при сохранении в Firebase (продолжаем обработку)")
    
    print()
    
    # Шаг 2: Генерация Telegram-поста
    print("📱 Шаг 2: Генерация Telegram-поста")
    print("-" * 40)
    
    try:
        telegram_post = parser.generate_telegram_post(processed_article)
        
        print("✅ Telegram-пост сгенерирован успешно!")
        print(f"📏 Длина: {len(telegram_post)} символов")
        print()
        
        print("📱 СГЕНЕРИРОВАННЫЙ ПОСТ:")
        print("=" * 50)
        print(telegram_post)
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Ошибка при генерации Telegram-поста: {e}")
        return
    
    print()
    
    # Шаг 3: Подготовка к отправке в Telegram
    print("📤 Шаг 3: Подготовка к отправке в Telegram")
    print("-" * 40)
    
    # Здесь можно добавить логику отправки через python-telegram-bot
    telegram_data = {
        "text": telegram_post,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False,
        "chat_id": "@your_channel_name",  # Замените на ваш канал
        "article_slug": processed_article["slug"],
        "article_title": processed_article["title"]
    }
    
    print("📋 Данные для отправки в Telegram:")
    for key, value in telegram_data.items():
        if key == "text":
            print(f"   {key}: [текст поста выше]")
        else:
            print(f"   {key}: {value}")
    
    print()
    print("✅ Цепочка обработки завершена успешно!")
    print("📤 Пост готов к отправке в Telegram через python-telegram-bot")

def show_usage_example():
    """Показывает пример использования функции в коде"""
    
    print("\n📖 ПРИМЕР ИСПОЛЬЗОВАНИЯ В КОДЕ:")
    print("=" * 60)
    
    example_code = '''
# Пример интеграции в существующий код

from rss_parser import RSSParser

# Создаем парсер
parser = RSSParser()

# Обрабатываем статью (существующий код)
processed_article = parser.process_article(original_article)

if processed_article:
    # Сохраняем в Firebase (существующий код)
    parser.save_to_firebase(original_article, processed_article)
    
    # НОВАЯ ФУНКЦИЯ: Генерируем Telegram-пост
    telegram_post = parser.generate_telegram_post(processed_article)
    
    # Отправляем в Telegram (через python-telegram-bot)
    # bot.send_message(
    #     chat_id="@your_channel",
    #     text=telegram_post,
    #     parse_mode="Markdown"
    # )
    
    print(f"✅ Статья обработана и пост сгенерирован ({len(telegram_post)} символов)")
'''
    
    print(example_code)

if __name__ == "__main__":
    # Запускаем симуляцию
    simulate_article_processing_pipeline()
    
    # Показываем пример использования
    show_usage_example() 