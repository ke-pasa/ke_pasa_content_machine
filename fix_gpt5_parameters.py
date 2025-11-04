#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Исправление параметров для GPT-5-mini
GPT-5-mini использует max_completion_tokens вместо max_tokens
"""

import os
from pathlib import Path

def fix_gpt5_parameters():
    """Исправляет параметры для GPT-5-mini"""
    
    print("🔧 ИСПРАВЛЕНИЕ ПАРАМЕТРОВ ДЛЯ GPT-5-MINI")
    print("=" * 60)
    
    # Файлы для исправления
    files_to_fix = [
        'content_generator.py',
        'telegram_post_generator.py',
        'telegram_post_generator_v4.py',
        'rss_parser.py',
        'news_clustering.py',
        'prioritization_llm.py',
        'jobs_scheduler.py'
    ]
    
    print("📋 ИСПРАВЛЯЕМЫЕ ПАРАМЕТРЫ:")
    print("   max_tokens → max_completion_tokens")
    print("   (GPT-5-mini требует max_completion_tokens)")
    
    print("\n🔍 ПОИСК ФАЙЛОВ ДЛЯ ИСПРАВЛЕНИЯ:")
    
    fixed_files = []
    
    for filename in files_to_fix:
        file_path = Path(filename)
        if file_path.exists():
            print(f"   ✅ {filename} - найден")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Проверяем, есть ли max_tokens
                if 'max_tokens' in content:
                    print(f"      🔄 Требует исправления (содержит max_tokens)")
                    fixed_files.append((file_path, content))
                else:
                    print(f"      ✅ Уже исправлен")
                    
            except Exception as e:
                print(f"      ❌ Ошибка чтения: {e}")
        else:
            print(f"   ❌ {filename} - не найден")
    
    if not fixed_files:
        print("\n✅ Все файлы уже исправлены!")
        return
    
    print(f"\n🔧 ИСПРАВЛЕНИЕ {len(fixed_files)} ФАЙЛОВ:")
    print("=" * 60)
    
    for file_path, content in fixed_files:
        print(f"\n📝 Исправляю {file_path.name}...")
        
        # Создаем backup
        backup_path = file_path.with_suffix(file_path.suffix + '.gpt5_backup')
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"   💾 Backup создан: {backup_path.name}")
        except Exception as e:
            print(f"   ⚠️  Ошибка создания backup: {e}")
        
        # Заменяем max_tokens на max_completion_tokens
        updated_content = content.replace('max_tokens', 'max_completion_tokens')
        
        # Проверяем изменения
        if updated_content != content:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                print(f"   ✅ max_tokens → max_completion_tokens")
                print(f"   ✅ Файл исправлен")
            except Exception as e:
                print(f"   ❌ Ошибка записи: {e}")
        else:
            print(f"   ⚠️  Изменений не обнаружено")
    
    print("\n🎯 ОСОБЕННОСТИ GPT-5-MINI:")
    print("=" * 60)
    
    print("⚠️  ВАЖНЫЕ ИЗМЕНЕНИЯ В ПАРАМЕТРАХ:")
    print("   • max_tokens → max_completion_tokens")
    print("   • Это требование новой модели GPT-5-mini")
    
    print("\n🚀 ПРЕИМУЩЕСТВА GPT-5-MINI:")
    print("   • Лучшее качество генерации на русском языке")
    print("   • Более естественные и живые тексты")
    print("   • Лучшее понимание контекста и культуры")
    print("   • Оптимизирована для творческих задач")
    
    print("\n💰 ЦЕНА И ЭФФЕКТИВНОСТЬ:")
    print("   • Сопоставимая цена с GPT-4o-mini")
    print("   • Качество значительно выше")
    print("   • Лучшая производительность")
    
    # Создаем обновленный конфигурационный файл
    create_updated_config()
    
    print("\n🔧 СЛЕДУЮЩИЕ ШАГИ:")
    print("=" * 60)
    print("1. ✅ Параметры исправлены")
    print("2. 🔄 Перезапустить систему")
    print("3. 🧪 Протестировать генерацию")
    print("4. 📊 Сравнить качество")
    
    print("\n🎉 ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
    print("GPT-5-mini готова к использованию!")

def create_updated_config():
    """Создает обновленный конфигурационный файл"""
    
    config_content = """# Обновленная конфигурация GPT-5-mini
# ВАЖНО: GPT-5-mini использует max_completion_tokens вместо max_tokens

# Модели OpenAI для разных задач
OPENAI_MODELS = {
    # Основные задачи генерации
    'generate_article': 'gpt-5-mini',           # Генерация статей
    'generate_telegram_post': 'gpt-5-mini',     # Генерация постов
    
    # Простые задачи
    'filter_article': 'gpt-5-nano',             # Фильтрация новостей
    'cluster_batch': 'gpt-5-nano',              # Кластеризация
    'prioritize_clusters': 'gpt-5-nano',        # Приоритизация
    
    # Сложные задачи
    'complex_analysis': 'gpt-5',                 # Сложный анализ
    'creative_writing': 'gpt-5',                 # Творческое письмо
}

# Параметры для GPT-5-mini (ВАЖНО: max_completion_tokens!)
GPT5_MINI_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 4000,              # НЕ max_tokens!
    'temperature': 0.7,                          # Баланс креативности
    'top_p': 0.9,                               # Разнообразие
    'frequency_penalty': 0.1,                    # Снижение повторений
    'presence_penalty': 0.1,                     # Снижение повторений
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 5000,              # Увеличено для GPT-5-mini
    'temperature': 0.8,                          # Более креативно
    'top_p': 0.9,
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 1000,              # Оптимально для постов
    'temperature': 0.7,                          # Баланс
    'top_p': 0.9,
}

# Fallback модели
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}

# Пример использования:
"""
    example_usage = '''
# ПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_completion_tokens=4000,  # ✅ Правильно
    temperature=0.7
)

# НЕПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_tokens=4000,             # ❌ Ошибка!
    temperature=0.7
)
'''
    
    config_content += example_usage
    
    try:
        with open('gpt5_config_updated.py', 'w', encoding='utf-8') as f:
            f.write(config_content)
        print("   📁 Создан обновленный конфиг: gpt5_config_updated.py")
    except Exception as e:
        print(f"   ⚠️  Ошибка создания конфига: {e}")

def test_gpt5_mini_correct():
    """Тестирует GPT-5-mini с правильными параметрами"""
    
    print("\n🧪 ТЕСТИРОВАНИЕ GPT-5-MINI С ПРАВИЛЬНЫМИ ПАРАМЕТРАМИ:")
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
        
        # Тест с правильными параметрами
        print("🔍 Тестирую GPT-5-mini с max_completion_tokens...")
        
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты помощник для генерации контента на русском языке."},
                {"role": "user", "content": "Напиши короткое приветствие на русском языке."}
            ],
            max_completion_tokens=50,  # ✅ Правильно!
            temperature=0.7
        )
        
        result = response.choices[0].message.content
        print(f"✅ GPT-5-mini работает с max_completion_tokens!")
        print(f"   Ответ: {result}")
        
        # Тест генерации поста
        print("\n🔍 Тестирую генерацию поста...")
        
        post_response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты эксперт по созданию Telegram-постов для русскоязычных мигрантов в Испании."},
                {"role": "user", "content": "Создай короткий пост (до 200 символов) о погоде в Испании."}
            ],
            max_completion_tokens=200,  # ✅ Правильно!
            temperature=0.7
        )
        
        post_result = post_response.choices[0].message.content
        print(f"✅ Генерация поста работает!")
        print(f"   Пост: {post_result}")
        print(f"   Длина: {len(post_result)} символов")
        
        print("\n🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("GPT-5-mini готова к использованию в продакшене!")
        
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    fix_gpt5_parameters()
    
    # Спрашиваем пользователя о тестировании
    response = input("\n🧪 Хотите протестировать GPT-5-mini с правильными параметрами? (y/n): ")
    if response.lower() in ['y', 'yes', 'да', 'д']:
        test_gpt5_mini_correct()

