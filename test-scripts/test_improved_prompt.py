#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест улучшенного промпта для создания статей
Проверяет, что новый промпт создает более естественные и человечные тексты
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser


def test_improved_prompt():
    """
    Тестирует улучшенный промпт для создания статей
    """
    print("🚀 ТЕСТ УЛУЧШЕННОГО ПРОМПТА ДЛЯ СОЗДАНИЯ СТАТЕЙ")
    print("=" * 80)
    
    # Создаем экземпляр парсера
    rss_parser = RSSParser()
    
    # Тестовая статья с сухим контентом
    test_article = {
        "title": "Изменения в налоговом законодательстве Испании 2025",
        "content": """
        Министерство финансов Испании внесло изменения в налоговый кодекс, которые вступят в силу с 1 января 2025 года. Основные изменения касаются подоходного налога для физических лиц и корпоративного налога для юридических лиц.

        Для физических лиц:
        - Снижение налоговой ставки с 24% до 22% для доходов до 20,000 евро
        - Введение дополнительной налоговой льготы для семей с детьми
        - Изменение порядка декларирования доходов от аренды недвижимости

        Для юридических лиц:
        - Снижение корпоративного налога с 25% до 23%
        - Новые льготы для компаний, инвестирующих в экологические проекты
        - Упрощение процедуры налогового учета для малого бизнеса

        По оценкам экспертов, эти изменения приведут к снижению налоговой нагрузки на 15% для среднего класса и созданию дополнительных 50,000 рабочих мест в течение года.
        """,
        "link": "https://example.com/news/cambios-fiscales-espana-2025/",
        "published": "2025-01-15T10:00:00Z"
    }
    
    print("📝 ИСХОДНАЯ СТАТЬЯ:")
    print("-" * 40)
    print(f"Заголовок: {test_article['title']}")
    print(f"Контент: {test_article['content'][:200]}...")
    print("-" * 40)
    
    print("\n🤖 Обрабатываю через улучшенный промпт...")
    
    # Проверяем наличие OpenAI API ключа
    if not rss_parser.openai_client:
        print("❌ OPENAI_API_KEY не настроен")
        print("💡 Добавьте в .env файл: OPENAI_API_KEY=your_api_key_here")
        return
    
    # Обрабатываем статью через улучшенный промпт
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
        
        # Анализируем естественность текста
        print(f"\n🎯 АНАЛИЗ ЕСТЕСТВЕННОСТИ:")
        
        # Проверяем на ИИ-маркеры
        ai_indicators = [
            "следует отметить", "необходимо подчеркнуть", "важно отметить",
            "стоит отметить", "следует подчеркнуть", "необходимо отметить",
            "в рамках", "в контексте", "в соответствии с", "в соответствии",
            "в целях", "в рамках реализации", "в процессе", "в ходе",
            "осуществляется", "реализуется", "проводится", "выполняется"
        ]
        
        found_ai = [phrase for phrase in ai_indicators if phrase in content.lower()]
        if found_ai:
            print(f"   ⚠️  Найдены ИИ-маркеры: {', '.join(found_ai[:3])}")
        else:
            print("   ✅ ИИ-маркеры не найдены")
        
        # Проверяем на естественные обороты
        natural_indicators = [
            "мы", "вы", "они", "наш", "ваш", "их",
            "представьте", "вообразите", "оказывается", "кстати",
            "между прочим", "к слову", "кстати говоря",
            "как вы знаете", "как известно", "как говорят"
        ]
        
        found_natural = [word for word in natural_indicators if word in content.lower()]
        if found_natural:
            print(f"   ✅ Найдены естественные обороты: {', '.join(found_natural[:5])}")
        else:
            print("   ⚠️  Естественные обороты не найдены")
        
        # Проверяем длину предложений
        sentences = content.split('.')
        avg_sentence_length = sum(len(s.strip()) for s in sentences if s.strip()) / len([s for s in sentences if s.strip()])
        print(f"   📏 Средняя длина предложения: {avg_sentence_length:.1f} символов")
        
        if avg_sentence_length < 100:
            print("   ✅ Предложения достаточно короткие")
        else:
            print("   ⚠️  Предложения слишком длинные")
        
        # Проверяем на вопросы
        if "?" in content:
            print("   ✅ Используются вопросы")
        else:
            print("   ⚠️  Вопросы не найдены")
        
        # Проверяем на личные местоимения
        personal_pronouns = ["мы", "вы", "они", "наш", "ваш", "их", "нам", "вам", "им"]
        found_pronouns = [word for word in personal_pronouns if word in content.lower()]
        if found_pronouns:
            print(f"   ✅ Используются личные местоимения: {', '.join(found_pronouns[:3])}")
        else:
            print("   ⚠️  Личные местоимения не найдены")
        
    else:
        print("❌ Ошибка при обработке статьи")


def test_comparison():
    """
    Сравнивает старый и улучшенный подходы
    """
    print("\n" + "=" * 80)
    print("🔄 СРАВНЕНИЕ СТАРОГО И УЛУЧШЕННОГО ПОДХОДОВ")
    print("=" * 80)
    
    print("\n📋 ОСНОВНЫЕ УЛУЧШЕНИЯ:")
    print("1. 🎭 Новый персонаж: 'опытный журналист' вместо 'талантливый журналист и редактор'")
    print("2. 💬 Тон: 'как будто объясняешь другу за чашкой кофе'")
    print("3. 🚫 Избегание: конкретные ИИ-маркеры и канцеляризмы")
    print("4. 📝 Структура: более простая и понятная")
    print("5. 🎯 Фокус: на читателя-мигранта и его потребности")
    print("6. 🔤 Язык: более разговорный и естественный")
    print("7. 📊 Системное сообщение: акцент на естественность")


def show_usage_examples():
    """
    Показывает примеры использования
    """
    print("\n" + "=" * 80)
    print("📖 ПРИМЕРЫ ИСПОЛЬЗОВАНИЯ")
    print("=" * 80)
    
    print("\n1️⃣ Запуск с улучшенным промптом:")
    print("   python rss_parser.py")
    
    print("\n2️⃣ Обработка одной RSS-ленты:")
    print("   python rss_parser.py https://example.com/rss.xml")
    
    print("\n3️⃣ Использование в коде:")
    print("""
from rss_parser import RSSParser

rss_parser = RSSParser()

# Обработка статьи с улучшенным промптом
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
        test_improved_prompt()
        test_comparison()
        show_usage_examples()
        
        print("\n" + "=" * 80)
        print("✅ ТЕСТИРОВАНИЕ УЛУЧШЕННОГО ПРОМПТА ЗАВЕРШЕНО")
        print("=" * 80)
        
    except Exception as e:
        print(f"\n❌ Ошибка при тестировании: {e}")
        import traceback
        traceback.print_exc() 