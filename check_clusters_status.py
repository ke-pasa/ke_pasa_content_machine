#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статуса кластеров и выявление проблемы с генерацией статей
"""

from firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_clusters_status():
    """Проверяет статус кластеров и выявляет проблему с генерацией статей"""
    print("🔍 ПРОВЕРКА СТАТУСА КЛАСТЕРОВ")
    print("=" * 50)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        
        # Получаем все кластеры
        clusters_ref = firebase_client.db.collection('news_clusters')
        all_clusters = list(clusters_ref.stream())
        
        print(f"📁 Всего кластеров в базе: {len(all_clusters)}")
        
        if not all_clusters:
            print("❌ Кластеров нет вообще!")
            return
        
        # Анализируем статус кластеров
        clusters_with_articles = []
        clusters_without_articles = []
        
        for cluster in all_clusters:
            cluster_data = cluster.to_dict()
            cluster_id = cluster.id
            
            # Проверяем, есть ли сгенерированные статьи
            articles_generated = cluster_data.get('articles_generated', False)
            generated_article_id = cluster_data.get('generated_article_id')
            announcements_count = len(cluster_data.get('announcements', []))
            
            if articles_generated and generated_article_id:
                clusters_with_articles.append({
                    'id': cluster_id,
                    'announcements': announcements_count,
                    'article_id': generated_article_id
                })
            else:
                clusters_without_articles.append({
                    'id': cluster_id,
                    'announcements': announcements_count,
                    'articles_generated': articles_generated
                })
        
        print(f"\n📊 СТАТУС КЛАСТЕРОВ:")
        print(f"  ✅ С сгенерированными статьями: {len(clusters_with_articles)}")
        print(f"  ❌ Без сгенерированных статей: {len(clusters_without_articles)}")
        
        # Показываем примеры кластеров со статьями
        if clusters_with_articles:
            print(f"\n📝 КЛАСТЕРЫ СО СТАТЬЯМИ:")
            for i, cluster in enumerate(clusters_with_articles[:5]):
                print(f"  {i+1}. {cluster['id']}: {cluster['announcements']} анонсов → статья {cluster['article_id']}")
        
        # Показываем примеры кластеров без статей
        if clusters_without_articles:
            print(f"\n⏳ КЛАСТЕРЫ БЕЗ СТАТЕЙ:")
            for i, cluster in enumerate(clusters_without_articles[:5]):
                status = "✅" if cluster['articles_generated'] else "❌"
                print(f"  {i+1}. {cluster['id']}: {cluster['announcements']} анонсов, генерация: {status}")
        
        # Проверяем, есть ли готовые статьи для экспорта
        articles_ref = firebase_client.db.collection('articles')
        exported_articles = list(articles_ref.where('exported_to_site', '==', True).stream())
        
        print(f"\n📄 СТАТЬИ ДЛЯ ЭКСПОРТА:")
        print(f"  Экспортировано на сайт: {len(exported_articles)}")
        
        if exported_articles:
            print(f"  ✅ Есть готовые статьи для экспорта")
            for i, article in enumerate(exported_articles[:3]):
                article_data = article.to_dict()
                title = article_data.get('title', 'N/A')[:60]
                print(f"    {i+1}. {title}...")
        else:
            print(f"  ❌ НЕТ готовых статей для экспорта!")
        
        # Анализ проблемы
        print(f"\n🔍 АНАЛИЗ ПРОБЛЕМЫ:")
        
        if len(clusters_with_articles) == 0:
            print(f"  ❌ ПРОБЛЕМА: Генерация статей из кластеров не работает!")
            print(f"     - Кластеры создаются ({len(all_clusters)})")
            print(f"     - Но статьи не генерируются")
            print(f"     - Нужно проверить content_generator.py")
        
        elif len(exported_articles) == 0:
            print(f"  ❌ ПРОБЛЕМА: Экспорт статей не работает!")
            print(f"     - Статьи генерируются ({len(clusters_with_articles)})")
            print(f"     - Но не экспортируются на сайт")
            print(f"     - Нужно проверить article_exporter.py")
        
        else:
            print(f"  ✅ Цепочка работает до экспорта")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        if len(clusters_with_articles) == 0:
            print(f"  1. 🔧 Запустить генерацию статей из кластеров")
            print(f"  2. 📝 Проверить content_generator.py - возможно, есть ошибки")
        
        if len(exported_articles) == 0 and len(clusters_with_articles) > 0:
            print(f"  1. 📄 Запустить экспорт статей на сайт")
            print(f"  2. 🔧 Проверить article_exporter.py")
        
        if len(exported_articles) > 0:
            print(f"  1. ⭐ Запустить ранжирование статей")
            print(f"  2. 📱 Запустить генерацию Telegram постов")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке кластеров: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_clusters_status()







