#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ свежести новостей в RSS лентах
"""
import feedparser
import requests
from datetime import datetime, timezone, timedelta
import time
from typing import Dict, List, Tuple
import os
from dotenv import load_dotenv

def analyze_rss_freshness():
    """Анализирует свежесть новостей в RSS лентах"""
    print("🔍 АНАЛИЗ СВЕЖЕСТИ RSS ЛЕНТ")
    print("=" * 60)
    
    load_dotenv()
    
    # Читаем список RSS лент
    try:
        with open('feeds.txt', 'r', encoding='utf-8') as f:
            feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
    except FileNotFoundError:
        print("❌ Файл feeds.txt не найден")
        return
    
    print(f"📋 Найдено {len(feeds)} RSS лент для анализа")
    print()
    
    # Анализируем каждую ленту
    results = []
    current_time = datetime.now(timezone.utc)
    
    for i, feed_url in enumerate(feeds, 1):
        print(f"🔍 [{i}/{len(feeds)}] Анализирую: {feed_url}")
        
        try:
            # Парсим RSS ленту
            feed = feedparser.parse(feed_url)
            
            if feed.bozo or not feed.entries:
                print(f"   ❌ Ошибка парсинга или нет записей")
                results.append({
                    'url': feed_url,
                    'status': 'error',
                    'reason': 'parsing_error_or_no_entries',
                    'fresh_articles': 0,
                    'total_articles': 0,
                    'oldest_date': None,
                    'newest_date': None
                })
                continue
            
            # Анализируем даты статей
            dates = []
            fresh_count = 0
            total_count = len(feed.entries)
            
            for entry in feed.entries:
                # Пытаемся получить дату из разных полей
                pub_date = None
                
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    pub_date = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
                elif hasattr(entry, 'published'):
                    try:
                        pub_date = datetime.fromisoformat(entry.published.replace('Z', '+00:00'))
                    except:
                        pass
                
                if pub_date:
                    dates.append(pub_date)
                    
                    # Проверяем свежесть (статья не старше 30 дней)
                    if current_time - pub_date <= timedelta(days=30):
                        fresh_count += 1
            
            if dates:
                oldest_date = min(dates)
                newest_date = max(dates)
                freshness_ratio = fresh_count / total_count if total_count > 0 else 0
                
                print(f"   📊 Всего статей: {total_count}")
                print(f"   📊 Свежих (≤30 дней): {fresh_count}")
                print(f"   📊 Соотношение свежих: {freshness_ratio:.1%}")
                print(f"   📅 Самая старая: {oldest_date.strftime('%Y-%m-%d')}")
                print(f"   📅 Самая новая: {newest_date.strftime('%Y-%m-%d')}")
                
                # Определяем статус ленты
                if newest_date < current_time - timedelta(days=90):
                    status = 'very_old'
                    reason = 'newest_article_older_than_90_days'
                elif newest_date < current_time - timedelta(days=30):
                    status = 'old'
                    reason = 'newest_article_older_than_30_days'
                elif freshness_ratio < 0.3:
                    status = 'mostly_old'
                    reason = 'less_than_30_percent_fresh_articles'
                else:
                    status = 'fresh'
                    reason = 'acceptable_freshness'
                
                print(f"   🏷️  Статус: {status}")
                
            else:
                print(f"   ❌ Не удалось получить даты статей")
                status = 'no_dates'
                reason = 'could_not_extract_dates'
                oldest_date = None
                newest_date = None
                freshness_ratio = 0
            
            results.append({
                'url': feed_url,
                'status': status,
                'reason': reason,
                'fresh_articles': fresh_count,
                'total_articles': total_count,
                'oldest_date': oldest_date,
                'newest_date': newest_date,
                'freshness_ratio': freshness_ratio
            })
            
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
            results.append({
                'url': feed_url,
                'status': 'error',
                'reason': str(e),
                'fresh_articles': 0,
                'total_articles': 0,
                'oldest_date': None,
                'newest_date': None
            })
        
        print()
        time.sleep(1)  # Небольшая пауза между запросами
    
    # Выводим итоговую статистику
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("=" * 60)
    
    status_counts = {}
    for result in results:
        status = result['status']
        status_counts[status] = status_counts.get(status, 0) + 1
    
    print(f"✅ Свежие ленты: {status_counts.get('fresh', 0)}")
    print(f"⚠️  Ленты с устаревшими новостями: {status_counts.get('mostly_old', 0)}")
    print(f"🔄 Старые ленты: {status_counts.get('old', 0)}")
    print(f"❌ Очень старые ленты: {status_counts.get('very_old', 0)}")
    print(f"🚫 Ленты с ошибками: {status_counts.get('error', 0)}")
    print(f"❓ Ленты без дат: {status_counts.get('no_dates', 0)}")
    
    # Показываем проблемные ленты
    print(f"\n🚫 ЛЕНТЫ ДЛЯ УДАЛЕНИЯ:")
    print("-" * 60)
    
    problematic_feeds = []
    for result in results:
        if result['status'] in ['very_old', 'old', 'mostly_old']:
            problematic_feeds.append(result)
            print(f"❌ {result['url']}")
            print(f"   Причина: {result['reason']}")
            if result['newest_date']:
                days_old = (current_time - result['newest_date']).days
                print(f"   Последняя новость: {days_old} дней назад")
            print()
    
    # Создаем файл с лентами для удаления
    if problematic_feeds:
        with open('feeds_to_remove.txt', 'w', encoding='utf-8') as f:
            f.write("# RSS ленты для удаления (устаревшие новости)\n")
            f.write(f"# Создано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("# Причина: новости старше 30 дней или менее 30% свежих статей\n\n")
            
            for feed in problematic_feeds:
                f.write(f"# {feed['reason']}\n")
                f.write(f"{feed['url']}\n\n")
        
        print(f"💾 Список лент для удаления сохранен в feeds_to_remove.txt")
        print(f"🔧 Для удаления выполните: python remove_old_feeds.py")
    
    # Создаем очищенный список лент
    fresh_feeds = [result['url'] for result in results if result['status'] == 'fresh']
    
    with open('feeds_fresh_only.txt', 'w', encoding='utf-8') as f:
        f.write("# RSS ленты с актуальными новостями\n")
        f.write(f"# Создано: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("# Критерий: новости не старше 30 дней и более 30% свежих статей\n\n")
        
        for feed_url in fresh_feeds:
            f.write(f"{feed_url}\n")
    
    print(f"💾 Очищенный список лент сохранен в feeds_fresh_only.txt")
    print(f"📋 Осталось свежих лент: {len(fresh_feeds)}")

if __name__ == "__main__":
    analyze_rss_freshness()







