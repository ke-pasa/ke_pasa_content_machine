#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статуса статей для выявления проблемы с фильтром кластеризации
"""

from workers.tools.firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_articles_status():
    """Проверяет статус статей для кластеризации"""
    print("🔍 ПРОВЕРКА СТАТУСА СТАТЕЙ ДЛЯ КЛАСТЕРИЗАЦИИ")
    print("=" * 60)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        
        # Получаем все статьи
        articles_ref = firebase_client.db.collection('articles')
        all_articles = list(articles_ref.limit(100).stream())
        
        print(f"📋 Всего статей в базе (первые 100): {len(all_articles)}")
        
        if not all_articles:
            print("❌ Статей нет вообще!")
            return
        
        # Анализируем статус статей
        processed_articles = []
        clustered_articles = []
        published_articles = []
        ready_for_clustering = []
        
        for article in all_articles:
            article_data = article.to_dict()
            article_id = article.id
            
            # Проверяем различные статусы
            processed = article_data.get('processed', False)
            is_clustered = article_data.get('is_clustered', False)
            published = article_data.get('published', False)
            
            if processed:
                processed_articles.append(article_id)
            if is_clustered:
                clustered_articles.append(article_id)
            if published:
                published_articles.append(article_id)
            
            # Статьи, готовые к кластеризации: processed=True, is_clustered=False, published=False
            if processed and not is_clustered and not published:
                ready_for_clustering.append(article_id)
        
        print(f"\n📊 СТАТУС СТАТЕЙ:")
        print(f"  ✅ Обработано через LLM (processed=True): {len(processed_articles)}")
        print(f"  🔗 Кластеризовано (is_clustered=True): {len(clustered_articles)}")
        print(f"  📱 Опубликовано (published=True): {len(published_articles)}")
        print(f"  🎯 Готово к кластеризации: {len(ready_for_clustering)}")
        
        # Показываем примеры статей для кластеризации
        if ready_for_clustering:
            print(f"\n📄 СТАТЬИ, ГОТОВЫЕ К КЛАСТЕРИЗАЦИИ:")
            for i, article_id in enumerate(ready_for_clustering[:5]):
                article_doc = firebase_client.db.collection('articles').document(article_id).get()
                if article_doc.exists:
                    article_data = article_doc.to_dict()
                    title = article_data.get('title', 'N/A')[:60]
                    print(f"  {i+1}. {article_id}: {title}...")
        else:
            print(f"\n❌ НЕТ СТАТЕЙ, ГОТОВЫХ К КЛАСТЕРИЗАЦИИ!")
            
            # Анализируем, почему нет готовых статей
            print(f"\n🔍 АНАЛИЗ ПРОБЛЕМЫ:")
            
            if len(processed_articles) == 0:
                print(f"  ❌ ПРОБЛЕМА: Нет статей с processed=True")
                print(f"     - LLM фильтрация не работает или не отмечает статьи")
            
            if len(processed_articles) > 0 and len(clustered_articles) == len(processed_articles):
                print(f"  ❌ ПРОБЛЕМА: Все обработанные статьи уже кластеризованы")
                print(f"     - Нужно дождаться новых статей или проверить логику")
            
            if len(processed_articles) > 0 and len(published_articles) > 0:
                print(f"  ❌ ПРОБЛЕМА: Есть опубликованные статьи")
                print(f"     - Возможно, логика публикации работает раньше кластеризации")
        
        # Показываем детали по нескольким статьям
        print(f"\n📋 ДЕТАЛИ ПО СТАТЬЯМ:")
        for i, article in enumerate(all_articles[:5]):
            article_data = article.to_dict()
            article_id = article.id
            
            print(f"\n  📰 СТАТЬЯ {i+1}:")
            print(f"    ID: {article_id}")
            print(f"    Заголовок: {article_data.get('title', 'N/A')[:50]}...")
            print(f"    processed: {article_data.get('processed', False)}")
            print(f"    is_clustered: {article_data.get('is_clustered', False)}")
            print(f"    published: {article_data.get('published', False)}")
            print(f"    created_at: {article_data.get('created_at', 'N/A')}")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке статей: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_articles_status()







