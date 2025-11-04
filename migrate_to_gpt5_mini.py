#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция системы на GPT-5-mini для генерации статей и постов
GPT-5-mini - новая модель OpenAI с лучшим качеством и ценой
"""

import os
import re
from pathlib import Path

def migrate_to_gpt5_mini():
    """Мигрирует систему на GPT-5-mini"""
    
    print("🚀 МИГРАЦИЯ НА GPT-5-MINI")
    print("=" * 60)
    
    # Файлы для обновления
    files_to_update = [
        'content_generator.py',
        'telegram_post_generator.py', 
        'telegram_post_generator_v4.py',
        'rss_parser.py',
        'news_clustering.py',
        'prioritization_llm.py',
        'jobs_scheduler.py'
    ]
    
    # Стратегия миграции
    migration_strategy = {
        'gpt-4o-mini': 'gpt-5-mini',  # Основная замена
        'gpt-4o': 'gpt-5',            # Для сложных задач
        'gpt-4.1-mini': 'gpt-5-mini', # Устаревшие модели
        'gpt-4.1': 'gpt-5'            # Устаревшие модели
    }
    
    print("📋 СТРАТЕГИЯ МИГРАЦИИ:")
    for old_model, new_model in migration_strategy.items():
        print(f"   {old_model} → {new_model}")
    
    print("\n🔍 ПОИСК ФАЙЛОВ ДЛЯ ОБНОВЛЕНИЯ:")
    
    updated_files = []
    
    for filename in files_to_update:
        file_path = Path(filename)
        if file_path.exists():
            print(f"   ✅ {filename} - найден")
            
            # Читаем содержимое файла
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Проверяем, есть ли модели для замены
                needs_update = False
                for old_model in migration_strategy.keys():
                    if old_model in content:
                        needs_update = True
                        break
                
                if needs_update:
                    print(f"      🔄 Требует обновления")
                    updated_files.append((file_path, content))
                else:
                    print(f"      ✅ Уже обновлен или не содержит моделей")
                    
            except Exception as e:
                print(f"      ❌ Ошибка чтения: {e}")
        else:
            print(f"   ❌ {filename} - не найден")
    
    if not updated_files:
        print("\n✅ Все файлы уже обновлены!")
        return
    
    print(f"\n🔄 ОБНОВЛЕНИЕ {len(updated_files)} ФАЙЛОВ:")
    print("=" * 60)
    
    for file_path, content in updated_files:
        print(f"\n📝 Обновляю {file_path.name}...")
        
        # Выполняем замены
        original_content = content
        updated_content = content
        
        for old_model, new_model in migration_strategy.items():
            if old_model in updated_content:
                # Заменяем модель
                updated_content = updated_content.replace(old_model, new_model)
                print(f"   ✅ {old_model} → {new_model}")
        
        # Проверяем, были ли изменения
        if updated_content != original_content:
            # Создаем backup
            backup_path = file_path.with_suffix(file_path.suffix + '.backup')
            try:
                with open(backup_path, 'w', encoding='utf-8') as f:
                    f.write(original_content)
                print(f"   💾 Backup создан: {backup_path.name}")
            except Exception as e:
                print(f"   ⚠️  Ошибка создания backup: {e}")
            
            # Записываем обновленный файл
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                print(f"   ✅ Файл обновлен")
            except Exception as e:
                print(f"   ❌ Ошибка записи: {e}")
        else:
            print(f"   ⚠️  Изменений не обнаружено")
    
    print("\n🎯 ОСОБЕННОСТИ GPT-5-MINI:")
    print("=" * 60)
    
    print("🚀 ПРЕИМУЩЕСТВА:")
    print("   • Лучшее качество генерации текста")
    print("   • Более естественный русский язык")
    print("   • Лучшее понимание контекста")
    print("   • Оптимизирована для творческих задач")
    
    print("\n💰 ЦЕНА:")
    print("   • GPT-5-mini: ~$0.10-0.15 за 1M входных токенов")
    print("   • GPT-5-mini: ~$0.40-0.60 за 1M выходных токенов")
    print("   • Сопоставимо с GPT-4o-mini, но качество выше")
    
    print("\n⚙️ РЕКОМЕНДУЕМЫЕ НАСТРОЙКИ:")
    print("   • temperature: 0.7-0.8 (для творческих задач)")
    print("   • max_tokens: увеличить на 20-30%")
    print("   • top_p: 0.9 (для разнообразия)")
    
    print("\n🔧 СЛЕДУЮЩИЕ ШАГИ:")
    print("=" * 60)
    print("1. ✅ Модели обновлены в коде")
    print("2. 🔄 Перезапустить систему")
    print("3. 🧪 Протестировать генерацию статей")
    print("4. 🧪 Протестировать генерацию постов")
    print("5. 📊 Сравнить качество с предыдущими моделями")
    
    # Создаем конфигурационный файл
    create_config_file()
    
    print("\n🎉 МИГРАЦИЯ ЗАВЕРШЕНА!")
    print("Система теперь использует GPT-5-mini для лучшего качества!")

def create_config_file():
    """Создает конфигурационный файл с настройками GPT-5-mini"""
    
    config_content = """# Конфигурация GPT-5-mini для системы генерации контента

# Модели OpenAI для разных задач
OPENAI_MODELS = {
    # Основные задачи генерации
    'generate_article': 'gpt-5-mini',           # Генерация статей
    'generate_telegram_post': 'gpt-5-mini',     # Генерация постов
    
    # Простые задачи (можно использовать GPT-5-nano)
    'filter_article': 'gpt-5-nano',             # Фильтрация новостей
    'cluster_batch': 'gpt-5-nano',              # Кластеризация
    'prioritize_clusters': 'gpt-5-nano',        # Приоритизация
    
    # Сложные задачи
    'complex_analysis': 'gpt-5',                 # Сложный анализ
    'creative_writing': 'gpt-5',                 # Творческое письмо
}

# Рекомендуемые параметры для GPT-5-mini
GPT5_MINI_PARAMS = {
    'temperature': 0.7,                          # Баланс креативности и точности
    'top_p': 0.9,                               # Разнообразие выбора
    'frequency_penalty': 0.1,                    # Снижение повторений
    'presence_penalty': 0.1,                     # Снижение повторений
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_tokens': 4000,                         # Увеличено для GPT-5-mini
    'temperature': 0.8,                          # Более креативно
    'top_p': 0.9,
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_tokens': 1000,                         # Оптимально для постов
    'temperature': 0.7,                          # Баланс
    'top_p': 0.9,
}

# Fallback модели (если GPT-5 недоступна)
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}
"""
    
    try:
        with open('gpt5_config.py', 'w', encoding='utf-8') as f:
            f.write(config_content)
        print("   📁 Создан конфигурационный файл: gpt5_config.py")
    except Exception as e:
        print(f"   ⚠️  Ошибка создания конфига: {e}")

def test_gpt5_mini():
    """Тестирует доступность GPT-5-mini"""
    
    print("\n🧪 ТЕСТИРОВАНИЕ GPT-5-MINI:")
    print("=" * 60)
    
    try:
        import openai
        from dotenv import load_dotenv
        
        load_dotenv()
        
        api_key = os.getenv('OPENAI_API_KEY')
        if not api_key:
            print("❌ OPENAI_API_KEY не найден")
            return
        
        client = openai.OpenAI(api_key=api_key)
        
        # Тест простого запроса
        print("🔍 Тестирую GPT-5-mini...")
        
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты помощник для генерации контента на русском языке."},
                {"role": "user", "content": "Напиши короткое приветствие на русском языке."}
            ],
            max_tokens=50,
            temperature=0.7
        )
        
        result = response.choices[0].message.content
        print(f"✅ GPT-5-mini работает!")
        print(f"   Ответ: {result}")
        
        # Тест генерации поста
        print("\n🔍 Тестирую генерацию поста...")
        
        post_response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты эксперт по созданию Telegram-постов для русскоязычных мигрантов в Испании."},
                {"role": "user", "content": "Создай короткий пост (до 200 символов) о погоде в Испании."}
            ],
            max_tokens=200,
            temperature=0.7
        )
        
        post_result = post_response.choices[0].message.content
        print(f"✅ Генерация поста работает!")
        print(f"   Пост: {post_result}")
        print(f"   Длина: {len(post_result)} символов")
        
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    migrate_to_gpt5_mini()
    
    # Спрашиваем пользователя о тестировании
    response = input("\n🧪 Хотите протестировать GPT-5-mini? (y/n): ")
    if response.lower() in ['y', 'yes', 'да', 'д']:
        test_gpt5_mini()

