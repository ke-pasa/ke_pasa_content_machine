#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка реальных статей в базе данных
"""

from firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_real_articles():
    """Проверяет реальные статьи в базе данных"""
    print("🔍 ПРОВЕРКА РЕАЛЬНЫХ СТАТЕЙ В БАЗЕ ДАННЫХ")
    print("=" * 60)
    
    # Загружаем переменные окружения
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        
        # Получаем статьи
        articles_ref = firebase_client.db.collection('articles')
        articles = list(articles_ref.limit(10).stream())
        
        print(f"📋 Проверяю первые {len(articles)} статей:")
        
        for i, article in enumerate(articles):
            article_data = article.to_dict()
            
            print(f"\n📰 СТАТЬЯ {i+1}:")
            print(f"  ID: {article.id}")
            print(f"  Заголовок: {article_data.get('title', 'N/A')[:80]}...")
            print(f"  Описание: {article_data.get('summary', 'N/A')[:100]}...")
            print(f"  Ссылка: {article_data.get('link', 'N/A')}")
            print(f"  Категории: {article_data.get('categories', [])}")
            print(f"  Дата публикации: {article_data.get('published', 'N/A')}")
            print(f"  Обработано через LLM: {article_data.get('processed', False)}")
            print(f"  Кластеризовано: {article_data.get('is_clustered', False)}")
            print(f"  Опубликовано: {article_data.get('published', False)}")
            
            # Проверяем качество данных
            title = article_data.get('title', '')
            summary = article_data.get('summary', '')
            
            if not title or len(title.strip()) < 10:
                print(f"  ⚠️  ПРОБЛЕМА: Слишком короткий заголовок")
            
            if not summary or len(summary.strip()) < 20:
                print(f"  ⚠️  ПРОБЛЕМА: Слишком короткое описание")
            
            if not article_data.get('link'):
                print(f"  ⚠️  ПРОБЛЕМА: Отсутствует ссылка")
            
            if not article_data.get('categories'):
                print(f"  ⚠️  ПРОБЛЕМА: Отсутствуют категории")
        
        # Анализ проблем
        print(f"\n🔍 АНАЛИЗ ПРОБЛЕМ:")
        
        articles_without_title = [a for a in articles if not a.to_dict().get('title', '').strip()]
        articles_without_summary = [a for a in articles if not a.to_dict().get('summary', '').strip()]
        articles_without_link = [a for a in articles if not a.to_dict().get('link')]
        articles_without_categories = [a for a in articles if not a.to_dict().get('categories')]
        
        print(f"  📰 Без заголовка: {len(articles_without_title)}")
        print(f"  📝 Без описания: {len(articles_without_summary)}")
        print(f"  🔗 Без ссылки: {len(articles_without_link)}")
        print(f"  🏷️  Без категорий: {len(articles_without_categories)}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        if len(articles_without_title) > 0:
            print(f"  1. 🔧 Исправить парсинг заголовков RSS")
        
        if len(articles_without_summary) > 0:
            print(f"  2. 📝 Исправить парсинг описаний RSS")
        
        if len(articles_without_link) > 0:
            print(f"  3. 🔗 Исправить парсинг ссылок RSS")
        
        if len(articles_without_categories) > 0:
            print(f"  4. 🏷️  Исправить парсинг категорий RSS")
        
        if len(articles_without_title) == 0 and len(articles_without_summary) == 0:
            print(f"  5. 🤖 Проверить критерии LLM фильтрации - возможно, слишком строгие")
            print(f"  6. 📊 Запустить тест с реальными статьями через LLM")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке статей: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_real_articles()







