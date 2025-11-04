#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Массовое исправление поля processed для статей с content
"""
from firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def fix_processed_field():
    """Исправляет поле processed для статей с content"""
    print("🔧 МАССОВОЕ ИСПРАВЛЕНИЕ ПОЛЯ PROCESSED")
    print("=" * 50)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        articles_ref = firebase_client.db.collection('articles')
        
        # Получаем статьи с processed=False, но с content
        print("🔍 Ищу статьи с processed=False, но с content...")
        articles = list(articles_ref.where('processed', '==', False).stream())
        
        if not articles:
            print("✅ Нет статей для исправления")
            return
        
        print(f"📋 Найдено {len(articles)} статей с processed=False")
        
        # Фильтруем только те, у которых есть content
        articles_with_content = []
        for article in articles:
            data = article.to_dict()
            if data.get('content'):
                articles_with_content.append({
                    'id': article.id,
                    'title': data.get('title', 'N/A')[:50],
                    'content_length': len(data.get('content', ''))
                })
        
        print(f"📄 Из них {len(articles_with_content)} имеют content (прошли LLM фильтрацию)")
        
        if not articles_with_content:
            print("✅ Нет статей с content для исправления")
            return
        
        # Исправляем поле processed
        print(f"\n🔄 Исправляю поле processed для {len(articles_with_content)} статей...")
        
        fixed_count = 0
        error_count = 0
        
        for i, article_info in enumerate(articles_with_content, 1):
            try:
                success = firebase_client.update_article_field(article_info['id'], 'processed', True)
                if success:
                    fixed_count += 1
                    if i % 50 == 0:
                        print(f"  ✅ Исправлено {i}/{len(articles_with_content)} статей...")
                else:
                    error_count += 1
                    print(f"  ❌ Ошибка исправления статьи {article_info['id'][:8]}...")
                    
            except Exception as e:
                error_count += 1
                print(f"  ❌ Исключение при исправлении статьи {article_info['id'][:8]}: {e}")
        
        print(f"\n🎯 ИТОГИ ИСПРАВЛЕНИЯ:")
        print(f"   ✅ Успешно исправлено: {fixed_count}")
        print(f"   ❌ Ошибок: {error_count}")
        print(f"   📊 Всего обработано: {len(articles_with_content)}")
        
        if fixed_count > 0:
            print(f"\n💡 Теперь у вас должно быть {fixed_count} статей с processed=True")
            print("   Запустите оркестратор снова для генерации статей")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fix_processed_field()







