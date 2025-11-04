#!/usr/bin/env python3
"""
Финальный тест улучшенных промптов
Проверяет все новые требования и показывает примеры работы
"""

import os
import sys
import json
from datetime import datetime
from typing import Dict, Any, List

# Добавляем путь к родительской директории для импорта
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser

def test_simple_article():
    """Тестирует промпт для статей на простом примере"""
    print("🧪 ТЕСТ ПРОМПТА ДЛЯ СТАТЕЙ - ПРОСТОЙ ПРИМЕР")
    print("=" * 60)
    
    parser = RSSParser()
    
    # Простая статья с понятными терминами
    test_article = {
        "title": "New minimum wage increase in Spain",
        "content": """
        The Spanish government has announced an increase in the minimum wage (SMI - Salario Mínimo Interprofesional) from €1,080 to €1,134 per month, effective from January 1, 2025. This represents a 5% increase and will benefit approximately 2.5 million workers across the country.

        The decision was made after negotiations between the government, led by Prime Minister Pedro Sánchez, and the main trade unions UGT and CCOO. The increase aims to improve the purchasing power of low-income workers and reduce wage inequality.

        Business organizations, particularly CEOE (Confederación Española de Organizaciones Empresariales), have expressed concerns about the impact on small businesses and employment levels. However, the government maintains that the increase is necessary to ensure a decent standard of living for all workers.

        The new minimum wage will apply to all workers regardless of their nationality, including foreign workers and migrants. This is particularly important for the migrant community in Spain, as many work in sectors that typically pay minimum wage.
        """
    }
    
    print(f"📝 Исходная статья:")
    print(f"Заголовок: {test_article['title']}")
    print(f"Контент: {test_article['content'][:200]}...")
    print()
    
    # Обрабатываем статью
    print("🔄 Обрабатываем статью...")
    translated = parser.process_article(test_article)
    
    if translated:
        print("✅ Статья успешно обработана!")
        print()
        
        # Показываем полный результат
        print("📄 ПОЛНЫЙ РЕЗУЛЬТАТ:")
        print("=" * 60)
        print(f"Заголовок: {translated.get('title', 'N/A')}")
        print(f"Описание: {translated.get('description', 'N/A')}")
        print(f"Теги: {translated.get('tags', [])}")
        print()
        print("СОДЕРЖАНИЕ:")
        print("-" * 40)
        print(translated.get('content', 'N/A'))
        
        # Анализ
        print()
        print("📊 АНАЛИЗ:")
        print("-" * 40)
        content = translated.get('content', '').lower()
        
        # Проверяем объяснения терминов
        terms_to_explain = ['smi', 'salario mínimo interprofesional', 'pedro sánchez', 'ugt', 'ccoo', 'ceoe']
        explained_count = 0
        
        for term in terms_to_explain:
            if term in content:
                # Ищем объяснения
                term_index = content.find(term)
                context_start = max(0, term_index - 100)
                context_end = min(len(content), term_index + len(term) + 100)
                context = content[context_start:context_end]
                
                explanation_indicators = [
                    'это', 'означает', 'представляет', 'является', 'расшифровывается',
                    'минимальная', 'зарплата', 'профсоюз', 'организация', 'премьер'
                ]
                
                has_explanation = any(indicator in context for indicator in explanation_indicators)
                if has_explanation:
                    explained_count += 1
                    print(f"✅ {term} - объяснен")
                else:
                    print(f"❌ {term} - не объяснен")
        
        print(f"\n📚 Объяснено терминов: {explained_count}/{len(terms_to_explain)}")
        
        # Проверяем стиль
        conversational_phrases = ['кстати', 'оказывается', 'интересно', 'представьте', 'знаете ли']
        found_phrases = [phrase for phrase in conversational_phrases if phrase in content]
        print(f"💬 Разговорные фразы: {len(found_phrases)}")
        
        questions_count = content.count('?') + content.count('?')
        print(f"❓ Вопросы: {questions_count}")
        
        has_subheadings = '##' in translated.get('content', '')
        print(f"📋 Подзаголовки: {'✅' if has_subheadings else '❌'}")
        
    else:
        print("❌ Ошибка при обработке статьи")

def test_simple_telegram():
    """Тестирует промпт для Telegram-постов на простом примере"""
    print("\n" + "=" * 60)
    print("🧪 ТЕСТ ПРОМПТА ДЛЯ TELEGRAM-ПОСТОВ - ПРОСТОЙ ПРИМЕР")
    print("=" * 60)
    
    parser = RSSParser()
    
    # Простая статья для Telegram
    test_article = {
        "title": "Повышение минимальной зарплаты в Испании",
        "description": "Правительство Испании объявило о повышении минимальной зарплаты с 1 января 2025 года",
        "content": """
        Правительство Испании объявило о повышении минимальной зарплаты (SMI - Salario Mínimo Interprofesional) с 1080 до 1134 евро в месяц с 1 января 2025 года. Это увеличение на 5% затронет около 2.5 миллионов работников по всей стране.

        Решение было принято после переговоров между правительством во главе с премьер-министром Педро Санчесом и основными профсоюзами UGT и CCOO. Повышение направлено на улучшение покупательной способности работников с низким доходом и сокращение неравенства в оплате труда.

        Бизнес-организации, особенно CEOE (Испанская конфедерация бизнес-организаций), выразили обеспокоенность влиянием на малый бизнес и уровень занятости. Однако правительство утверждает, что повышение необходимо для обеспечения достойного уровня жизни всех работников.

        Новая минимальная зарплата будет применяться ко всем работникам независимо от их национальности, включая иностранных работников и мигрантов. Это особенно важно для мигрантского сообщества в Испании, поскольку многие работают в секторах, которые обычно платят минимальную зарплату.
        """,
        "tags": ["зарплата", "работа", "Испания", "2025"],
        "slug": "aumento-salario-minimo-espana-2025"
    }
    
    print(f"📝 Исходная статья:")
    print(f"Заголовок: {test_article['title']}")
    print(f"Описание: {test_article['description']}")
    print()
    
    # Генерируем Telegram-пост
    print("🔄 Генерируем Telegram-пост...")
    telegram_post = parser.generate_telegram_post(test_article)
    
    if telegram_post:
        print("✅ Telegram-пост успешно сгенерирован!")
        print()
        
        # Показываем полный результат
        print("📱 ПОЛНЫЙ TELEGRAM-ПОСТ:")
        print("=" * 60)
        print(telegram_post)
        
        # Анализ
        print()
        print("📊 АНАЛИЗ:")
        print("-" * 40)
        
        post_length = len(telegram_post)
        print(f"📏 Длина: {post_length} символов")
        print(f"📏 Соответствие лимиту: {'✅' if post_length <= 1000 else '❌'}")
        
        post_lower = telegram_post.lower()
        
        # Проверяем объяснения терминов
        terms_to_explain = ['smi', 'salario mínimo interprofesional', 'pedro sánchez', 'ugt', 'ccoo', 'ceoe']
        explained_count = 0
        
        for term in terms_to_explain:
            if term in post_lower:
                term_index = post_lower.find(term)
                context_start = max(0, term_index - 50)
                context_end = min(len(post_lower), term_index + len(term) + 50)
                context = post_lower[context_start:context_end]
                
                explanation_indicators = [
                    'это', 'означает', 'представляет', 'является', 'расшифровывается',
                    'минимальная', 'зарплата', 'профсоюз', 'организация', 'премьер'
                ]
                
                has_explanation = any(indicator in context for indicator in explanation_indicators)
                if has_explanation:
                    explained_count += 1
                    print(f"✅ {term} - объяснен")
                else:
                    print(f"❌ {term} - не объяснен")
        
        print(f"\n📚 Объяснено терминов: {explained_count}/{len(terms_to_explain)}")
        
        # Проверяем стиль
        conversational_phrases = ['кстати', 'оказывается', 'интересно', 'представьте', 'знаете ли']
        found_phrases = [phrase for phrase in conversational_phrases if phrase in post_lower]
        print(f"💬 Разговорные фразы: {len(found_phrases)}")
        
        questions_count = post_lower.count('?') + post_lower.count('?')
        print(f"❓ Вопросы: {questions_count}")
        
        emoji_count = sum(1 for char in telegram_post if ord(char) > 127 and char in '🧲🧾🔗💬📝📊🎯✅❌🔄📚🎨💬❓📏📋📄')
        print(f"😊 Emoji: {emoji_count}")
        
        has_link = 'https://example.com/news/' in telegram_post
        print(f"🔗 Ссылка: {'✅' if has_link else '❌'}")
        
        discussion_indicators = [
            'что думаете', 'как считаете', 'ваше мнение', 'обсудим',
            'комментарии', 'пишите', 'делитесь', 'расскажите'
        ]
        
        has_discussion = any(indicator in post_lower for indicator in discussion_indicators)
        print(f"💬 Призыв к обсуждению: {'✅' if has_discussion else '❌'}")
        
    else:
        print("❌ Ошибка при генерации Telegram-поста")

def main():
    """Основная функция тестирования"""
    print("🚀 ФИНАЛЬНЫЙ ТЕСТ УЛУЧШЕННЫХ ПРОМПТОВ")
    print("=" * 60)
    print("Тестируем все улучшения на простых примерах")
    print("=" * 60)
    
    try:
        # Тестируем промпт для статей
        test_simple_article()
        
        # Тестируем промпт для Telegram-постов
        test_simple_telegram()
        
        print("\n" + "=" * 60)
        print("✅ ФИНАЛЬНОЕ ТЕСТИРОВАНИЕ ЗАВЕРШЕНО")
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ Ошибка во время тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main() 