#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки данных в Firebase
"""

import os
import sys
from rss_parser import RSSParser

def check_firebase_data():
    """Проверяет данные в Firebase"""
    
    print("🔥 ПРОВЕРКА ДАННЫХ В FIREBASE")
    print("=" * 50)
    
    # Создаем парсер
    rss_parser = RSSParser()
    
    try:
        if not rss_parser.db:
            print("❌ Firebase не подключен")
            return
        
        # Получаем последние статьи из Firebase
        articles_ref = rss_parser.db.collection('articles')
        docs = articles_ref.order_by('timestamp', direction='DESCENDING').limit(5).stream()
        
        articles = []
        for doc in docs:
            article_data = doc.to_dict()
            articles.append(article_data)
        
        if not articles:
            print("❌ Нет статей в Firebase")
            return
        
        print(f"📋 Найдено {len(articles)} статей в Firebase")
        
        # Анализируем каждую статью
        for i, article in enumerate(articles, 1):
            print(f"\n{i}. Статья: {article.get('title', 'Без заголовка')[:50]}...")
            print(f"   ID: {article.get('id', 'Нет ID')}")
            print(f"   Источник: {article.get('source', 'Не указан')}")
            print(f"   Есть telegram_post: {'✅' if article.get('telegram_post') else '❌'}")
            print(f"   Есть translated: {'✅' if article.get('translated') else '❌'}")
            
            if article.get('translated'):
                translated = article['translated']
                print(f"   Переведенный заголовок: {translated.get('title', 'Нет')[:50]}...")
                print(f"   Есть telegram_post в translated: {'✅' if translated.get('telegram_post') else '❌'}")
        
        # Проверяем, есть ли статьи с telegram_post
        articles_with_posts = [a for a in articles if a.get('telegram_post')]
        print(f"\n📊 Статей с telegram_post: {len(articles_with_posts)}")
        
        if articles_with_posts:
            print("✅ Есть готовые посты для отправки!")
        else:
            print("❌ Нет готовых постов. Нужно сгенерировать их.")
            
    except Exception as e:
        print(f"❌ Ошибка при работе с Firebase: {e}")

if __name__ == "__main__":
    check_firebase_data() 