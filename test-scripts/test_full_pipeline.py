#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для демонстрации полного пайплайна обработки RSS
"""

from rss_parser import RSSParser

def test_full_pipeline():
    """Тестирует полный пайплайн обработки RSS"""
    
    print("🚀 ТЕСТ ПОЛНОГО ПАЙПЛАЙНА RSS PARSER")
    print("=" * 60)
    
    # Создаем парсер
    parser = RSSParser()
    
    print("📋 Проверка конфигурации:")
    print(f"   OpenAI: {'✅ Подключен' if parser.openai_client else '❌ Не подключен'}")
    print(f"   Firebase: {'✅ Подключен' if parser.db else '❌ Не подключен'}")
    print()
    
    # Тестируем обработку одной RSS-ленты
    print("🔄 Тестируем обработку RSS-ленты...")
    test_url = "https://feeds.thelocal.com/rss/es"
    
    try:
        feed_data = parser.parse_feed(test_url)
        if feed_data and feed_data.get('entries'):
            print(f"✅ Загружено {len(feed_data['entries'])} статей из {feed_data.get('title', 'RSS-ленты')}")
            
            # Обрабатываем первые 3 статьи для демонстрации
            test_articles = feed_data['entries'][:3]
            print(f"\n🔍 Обрабатываем первые {len(test_articles)} статьи...")
            
            filtered_articles = parser.filter_articles(test_articles)
            
            print(f"\n📊 Результат обработки:")
            print(f"   📰 Статей загружено: {len(test_articles)}")
            print(f"   🤖 Статей обработано: {len(filtered_articles)}")
            print(f"   💾 Сохранено в Markdown: {len([a for a in filtered_articles if a.get('translated')])}")
            print(f"   🔥 Сохранено в Firebase: {len([a for a in filtered_articles if a.get('translated') and parser.db])}")
            
            # Показываем примеры обработанных статей
            if filtered_articles:
                print(f"\n📝 Примеры обработанных статей:")
                for i, article in enumerate(filtered_articles, 1):
                    if article.get('translated'):
                        translated = article['translated']
                        print(f"\n{i}. {translated.get('title', '')}")
                        print(f"   🏷️  {', '.join(translated.get('tags', []))}")
                        print(f"   📄 {translated.get('description', '')[:100]}...")
                        print(f"   🔗 {article.get('link', '')}")
            
        else:
            print("❌ Не удалось загрузить RSS-ленту")
            
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")
    
    print("\n" + "=" * 60)
    print("✅ Тест завершен!")

if __name__ == "__main__":
    test_full_pipeline() 