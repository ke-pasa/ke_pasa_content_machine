#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка состояния статей в базе данных
"""

from firebase_client import get_firebase_client

def check_articles():
    """Проверяет состояние статей в базе"""
    try:
        firebase_client = get_firebase_client()
        
        # Получаем все статьи
        articles_ref = firebase_client.db.collection('articles')
        articles = list(articles_ref.stream())
        
        print(f"📊 СТАТУС СТАТЕЙ В БАЗЕ ДАННЫХ")
        print(f"=" * 50)
        print(f"📋 Всего статей: {len(articles)}")
        
        if not articles:
            print("❌ Статей нет!")
            return
        
        # Анализируем статус статей
        processed = [a for a in articles if a.to_dict().get('processed', False)]
        clustered = [a for a in articles if a.to_dict().get('is_clustered', False)]
        published = [a for a in articles if a.to_dict().get('published', False)]
        
        print(f"\n🔄 СТАТУС ОБРАБОТКИ:")
        print(f"  ✅ Обработано через LLM: {len(processed)}")
        print(f"  🔗 Кластеризовано: {len(clustered)}")
        print(f"  📱 Опубликовано: {len(published)}")
        print(f"  ⏳ Ожидают обработки: {len(articles) - len(processed)}")
        
        # Показываем примеры статей
        print(f"\n📰 ПРИМЕРЫ СТАТЕЙ:")
        for i, article in enumerate(articles[:5]):
            article_data = article.to_dict()
            title = article_data.get('title', 'N/A')[:60]
            processed_status = "✅" if article_data.get('processed', False) else "⏳"
            clustered_status = "🔗" if article_data.get('is_clustered', False) else "⏳"
            published_status = "📱" if article_data.get('published', False) else "⏳"
            
            print(f"  {i+1}. {processed_status}{clustered_status}{published_status} {title}...")
        
        # Проверяем кластеры
        clusters_ref = firebase_client.db.collection('news_clusters')
        clusters = list(clusters_ref.stream())
        
        print(f"\n🔗 КЛАСТЕРЫ:")
        print(f"  📁 Всего кластеров: {len(clusters)}")
        
        if clusters:
            for cluster in clusters[:3]:
                cluster_id = cluster.id
                cluster_data = cluster.to_dict()
                articles_count = len(cluster_data.get('announcements', []))
                articles_generated = cluster_data.get('articles_generated', False)
                
                status = "✅" if articles_generated else "⏳"
                print(f"    {status} {cluster_id}: {articles_count} статей, генерация: {articles_generated}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        if len(articles) < 5:
            print(f"  📈 Нужно больше статей для кластеризации (минимум 5, сейчас {len(articles)})")
        if len(processed) < len(articles):
            print(f"  🤖 Нужно обработать {len(articles) - len(processed)} статей через LLM")
        if len(clusters) == 0 and len(processed) >= 5:
            print(f"  🔗 Можно запустить кластеризацию для {len(processed)} обработанных статей")
        if len(clusters) > 0:
            unprocessed_clusters = [c for c in clusters if not c.to_dict().get('articles_generated', False)]
            if unprocessed_clusters:
                print(f"  📝 Можно генерировать статьи для {len(unprocessed_clusters)} кластеров")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_articles()
