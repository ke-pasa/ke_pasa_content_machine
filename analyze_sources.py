#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from workers.tools.firebase_client import get_firebase_client
import os

def analyze_sources():
    """Анализирует качество источников и сгенерированных статей"""
    try:
        db = get_firebase_client().db
        
        print("🔍 АНАЛИЗ КАЧЕСТВА СИСТЕМЫ")
        print("=" * 60)
        
        # 1. Анализируем источники
        print("\n📰 АНАЛИЗ ИСТОЧНИКОВ:")
        sources = list(db.collection('sources').limit(10).stream())
        print(f"Всего источников: {len(sources)}")
        
        content_lengths = []
        for i, source in enumerate(sources[:5]):
            data = source.to_dict()
            title = data.get('title', 'No title')
            content = data.get('content', '')
            content_len = len(content)
            content_lengths.append(content_len)
            
            print(f"{i+1}. {title[:60]}...")
            print(f"   Длина контента: {content_len} символов")
            print(f"   Начало: {content[:100]}..." if content_len > 100 else f"   Контент: {content}")
            print()
        
        avg_content_length = sum(content_lengths) / len(content_lengths) if content_lengths else 0
        print(f"📊 Средняя длина контента источников: {avg_content_length:.0f} символов")
        
        # 2. Анализируем сгенерированные статьи
        print("\n📝 АНАЛИЗ СГЕНЕРИРОВАННЫХ СТАТЕЙ:")
        articles = list(db.collection('articles').limit(10).stream())
        print(f"Всего статей в БД: {len(articles)}")
        
        article_lengths = []
        for i, article in enumerate(articles[:5]):
            data = article.to_dict()
            title = data.get('title', 'No title')
            content = data.get('content', '')
            content_len = len(content)
            article_lengths.append(content_len)
            
            print(f"{i+1}. {title[:60]}...")
            print(f"   Длина контента: {content_len} символов")
            print(f"   Начало: {content[:100]}..." if content_len > 100 else f"   Контент: {content}")
            print()
        
        avg_article_length = sum(article_lengths) / len(article_lengths) if article_lengths else 0
        print(f"📊 Средняя длина сгенерированных статей: {avg_article_length:.0f} символов")
        
        # 3. Анализируем файлы
        print("\n📁 АНАЛИЗ ФАЙЛОВ:")
        news_dir = "spain-news-portal/src/content/news"
        if os.path.exists(news_dir):
            files = [f for f in os.listdir(news_dir) if f.endswith('.md')]
            print(f"Файлов новостей: {len(files)}")
            
            # Анализируем несколько файлов
            for i, filename in enumerate(files[:3]):
                filepath = os.path.join(news_dir, filename)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Извлекаем frontmatter и content
                    if '---' in content:
                        parts = content.split('---')
                        if len(parts) >= 3:
                            frontmatter = parts[1]
                            article_content = parts[2]
                            
                            print(f"{i+1}. {filename}")
                            print(f"   Длина файла: {len(content)} символов")
                            print(f"   Длина контента: {len(article_content)} символов")
                            print(f"   Начало контента: {article_content[:100]}...")
                            print()
                except Exception as e:
                    print(f"Ошибка чтения {filename}: {e}")
        
        # 4. Выводы
        print("\n💡 ВЫВОДЫ:")
        print("-" * 40)
        
        if avg_content_length < 500:
            print("❌ ПРОБЛЕМА: Источники содержат слишком мало текста")
            print("   Это может быть причиной низкого качества статей")
        else:
            print("✅ Источники содержат достаточно текста")
        
        if avg_article_length < 1000:
            print("❌ ПРОБЛЕМА: Статьи слишком короткие")
            print("   Возможно, промпт не работает корректно")
        else:
            print("✅ Статьи имеют достаточную длину")
        
        if len(files) > 300:
            print("⚠️  ВНИМАНИЕ: Сгенерировано слишком много статей")
            print("   Система вышла из-под контроля")
        
        print(f"\n📈 РЕКОМЕНДАЦИИ:")
        print("1. Проверить качество извлечения контента из RSS")
        print("2. Улучшить промпт для более конкретного контента")
        print("3. Добавить валидацию качества перед сохранением")
        print("4. Ограничить количество генерируемых статей")
        
    except Exception as e:
        print(f"Ошибка при анализе: {e}")

if __name__ == "__main__":
    analyze_sources()







