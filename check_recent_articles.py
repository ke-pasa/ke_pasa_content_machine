#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка последних статей в базе
"""
from firebase_client import get_firebase_client

def check_recent_articles():
    """Проверяет последние статьи в базе"""
    try:
        client = get_firebase_client()
        articles = list(client.db.collection('articles').limit(5).stream())
        
        print(f"📋 Всего статей в базе: {len(articles)}")
        
        if articles:
            latest = articles[-1].to_dict()
            created_at = latest.get('created_at', 'N/A')
            print(f"📅 Последняя статья создана: {created_at}")
            
            # Проверяем статус последних статей
            print(f"\n📊 Статус последних статей:")
            for i, article in enumerate(articles[-3:], 1):
                data = article.to_dict()
                title = data.get('title', 'N/A')[:50]
                processed = data.get('processed', False)
                print(f"  {i}. {title}...")
                print(f"     processed: {processed}")
        else:
            print("❌ Статей нет")
            
    except Exception as e:
        print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    check_recent_articles()







