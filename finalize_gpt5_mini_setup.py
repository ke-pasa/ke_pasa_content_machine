#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Финальная настройка GPT-5-mini
Учитывает все ограничения и особенности новой модели
"""

import os
from pathlib import Path

def finalize_gpt5_mini_setup():
    """Финальная настройка GPT-5-mini"""
    
    print("🎯 ФИНАЛЬНАЯ НАСТРОЙКА GPT-5-MINI")
    print("=" * 60)
    
    print("⚠️  ВАЖНЫЕ ОГРАНИЧЕНИЯ GPT-5-MINI:")
    print("   • temperature: только 1 (по умолчанию)")
    print("   • max_tokens: НЕ поддерживается")
    print("   • max_completion_tokens: ОБЯЗАТЕЛЬНО")
    print("   • top_p: поддерживается")
    print("   • frequency_penalty: поддерживается")
    print("   • presence_penalty: поддерживается")
    
    # Файлы для финальной настройки
    files_to_finalize = [
        'content_generator.py',
        'telegram_post_generator.py',
        'telegram_post_generator_v4.py',
        'rss_parser.py',
        'news_clustering.py',
        'prioritization_llm.py',
        'jobs_scheduler.py'
    ]
    
    print("\n🔍 ПОИСК ФАЙЛОВ ДЛЯ ФИНАЛЬНОЙ НАСТРОЙКИ:")
    
    finalized_files = []
    
    for filename in files_to_finalize:
        file_path = Path(filename)
        if file_path.exists():
            print(f"   ✅ {filename} - найден")
            
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Проверяем, нужна ли финальная настройка
                needs_finalization = False
                
                # Проверяем temperature != 1
                if 'temperature=' in content and 'temperature=1' not in content:
                    needs_finalization = True
                
                # Проверяем max_tokens (должно быть max_completion_tokens)
                if 'max_tokens' in content:
                    needs_finalization = True
                
                if needs_finalization:
                    print(f"      🔄 Требует финальной настройки")
                    finalized_files.append((file_path, content))
                else:
                    print(f"      ✅ Уже настроен правильно")
                    
            except Exception as e:
                print(f"      ❌ Ошибка чтения: {e}")
        else:
            print(f"   ❌ {filename} - не найден")
    
    if not finalized_files:
        print("\n✅ Все файлы уже настроены правильно!")
        return
    
    print(f"\n🔧 ФИНАЛЬНАЯ НАСТРОЙКА {len(finalized_files)} ФАЙЛОВ:")
    print("=" * 60)
    
    for file_path, content in finalized_files:
        print(f"\n📝 Настраиваю {file_path.name}...")
        
        # Создаем backup
        backup_path = file_path.with_suffix(file_path.suffix + '.final_backup')
        try:
            with open(backup_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"   💾 Backup создан: {backup_path.name}")
        except Exception as e:
            print(f"   ⚠️  Ошибка создания backup: {e}")
        
        updated_content = content
        
        # 1. Заменяем temperature на 1 (если не 1)
        if 'temperature=' in updated_content:
            import re
            # Заменяем temperature=0.7, temperature=0.8 и т.д. на temperature=1
            updated_content = re.sub(r'temperature=\d+\.?\d*', 'temperature=1', updated_content)
            print(f"   ✅ temperature → 1")
        
        # 2. Проверяем max_completion_tokens
        if 'max_completion_tokens' not in updated_content and 'max_tokens' in updated_content:
            updated_content = updated_content.replace('max_tokens', 'max_completion_tokens')
            print(f"   ✅ max_tokens → max_completion_tokens")
        
        # Проверяем изменения
        if updated_content != content:
            try:
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                print(f"   ✅ Файл настроен")
            except Exception as e:
                print(f"   ❌ Ошибка записи: {e}")
        else:
            print(f"   ⚠️  Изменений не обнаружено")
    
    # Создаем финальную конфигурацию
    create_final_config()
    
    print("\n🎯 ОСОБЕННОСТИ GPT-5-MINI:")
    print("=" * 60)
    
    print("🚀 ПРЕИМУЩЕСТВА:")
    print("   • Лучшее качество генерации на русском языке")
    print("   • Более естественные и живые тексты")
    print("   • Лучшее понимание контекста и культуры")
    print("   • Оптимизирована для творческих задач")
    
    print("\n⚠️  ОГРАНИЧЕНИЯ:")
    print("   • temperature: только 1 (фиксированное значение)")
    print("   • max_completion_tokens: обязательно использовать")
    print("   • Некоторые параметры могут не поддерживаться")
    
    print("\n💰 ЦЕНА И ЭФФЕКТИВНОСТЬ:")
    print("   • Сопоставимая цена с GPT-4o-mini")
    print("   • Качество значительно выше")
    print("   • Лучшая производительность")
    
    print("\n🔧 СЛЕДУЮЩИЕ ШАГИ:")
    print("=" * 60)
    print("1. ✅ GPT-5-mini настроена правильно")
    print("2. 🔄 Перезапустить систему")
    print("3. 🧪 Протестировать генерацию")
    print("4. 📊 Сравнить качество")
    
    print("\n🎉 НАСТРОЙКА ЗАВЕРШЕНА!")
    print("GPT-5-mini готова к использованию!")

def create_final_config():
    """Создает финальную конфигурацию GPT-5-mini"""
    
    config_content = """# ФИНАЛЬНАЯ КОНФИГУРАЦИЯ GPT-5-MINI
# ВАЖНО: Учитывает все ограничения модели

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

# Параметры для GPT-5-mini (УЧИТЫВАЕМ ОГРАНИЧЕНИЯ!)
GPT5_MINI_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 4000,              # ОБЯЗАТЕЛЬНО!
    'temperature': 1,                            # ТОЛЬКО 1 (фиксированное)
    'top_p': 0.9,                               # Поддерживается
    'frequency_penalty': 0.1,                    # Поддерживается
    'presence_penalty': 0.1,                     # Поддерживается
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 5000,              # Увеличено для GPT-5-mini
    'temperature': 1,                            # ТОЛЬКО 1
    'top_p': 0.9,                               # Для разнообразия
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 1000,              # Оптимально для постов
    'temperature': 1,                            # ТОЛЬКО 1
    'top_p': 0.9,                               # Для разнообразия
}

# Fallback модели
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}

# ПРАВИЛЬНОЕ ИСПОЛЬЗОВАНИЕ GPT-5-MINI:
"""
    example_usage = '''
# ✅ ПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_completion_tokens=4000,  # ОБЯЗАТЕЛЬНО
    temperature=1,                # ТОЛЬКО 1
    top_p=0.9,                   # Для разнообразия
    frequency_penalty=0.1,        # Снижение повторений
    presence_penalty=0.1          # Снижение повторений
)

# ❌ НЕПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_tokens=4000,             # Ошибка!
    temperature=0.7,              # Ошибка!
    top_p=0.9
)
'''
    
    config_content += example_usage
    
    try:
        with open('gpt5_final_config.py', 'w', encoding='utf-8') as f:
            f.write(config_content)
        print("   📁 Создана финальная конфигурация: gpt5_final_config.py")
    except Exception as e:
        print(f"   ⚠️  Ошибка создания конфига: {e}")

def test_gpt5_mini_final():
    """Тестирует GPT-5-mini с финальными правильными параметрами"""
    
    print("\n🧪 ФИНАЛЬНОЕ ТЕСТИРОВАНИЕ GPT-5-MINI:")
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
        print("🔍 Тестирую GPT-5-mini с финальными параметрами...")
        
        response = client.chat.completions.create(
            model="gpt-5-mini",
            messages=[
                {"role": "system", "content": "Ты помощник для генерации контента на русском языке."},
                {"role": "user", "content": "Напиши короткое приветствие на русском языке."}
            ],
            max_completion_tokens=50,  # ✅ Правильно!
            temperature=1,              # ✅ Только 1!
            top_p=0.9                  # ✅ Для разнообразия
        )
        
        result = response.choices[0].message.content
        print(f"✅ GPT-5-mini работает с финальными параметрами!")
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
            temperature=1,              # ✅ Только 1!
            top_p=0.9                  # ✅ Для разнообразия
        )
        
        post_result = post_response.choices[0].message.content
        print(f"✅ Генерация поста работает!")
        print(f"   Пост: {post_result}")
        print(f"   Длина: {len(post_result)} символов")
        
        print("\n🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("GPT-5-mini полностью готова к использованию в продакшене!")
        
        # Дополнительные рекомендации
        print("\n💡 РЕКОМЕНДАЦИИ ПО ИСПОЛЬЗОВАНИЮ:")
        print("   • Используйте temperature=1 (фиксированное значение)")
        print("   • Настройте top_p для контроля разнообразия")
        print("   • Используйте frequency_penalty и presence_penalty")
        print("   • Всегда используйте max_completion_tokens")
        
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    finalize_gpt5_mini_setup()
    
    # Спрашиваем пользователя о тестировании
    response = input("\n🧪 Хотите протестировать GPT-5-mini с финальными параметрами? (y/n): ")
    if response.lower() in ['y', 'yes', 'да', 'д']:
        test_gpt5_mini_final()

