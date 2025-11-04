#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОВЕРКА СТАТУСА ОРКЕСТРАТОРА И ПЛАНИРОВЩИКА
Показывает текущее состояние системы и логи
"""

import os
from datetime import datetime
import pytz
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_orchestrator_status():
    """Проверяет статус оркестратора и планировщика"""
    
    print("🔍 ПРОВЕРКА СТАТУСА ОРКЕСТРАТОРА И ПЛАНИРОВЩИКА")
    print("=" * 60)
    
    try:
        from firebase_client import get_firebase_client
        from jobs_scheduler import PublicationSchedulerImproved
        
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Проверяем блокировку оркестратора
        print("\n🔐 ПРОВЕРКА БЛОКИРОВКИ ОРКЕСТРАТОРА:")
        try:
            locks_ref = firebase_client.db.collection('locks').document('orchestrator')
            lock_doc = locks_ref.get()
            
            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                holder_id = lock_data.get('holder_id', 'unknown')
                acquired_at = lock_data.get('acquired_at', 'unknown')
                expires_at = lock_data.get('expires_at', 'unknown')
                started_at = lock_data.get('started_at', 'unknown')
                
                print(f"   ✅ Оркестратор активен")
                print(f"   ID экземпляра: {holder_id}")
                print(f"   Запущен: {started_at}")
                print(f"   Блокировка получена: {acquired_at}")
                print(f"   Истекает: {expires_at}")
                
                # Проверяем, не истекла ли блокировка
                if expires_at != 'unknown':
                    try:
                        exp_dt = datetime.fromisoformat(expires_at)
                        now = datetime.now(exp_dt.tzinfo or pytz.UTC)
                        if exp_dt < now:
                            print(f"   ⚠️  Блокировка истекла!")
                        else:
                            time_left = exp_dt - now
                            print(f"   ⏰ Время до истечения: {time_left}")
                    except:
                        print(f"   ⚠️  Не удалось проверить время истечения")
            else:
                print(f"   ❌ Оркестратор не активен (нет блокировки)")
                
        except Exception as e:
            print(f"   ❌ Ошибка проверки блокировки: {e}")
        
        # Проверяем последние публикации в Telegram
        print(f"\n📱 ПРОВЕРКА ПОСЛЕДНИХ ПУБЛИКАЦИЙ:")
        try:
            posts_ref = firebase_client.db.collection('telegram_posts')
            query = posts_ref.order_by('created_at', direction='DESCENDING').limit(5)
            docs = query.stream()
            
            posts = []
            for doc in docs:
                data = doc.to_dict()
                if data and 'created_at' in data:
                    posts.append(data)
            
            if posts:
                print(f"   Последние {len(posts)} публикаций:")
                for i, post in enumerate(posts):
                    title = post.get('title', 'Без заголовка')[:50]
                    created_at = post.get('created_at', 'unknown')
                    print(f"     {i+1}. {title}")
                    print(f"        Время: {created_at}")
            else:
                print(f"   ❌ Нет публикаций в Telegram")
                
        except Exception as e:
            print(f"   ❌ Ошибка проверки публикаций: {e}")
        
        # Проверяем статьи для публикации
        print(f"\n📰 ПРОВЕРКА СТАТЕЙ ДЛЯ ПУБЛИКАЦИИ:")
        try:
            articles_ref = firebase_client.db.collection('articles')
            
            # Статьи готовые к публикации
            ready_query = (
                articles_ref
                .where('exported_to_site', '==', True)
                .where('published', '==', False)
            )
            ready_docs = ready_query.stream()
            ready_articles = [doc.to_dict() for doc in ready_docs]
            
            print(f"   Статьи готовые к публикации: {len(ready_articles)}")
            
            if ready_articles:
                print(f"   Примеры готовых статей:")
                for i, article in enumerate(ready_articles[:3]):
                    title = article.get('title', 'Без заголовка')[:50]
                    priority = article.get('priority_score', 0)
                    exported_at = article.get('exported_at', 'unknown')
                    print(f"     {i+1}. {title}")
                    print(f"        Приоритет: {priority:.2f}")
                    print(f"        Экспортирована: {exported_at}")
            
            # Статьи уже опубликованные
            published_query = (
                articles_ref
                .where('published', '==', True)
            )
            published_docs = published_query.stream()
            published_articles = [doc.to_dict() for doc in published_docs]
            
            print(f"   Статьи уже опубликованные: {len(published_articles)}")
            
        except Exception as e:
            print(f"   ❌ Ошибка проверки статей: {e}")
        
        # Проверяем планировщик
        print(f"\n⏰ ПРОВЕРКА ПЛАНИРОВЩИКА:")
        try:
            scheduler = PublicationSchedulerImproved(firebase_client)
            settings = scheduler._get_settings()
            
            print(f"   ✅ Планировщик создан успешно")
            print(f"   Настройки: {len(settings)} параметров")
            
            # Текущее время
            current_time = datetime.now(scheduler.madrid_tz)
            current_hour = current_time.hour
            current_minute = current_time.minute
            
            print(f"   Текущее время (Madrid): {current_time.strftime('%H:%M:%S')}")
            
            # Проверяем время публикации
            is_hourly_time = scheduler._is_hourly_publication_time()
            can_publish = scheduler._can_publish_now(settings)
            
            print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
            print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
            
            if is_hourly_time and can_publish:
                print(f"   🚀 СИСТЕМА ГОТОВА К ПУБЛИКАЦИИ!")
                print(f"   Можно опубликовать 1 пост в часе {current_hour}:00")
            elif is_hourly_time and not can_publish:
                print(f"   ⚠️  Время подходящее, но есть блокировка")
            else:
                print(f"   ❌ Сейчас не время для публикации")
                
        except Exception as e:
            print(f"   ❌ Ошибка проверки планировщика: {e}")
        
        # Проверяем последние действия в системе
        print(f"\n📊 ПОСЛЕДНИЕ ДЕЙСТВИЯ В СИСТЕМЕ:")
        try:
            # Последние обновления статей
            articles_ref = firebase_client.db.collection('articles')
            recent_query = articles_ref.order_by('created_at', direction='DESCENDING').limit(5)
            recent_docs = recent_query.stream()
            
            recent_articles = []
            for doc in recent_docs:
                data = doc.to_dict()
                if data and 'created_at' in data:
                    recent_articles.append(data)
            
            if recent_articles:
                print(f"   Последние {len(recent_articles)} статей:")
                for i, article in enumerate(recent_articles):
                    title = article.get('title', 'Без заголовка')[:50]
                    created_at = article.get('created_at', 'unknown')
                    exported = article.get('exported_to_site', False)
                    published = article.get('published', False)
                    print(f"     {i+1}. {title}")
                    print(f"        Создана: {created_at}")
                    print(f"        Экспортирована: {'✅' if exported else '❌'}")
                    print(f"        Опубликована: {'✅' if published else '❌'}")
            else:
                print(f"   ❌ Нет статей в системе")
                
        except Exception as e:
            print(f"   ❌ Ошибка проверки последних действий: {e}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        # Проверяем, есть ли готовые статьи
        if 'ready_articles' in locals() and len(ready_articles) > 0:
            print(f"   • Есть {len(ready_articles)} статей готовых к публикации")
            print(f"   • Планировщик должен их опубликовать автоматически")
        else:
            print(f"   • Нет статей готовых к публикации")
            print(f"   • Проверьте процесс генерации статей")
        
        # Проверяем время
        if 'is_hourly_time' in locals() and is_hourly_time:
            if 'can_publish' in locals() and can_publish:
                print(f"   • Сейчас можно публиковать в часе {current_hour}:00")
                print(f"   • Запустите планировщик вручную для тестирования")
            else:
                print(f"   • Время подходящее, но есть блокировка")
                print(f"   • Проверьте настройки планировщика")
        else:
            print(f"   • Сейчас не время для публикации")
            print(f"   • Следующее окно: проверьте разрешенные часы")
        
        print(f"\n🎯 СТАТУС СИСТЕМЫ:")
        
        # Определяем общий статус
        orchestrator_active = 'lock_doc' in locals() and lock_doc.exists
        has_ready_articles = 'ready_articles' in locals() and len(ready_articles) > 0
        scheduler_ready = 'is_hourly_time' in locals() and 'can_publish' in locals() and is_hourly_time and can_publish
        
        if orchestrator_active and has_ready_articles and scheduler_ready:
            print(f"   ✅ СИСТЕМА ПОЛНОСТЬЮ ГОТОВА К РАБОТЕ!")
        elif orchestrator_active and has_ready_articles:
            print(f"   ⚠️  Оркестратор работает, статьи готовы, но планировщик заблокирован")
        elif orchestrator_active:
            print(f"   ⚠️  Оркестратор работает, но нет готовых статей")
        else:
            print(f"   ❌ Оркестратор не активен")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка проверки: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_orchestrator_status()

