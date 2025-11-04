#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка логики системы по этапам
"""

from workers.tools.firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_system_logic():
    """Проверяет всю логику системы по этапам"""
    print("🔍 ПРОВЕРКА ЛОГИКИ СИСТЕМЫ ПО ЭТАПАМ")
    print("=" * 60)
    
    # Загружаем переменные окружения
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        
        # ЭТАП 1: RSS парсинг и фильтрация
        print("\n📡 ЭТАП 1: RSS ПАРСИНГ И ФИЛЬТРАЦИЯ")
        print("-" * 40)
        
        # Проверяем коллекцию articles
        articles_ref = firebase_client.db.collection('articles')
        all_articles = list(articles_ref.stream())
        
        print(f"📋 Всего статей в базе: {len(all_articles)}")
        
        if all_articles:
            # Анализируем статус фильтрации
            processed_articles = [a for a in all_articles if a.to_dict().get('processed', False)]
            unprocessed_articles = [a for a in all_articles if not a.to_dict().get('processed', False)]
            
            print(f"  ✅ Обработано через LLM (интересно): {len(processed_articles)}")
            print(f"  ⏳ Не обработано (не интересно): {len(unprocessed_articles)}")
            
            # Показываем примеры обработанных статей
            if processed_articles:
                print(f"\n  📰 Примеры обработанных статей:")
                for i, article in enumerate(processed_articles[:3]):
                    title = article.to_dict().get('title', 'N/A')[:50]
                    processed_at = article.to_dict().get('processed_at', 'N/A')
                    print(f"    {i+1}. {title}... (обработано: {processed_at})")
            else:
                print(f"  ❌ НЕТ ОБРАБОТАННЫХ СТАТЕЙ - ЭТАП 1 НЕ РАБОТАЕТ!")
        
        # ЭТАП 2: Кластеризация статей
        print("\n🔗 ЭТАП 2: КЛАСТЕРИЗАЦИЯ СТАТЕЙ")
        print("-" * 40)
        
        clusters_ref = firebase_client.db.collection('news_clusters')
        all_clusters = list(clusters_ref.stream())
        
        print(f"📁 Всего кластеров: {len(all_clusters)}")
        
        if all_clusters:
            # Анализируем статус кластеров
            clustered_articles = [a for a in all_articles if a.to_dict().get('is_clustered', False)]
            print(f"  🔗 Кластеризовано статей: {len(clustered_articles)}")
            
            # Показываем примеры кластеров
            print(f"\n  📁 Примеры кластеров:")
            for i, cluster in enumerate(all_clusters[:3]):
                cluster_data = cluster.to_dict()
                announcements_count = len(cluster_data.get('announcements', []))
                articles_generated = cluster_data.get('articles_generated', False)
                status = "✅" if articles_generated else "⏳"
                print(f"    {i+1}. {status} {cluster.id}: {announcements_count} статей, генерация: {articles_generated}")
        else:
            print(f"  ❌ НЕТ КЛАСТЕРОВ - ЭТАП 2 НЕ РАБОТАЕТ!")
        
        # ЭТАП 3: Написание статей на основе кластеров
        print("\n📝 ЭТАП 3: НАПИСАНИЕ СТАТЕЙ НА ОСНОВЕ КЛАСТЕРОВ")
        print("-" * 40)
        
        if all_clusters:
            generated_clusters = [c for c in all_clusters if c.to_dict().get('articles_generated', False)]
            print(f"  📝 Кластеров с сгенерированными статьями: {len(generated_clusters)}")
            
            if generated_clusters:
                print(f"  ✅ ЭТАП 3 РАБОТАЕТ")
                # Показываем примеры сгенерированных статей
                for i, cluster in enumerate(generated_clusters[:2]):
                    cluster_data = cluster.to_dict()
                    generated_article_id = cluster_data.get('generated_article_id')
                    print(f"    {i+1}. Кластер {cluster.id} -> Статья: {generated_article_id}")
            else:
                print(f"  ❌ ЭТАП 3 НЕ РАБОТАЕТ - статьи не генерируются!")
        else:
            print(f"  ❌ ЭТАП 3 НЕ РАБОТАЕТ - нет кластеров!")
        
        # ЭТАП 4: Экспорт статей на сайт в Markdown
        print("\n📄 ЭТАП 4: ЭКСПОРТ СТАТЕЙ НА САЙТ В MARKDOWN")
        print("-" * 40)
        
        # Проверяем, есть ли статьи с экспортом
        exported_articles = [a for a in all_articles if a.to_dict().get('exported_to_site', False)]
        print(f"  📄 Статей экспортировано на сайт: {len(exported_articles)}")
        
        if exported_articles:
            print(f"  ✅ ЭТАП 4 РАБОТАЕТ")
        else:
            print(f"  ❌ ЭТАП 4 НЕ РАБОТАЕТ - статьи не экспортируются!")
        
        # ЭТАП 5: Оценка статей - проставляем рейтинг
        print("\n⭐ ЭТАП 5: ОЦЕНКА СТАТЕЙ - ПРОСТАВЛЯЕМ РЕЙТИНГ")
        print("-" * 40)
        
        # Проверяем коллекцию article_rankings
        rankings_ref = firebase_client.db.collection('article_rankings')
        all_rankings = list(rankings_ref.stream())
        
        print(f"  ⭐ Статей с рейтингом: {len(all_rankings)}")
        
        if all_rankings:
            print(f"  ✅ ЭТАП 5 РАБОТАЕТ")
            # Показываем примеры рейтингов
            for i, ranking in enumerate(all_rankings[:2]):
                ranking_data = ranking.to_dict()
                article_id = ranking_data.get('article_id', 'N/A')
                score = ranking_data.get('score', 0)
                print(f"    {i+1}. Статья {article_id}: рейтинг {score}")
        else:
            print(f"  ❌ ЭТАП 5 НЕ РАБОТАЕТ - рейтинги не проставляются!")
        
        # ЭТАП 6: Выбор лучших статей для Telegram канала
        print("\n🎯 ЭТАП 6: ВЫБОР ЛУЧШИХ СТАТЕЙ ДЛЯ TELEGRAM КАНАЛА")
        print("-" * 40)
        
        # Проверяем, есть ли статьи с высоким рейтингом
        high_rated_articles = []
        if all_rankings:
            high_rated_articles = [r for r in all_rankings if r.to_dict().get('score', 0) > 0.7]
            print(f"  🎯 Статей с высоким рейтингом (>0.7): {len(high_rated_articles)}")
            
            if high_rated_articles:
                print(f"  ✅ ЭТАП 6 РАБОТАЕТ - есть кандидаты для Telegram")
            else:
                print(f"  ⚠️ ЭТАП 6 ЧАСТИЧНО РАБОТАЕТ - нет высокорейтинговых статей")
        else:
            print(f"  ❌ ЭТАП 6 НЕ РАБОТАЕТ - нет рейтингов для выбора!")
        
        # ЭТАП 7: Написание постов для выбранных лучших статей
        print("\n📱 ЭТАП 7: НАПИСАНИЕ ПОСТОВ ДЛЯ ВЫБРАННЫХ ЛУЧШИХ СТАТЕЙ")
        print("-" * 40)
        
        # Проверяем, есть ли статьи с Telegram постами
        articles_with_posts = [a for a in all_articles if a.to_dict().get('telegram_post')]
        print(f"  📱 Статей с Telegram постами: {len(articles_with_posts)}")
        
        if articles_with_posts:
            print(f"  ✅ ЭТАП 7 РАБОТАЕТ")
            # Показываем примеры постов
            for i, article in enumerate(articles_with_posts[:2]):
                post = article.to_dict().get('telegram_post', '')[:100]
                print(f"    {i+1}. Пост: {post}...")
        else:
            print(f"  ❌ ЭТАП 7 НЕ РАБОТАЕТ - Telegram посты не генерируются!")
        
        # ЭТАП 8: Планирование публикаций и публикация постов в Telegram канал
        print("\n📅 ЭТАП 8: ПЛАНИРОВАНИЕ ПУБЛИКАЦИЙ И ПУБЛИКАЦИЯ В TELEGRAM")
        print("-" * 40)
        
        # Проверяем коллекцию log для публикаций
        logs_ref = firebase_client.db.collection('log')
        publication_logs = list(logs_ref.where('message', '==', 'publication_success').stream())
        
        print(f"  📅 Успешных публикаций в Telegram: {len(publication_logs)}")
        
        if publication_logs:
            print(f"  ✅ ЭТАП 8 РАБОТАЕТ")
            # Показываем последние публикации
            for i, log in enumerate(publication_logs[-2:]):
                log_data = log.to_dict()
                timestamp = log_data.get('timestamp', 'N/A')
                print(f"    {i+1}. Публикация: {timestamp}")
        else:
            print(f"  ❌ ЭТАП 8 НЕ РАБОТАЕТ - публикации не происходят!")
        
        # ИТОГОВАЯ ДИАГНОСТИКА
        print("\n🔍 ИТОГОВАЯ ДИАГНОСТИКА")
        print("=" * 60)
        
        working_stages = 0
        total_stages = 8
        
        if len(processed_articles) > 0:
            working_stages += 1
        if len(all_clusters) > 0:
            working_stages += 1
        if len(generated_clusters) > 0:
            working_stages += 1
        if len(exported_articles) > 0:
            working_stages += 1
        if len(all_rankings) > 0:
            working_stages += 1
        if len(high_rated_articles) > 0:
            working_stages += 1
        if len(articles_with_posts) > 0:
            working_stages += 1
        if len(publication_logs) > 0:
            working_stages += 1
        
        print(f"📊 Работающих этапов: {working_stages}/{total_stages}")
        
        if working_stages == total_stages:
            print("🎉 ВСЕ ЭТАПЫ РАБОТАЮТ КОРРЕКТНО!")
        elif working_stages >= 6:
            print("✅ БОЛЬШИНСТВО ЭТАПОВ РАБОТАЕТ")
        elif working_stages >= 4:
            print("⚠️ ЧАСТЬ ЭТАПОВ РАБОТАЕТ")
        else:
            print("❌ БОЛЬШИНСТВО ЭТАПОВ НЕ РАБОТАЕТ")
        
        # РЕКОМЕНДАЦИИ
        print("\n💡 РЕКОМЕНДАЦИИ ПО ИСПРАВЛЕНИЮ:")
        
        if len(processed_articles) == 0:
            print("  1. 🔧 Исправить RSS парсинг - статьи не обрабатываются через LLM")
        
        if len(all_clusters) == 0:
            print("  2. 🔗 Запустить кластеризацию - нет кластеров для генерации статей")
        
        if len(generated_clusters) == 0:
            print("  3. 📝 Запустить генерацию статей - кластеры не превращаются в статьи")
        
        if len(exported_articles) == 0:
            print("  4. 📄 Запустить экспорт статей - статьи не экспортируются на сайт")
        
        if len(all_rankings) == 0:
            print("  5. ⭐ Запустить ранжирование - статьи не получают рейтинги")
        
        if len(articles_with_posts) == 0:
            print("  6. 📱 Запустить генерацию Telegram постов - посты не создаются")
        
        if len(publication_logs) == 0:
            print("  7. 📅 Запустить планировщик публикаций - посты не публикуются")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке системы: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_system_logic()
