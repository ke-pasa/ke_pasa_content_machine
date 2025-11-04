#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Сброс флагов кластеризации для перехода на новую логику без кластеризации
"""
from firebase_client import get_firebase_client
import os
from dotenv import load_dotenv

def reset_clustering_flags():
    """Сбрасывает флаги кластеризации для всех статей"""
    print("🔄 СБРОС ФЛАГОВ КЛАСТЕРИЗАЦИИ")
    print("=" * 50)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        articles_ref = firebase_client.db.collection('articles')
        
        # Получаем все статьи с is_clustered=True
        clustered_articles = list(articles_ref.where('is_clustered', '==', True).stream())
        
        if not clustered_articles:
            print("✅ Нет статей для сброса кластеризации")
            return
        
        print(f"📋 Найдено {len(clustered_articles)} статей с is_clustered=True")
        print("🔄 Сбрасываем флаги...")
        
        reset_count = 0
        for article in clustered_articles:
            try:
                article_id = article.id
                # Сбрасываем флаги кластеризации
                articles_ref.document(article_id).update({
                    'is_clustered': False,
                    'clustered_at': None
                })
                reset_count += 1
                
                if reset_count % 10 == 0:
                    print(f"  ✅ Сброшено {reset_count}/{len(clustered_articles)} статей...")
                    
            except Exception as e:
                print(f"❌ Ошибка при сбросе статьи {article.id}: {e}")
        
        print(f"\n✅ ГОТОВО! Сброшено {reset_count}/{len(clustered_articles)} статей")
        print("\n💡 Теперь статьи готовы для обработки по новой логике:")
        print("   1. RSS парсинг → LLM фильтрация (processed=True)")
        print("   2. Генерация статей (exported_to_site=True)")
        print("   3. Ранжирование и выбор для Telegram")
        
    except Exception as e:
        print(f"❌ Ошибка при сбросе флагов: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    reset_clustering_flags()







