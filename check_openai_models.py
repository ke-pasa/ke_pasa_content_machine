#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для проверки доступных моделей OpenAI и их параметров
Помогает выбрать оптимальную модель для разных задач
"""

import os
import openai
from dotenv import load_dotenv

def check_openai_models():
    """Проверяет доступные модели OpenAI"""
    
    print("🔍 ПРОВЕРКА ДОСТУПНЫХ МОДЕЛЕЙ OPENAI")
    print("=" * 60)
    
    # Загружаем переменные окружения
    load_dotenv()
    
    # Проверяем API ключ
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("❌ OPENAI_API_KEY не найден в .env файле")
        return
    
    try:
        # Создаем клиент OpenAI
        client = openai.OpenAI(api_key=api_key)
        
        print("📡 Получаю список доступных моделей...")
        
        # Получаем список моделей
        models = client.models.list()
        
        # Фильтруем только GPT модели
        gpt_models = []
        for model in models.data:
            if 'gpt' in model.id.lower():
                gpt_models.append({
                    'id': model.id,
                    'created': model.created,
                    'owned_by': model.owned_by
                })
        
        print(f"✅ Найдено {len(gpt_models)} GPT моделей:")
        print()
        
        # Сортируем по дате создания (новые сначала)
        gpt_models.sort(key=lambda x: x['created'], reverse=True)
        
        for i, model in enumerate(gpt_models, 1):
            print(f"{i:2d}. {model['id']}")
            print(f"     Создана: {model['created']}")
            print(f"     Владелец: {model['owned_by']}")
            print()
        
        # Анализируем модели
        print("🔍 АНАЛИЗ МОДЕЛЕЙ:")
        print("=" * 60)
        
        # Ищем GPT-5 модели
        gpt5_models = [m for m in gpt_models if 'gpt-5' in m['id'].lower()]
        gpt4_models = [m for m in gpt_models if 'gpt-4' in m['id'].lower()]
        gpt3_models = [m for m in gpt_models if 'gpt-3' in m['id'].lower()]
        
        if gpt5_models:
            print("🚀 GPT-5 МОДЕЛИ (новейшие):")
            for model in gpt5_models:
                print(f"   ✅ {model['id']} - {model['created']}")
        else:
            print("❌ GPT-5 модели не найдены")
        
        if gpt4_models:
            print(f"\n🔵 GPT-4 МОДЕЛИ ({len(gpt4_models)} шт.):")
            for model in gpt4_models:
                print(f"   ✅ {model['id']} - {model['created']}")
        
        if gpt3_models:
            print(f"\n🟢 GPT-3 МОДЕЛИ ({len(gpt3_models)} шт.):")
            for model in gpt3_models:
                print(f"   ✅ {model['id']} - {model['created']}")
        
        # Рекомендации
        print("\n💡 РЕКОМЕНДАЦИИ ПО ВЫБОРУ МОДЕЛИ:")
        print("=" * 60)
        
        if gpt5_models:
            print("🎯 ДЛЯ СТАТЕЙ И ПОСТОВ:")
            print("   • GPT-5-mini - оптимальный баланс качества и цены")
            print("   • GPT-5-nano - для простых задач (фильтрация, кластеризация)")
            print("   • GPT-5 - для сложных творческих задач")
            
            print("\n💰 ЭКОНОМИЯ:")
            print("   • GPT-5-mini дешевле GPT-4o-mini на 30-50%")
            print("   • GPT-5-nano дешевле GPT-4o-mini на 60-70%")
            print("   • Качество сопоставимо или лучше")
        else:
            print("⚠️  GPT-5 модели недоступны, используйте GPT-4:")
            print("   • GPT-4o-mini - для статей и постов")
            print("   • GPT-4o - для сложных задач")
        
        # Проверяем конкретные модели
        print("\n🔍 ДЕТАЛЬНАЯ ПРОВЕРКА КЛЮЧЕВЫХ МОДЕЛЕЙ:")
        print("=" * 60)
        
        key_models = ['gpt-5-mini', 'gpt-5-nano', 'gpt-5', 'gpt-4o-mini', 'gpt-4o']
        
        for model_name in key_models:
            found = [m for m in gpt_models if model_name in m['id'].lower()]
            if found:
                print(f"✅ {model_name.upper()}: ДОСТУПНА")
                for model in found:
                    print(f"   ID: {model['id']}")
                    print(f"   Дата: {model['created']}")
            else:
                print(f"❌ {model_name.upper()}: НЕ ДОСТУПНА")
        
        # Тестируем доступность
        print("\n🧪 ТЕСТИРОВАНИЕ ДОСТУПНОСТИ МОДЕЛЕЙ:")
        print("=" * 60)
        
        test_models = []
        if gpt5_models:
            test_models.extend([m['id'] for m in gpt5_models[:2]])
        if gpt4_models:
            test_models.extend([m['id'] for m in gpt4_models[:2]])
        
        for model_id in test_models:
            try:
                print(f"🔍 Тестирую {model_id}...")
                # Простой тест - создаем короткий запрос
                response = client.chat.completions.create(
                    model=model_id,
                    messages=[{"role": "user", "content": "Привет! Как дела?"}],
                    max_tokens=10
                )
                print(f"   ✅ {model_id} работает")
                print(f"   Ответ: {response.choices[0].message.content}")
            except Exception as e:
                print(f"   ❌ {model_id} ошибка: {str(e)[:100]}...")
            print()
        
    except Exception as e:
        print(f"❌ Ошибка при проверке моделей: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_openai_models()

