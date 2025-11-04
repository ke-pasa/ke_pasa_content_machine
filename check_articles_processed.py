#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статей, которые должны иметь processed=True
"""
from workers.tools.firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_articles_processed():
    """Проверяет статьи, которые должны иметь processed=True"""
    print("🔍 ПРОВЕРКА СТАТЕЙ С PROCESSED")
    print("=" * 50)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        articles_ref = firebase_client.db.collection('articles')
        
        # Получаем все статьи
        all_articles = list(articles_ref.stream())
        
        print(f"📋 Всего статей в базе: {len(all_articles)}")
        
        if not all_articles:
            print("❌ Статей нет")
            return
        
        # Анализируем статус processed
        processed_true = []
        processed_false = []
        processed_missing = []
        
        for article in all_articles:
            data = article.to_dict()
            article_id = article.id
            
            if 'processed' not in data:
                processed_missing.append({
                    'id': article_id,
                    'title': data.get('title', 'N/A')[:50],
                    'link': data.get('link', 'N/A')
                })
            elif data['processed'] == True:
                processed_true.append({
                    'id': article_id,
                    'title': data.get('title', 'N/A')[:50],
                    'link': data.get('link', 'N/A')
                })
            else:
                processed_false.append({
                    'id': article_id,
                    'title': data.get('title', 'N/A')[:50],
                    'link': data.get('link', 'N/A')
                })
        
        print(f"\n📊 СТАТУС ПОЛЯ PROCESSED:")
        print(f"   ✅ processed=True: {len(processed_true)}")
        print(f"   ❌ processed=False: {len(processed_false)}")
        print(f"   ❓ processed отсутствует: {len(processed_missing)}")
        
        if processed_false:
            print(f"\n📄 СТАТЬИ С PROCESSED=FALSE:")
            for i, article in enumerate(processed_false[:5], 1):
                print(f"  {i}. {article['title']}...")
                print(f"     ID: {article['id']}")
                print(f"     Ссылка: {article['link']}")
        
        if processed_missing:
            print(f"\n❓ СТАТЬИ БЕЗ ПОЛЯ PROCESSED:")
            for i, article in enumerate(processed_missing[:3], 1):
                print(f"  {i}. {article['title']}...")
                print(f"     ID: {article['id']}")
        
        # Проверяем, есть ли статьи с content (значит, прошли LLM фильтрацию)
        with_content = [a for a in all_articles if a.to_dict().get('content')]
        print(f"\n📄 Статей с полным текстом (content): {len(with_content)}")
        
        if with_content:
            print("   Примеры статей с content:")
            for i, article in enumerate(with_content[:3], 1):
                data = article.to_dict()
                print(f"  {i}. {data.get('title', 'N/A')[:50]}...")
                print(f"     processed: {data.get('processed', 'N/A')}")
                print(f"     content length: {len(data.get('content', ''))}")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_articles_processed()







