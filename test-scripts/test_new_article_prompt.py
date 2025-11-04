#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест нового промпта для создания статей
Проверяет, что новый промпт создает более живые и интересные статьи
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser


def test_new_article_prompt():
    """
    Тестирует новый промпт для создания статей
    """
    print("🚀 ТЕСТ НОВОГО ПРОМПТА ДЛЯ СОЗДАНИЯ СТАТЕЙ")
    print("=" * 80)
    
    # Создаем экземпляр парсера
    rss_parser = RSSParser()
    
    # Тестовая статья с сухим контентом
    test_article = {
        "title": "Новые правила получения визы в Испании в 2025 году",
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
        "link": "https://example.com/news/nuevas-reglas-visa-espana-2025/",
        "published": "2025-01-15T10:00:00Z"
    }
    
    print("📝 ИСХОДНАЯ СТАТЬЯ:")
    print("-" * 40)
    print(f"Заголовок: {test_article['title']}")
    print(f"Контент: {test_article['content'][:200]}...")
    print("-" * 40)
    
    print("\n🤖 Обрабатываю через новый промпт...")
    
    # Проверяем наличие OpenAI API ключа
    if not rss_parser.openai_client:
        print("❌ OPENAI_API_KEY не настроен")
        print("💡 Добавьте в .env файл: OPENAI_API_KEY=your_api_key_here")
        return
    
    # Обрабатываем статью через новый промпт
    translated = rss_parser.process_article(test_article)
    
    if translated:
        print("✅ Статья успешно обработана!")
        print("\n📄 РЕЗУЛЬТАТ ОБРАБОТКИ:")
        print("=" * 80)
        
        print(f"📰 Заголовок: {translated.get('title', '')}")
        print(f"📝 Описание: {translated.get('description', '')}")
        print(f"🏷️  Теги: {', '.join(translated.get('tags', []))}")
        print(f"📅 Дата: {translated.get('pubDate', '')}")
        print(f"👤 Автор: {translated.get('author', '')}")
        print(f"🔗 Slug: {translated.get('slug', '')}")
        print(f"📂 Категория: {translated.get('category', '')}")
        
        print(f"\n📖 СОДЕРЖАНИЕ:")
        print("-" * 40)
        content = translated.get('content', '')
        print(content)
        print("-" * 40)
        
        print(f"\n📊 СТАТИСТИКА:")
        print(f"   Длина контента: {len(content)} символов")
        print(f"   Количество абзацев: {content.count(chr(10) + chr(10)) + 1}")
        print(f"   Количество подзаголовков: {content.count('##')}")
        
        # Анализируем стиль
        print(f"\n🎨 АНАЛИЗ СТИЛЯ:")
        if "##" in content:
            print("   ✅ Используются подзаголовки")
        else:
            print("   ⚠️  Подзаголовки не найдены")
        
        if "?" in content:
            print("   ✅ Используются вопросы")
        else:
            print("   ⚠️  Вопросы не найдены")
        
        if any(word in content.lower() for word in ["но", "однако", "впрочем", "между тем"]):
            print("   ✅ Используются переходы")
        else:
            print("   ⚠️  Переходы не найдены")
        
        # Проверяем на "живость" текста
        lively_indicators = ["представьте", "вообразите", "оказывается", "интересно", "кстати", "между прочим"]
        found_lively = [word for word in lively_indicators if word in content.lower()]
        if found_lively:
            print(f"   ✅ Найдены живые обороты: {', '.join(found_lively)}")
        else:
            print("   ⚠️  Живые обороты не найдены")
        
    else:
        print("❌ Ошибка при обработке статьи")


def test_comparison():
    """
    Сравнивает старый и новый подходы
    """
    print("\n" + "=" * 80)
    print("🔄 СРАВНЕНИЕ СТАРОГО И НОВОГО ПОДХОДОВ")
    print("=" * 80)
    
    print("\n📋 ОСНОВНЫЕ ИЗМЕНЕНИЯ:")
    print("1. 🎭 Новый персонаж: 'талантливый журналист и редактор' вместо 'журналист-переводчик'")
    print("2. 🎨 Стиль: Meduza/The Village/Tinkoff Journal вместо 'литературный русский'")
    print("3. 📝 Структура: Подзаголовки, короткие абзацы, вовлекающее вступление")
    print("4. 💬 Тон: Разговорный, живой, без канцеляризмов")
    print("5. 🎯 Цель: Найти угол зрения, интригу, эмоцию")
    print("6. 📊 Температура: 0.7 вместо 0.3 (больше креативности)")
    print("7. 📋 Формат: Полная структура статьи с метаданными")


def show_usage_examples():
    """
    Показывает примеры использования
    """
    print("\n" + "=" * 80)
    print("📖 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ")
    print("=" * 80)
    
    print("\n1️⃣ Запуск с новым промптом:")
    print("   python rss_parser.py")
    
    print("\n2️⃣ Обработка одной RSS-ленты:")
    print("   python rss_parser.py https://example.com/rss.xml")
    
    print("\n3️⃣ Использование в коде:")
    print("""
from rss_parser import RSSParser

rss_parser = RSSParser()

# Обработка статьи с новым промптом
article = {
    "title": "Заголовок статьи",
    "content": "Содержание статьи..."
}

translated = rss_parser.process_article(article)
if translated:
    print(f"Новый заголовок: {translated['title']}")
    print(f"Описание: {translated['description']}")
    print(f"Контент: {translated['content']}")
    print(f"Теги: {translated['tags']}")
    print(f"Автор: {translated['author']}")
    print(f"Slug: {translated['slug']}")
    print(f"Категория: {translated['category']}")
""")


if __name__ == "__main__":
    try:
        test_new_article_prompt()
        test_comparison()
        show_usage_examples()
        
        print("\n" + "=" * 80)
        print("✅ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc() 