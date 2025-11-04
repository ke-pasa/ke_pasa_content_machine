#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИССЛЕДОВАНИЕ СТРУКТУРЫ FIREBASE
Показывает все коллекции и документы для поиска настроек Telegram
"""

from workers.tools.firebase_client import get_firebase_client

def explore_firebase_structure():
    """Исследует структуру Firebase для поиска настроек"""
    
    print("🔍 ИССЛЕДОВАНИЕ СТРУКТУРЫ FIREBASE")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Получаем все коллекции
        print("📚 ПОИСК КОЛЛЕКЦИЙ:")
        collections = firebase_client.db.collections()
        
        for collection in collections:
            collection_name = collection.id
            print(f"\n📁 Коллекция: {collection_name}")
            
            # Получаем документы в коллекции
            docs = collection.limit(10).stream()  # Ограничиваем для производительности
            
            doc_count = 0
            for doc in docs:
                doc_count += 1
                doc_id = doc.id
                doc_data = doc.to_dict() or {}
                
                print(f"   📄 Документ: {doc_id}")
                
                # Ищем настройки Telegram в данных документа
                telegram_keys = []
                for key, value in doc_data.items():
                    if 'telegram' in key.lower() or 'bot' in key.lower() or 'chat' in key.lower():
                        telegram_keys.append(key)
                
                if telegram_keys:
                    print(f"      🔍 Найдены ключи Telegram: {telegram_keys}")
                    for key in telegram_keys:
                        value = doc_data[key]
                        if isinstance(value, str) and len(value) > 20:
                            print(f"         {key}: {value[:20]}...{value[-10:]}")
                        else:
                            print(f"         {key}: {value}")
                
                # Показываем первые несколько ключей
                all_keys = list(doc_data.keys())
                if all_keys:
                    print(f"      📋 Ключи: {all_keys[:5]}{'...' if len(all_keys) > 5 else ''}")
                
                # Ограничиваем вывод документов
                if doc_count >= 5:
                    print(f"      ... и еще документов")
                    break
            
            if doc_count == 0:
                print(f"   📄 Документов: 0")
            
            # Ограничиваем вывод коллекций
            if collection_name == 'settings':
                print(f"   🔍 ДЕТАЛЬНОЕ ИССЛЕДОВАНИЕ КОЛЛЕКЦИИ SETTINGS:")
                settings_docs = collection.stream()
                for doc in settings_docs:
                    doc_id = doc.id
                    doc_data = doc.to_dict() or {}
                    print(f"      📄 {doc_id}: {list(doc_data.keys())}")
        
        # Специальный поиск настроек Telegram
        print(f"\n🔍 СПЕЦИАЛЬНЫЙ ПОИСК НАСТРОЕК TELEGRAM:")
        
        # Ищем в коллекции settings
        settings_ref = firebase_client.db.collection('settings')
        settings_docs = settings_ref.stream()
        
        telegram_found = False
        for doc in settings_docs:
            doc_id = doc.id
            doc_data = doc.to_dict() or {}
            
            # Проверяем, есть ли настройки Telegram
            if 'telegram' in doc_id.lower():
                print(f"   ✅ Найден документ с Telegram: {doc_id}")
                telegram_found = True
                for key, value in doc_data.items():
                    print(f"      {key}: {value}")
            
            # Проверяем содержимое на наличие Telegram настроек
            telegram_keys = [k for k in doc_data.keys() if 'telegram' in k.lower()]
            if telegram_keys:
                print(f"   ✅ В документе {doc_id} найдены ключи Telegram: {telegram_keys}")
                telegram_found = True
                for key in telegram_keys:
                    value = doc_data[key]
                    if isinstance(value, str) and len(value) > 20:
                        print(f"      {key}: {value[:20]}...{value[-10:]}")
                    else:
                        print(f"      {key}: {value}")
        
        if not telegram_found:
            print(f"   ❌ Настройки Telegram не найдены ни в одном документе")
            print(f"   💡 Создайте документ settings/telegram или добавьте настройки в существующий")
        
    except Exception as e:
        print(f"❌ Ошибка исследования Firebase: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    explore_firebase_structure()

