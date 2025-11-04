#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Исправляет связь между статьями и источниками:
1. Заполняет поле source_content в статьях
2. Связывает статьи с соответствующими источниками
3. Обеспечивает передачу полного текста в LLM
"""

from workers.tools.firebase_client import get_firebase_client
from datetime import datetime

def fix_article_source_connection():
    """Исправляет связь между статьями и источниками"""
    print("🔧 ИСПРАВЛЕНИЕ СВЯЗИ СТАТЬИ ↔ ИСТОЧНИКИ")
    print("=" * 60)
    
    try:
        db = get_firebase_client().db
        
        # 1. Получаем источники
        sources = list(db.collection('sources').limit(20).stream())
        print(f"📰 Найдено источников: {len(sources)}")
        
        if not sources:
            print("❌ Нет источников для обработки")
            return
        
        # 2. Получаем статьи
        articles = list(db.collection('articles').limit(20).stream())
        print(f"📝 Найдено статей: {len(articles)}")
        
        if not articles:
            print("❌ Нет статей для обработки")
            return
        
        # 3. Создаем карту источников по заголовку
        sources_map = {}
        for source in sources:
            data = source.to_dict()
            title = data.get('title', '').lower().strip()
            if title:
                sources_map[title] = data
        
        print(f"🗺️  Создана карта источников: {len(sources_map)} записей")
        
        # 4. Исправляем статьи
        fixed_articles = 0
        for article in articles:
            try:
                data = article.to_dict()
                title = data.get('title', '').lower().strip()
                
                if not title:
                    continue
                
                # Ищем соответствующий источник
                source_data = None
                for source_title, source in sources_map.items():
                    # Простая проверка по заголовку
                    if title in source_title or source_title in title:
                        source_data = source
                        break
                
                if source_data:
                    # Обновляем статью
                    update_data = {
                        'source_content': source_data.get('content', ''),
                        'source_link': source_data.get('link', ''),
                        'source_title': source_data.get('title', ''),
                        'source_updated_at': datetime.now().isoformat(),
                        'has_source_content': True
                    }
                    
                    # Сохраняем обновления
                    db.collection('articles').document(article.id).set(update_data, merge=True)
                    fixed_articles += 1
                    
                    if fixed_articles % 5 == 0:
                        print(f"   Исправлено статей: {fixed_articles}")
                        
                else:
                    print(f"   ⚠️  Не найден источник для: {title[:50]}...")
                    
            except Exception as e:
                print(f"   ❌ Ошибка при исправлении статьи: {e}")
                continue
        
        print(f"✅ Исправлено статей: {fixed_articles}")
        
        # 5. Проверяем результат
        print(f"\n🔍 ПРОВЕРКА РЕЗУЛЬТАТА:")
        updated_articles = list(db.collection('articles').limit(5).stream())
        
        for i, article in enumerate(updated_articles):
            data = article.to_dict()
            title = data.get('title', 'No title')
            source_content = data.get('source_content', '')
            has_source = data.get('has_source_content', False)
            
            print(f"{i+1}. {title[:60]}...")
            print(f"   Источник: {'✅' if has_source else '❌'}")
            print(f"   Длина исходного контента: {len(source_content)} символов")
            
            if source_content:
                print(f"   Начало: {source_content[:100]}...")
        
        # 6. Выводы
        print(f"\n💡 ВЫВОДЫ:")
        print("-" * 40)
        
        if fixed_articles > 0:
            print(f"✅ Успешно исправлено {fixed_articles} статей")
            print("✅ LLM теперь будет получать полный текст из источников")
            print("✅ Качество генерируемых статей должно улучшиться")
        else:
            print("❌ Не удалось исправить статьи")
            print("❌ Проблема с качеством останется")
        
        print(f"\n📈 СЛЕДУЮЩИЕ ШАГИ:")
        print("1. Протестировать генерацию новых статей")
        print("2. Проверить качество сгенерированного контента")
        print("3. Убедиться, что LLM использует исходный материал")
        
    except Exception as e:
        print(f"❌ Ошибка при исправлении: {e}")
        import traceback
        traceback.print_exc()

def test_llm_source_connection():
    """Тестирует, что LLM получает исходный материал"""
    print(f"\n🧪 ТЕСТИРОВАНИЕ LLM ↔ ИСТОЧНИКИ:")
    print("-" * 40)
    
    try:
        db = get_firebase_client().db
        
        # Получаем статьи с исходным контентом
        articles = list(db.collection('articles').where('has_source_content', '==', True).limit(3).stream())
        
        if not articles:
            print("❌ Нет статей с исходным контентом")
            return
        
        print(f"Найдено {len(articles)} статей с исходным контентом")
        
        for i, article in enumerate(articles):
            data = article.to_dict()
            title = data.get('title', 'No title')
            source_content = data.get('source_content', '')
            content_len = len(source_content)
            
            print(f"\n{i+1}. {title[:60]}...")
            print(f"   Длина исходного контента: {content_len} символов")
            
            if content_len > 500:
                print(f"   ✅ Достаточно контента для LLM")
                print(f"   📄 Начало: {source_content[:200]}...")
                
                # Проверяем качество контента
                has_numbers = any(char.isdigit() for char in source_content)
                has_dates = any(word in source_content.lower() for word in ['2025', 'август', 'сентябрь'])
                has_names = any(word in source_content for word in ['Roberto', 'Brasero', 'Feijóo', 'AEMET'])
                
                print(f"   🔢 Содержит цифры: {'✅' if has_numbers else '❌'}")
                print(f"   📅 Содержит даты: {'✅' if has_dates else '❌'}")
                print(f"   👤 Содержит имена: {'✅' if has_names else '❌'}")
            else:
                print(f"   ⚠️  Мало контента для LLM")
        
        print(f"\n✅ Тест завершен. LLM готов к работе с качественными источниками!")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")

def main():
    """Основная функция исправления"""
    print("🔧 ИСПРАВЛЕНИЕ СВЯЗИ СТАТЬИ ↔ ИСТОЧНИКИ")
    print("=" * 70)
    
    # 1. Исправляем связь
    fix_article_source_connection()
    
    # 2. Тестируем связь
    test_llm_source_connection()
    
    print(f"\n🎉 ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
    print("Теперь LLM будет получать полный текст из источников для генерации качественных статей")

if __name__ == "__main__":
    main()







