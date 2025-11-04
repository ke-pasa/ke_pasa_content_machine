#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый скрипт для проверки работы с Firebase
"""

from rss_parser import RSSParser

def test_firebase_integration():
    """Тестирует интеграцию с Firebase"""
    
    print("🧪 ТЕСТ ИНТЕГРАЦИИ С FIREBASE")
    print("=" * 50)
    
    # Создаем парсер
    parser = RSSParser()
    
    # Проверяем подключение к Firebase
    if parser.db:
        print("✅ Firebase подключен")
        
        # Тестовая статья
        test_article = {
            'title': 'Test Article for Firebase',
            'link': 'https://example.com/test-article',
            'summary': 'This is a test article for Firebase integration',
            'published': '2025-01-29',
            'image': 'https://example.com/image.jpg',
            'categories': ['test', 'firebase'],
            'category': 'news',
            'feed_title': 'Test Feed',
            'feed_url': 'https://example.com/feed'
        }
        
        # Проверяем дубликат
        print("\n🔍 Проверяем дубликат...")
        is_dup = parser.is_duplicate(test_article)
        print(f"Дубликат: {is_dup}")
        
        if not is_dup:
            # Создаем тестовый перевод
            test_translated = {
                'title': 'Тестовая статья для Firebase',
                'description': 'Это тестовая статья для интеграции с Firebase',
                'content': 'Полный текст тестовой статьи...',
                'tags': ['тест', 'firebase', 'интеграция']
            }
            
            # Сохраняем в Firebase
            print("\n💾 Сохраняем в Firebase...")
            success = parser.save_to_firebase(test_article, test_translated)
            print(f"Сохранение: {'✅ Успешно' if success else '❌ Ошибка'}")
            
            # Проверяем дубликат снова
            print("\n🔍 Проверяем дубликат после сохранения...")
            is_dup_after = parser.is_duplicate(test_article)
            print(f"Дубликат: {is_dup_after}")
        
    else:
        print("❌ Firebase не подключен")
        print("💡 Создайте файл firebase_key.json с ключом сервисного аккаунта")

if __name__ == "__main__":
    test_firebase_integration() 