#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для демонстрации работы RSS Parser с одной статьей
"""

from rss_parser import RSSParser, get_full_text

def test_single_article():
    """Тестирует обработку одной статьи"""
    
    # Создаем тестовую статью
    test_article = {
        'title': 'Can I buy a car in Spain if I\'m not a resident?',
        'link': 'https://www.thelocal.es/20210712/reader-question-can-i-buy-a-car-in-spain-if-im-not-a-resident',
        'summary': 'If you spend only part of your time in Spain but don\'t officially reside in the country, what are the rules regarding vehicle ownership?',
        'published': '2021-07-12',
        'image': 'https://assets.thelocal.com/cdn-cgi/plain/https://apiwp.thelocal.com/wp-content/uploads/2021/07/AFP__20191105__1LY1PG__v3__Preview__SpainEconomyAuto.jpg@webp'
    }
    
    print("🧪 ТЕСТ ОБРАБОТКИ ОДНОЙ СТАТЬИ")
    print("=" * 50)
    
    # Создаем парсер
    parser = RSSParser()
    
    # Проверяем, интересна ли статья
    print(f"📰 Заголовок: {test_article['title']}")
    print(f"🔗 Ссылка: {test_article['link']}")
    print()
    
    print("🔍 Проверяю интересность статьи...")
    if parser.is_interesting(test_article):
        print("✅ Статья интересна для русскоязычных мигрантов")
        
        # Извлекаем полный текст
        print("📄 Извлекаю полный текст...")
        full_text = get_full_text(test_article['link'])
        
        if full_text:
            test_article['content'] = full_text
            print(f"✅ Полный текст извлечен ({len(full_text)} символов)")
            
            # Обрабатываем через LLM
            print("🤖 Обрабатываю через LLM...")
            translated = parser.process_article(test_article)
            
            if translated:
                test_article['translated'] = translated
                print("✅ Статья успешно обработана!")
                print()
                print("🌐 РЕЗУЛЬТАТ ОБРАБОТКИ:")
                print("-" * 30)
                print(f"Заголовок: {translated.get('title', '')}")
                print(f"Описание: {translated.get('description', '')}")
                print(f"Теги: {', '.join(translated.get('tags', []))}")
                
                content = translated.get('content', '')
                if len(content) > 300:
                    content = content[:300] + "..."
                print(f"Текст: {content}")
                
                # Сохраняем в Markdown
                print()
                print("💾 Сохраняю в Markdown...")
                saved_path = parser.save_article_md(test_article)
                if saved_path:
                    print(f"✅ Статья сохранена: {saved_path}")
                else:
                    print("❌ Не удалось сохранить статью")
            else:
                print("❌ Не удалось обработать статью через LLM")
        else:
            print("❌ Не удалось извлечь полный текст")
    else:
        print("❌ Статья не интересна для русскоязычных мигрантов")

if __name__ == "__main__":
    test_single_article() 