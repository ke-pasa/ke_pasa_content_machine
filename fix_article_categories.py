#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Скрипт для исправления категорий в существующих статьях
Анализирует содержание и назначает правильные категории
"""

import os
import re
from pathlib import Path

def determine_category_from_content(title, content):
    """
    Определяет правильную категорию на основе содержания статьи
    """
    text = f"{title} {content}".lower()
    
    # Ключевые слова для каждой категории
    category_keywords = {
        'weather': ['погода', 'климат', 'aemet', 'жара', 'холод', 'дождь', 'шторм', 'температура', 'градус'],
        'migration': ['миграция', 'виза', 'паспорт', 'гражданство', 'residencia', 'nie', 'документы', 'иммиграция'],
        'policy': ['политика', 'правительство', 'закон', 'реформа', 'выборы', 'партии', 'законодательство', 'права'],
        'health': ['здоровье', 'медицина', 'больница', 'врач', 'лечение', 'эпидемии', 'вакцинация'],
        'crime': ['преступность', 'полиция', 'арест', 'суд', 'безопасность', 'нарушения', 'штраф', 'нелегальный'],
        'events': ['события', 'фестиваль', 'концерт', 'выставка', 'праздник', 'мероприятия', 'традиции'],
        'education': ['образование', 'школа', 'университет', 'студент', 'обучение', 'академия'],
        'transport': ['транспорт', 'метро', 'автобус', 'поезд', 'дорога', 'пробка', 'аэропорт'],
        'economy': ['экономика', 'банк', 'деньги', 'работа', 'бизнес', 'инфляция', 'зарплата', 'рынок труда', 'евро']
    }
    
    # Подсчитываем совпадения для каждой категории
    category_scores = {}
    for category, keywords in category_keywords.items():
        score = sum(1 for keyword in keywords if keyword in text)
        if score > 0:
            category_scores[category] = score
    
    # Возвращаем категорию с наивысшим баллом
    if category_scores:
        best_category = max(category_scores, key=category_scores.get)
        return best_category
    
    return 'general'

def fix_article_categories():
    """
    Исправляет категории во всех статьях в директории news
    """
    news_dir = Path("spain-news-portal/src/content/news")
    
    if not news_dir.exists():
        print("❌ Директория с новостями не найдена")
        return
    
    print("🔧 ИСПРАВЛЕНИЕ КАТЕГОРИЙ В СТАТЬЯХ")
    print("=" * 50)
    
    articles = list(news_dir.glob("*.md"))
    print(f"📁 Найдено статей: {len(articles)}")
    
    fixed_count = 0
    category_changes = {}
    
    for article_path in articles:
        print(f"\n📰 Обрабатываю: {article_path.name}")
        
        try:
            with open(article_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Извлекаем метаданные
            metadata_match = re.search(r'---\n(.*?)\n---', content, re.DOTALL)
            if not metadata_match:
                print(f"   ⚠️  Не найдены метаданные")
                continue
            
            metadata = metadata_match.group(1)
            
            # Ищем текущую категорию
            current_category_match = re.search(r'category:\s*["\']([^"\']+)["\']', metadata)
            if not current_category_match:
                print(f"   ⚠️  Категория не найдена в метаданных")
                continue
            
            current_category = current_category_match.group(1)
            
            # Извлекаем заголовок и контент для анализа
            title_match = re.search(r'title:\s*["\']([^"\']+)["\']', metadata)
            title = title_match.group(1) if title_match else ""
            
            # Убираем метаданные для анализа контента
            content_only = re.sub(r'---\n.*?\n---', '', content, flags=re.DOTALL).strip()
            
            # Определяем правильную категорию
            correct_category = determine_category_from_content(title, content_only)
            
            print(f"   📂 Текущая категория: {current_category}")
            print(f"   🎯 Правильная категория: {correct_category}")
            
            if current_category != correct_category:
                # Заменяем категорию в метаданных
                new_metadata = re.sub(
                    r'category:\s*["\'][^"\']+["\']',
                    f'category: "{correct_category}"',
                    metadata
                )
                
                # Обновляем весь контент
                new_content = content.replace(metadata, new_metadata)
                
                # Записываем обратно
                with open(article_path, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                
                print(f"   ✅ Категория исправлена: {current_category} → {correct_category}")
                fixed_count += 1
                
                if correct_category not in category_changes:
                    category_changes[correct_category] = 0
                category_changes[correct_category] += 1
            else:
                print(f"   ✅ Категория уже правильная")
                
        except Exception as e:
            print(f"   ❌ Ошибка обработки: {e}")
    
    # Итоговая статистика
    print(f"\n📊 ИТОГИ ИСПРАВЛЕНИЯ:")
    print(f"   Исправлено статей: {fixed_count}")
    
    if category_changes:
        print(f"   Распределение по категориям:")
        for category, count in sorted(category_changes.items()):
            print(f"      • {category}: {count}")
    
    print(f"\n🎯 РЕКОМЕНДАЦИИ:")
    print(f"   • Проверьте качество статей после исправления")
    print(f"   • Убедитесь, что LLM теперь правильно определяет категории")
    print(f"   • Рассмотрите возможность перегенерации статей с улучшенным промптом")

if __name__ == "__main__":
    fix_article_categories()







