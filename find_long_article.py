#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Поиск конкретной статьи с длинным контентом из логов
"""

from firebase_client import get_firebase_client

def find_long_article():
    """Ищет статью с длинным контентом"""
    
    print("🔍 ПОИСК СТАТЬИ С ДЛИННЫМ КОНТЕНТОМ")
    print("=" * 50)
    
    try:
        firebase_client = get_firebase_client()
        
        # Ищем статью по заголовку из логов
        target_title = "Incendios en España hoy, en directo"
        
        print(f"🎯 Ищу статью: {target_title}")
        
        # Получаем статьи
        articles_ref = firebase_client.db.collection('articles')
        articles_docs = list(articles_ref.limit(200).stream())
        
        print(f"📊 Проверяю {len(articles_docs)} статей...")
        
        found_articles = []
        
        for doc in articles_docs:
            article = doc.to_dict()
            article['id'] = doc.id
            
            title = article.get('title', '')
            content = article.get('content', '')
            summary = article.get('summary', '')
            
            # Ищем по части заголовка
            if 'Incendios' in title or 'incendios' in title.lower():
                found_articles.append({
                    'id': article.get('id'),
                    'title': title,
                    'content_length': len(content),
                    'summary_length': len(summary),
                    'estimated_tokens': len(content) * 0.25
                })
            
            # Также ищем статьи с очень длинным контентом
            if len(content) > 100000:  # Более 100,000 символов
                found_articles.append({
                    'id': article.get('id'),
                    'title': title[:100] + '...' if len(title) > 100 else title,
                    'content_length': len(content),
                    'summary_length': len(summary),
                    'estimated_tokens': len(content) * 0.25,
                    'note': 'Очень длинный контент'
                })
        
        if found_articles:
            print(f"\n✅ Найдено {len(found_articles)} статей:")
            for article in found_articles:
                print(f"\n📰 ID: {article['id']}")
                print(f"   Заголовок: {article['title']}")
                print(f"   Размер content: {article['content_length']:,} символов")
                print(f"   Размер summary: {article['summary_length']:,} символов")
                print(f"   Оценка токенов: ~{article['estimated_tokens']:,.0f}")
                if 'note' in article:
                    print(f"   Примечание: {article['note']}")
                
                # Проверяем, превышает ли лимит
                if article['estimated_tokens'] > 128000:
                    print(f"   🚨 СТАТУС: ПРЕВЫШЕНИЕ ЛИМИТА OPENAI!")
                elif article['estimated_tokens'] > 100000:
                    print(f"   ⚠️  СТАТУС: БЛИЗКО К ЛИМИТУ")
                else:
                    print(f"   ✅ СТАТУС: В ПРЕДЕЛАХ")
        else:
            print("\n❌ Статья не найдена в базе данных")
            print("   Возможные причины:")
            print("   1. Статья еще не сохранена в базе")
            print("   2. Статья была удалена")
            print("   3. Заголовок отличается")
        
        # Проверяем последние статьи
        print(f"\n🔍 ПОСЛЕДНИЕ 5 СТАТЕЙ В БАЗЕ:")
        recent_articles = articles_docs[-5:] if len(articles_docs) >= 5 else articles_docs
        
        for i, doc in enumerate(recent_articles, 1):
            article = doc.to_dict()
            title = article.get('title', 'N/A')[:80]
            content_length = len(article.get('content', ''))
            created_at = article.get('created_at', 'N/A')
            
            print(f"   {i}. {title}")
            print(f"      Размер: {content_length:,} символов (~{content_length * 0.25:.0f} токенов)")
            print(f"      Создано: {created_at}")
        
    except Exception as e:
        print(f"❌ Ошибка при поиске: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    find_long_article()

