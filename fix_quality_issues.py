#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Скрипт для исправления проблем с качеством статей:
1. Останавливает неконтролируемую генерацию
2. Очищает низкокачественный контент
3. Восстанавливает контроль над системой
"""

import os
import shutil
from datetime import datetime
from workers.tools.firebase_client import get_firebase_client

def create_backup():
    """Создает резервную копию текущих статей"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = f"backup_articles_{timestamp}"
    
    if os.path.exists("spain-news-portal/src/content/news"):
        shutil.copytree("spain-news-portal/src/content/news", backup_dir)
        print(f"✅ Резервная копия создана: {backup_dir}")
        return backup_dir
    return None

def stop_generation():
    """Останавливает процессы генерации"""
    try:
        db = get_firebase_client().db
        
        # Очищаем очередь задач
        queued_tasks = list(db.collection('llm_tasks').where('status', '==', 'queued').stream())
        for task in queued_tasks:
            db.collection('llm_tasks').document(task.id).delete()
        print(f"✅ Удалено {len(queued_tasks)} задач из очереди")
        
        # Останавливаем активные батчи
        active_batches = list(db.collection('llm_batches').where('status', 'in', ['submitted', 'validating', 'in_progress', 'finalizing']).stream())
        for batch in active_batches:
            db.collection('llm_batches').document(batch.id).set({'status': 'cancelled'}, merge=True)
        print(f"✅ Остановлено {len(active_batches)} активных батчей")
        
        # Очищаем блокировки
        locks = list(db.collection('locks').stream())
        for lock in locks:
            db.collection('locks').document(lock.id).delete()
        print(f"✅ Очищено {len(locks)} блокировок")
        
    except Exception as e:
        print(f"⚠️  Ошибка при остановке генерации: {e}")

def clean_low_quality_articles():
    """Удаляет низкокачественные статьи"""
    try:
        db = get_firebase_client().db
        
        # Получаем все статьи
        articles = list(db.collection('articles').limit(1000).stream())
        print(f"📊 Всего статей в БД: {len(articles)}")
        
        # Анализируем качество
        low_quality_count = 0
        for article in articles:
            data = article.to_dict()
            content = data.get('content', '')
            title = data.get('title', '')
            
            # Критерии низкого качества
            is_low_quality = False
            
            # 1. Слишком короткие статьи
            if len(content) < 500:
                is_low_quality = True
            
            # 2. Статьи с общими фразами
            generic_phrases = [
                "жара в испании", "лесные пожары", "погода в испании",
                "что происходит", "как справиться", "что нас ждет"
            ]
            content_lower = content.lower()
            if any(phrase in content_lower for phrase in generic_phrases):
                if len(content) < 1000:  # Если статья короткая + общие фразы
                    is_low_quality = True
            
            # 3. Статьи без конкретных деталей
            if not any(char.isdigit() for char in content):  # Нет цифр
                if len(content) < 800:
                    is_low_quality = True
            
            if is_low_quality:
                low_quality_count += 1
                # Помечаем для удаления
                db.collection('articles').document(article.id).set({
                    'quality_mark': 'low',
                    'marked_for_deletion': True,
                    'marked_at': datetime.now().isoformat()
                }, merge=True)
        
        print(f"📝 Помечено низкокачественных статей: {low_quality_count}")
        
        # Удаляем низкокачественные статьи
        if low_quality_count > 0:
            response = input(f"Удалить {low_quality_count} низкокачественных статей? (y/n): ")
            if response.lower() == 'y':
                deleted_count = 0
                for article in articles:
                    data = article.to_dict()
                    if data.get('marked_for_deletion'):
                        db.collection('articles').document(article.id).delete()
                        deleted_count += 1
                
                print(f"✅ Удалено {deleted_count} низкокачественных статей")
        
    except Exception as e:
        print(f"⚠️  Ошибка при очистке статей: {e}")

def limit_article_count():
    """Ограничивает количество статей до разумного предела"""
    try:
        db = get_firebase_client().db
        
        # Получаем все статьи
        articles = list(db.collection('articles').limit(1000).stream())
        current_count = len(articles)
        
        if current_count > 50:  # Оставляем только 50 лучших
            print(f"📊 Текущее количество статей: {current_count}")
            print(f"🎯 Целевое количество: 50")
            
            # Сортируем по дате создания (новые сначала)
            articles_with_dates = []
            for article in articles:
                data = article.to_dict()
                created_at = data.get('created_at', '1970-01-01')
                articles_with_dates.append((article.id, created_at, data))
            
            # Сортируем по дате (новые сначала)
            articles_with_dates.sort(key=lambda x: x[1], reverse=True)
            
            # Оставляем только первые 50
            to_delete = articles_with_dates[50:]
            
            if to_delete:
                response = input(f"Удалить {len(to_delete)} статей, оставив только 50 лучших? (y/n): ")
                if response.lower() == 'y':
                    deleted_count = 0
                    for article_id, _, _ in to_delete:
                        db.collection('articles').document(article_id).delete()
                        deleted_count += 1
                    
                    print(f"✅ Удалено {deleted_count} статей")
                    print(f"📊 Осталось статей: 50")
        
    except Exception as e:
        print(f"⚠️  Ошибка при ограничении количества статей: {e}")

def create_quality_control():
    """Создает систему контроля качества"""
    try:
        # Создаем файл с настройками качества
        quality_config = """# Настройки контроля качества статей

# Минимальные требования к статье
MIN_ARTICLE_LENGTH = 800  # символов
MAX_ARTICLES_PER_DAY = 5  # максимум статей в день
MIN_SOURCE_CONTENT_LENGTH = 500  # минимальная длина исходного материала

# Критерии качества
QUALITY_CRITERIA = {
    'min_length': 800,
    'require_specific_details': True,
    'require_numbers_dates': True,
    'max_generic_phrases': 2,
    'min_unique_content': 0.7
}

# Ограничения генерации
GENERATION_LIMITS = {
    'max_articles_total': 100,
    'max_articles_per_category': 20,
    'max_articles_per_region': 15
}
"""
        
        with open('quality_control_config.py', 'w', encoding='utf-8') as f:
            f.write(quality_config)
        
        print("✅ Создан файл конфигурации качества")
        
    except Exception as e:
        print(f"⚠️  Ошибка при создании конфигурации: {e}")

def main():
    """Основная функция исправления"""
    print("🔧 ИСПРАВЛЕНИЕ ПРОБЛЕМ С КАЧЕСТВОМ СТАТЕЙ")
    print("=" * 60)
    
    # 1. Создаем резервную копию
    print("\n📦 Создание резервной копии...")
    backup_dir = create_backup()
    
    # 2. Останавливаем генерацию
    print("\n🛑 Остановка процессов генерации...")
    stop_generation()
    
    # 3. Очищаем низкокачественный контент
    print("\n🧹 Очистка низкокачественного контента...")
    clean_low_quality_articles()
    
    # 4. Ограничиваем количество статей
    print("\n📊 Ограничение количества статей...")
    limit_article_count()
    
    # 5. Создаем систему контроля качества
    print("\n⚙️  Создание системы контроля качества...")
    create_quality_control()
    
    print("\n✅ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
    print("\n📋 СЛЕДУЮЩИЕ ШАГИ:")
    print("1. Проверить качество оставшихся статей")
    print("2. Настроить ограничения в batch_orchestrator.py")
    print("3. Улучшить промпты для более конкретного контента")
    print("4. Добавить валидацию качества перед сохранением")
    print("5. Запустить тестовую генерацию 2-3 статей")

if __name__ == "__main__":
    main()







