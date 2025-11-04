#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОВЕРКА ВРЕМЕНИ ПОСЛЕДНЕЙ ПУБЛИКАЦИИ
Показывает, когда была последняя публикация в Telegram
"""

from firebase_client import get_firebase_client
from jobs_scheduler import PublicationSchedulerImproved
from datetime import datetime
import pytz

def check_last_publication():
    """Проверяет время последней публикации"""
    
    print("🔍 ПРОВЕРКА ВРЕМЕНИ ПОСЛЕДНЕЙ ПУБЛИКАЦИИ")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        print(f"✅ Планировщик создан успешно")
        
        # Проверяем время последней публикации
        last_post_time = scheduler._get_last_post_time()
        
        print(f"\n📱 ПОСЛЕДНЯЯ ПУБЛИКАЦИЯ:")
        if last_post_time:
            print(f"   Время: {last_post_time}")
            print(f"   Час: {last_post_time.hour}:00")
            
            # Текущее время
            madrid_tz = pytz.timezone('Europe/Madrid')
            current_time = datetime.now(madrid_tz)
            current_hour = current_time.hour
            
            print(f"\n⏰ ТЕКУЩЕЕ ВРЕМЯ:")
            print(f"   Время: {current_time}")
            print(f"   Час: {current_hour}:00")
            
            # Проверяем, в том же ли часу
            same_hour = last_post_time.hour == current_hour
            print(f"   В том же часу: {'✅ ДА' if same_hour else '❌ НЕТ'}")
            
            if same_hour:
                print(f"   ❌ Публикация заблокирована (уже публиковали в {current_hour}:00)")
            else:
                print(f"   ✅ Можно публиковать (последняя публикация была в {last_post_time.hour}:00)")
        else:
            print(f"   ❌ Нет публикаций в базе")
            print(f"   ✅ Можно публиковать (первый запуск)")
        
        # Проверяем коллекцию telegram_posts
        print(f"\n📊 КОЛЛЕКЦИЯ TELEGRAM_POSTS:")
        posts_ref = firebase_client.db.collection('telegram_posts')
        posts = list(posts_ref.order_by('created_at', direction='DESCENDING').limit(5).stream())
        
        if posts:
            print(f"   Последние {len(posts)} постов:")
            for i, post in enumerate(posts):
                post_data = post.to_dict()
                title = post_data.get('title', 'Без заголовка')[:50]
                created_at = post_data.get('created_at', 'Неизвестно')
                print(f"     {i+1}. {title}")
                print(f"        Время: {created_at}")
        else:
            print(f"   ❌ Постов в базе нет")
        
        # Проверяем коллекцию articles с published_in_telegram=True
        print(f"\n📰 СТАТЬИ С PUBLISHED_IN_TELEGRAM:")
        articles_ref = firebase_client.db.collection('articles')
        published_articles = list(articles_ref.where('published_in_telegram', '==', True).limit(5).stream())
        
        if published_articles:
            print(f"   Последние {len(published_articles)} опубликованных статей:")
            for i, article in enumerate(published_articles):
                article_data = article.to_dict()
                title = article_data.get('title', 'Без заголовка')[:50]
                published_at = article_data.get('published_at', 'Неизвестно')
                print(f"     {i+1}. {title}")
                print(f"        Опубликована: {published_at}")
        else:
            print(f"   ❌ Опубликованных статей нет")
        
    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_last_publication()

