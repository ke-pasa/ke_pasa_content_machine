#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для диагностики проблемы с полем summary в Firebase
Проверяет статьи без обязательных полей и предлагает решения
"""

from firebase_client import get_firebase_client
from datetime import datetime
import pytz

def check_summary_field():
    """Проверяет статьи без поля summary"""
    print("🔍 ДИАГНОСТИКА ПОЛЯ SUMMARY В FIREBASE")
    print("=" * 60)
    
    try:
        firebase_client = get_firebase_client()
        db = firebase_client.db
        
        # Получаем статьи для анализа
        articles_ref = db.collection('articles')
        articles = list(articles_ref.limit(100).stream())
        
        print(f"📊 Проанализировано {len(articles)} статей")
        
        # Анализируем каждую статью
        articles_without_summary = []
        articles_without_title = []
        articles_without_link = []
        articles_complete = []
        
        for doc in articles:
            data = doc.to_dict() or {}
            doc_id = doc.id
            
            # Проверяем обязательные поля
            title = data.get('title', '').strip()
            summary = data.get('summary', '').strip()
            link = data.get('link', '').strip()
            
            # Классифицируем статьи
            if not title:
                articles_without_title.append((doc_id, data))
            elif not summary:
                articles_without_summary.append((doc_id, data))
            elif not link:
                articles_without_link.append((doc_id, data))
            else:
                articles_complete.append((doc_id, data))
        
        # Выводим статистику
        print(f"\n📊 СТАТИСТИКА ПОЛЕЙ:")
        print(f"  ✅ Полные статьи: {len(articles_complete)}")
        print(f"  ❌ Без title: {len(articles_without_title)}")
        print(f"  ❌ Без summary: {len(articles_without_summary)}")
        print(f"  ❌ Без link: {len(articles_without_link)}")
        
        # Анализируем статьи без summary
        if articles_without_summary:
            print(f"\n🔍 СТАТЬИ БЕЗ ПОЛЯ SUMMARY ({len(articles_without_summary)}):")
            print("-" * 50)
            
            for i, (doc_id, data) in enumerate(articles_without_summary[:5], 1):
                print(f"\n{i}. ID: {doc_id}")
                print(f"   Заголовок: {data.get('title', 'НЕТ')[:80]}...")
                print(f"   Источник: {data.get('source', 'НЕТ')}")
                print(f"   Есть content: {'✅' if data.get('content') else '❌'}")
                print(f"   Есть description: {'✅' if data.get('description') else '❌'}")
                
                # Проверяем альтернативные поля
                content = data.get('content', '')
                description = data.get('description', '')
                
                if content:
                    print(f"   Длина content: {len(content)} символов")
                    print(f"   Начало content: {content[:100]}...")
                
                if description:
                    print(f"   Длина description: {len(description)} символов")
                    print(f"   Начало description: {description[:100]}...")
                
                # Предлагаем решение
                if content and len(content) > 50:
                    print(f"   💡 РЕШЕНИЕ: Использовать content как summary")
                elif description and len(description) > 20:
                    print(f"   💡 РЕШЕНИЕ: Использовать description как summary")
                else:
                    print(f"   ⚠️  ПРОБЛЕМА: Нет альтернативного текста для summary")
        
        # Анализируем полные статьи
        if articles_complete:
            print(f"\n✅ ПРИМЕРЫ ПОЛНЫХ СТАТЕЙ:")
            print("-" * 50)
            
            for i, (doc_id, data) in enumerate(articles_complete[:3], 1):
                print(f"\n{i}. ID: {doc_id}")
                print(f"   Заголовок: {data.get('title', 'НЕТ')[:80]}...")
                print(f"   Summary: {data.get('summary', 'НЕТ')[:100]}...")
                print(f"   Link: {data.get('link', 'НЕТ')[:80]}...")
                print(f"   Статус: processed={data.get('processed', False)}, exported={data.get('exported_to_site', False)}, published={data.get('published', False)}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        print("-" * 50)
        
        if articles_without_summary:
            print("1. 🔧 Исправить статьи без summary:")
            print("   - Использовать поле 'content' как fallback для 'summary'")
            print("   - Использовать поле 'description' как fallback для 'summary'")
            print("   - Обновить логику парсинга RSS для обязательного заполнения summary")
        
        print("2. 📝 Улучшить валидацию данных:")
        print("   - Проверять наличие обязательных полей при сохранении")
        print("   - Автоматически заполнять summary из content/description")
        
        print("3. 🚀 Оптимизировать процесс генерации:")
        print("   - Пропускать статьи без обязательных полей")
        print("   - Логировать проблемы с данными для исправления")
        
        return {
            'total': len(articles),
            'complete': len(articles_complete),
            'without_summary': len(articles_without_summary),
            'without_title': len(articles_without_title),
            'without_link': len(articles_without_link)
        }
        
    except Exception as e:
        print(f"❌ Ошибка при проверке: {e}")
        return None

def fix_summary_field():
    """Исправляет статьи без поля summary"""
    print(f"\n🔧 ИСПРАВЛЕНИЕ ПОЛЯ SUMMARY")
    print("=" * 50)
    
    try:
        firebase_client = get_firebase_client()
        db = firebase_client.db
        
        # Получаем статьи без summary
        articles_ref = db.collection('articles')
        articles = list(articles_ref.limit(100).stream())
        
        fixed_count = 0
        
        for doc in articles:
            data = doc.to_dict() or {}
            doc_id = doc.id
            
            # Проверяем, есть ли summary
            if not data.get('summary', '').strip():
                # Ищем альтернативный текст
                content = data.get('content', '')
                description = data.get('description', '')
                
                new_summary = ''
                if content and len(content) > 20:
                    # Берем первые 200 символов content
                    new_summary = content[:200].strip()
                    if len(content) > 200:
                        new_summary += "..."
                elif description and len(description) > 20:
                    # Используем description
                    new_summary = description.strip()
                
                if new_summary:
                    try:
                        # Обновляем документ
                        doc_ref = articles_ref.document(doc_id)
                        doc_ref.update({
                            'summary': new_summary,
                            'summary_fixed_at': datetime.now(pytz.UTC).isoformat()
                        })
                        fixed_count += 1
                        print(f"✅ Исправлена статья {doc_id}: добавлено summary ({len(new_summary)} символов)")
                    except Exception as e:
                        print(f"❌ Ошибка исправления статьи {doc_id}: {e}")
        
        print(f"\n🎉 ИСПРАВЛЕНИЕ ЗАВЕРШЕНО:")
        print(f"   Исправлено статей: {fixed_count}")
        
        return fixed_count
        
    except Exception as e:
        print(f"❌ Ошибка при исправлении: {e}")
        return 0

if __name__ == "__main__":
    # Проверяем текущее состояние
    stats = check_summary_field()
    
    if stats and stats['without_summary'] > 0:
        print(f"\n🚀 Найдено {stats['without_summary']} статей без summary")
        
        # Спрашиваем пользователя
        response = input("\nХотите исправить эти статьи? (y/n): ")
        if response.lower() in ['y', 'yes', 'да']:
            fixed = fix_summary_field()
            print(f"\n✅ Исправлено {fixed} статей!")
        else:
            print("❌ Исправление отменено пользователем")
    else:
        print("\n✅ Все статьи имеют поле summary!")





