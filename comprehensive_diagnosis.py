#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КОМПЛЕКСНАЯ ДИАГНОСТИКА СИСТЕМЫ ПУБЛИКАЦИЙ
Проверяет всю цепочку от планировщика до Telegram
"""

from workers.tools.firebase_client import get_firebase_client
from jobs_scheduler import PublicationSchedulerImproved
from datetime import datetime
import pytz

def comprehensive_diagnosis():
    """Комплексная диагностика системы"""
    
    print("🔍 КОМПЛЕКСНАЯ ДИАГНОСТИКА СИСТЕМЫ ПУБЛИКАЦИЙ")
    print("=" * 70)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved(firebase_client)
        
        print("✅ Планировщик создан успешно")
        
        # 1. ПРОВЕРКА НАСТРОЕК
        print("\n📋 1. ПРОВЕРКА НАСТРОЕК")
        print("-" * 40)
        
        settings = scheduler._get_settings()
        print(f"   Настройки получены: {len(settings)} параметров")
        
        # Проверяем ключевые настройки
        enabled = settings.get('enabled', False)
        bot_token = settings.get('telegram_bot_token', '')
        chat_id = settings.get('telegram_chat_id', '')
        
        print(f"   Публикация включена: {'✅ ДА' if enabled else '❌ НЕТ'}")
        print(f"   Bot Token: {'✅ Установлен' if bot_token else '❌ НЕ УСТАНОВЛЕН'}")
        print(f"   Chat ID: {'✅ Установлен' if chat_id else '❌ НЕ УСТАНОВЛЕН'}")
        
        if not enabled or not bot_token or not chat_id:
            print(f"   ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Настройки неполные!")
            return
        
        # 2. ПРОВЕРКА ВРЕМЕНИ
        print("\n⏰ 2. ПРОВЕРКА ВРЕМЕНИ")
        print("-" * 40)
        
        madrid_tz = pytz.timezone('Europe/Madrid')
        current_time = datetime.now(madrid_tz)
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        print(f"   Текущее время (Madrid): {current_time.strftime('%H:%M:%S')}")
        print(f"   Час: {current_hour}:00")
        print(f"   Минута: {current_minute}")
        
        # Проверяем разрешенные часы
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22, 23]
        is_allowed_hour = current_hour in allowed_hours
        
        print(f"   Разрешенные часы: {allowed_hours}")
        print(f"   Текущий час разрешен: {'✅ ДА' if is_allowed_hour else '❌ НЕТ'}")
        
        if not is_allowed_hour:
            print(f"   ❌ ПРОБЛЕМА: Час {current_hour}:00 НЕ в списке разрешенных!")
            next_allowed = [h for h in allowed_hours if h > current_hour]
            if next_allowed:
                print(f"   ⏰ Следующий разрешенный час: {next_allowed[0]}:00")
            return
        
        # 3. ПРОВЕРКА БЛОКИРОВКИ
        print("\n🔒 3. ПРОВЕРКА БЛОКИРОВКИ")
        print("-" * 40)
        
        # Проверяем время последней публикации
        last_post_time = scheduler._get_last_post_time()
        
        if last_post_time:
            print(f"   Последняя публикация: {last_post_time.strftime('%H:%M:%S')}")
            print(f"   В том же часу: {'✅ ДА' if last_post_time.hour == current_hour else '❌ НЕТ'}")
            
            if last_post_time.hour == current_hour:
                print(f"   ❌ ПРОБЛЕМА: Уже публиковали в этом часу ({current_hour}:00)")
                print(f"   ⏰ Блокировка активна до следующего часа")
                return
        else:
            print(f"   Последняя публикация: НЕТ (первый запуск)")
        
        # Проверяем локальную блокировку
        print(f"   Локальный час публикации: {scheduler._last_publication_hour}")
        print(f"   Локальная блокировка: {'✅ ДА' if scheduler._publication_lock else '❌ НЕТ'}")
        
        # 4. ПРОВЕРКА СТАТЕЙ
        print("\n📰 4. ПРОВЕРКА СТАТЕЙ")
        print("-" * 40)
        
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"   Доступных статей: {len(articles)}")
        
        if not articles:
            print(f"   ❌ КРИТИЧЕСКАЯ ПРОБЛЕМА: Нет статей для публикации!")
            
            # Проверяем общее количество статей
            all_articles = list(firebase_client.db.collection('articles').stream())
            published_articles = [a for a in all_articles if a.to_dict().get('published', False)]
            exported_articles = [a for a in all_articles if a.to_dict().get('exported_to_site', False)]
            
            print(f"   Всего статей в базе: {len(all_articles)}")
            print(f"   Опубликованных: {len(published_articles)}")
            print(f"   Экспортированных на сайт: {len(exported_articles)}")
            
            return
        else:
            print(f"   ✅ Статьи найдены, показываем примеры:")
            for i, article in enumerate(articles[:3]):
                title = article.get('title', 'Без заголовка')[:60]
                priority = article.get('priority_score', 0)
                exported = article.get('exported_to_site', False)
                published = article.get('published', False)
                
                print(f"     {i+1}. {title}")
                print(f"        Приоритет: {priority:.2f}, Экспорт: {exported}, Опубликована: {published}")
        
        # 5. ПРОВЕРКА ВОЗМОЖНОСТИ ПУБЛИКАЦИИ
        print("\n🚀 5. ПРОВЕРКА ВОЗМОЖНОСТИ ПУБЛИКАЦИИ")
        print("-" * 40)
        
        can_publish = scheduler._can_publish_now(settings)
        print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
        
        if not can_publish:
            print(f"   ❌ ПРОБЛЕМА: Публикация заблокирована!")
            
            # Детальная проверка причин
            if not scheduler._is_hourly_publication_time():
                print(f"   Причина: Не подходящее время")
            elif not scheduler._check_publication_lock():
                print(f"   Причина: Активна блокировка")
            else:
                print(f"   Причина: Неизвестная")
            
            return
        
        # 6. ТЕСТОВАЯ ПУБЛИКАЦИЯ
        print("\n🧪 6. ТЕСТОВАЯ ПУБЛИКАЦИЯ")
        print("-" * 40)
        
        print(f"   Запускаем тестовую публикацию...")
        
        try:
            result = scheduler.run()
            
            print(f"   Результат: {result}")
            
            if result.get('status') == 'success':
                print(f"   ✅ ТЕСТОВАЯ ПУБЛИКАЦИЯ УСПЕШНА!")
                print(f"   Опубликовано статей: {result.get('articles_published', 0)}")
                print(f"   ID статьи: {result.get('published_article_id', 'N/A')}")
                print(f"   Заголовок: {result.get('published_article_title', 'N/A')}")
            else:
                print(f"   ❌ ТЕСТОВАЯ ПУБЛИКАЦИЯ НЕ УДАЛАСЬ!")
                print(f"   Статус: {result.get('status', 'N/A')}")
                print(f"   Ошибка: {result.get('error', 'N/A')}")
                
        except Exception as e:
            print(f"   ❌ ОШИБКА при тестовой публикации: {e}")
            import traceback
            traceback.print_exc()
        
        # 7. ИТОГОВАЯ ОЦЕНКА
        print("\n🎯 7. ИТОГОВАЯ ОЦЕНКА")
        print("-" * 40)
        
        if can_publish and articles:
            print(f"   ✅ СИСТЕМА ГОТОВА К ПУБЛИКАЦИИ!")
            print(f"   ✅ Все компоненты работают корректно")
            print(f"   ✅ Публикация должна происходить автоматически")
        elif not can_publish:
            print(f"   ⚠️  СИСТЕМА ЗАБЛОКИРОВАНА")
            print(f"   ⚠️  Нужно дождаться разрешенного времени или сбросить блокировку")
        elif not articles:
            print(f"   ❌ СИСТЕМА НЕ МОЖЕТ ПУБЛИКОВАТЬ")
            print(f"   ❌ Нет статей для публикации")
        else:
            print(f"   ❓ СИСТЕМА В НЕИЗВЕСТНОМ СОСТОЯНИИ")
            print(f"   ❓ Требуется дополнительная диагностика")
        
        # 8. РЕКОМЕНДАЦИИ
        print("\n💡 8. РЕКОМЕНДАЦИИ")
        print("-" * 40)
        
        if can_publish and articles:
            print(f"   • Система работает корректно")
            print(f"   • Публикация должна происходить автоматически")
            print(f"   • Проверьте Telegram канал @spain_kepasa")
        elif not can_publish:
            if last_post_time and last_post_time.hour == current_hour:
                print(f"   • Уже публиковали в этом часу ({current_hour}:00)")
                print(f"   • Дождитесь следующего разрешенного часа")
            else:
                print(f"   • Проверьте настройки блокировки")
                print(f"   • Возможно, нужно сбросить локальную блокировку")
        elif not articles:
            print(f"   • Нет статей для публикации")
            print(f"   • Проверьте процесс генерации статей")
            print(f"   • Убедитесь, что статьи экспортируются на сайт")
        
        print(f"\n🔍 Диагностика завершена")
        
    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    comprehensive_diagnosis()

