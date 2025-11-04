#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования расширенной генерации статей в content_generator.py
Демонстрирует генерацию статей в формате Markdown с SEO-полями
"""

import os
import sys
from datetime import datetime
from content_generator import generate_article, generate_telegram_post
from workers.tools.firebase_client import FirebaseClient


def main():
    """Демонстрация расширенной генерации контента"""
    
    print("🧠 Расширенная генерация статей для SEO и Markdown-экспорта")
    print("=" * 70)
    
    # Создаем тестовый кластер
    test_cluster = {
        "cluster_id": "demo_markdown_001",
        "topic_summary": "Новые правила аренды жилья в Барселоне",
        "combined_context": """Правительство Каталонии объявило о новых правилах аренды жилья в Барселоне. 
        Изменения касаются максимальных цен на аренду, требований к договорам и прав арендаторов. 
        Новые правила вступят в силу с 1 января 2025 года и затронут все новые договоры аренды.""",
        "sources": [
            {
                "title": "Nuevas normas de alquiler en Barcelona",
                "summary": "El gobierno catalán anuncia cambios en las normas de alquiler",
                "link": "https://example.com/news/rental-rules-barcelona",
                "image": "https://example.com/images/barcelona-housing.jpg"
            }
        ],
        "priority_score": 92,
        "urgent": False
    }
    
    print("📋 Тестовый кластер:")
    print(f"   Тема: {test_cluster['topic_summary']}")
    print(f"   Приоритет: {test_cluster['priority_score']}")
    print(f"   Срочность: {'Да' if test_cluster['urgent'] else 'Нет'}")
    print()
    
    # Демонстрация 1: Генерация статьи в формате JSON (по умолчанию)
    print("🔄 Демонстрация 1: Генерация статьи в формате JSON")
    print("-" * 50)
    
    try:
        article_json = generate_article(test_cluster, as_markdown=False)
        if article_json:
            print("✅ JSON статья сгенерирована успешно!")
            print(f"   Заголовок: {article_json.get('title', 'N/A')}")
            print(f"   SEO заголовок: {article_json.get('meta_title', 'N/A')}")
            print(f"   SEO описание: {article_json.get('meta_description', 'N/A')[:60]}...")
            print(f"   Категория: {article_json.get('category', 'N/A')}")
            print(f"   Ключевые слова: {article_json.get('meta_keywords', [])}")
            print(f"   Slug: {article_json.get('slug', 'N/A')}")
            print(f"   Теги: {article_json.get('tags', [])}")
        else:
            print("❌ Ошибка генерации JSON статьи")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    print()
    
    # Демонстрация 2: Генерация статьи в формате Markdown
    print("📝 Демонстрация 2: Генерация статьи в формате Markdown")
    print("-" * 50)
    
    try:
        article_markdown = generate_article(test_cluster, as_markdown=True)
        if article_markdown:
            print("✅ Markdown статья сгенерирована успешно!")
            print("📄 Содержимое статьи:")
            print("-" * 30)
            print(article_markdown[:500] + "..." if len(article_markdown) > 500 else article_markdown)
            print("-" * 30)
            
            # Сохраняем в файл для демонстрации
            filename = f"demo_article_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(article_markdown)
            print(f"💾 Статья сохранена в файл: {filename}")
        else:
            print("❌ Ошибка генерации Markdown статьи")
    except Exception as e:
        print(f"❌ Ошибка: {e}")
    
    print()
    
    # Демонстрация 3: Генерация Telegram-поста
    print("📱 Демонстрация 3: Генерация Telegram-поста")
    print("-" * 50)
    
    if article_json:
        try:
            telegram_post = generate_telegram_post(article_json)
            print("✅ Telegram-пост сгенерирован успешно!")
            print(f"📏 Длина поста: {len(telegram_post)} символов")
            print("📄 Содержимое поста:")
            print("-" * 30)
            print(telegram_post)
            print("-" * 30)
        except Exception as e:
            print(f"❌ Ошибка генерации Telegram-поста: {e}")
    
    print()
    
    # Демонстрация 4: Сравнение форматов
    print("🔍 Демонстрация 4: Сравнение форматов вывода")
    print("-" * 50)
    
    print("📊 Сравнение JSON и Markdown форматов:")
    print()
    print("JSON формат (as_markdown=False):")
    print("   ✅ Структурированные данные")
    print("   ✅ Легко парсится программно")
    print("   ✅ Совместим с Firebase")
    print("   ✅ Подходит для API")
    print()
    print("Markdown формат (as_markdown=True):")
    print("   ✅ Готов для публикации на сайте")
    print("   ✅ SEO-оптимизированный frontmatter")
    print("   ✅ Совместим с Astro и другими CMS")
    print("   ✅ Человекочитаемый формат")
    print()
    
    # Демонстрация 5: SEO-поля
    print("🎯 Демонстрация 5: SEO-поля в Markdown")
    print("-" * 50)
    
    if article_markdown:
        print("📋 SEO-поля в Markdown frontmatter:")
        lines = article_markdown.split('\n')
        in_frontmatter = False
        for line in lines:
            if line.strip() == '---':
                in_frontmatter = not in_frontmatter
                continue
            if in_frontmatter and line.strip():
                print(f"   {line}")
            elif not in_frontmatter and line.strip():
                break
    
    print()
    
    # Демонстрация 6: Использование в реальном проекте
    print("🚀 Демонстрация 6: Использование в реальном проекте")
    print("-" * 50)
    
    print("💡 Примеры использования:")
    print()
    print("1. Генерация для сайта (Markdown):")
    print("   article_md = generate_article(cluster, as_markdown=True)")
    print("   with open(f'content/news/{slug}.md', 'w') as f:")
    print("       f.write(article_md)")
    print()
    print("2. Генерация для Firebase (JSON):")
    print("   article_json = generate_article(cluster, as_markdown=False)")
    print("   firebase_client.save_article(article_json)")
    print()
    print("3. Генерация для API:")
    print("   article_data = generate_article(cluster, as_markdown=False)")
    print("   return jsonify(article_data)")
    print()
    
    print("=" * 70)
    print("🎉 Демонстрация завершена!")
    print()
    print("💡 Ключевые особенности:")
    print("   ✅ Обратная совместимость с JSON")
    print("   ✅ Поддержка Markdown с Astro frontmatter")
    print("   ✅ SEO-оптимизация (keywords, tags, category)")
    print("   ✅ Автоматическая генерация slug")
    print("   ✅ Fallback генерация при ошибках LLM")
    print("   ✅ Полное тестирование")


if __name__ == '__main__':
    main() 