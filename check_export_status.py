#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка статуса экспорта статей
"""
from workers.tools.firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def check_export_status():
    """Проверяет статус экспорта статей"""
    print("🔍 ПРОВЕРКА СТАТУСА ЭКСПОРТА СТАТЕЙ")
    print("=" * 50)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        articles_ref = firebase_client.db.collection('articles')
        
        # Получаем все статьи
        print("🔍 Анализирую статус статей...")
        articles = list(articles_ref.stream())
        
        if not articles:
            print("✅ Нет статей в базе")
            return
        
        total_articles = len(articles)
        processed_true = 0
        exported_true = 0
        published_true = 0
        ready_for_generation = 0
        
        for article in articles:
            data = article.to_dict() or {}
            
            if data.get('processed', False):
                processed_true += 1
                
                if data.get('exported_to_site', False):
                    exported_true += 1
                else:
                    if not data.get('published', False):
                        ready_for_generation += 1
                
                if data.get('published', False):
                    published_true += 1
        
        print(f"📊 СТАТУС СТАТЕЙ:")
        print(f"   📋 Всего статей: {total_articles}")
        print(f"   ✅ Обработано LLM (processed=True): {processed_true}")
        print(f"   📤 Экспортировано на сайт: {exported_true}")
        print(f"   📱 Опубликовано в Telegram: {published_true}")
        print(f"   🎯 Готово к генерации: {ready_for_generation}")
        
        if ready_for_generation > 0:
            print(f"\n💡 У вас есть {ready_for_generation} статей готовых для генерации!")
            print("   Запустите оркестратор для создания контента")
            
            # Показываем примеры готовых статей
            print(f"\n📄 ПРИМЕРЫ ГОТОВЫХ СТАТЕЙ:")
            count = 0
            for article in articles:
                if count >= 5:
                    break
                data = article.to_dict() or {}
                if (data.get('processed', False) and 
                    not data.get('exported_to_site', False) and 
                    not data.get('published', False)):
                    count += 1
                    title = data.get('title', 'N/A')[:60]
                    print(f"  {count}. {title}")
        else:
            print(f"\n✅ Все обработанные статьи уже экспортированы или опубликованы")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_export_status()







