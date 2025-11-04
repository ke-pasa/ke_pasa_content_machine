#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скрипт для диагностики проблемы с превышением лимита токенов OpenAI
Показывает размер промптов и потенциальные проблемы
"""

import json
from workers.tools.firebase_client import get_firebase_client

def debug_token_limit():
    """Диагностирует проблему с токенами"""
    
    print("🔍 ДИАГНОСТИКА ПРОБЛЕМЫ С ТОКЕНАМИ OPENAI")
    print("=" * 60)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Ищем статьи с очень длинным контентом
        print("📰 Поиск статей с очень длинным контентом...")
        
        # Получаем все статьи через коллекцию
        articles_ref = firebase_client.db.collection('articles')
        articles_docs = list(articles_ref.limit(100).stream())
        
        if not articles_docs:
            print("❌ Нет статей в базе данных")
            return
        
        print(f"📊 Найдено статей: {len(articles_docs)}")
        
        # Анализируем размер контента
        content_lengths = []
        problematic_articles = []
        
        for doc in articles_docs:
            article = doc.to_dict()
            article['id'] = doc.id
            
            content = article.get('content', '')
            summary = article.get('summary', '')
            title = article.get('title', '')
            
            content_length = len(content)
            summary_length = len(summary)
            
            content_lengths.append(content_length)
            
            # Находим проблемные статьи
            if content_length > 300000:  # Более 300,000 символов
                problematic_articles.append({
                    'id': article.get('id', 'Unknown'),
                    'title': title[:100] + '...' if len(title) > 100 else title,
                    'content_length': content_length,
                    'summary_length': summary_length,
                    'estimated_tokens': content_length * 0.25
                })
        
        # Статистика
        if content_lengths:
            avg_length = sum(content_lengths) / len(content_lengths)
            max_length = max(content_lengths)
            min_length = min(content_lengths)
            
            print(f"\n📊 СТАТИСТИКА РАЗМЕРА КОНТЕНТА:")
            print(f"   Средний размер: {avg_length:,.0f} символов (~{avg_length * 0.25:.0f} токенов)")
            print(f"   Минимальный: {min_length:,.0f} символов (~{min_length * 0.25:.0f} токенов)")
            print(f"   Максимальный: {max_length:,.0f} символов (~{max_length * 0.25:.0f} токенов)")
        
        # Проблемные статьи
        if problematic_articles:
            print(f"\n🚨 ПРОБЛЕМНЫЕ СТАТЬИ (слишком длинные):")
            for article in problematic_articles:
                print(f"   ID: {article['id']}")
                print(f"   Заголовок: {article['title']}")
                print(f"   Размер content: {article['content_length']:,} символов")
                print(f"   Размер summary: {article['summary_length']:,} символов")
                print(f"   Оценка токенов: ~{article['estimated_tokens']:,.0f}")
                print(f"   Статус: {'❌ ПРЕВЫШЕНИЕ ЛИМИТА' if article['estimated_tokens'] > 128000 else '⚠️ БЛИЗКО К ЛИМИТУ'}")
                print()
        else:
            print("\n✅ Проблемных статей не найдено")
        
        # Анализ промпта
        print("🔍 АНАЛИЗ ПРОМПТА ДЛЯ ГЕНЕРАЦИИ СТАТЕЙ:")
        
        # Пример системного промпта
        system_prompt = """Ты опытный журналист, который пишет простым и понятным языком для русскоязычных мигрантов в Испании. Твои тексты звучат естественно, как будто их написал человек, а не ИИ. Отвечай только в формате Markdown с YAML frontmatter."""
        
        # Пример пользовательского промпта (упрощенный)
        user_prompt_template = """Создай статью на основе:

Тема: {topic_summary}
Контекст: {combined_context}

[Остальная часть промпта...]"""
        
        system_tokens = len(system_prompt) * 0.25
        user_prompt_base_tokens = len(user_prompt_template) * 0.25
        
        print(f"   Системный промпт: ~{system_tokens:.0f} токенов")
        print(f"   Базовый пользовательский промпт: ~{user_prompt_base_tokens:.0f} токенов")
        
        # Расчет для разных размеров контента
        print(f"\n📊 РАСЧЕТ ТОКЕНОВ ДЛЯ РАЗНЫХ РАЗМЕРОВ:")
        test_sizes = [100000, 200000, 300000, 400000, 500000, 600000]
        
        for size in test_sizes:
            total_tokens = system_tokens + user_prompt_base_tokens + (size * 0.25)
            status = "❌ ПРЕВЫШЕНИЕ" if total_tokens > 128000 else "✅ В ПРЕДЕЛАХ"
            print(f"   {size:,} символов → ~{total_tokens:,.0f} токенов {status}")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        print(f"   1. Ограничить combined_context до 400,000 символов (~100,000 токенов)")
        print(f"   2. Добавить проверку размера перед отправкой в OpenAI")
        print(f"   3. Использовать summary вместо content для очень длинных статей")
        print(f"   4. Обрезать контент с сохранением начала")
        
        # Проверяем текущие настройки
        print(f"\n🔧 ТЕКУЩИЕ НАСТРОЙКИ:")
        print(f"   max_completion_tokens: 3000 (для Markdown)")
        print(f"   max_completion_tokens: 5000 (для JSON)")
        print(f"   Модель: gpt-4o-mini (лимит: 128,000 токенов)")
        
    except Exception as e:
        print(f"❌ Ошибка при диагностике: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_token_limit()
