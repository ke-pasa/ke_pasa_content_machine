#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Проверяет текущее состояние базы данных:
1. Анализирует коллекцию sources
2. Проверяет статьи и их источники
3. Выявляет проблемы с датами и категориями
"""

from firebase_client import get_firebase_client
from datetime import datetime, timedelta
import re

def check_database_status():
    """Проверяет состояние базы данных"""
    print("🔍 ПРОВЕРКА СОСТОЯНИЯ БАЗЫ ДАННЫХ")
    print("=" * 70)
    
    try:
        db = get_firebase_client().db
        
        # 1. Проверяем коллекцию sources
        print("\n📰 АНАЛИЗ КОЛЛЕКЦИИ SOURCES:")
        print("-" * 40)
        
        sources = list(db.collection('sources').stream())
        print(f"Всего источников: {len(sources)}")
        
        if sources:
            # Анализируем даты
            today = datetime.now()
            old_sources = []
            recent_sources = []
            
            for source in sources:
                data = source.to_dict()
                published_date = data.get('published_date', '')
                created_at = data.get('created_at', '')
                
                # Парсим дату публикации
                source_date = None
                if published_date:
                    try:
                        # Пробуем разные форматы дат
                        for fmt in ['%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%Y-%m-%dT%H:%M:%S']:
                            try:
                                source_date = datetime.strptime(published_date.split('T')[0], fmt)
                                break
                            except:
                                continue
                    except:
                        pass
                
                if source_date:
                    days_diff = (today - source_date).days
                    if days_diff > 30:  # Старые источники (старше 30 дней)
                        old_sources.append({
                            'id': source.id,
                            'title': data.get('title', 'No title')[:60],
                            'date': published_date,
                            'days_old': days_diff
                        })
                    else:
                        recent_sources.append({
                            'id': source.id,
                            'title': data.get('title', 'No title')[:60],
                            'date': published_date,
                            'days_old': days_diff
                        })
            
            print(f"   Источники за последние 30 дней: {len(recent_sources)}")
            print(f"   Старые источники (>30 дней): {len(old_sources)}")
            
            if old_sources:
                print(f"\n   📅 СТАРЫЕ ИСТОЧНИКИ (требуют удаления):")
                for i, old in enumerate(old_sources[:5]):  # Показываем первые 5
                    print(f"      {i+1}. {old['title']}... - {old['date']} ({old['days_old']} дней назад)")
                if len(old_sources) > 5:
                    print(f"      ... и еще {len(old_sources) - 5} старых источников")
        
        # 2. Проверяем коллекцию articles
        print(f"\n📝 АНАЛИЗ КОЛЛЕКЦИИ ARTICLES:")
        print("-" * 40)
        
        articles = list(db.collection('articles').limit(20).stream())
        print(f"Всего статей: {len(articles)}")
        
        if articles:
            # Анализируем категории
            categories_count = {}
            articles_with_sources = 0
            articles_without_sources = 0
            
            for article in articles:
                data = article.to_dict()
                category = data.get('category', 'general')
                has_source = data.get('has_source_content', False)
                
                # Подсчитываем категории
                categories_count[category] = categories_count.get(category, 0) + 1
                
                # Проверяем наличие источников
                if has_source:
                    articles_with_sources += 1
                else:
                    articles_without_sources += 1
            
            print(f"   Статей с источниками: {articles_with_sources}")
            print(f"   Статей без источников: {articles_without_sources}")
            
            print(f"\n   📂 РАСПРЕДЕЛЕНИЕ ПО КАТЕГОРИЯМ:")
            for category, count in sorted(categories_count.items(), key=lambda x: x[1], reverse=True):
                print(f"      {category}: {count} статей")
            
            # Проверяем проблемы с категориями
            if 'general' in categories_count and categories_count['general'] > 0:
                print(f"\n   ⚠️  ПРОБЛЕМА: {categories_count['general']} статей имеют категорию 'general'")
                print(f"      Нужно исправить категории согласно предустановленному списку")
        
        # 3. Проверяем связь между источниками и статьями
        print(f"\n🔗 АНАЛИЗ СВЯЗИ ИСТОЧНИКИ ↔ СТАТЬИ:")
        print("-" * 40)
        
        articles_with_sources = list(db.collection('articles').where('has_source_content', '==', True).limit(10).stream())
        
        if articles_with_sources:
            print(f"Найдено {len(articles_with_sources)} статей с источниками")
            
            for i, article in enumerate(articles_with_sources[:3]):  # Показываем первые 3
                data = article.to_dict()
                title = data.get('title', 'No title')
                source_title = data.get('source_title', 'No source')
                source_content_length = data.get('source_content_length', 0)
                match_confidence = data.get('match_confidence', 0)
                
                print(f"\n   {i+1}. {title[:60]}...")
                print(f"      Источник: {source_title[:60]}...")
                print(f"      Длина исходного контента: {source_content_length} символов")
                print(f"      Уверенность совпадения: {match_confidence:.2f}")
        else:
            print("   ❌ Нет статей с источниками")
        
        # 4. Проверяем качество источников
        print(f"\n📊 АНАЛИЗ КАЧЕСТВА ИСТОЧНИКОВ:")
        print("-" * 40)
        
        if sources:
            quality_scores = [s.to_dict().get('quality_score', 0) for s in sources]
            avg_quality = sum(quality_scores) / len(quality_scores)
            high_quality = sum(1 for score in quality_scores if score >= 4)
            
            print(f"   Среднее качество: {avg_quality:.2f}/5")
            print(f"   Высокое качество (≥4): {high_quality}/{len(sources)}")
            
            # Проверяем активные источники
            active_sources = list(db.collection('sources').where('status', '==', 'active').stream())
            print(f"   Активных источников: {len(active_sources)}")
        
        # 5. Выводы и рекомендации
        print(f"\n💡 ВЫВОДЫ И РЕКОМЕНДАЦИИ:")
        print("-" * 40)
        
        issues_found = []
        
        if old_sources:
            issues_found.append(f"❌ {len(old_sources)} старых источников требуют удаления")
        
        if 'general' in categories_count and categories_count['general'] > 0:
            issues_found.append(f"❌ {categories_count['general']} статей имеют категорию 'general'")
        
        if articles_without_sources > 0:
            issues_found.append(f"❌ {articles_without_sources} статей не имеют источников")
        
        if not issues_found:
            print("✅ Проблем не обнаружено")
            print("✅ База данных в хорошем состоянии")
        else:
            print("⚠️  Обнаружены проблемы:")
            for issue in issues_found:
                print(f"   {issue}")
        
        print(f"\n📈 РЕКОМЕНДАЦИИ:")
        if old_sources:
            print("1. Удалить старые источники (>30 дней)")
        if 'general' in categories_count and categories_count['general'] > 0:
            print("2. Исправить категории статей согласно предустановленному списку")
        if articles_without_sources > 0:
            print("3. Восстановить связь между статьями и источниками")
        
        print("4. Настроить фильтрацию RSS по датам")
        print("5. Автоматизировать назначение категорий")
        
    except Exception as e:
        print(f"❌ Ошибка при проверке: {e}")
        import traceback
        traceback.print_exc()

def main():
    """Основная функция"""
    print("🔍 ПРОВЕРКА СОСТОЯНИЯ БАЗЫ ДАННЫХ")
    print("=" * 80)
    
    check_database_status()
    
    print(f"\n🎉 ПРОВЕРКА ЗАВЕРШЕНА!")

if __name__ == "__main__":
    main()







