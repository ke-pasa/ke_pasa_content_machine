#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРИНУДИТЕЛЬНАЯ ПУБЛИКАЦИЯ В TELEGRAM
Запускает планировщик вручную для диагностики
"""

from firebase_client import get_firebase_client
from jobs_scheduler import PublicationSchedulerImproved

def force_telegram_publication():
    """Принудительно запускает публикацию в Telegram"""
    
    print("🚀 ПРИНУДИТЕЛЬНАЯ ПУБЛИКАЦИЯ В TELEGRAM")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        print(f"✅ Планировщик создан успешно")
        
        # Проверяем настройки
        settings = scheduler._get_settings()
        print(f"✅ Настройки получены: {len(settings)} параметров")
        
        # Проверяем время публикации
        is_hourly_time = scheduler._is_hourly_publication_time()
        can_publish = scheduler._can_publish_now(settings)
        
        print(f"\n⏰ ВРЕМЯ ПУБЛИКАЦИИ:")
        print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
        print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
        
        if not is_hourly_time or not can_publish:
            print(f"\n❌ Сейчас не время для публикации")
            print(f"   Попробуйте позже или измените настройки")
            return
        
        # Проверяем статьи
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"\n📰 СТАТЬИ ДЛЯ ПУБЛИКАЦИИ:")
        print(f"   Доступных статей: {len(articles)}")
        
        if not articles:
            print(f"   ❌ Нет статей для публикации")
            return
        
        # Показываем топ статьи
        ranked_articles = scheduler._rank_articles_for_telegram(articles, settings)
        if ranked_articles:
            best_article = ranked_articles[0]
            print(f"\n🏆 ЛУЧШАЯ СТАТЬЯ ДЛЯ ПУБЛИКАЦИИ:")
            print(f"   Заголовок: {best_article.get('title', 'Без заголовка')}")
            print(f"   Приоритет: {best_article.get('priority_score', 0):.2f}")
            print(f"   Срочная: {'✅ ДА' if best_article.get('urgent', False) else '❌ НЕТ'}")
        
        # Запускаем публикацию
        print(f"\n🚀 ЗАПУСКАЕМ ПУБЛИКАЦИЮ:")
        results = scheduler.run()
        
        print(f"\n📊 РЕЗУЛЬТАТ:")
        print(f"   Статус: {results.get('status', 'Неизвестно')}")
        print(f"   Опубликовано: {results.get('articles_published', 0)}")
        print(f"   Проверено: {results.get('total_articles_checked', 0)}")
        
        if results.get('status') == 'success':
            print(f"   ✅ Публикация успешна!")
            print(f"   ID статьи: {results.get('published_article_id', 'Неизвестно')}")
            print(f"   Заголовок: {results.get('published_article_title', 'Неизвестно')}")
            
            # Проверяем, создался ли пост в Telegram
            print(f"\n🔍 ПРОВЕРЯЕМ СОЗДАНИЕ ПОСТА:")
            posts_ref = firebase_client.db.collection('telegram_posts')
            query = posts_ref.order_by('created_at', direction='DESCENDING').limit(1)
            docs = query.stream()
            
            posts = []
            for doc in docs:
                data = doc.to_dict()
                if data and 'created_at' in data:
                    posts.append(data)
            
            if posts:
                latest_post = posts[0]
                print(f"   ✅ Последний пост в Telegram:")
                print(f"      Заголовок: {latest_post.get('title', 'Без заголовка')[:50]}")
                print(f"      Время: {latest_post.get('created_at', 'Неизвестно')}")
            else:
                print(f"   ❌ Пост в Telegram НЕ создался!")
                print(f"   Проверьте метод _publish_to_telegram")
        else:
            print(f"   ❌ Публикация не удалась")
            if 'error' in results:
                print(f"   Ошибка: {results.get('error')}")
        
    except Exception as e:
        print(f"❌ Ошибка публикации: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    force_telegram_publication()

