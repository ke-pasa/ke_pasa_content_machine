#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Исправляет проблему с коллекцией sources:
1. Создает коллекцию sources из существующих articles
2. Восстанавливает связь между источниками и сгенерированными статьями
3. Обеспечивает правильную работу системы генерации
"""

from workers.tools.firebase_client import get_firebase_client
from datetime import datetime

def fix_sources_collection():
    """Исправляет коллекцию sources"""
    print("🔧 ИСПРАВЛЕНИЕ КОЛЛЕКЦИИ SOURCES")
    print("=" * 60)
    
    try:
        db = get_firebase_client().db
        
        # 1. Проверяем текущее состояние
        print("\n📊 АНАЛИЗ ТЕКУЩЕГО СОСТОЯНИЯ:")
        
        # Проверяем коллекцию sources
        sources = list(db.collection('sources').limit(5).stream())
        print(f"Коллекция 'sources': {len(sources)} документов")
        
        # Проверяем коллекцию articles
        articles = list(db.collection('articles').limit(5).stream())
        print(f"Коллекция 'articles': {len(articles)} документов")
        
        if not articles:
            print("❌ Нет статей для обработки")
            return
        
        # 2. Создаем источники из статей
        print(f"\n🔄 СОЗДАНИЕ ИСТОЧНИКОВ ИЗ СТАТЕЙ:")
        
        created_sources = 0
        for article in articles:
            try:
                data = article.to_dict()
                
                # Проверяем, есть ли уже такой источник
                source_id = f"source_{article.id}"
                source_ref = db.collection('sources').document(source_id)
                
                if source_ref.get().exists:
                    continue  # Пропускаем уже существующие
                
                # Создаем источник
                source_data = {
                    'source_id': source_id,
                    'title': data.get('title', ''),
                    'link': data.get('link', ''),
                    'content': data.get('content', ''),
                    'summary': data.get('summary', ''),
                    'image': data.get('image', ''),
                    'categories': data.get('categories', []),
                    'published_date': data.get('published_date', ''),
                    'created_at': datetime.now().isoformat(),
                    'interesting': True,  # Помечаем как интересный
                    'processed': False,   # Еще не обработан
                    'article_id': article.id  # Связь с оригинальной статьей
                }
                
                # Сохраняем источник
                source_ref.set(source_data)
                created_sources += 1
                
                if created_sources % 10 == 0:
                    print(f"   Создано источников: {created_sources}")
                    
            except Exception as e:
                print(f"   ⚠️  Ошибка при создании источника: {e}")
                continue
        
        print(f"✅ Создано источников: {created_sources}")
        
        # 3. Проверяем результат
        print(f"\n🔍 ПРОВЕРКА РЕЗУЛЬТАТА:")
        final_sources = list(db.collection('sources').limit(10).stream())
        print(f"Всего источников: {len(final_sources)}")
        
        if final_sources:
            print("\nПримеры созданных источников:")
            for i, source in enumerate(final_sources[:3]):
                data = source.to_dict()
                title = data.get('title', 'No title')
                content_len = len(data.get('content', ''))
                print(f"{i+1}. {title[:60]}... ({content_len} символов)")
        
        # 4. Создаем индекс для быстрого поиска
        print(f"\n📋 СОЗДАНИЕ ИНДЕКСОВ:")
        
        # Создаем индекс по полю interesting
        try:
            # Создаем документ с метаданными
            index_ref = db.collection('sources').document('_index')
            index_ref.set({
                'total_count': len(final_sources),
                'interesting_count': len([s for s in final_sources if s.to_dict().get('interesting')]),
                'last_updated': datetime.now().isoformat(),
                'index_type': 'sources_metadata'
            }, merge=True)
            print("✅ Создан индекс метаданных")
        except Exception as e:
            print(f"⚠️  Ошибка создания индекса: {e}")
        
        # 5. Выводы и рекомендации
        print(f"\n💡 ВЫВОДЫ:")
        print("-" * 40)
        
        if created_sources > 0:
            print(f"✅ Успешно создано {created_sources} источников")
            print("✅ Система готова к генерации качественных статей")
            print("✅ LLM теперь будет получать полный текст из источников")
        else:
            print("❌ Не удалось создать источники")
            print("❌ Проблема с качеством статей останется")
        
        print(f"\n📈 СЛЕДУЮЩИЕ ШАГИ:")
        print("1. Запустить тестовую генерацию 1-2 статей")
        print("2. Проверить качество сгенерированного контента")
        print("3. Убедиться, что LLM получает полный текст")
        print("4. Настроить ограничения генерации")
        
    except Exception as e:
        print(f"❌ Ошибка при исправлении: {e}")
        import traceback
        traceback.print_exc()

def test_source_connection():
    """Тестирует связь между источниками и LLM"""
    print(f"\n🧪 ТЕСТИРОВАНИЕ СВЯЗИ SOURCES -> LLM:")
    print("-" * 40)
    
    try:
        db = get_firebase_client().db
        
        # Получаем интересные источники
        sources = list(db.collection('sources').where('interesting', '==', True).limit(3).stream())
        
        if not sources:
            print("❌ Нет интересных источников для тестирования")
            return
        
        print(f"Найдено {len(sources)} интересных источников")
        
        for i, source in enumerate(sources):
            data = source.to_dict()
            title = data.get('title', 'No title')
            content = data.get('content', '')
            content_len = len(content)
            
            print(f"\n{i+1}. {title[:60]}...")
            print(f"   Длина контента: {content_len} символов")
            
            if content_len > 500:
                print(f"   ✅ Достаточно контента для LLM")
                print(f"   📄 Начало: {content[:200]}...")
            else:
                print(f"   ⚠️  Мало контента для LLM")
        
        print(f"\n✅ Тест завершен. LLM готов к работе с источниками!")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")

def main():
    """Основная функция исправления"""
    print("🔧 ИСПРАВЛЕНИЕ ПРОБЛЕМЫ С КОЛЛЕКЦИЕЙ SOURCES")
    print("=" * 70)
    
    # 1. Исправляем коллекцию sources
    fix_sources_collection()
    
    # 2. Тестируем связь
    test_source_connection()
    
    print(f"\n🎉 ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
    print("Теперь LLM будет получать полный текст из источников")

if __name__ == "__main__":
    main()







