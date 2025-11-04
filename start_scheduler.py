#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Запуск планировщика с принудительной публикацией
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from jobs_scheduler import PublicationSchedulerFixed
from firebase_client import get_firebase_client

def force_publication():
    """Принудительно запускает публикацию"""
    print("🚀 Принудительный запуск публикации...")
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerFixed(firebase_client)
        
        # Получаем настройки
        settings = scheduler._get_settings()
        
        print(f"📅 Текущее время (Madrid): {datetime.now(scheduler.madrid_tz)}")
        
        # Получаем статьи
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"📰 Найдено статей для публикации: {len(articles)}")
        
        if not articles:
            print("❌ Нет статей для публикации")
            return
        
        # Ранжируем статьи
        ranked_articles = scheduler._rank_articles_for_telegram(articles, settings)
        if not ranked_articles:
            print("❌ Не удалось ранжировать статьи")
            return
        
        print(f"📈 Ранжировано статей: {len(ranked_articles)}")
        
        # Выбираем лучшую статью
        best_article = ranked_articles[0]
        print(f"🏆 Лучшая статья: {best_article.get('title', 'Unknown')[:60]}...")
        
        # Принудительно публикуем
        print("📤 Принудительно публикую статью...")
        
        # Сбрасываем блокировку времени
        scheduler._publication_lock = False
        scheduler._last_publication_hour = None
        
        # Запускаем публикацию
        scheduler.run_hourly_publication()
        
        print("✅ Публикация завершена")
        
    except Exception as e:
        print(f"❌ Ошибка принудительной публикации: {e}")
        import traceback
        traceback.print_exc()

def wait_for_next_hour():
    """Ждет до следующего часа и запускает публикацию"""
    print("⏰ Жду до следующего часа для публикации...")
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Создаем планировщик
        scheduler = PublicationSchedulerFixed(firebase_client)
        
        while True:
            current_time = datetime.now(scheduler.madrid_tz)
            current_hour = current_time.hour
            current_minute = current_time.minute
            
            print(f"🕐 Текущее время: {current_hour:02d}:{current_minute:02d}")
            
            # Проверяем, можно ли публиковать
            if current_minute <= 5:
                print("✅ Время подходит для публикации!")
                scheduler.run_hourly_publication()
                break
            
            # Ждем 1 минуту
            print("⏳ Жду 1 минуту...")
            import time
            time.sleep(60)
        
    except KeyboardInterrupt:
        print("\n⏹️ Остановлено пользователем")
    except Exception as e:
        print(f"❌ Ошибка ожидания: {e}")

if __name__ == "__main__":
    print("Выберите режим:")
    print("1. Принудительная публикация сейчас")
    print("2. Ждать до следующего часа")
    
    choice = input("Введите выбор (1 или 2): ").strip()
    
    if choice == "1":
        force_publication()
    elif choice == "2":
        wait_for_next_hour()
    else:
        print("❌ Неверный выбор")
