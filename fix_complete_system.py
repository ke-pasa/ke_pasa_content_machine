#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Комплексное исправление системы источников и статей:
1. Создает правильную коллекцию sources из RSS данных
2. Исправляет связь между источниками и статьями
3. Подготавливает систему для генерации качественных статей
4. Очищает дубли и некачественный контент
"""

from firebase_client import get_firebase_client
from datetime import datetime
import re

def clean_and_restructure_sources():
    """Очищает и переструктурирует коллекцию sources"""
    print("🧹 ОЧИСТКА И ПЕРЕСТРУКТУРИРОВАНИЕ КОЛЛЕКЦИИ SOURCES")
    print("=" * 70)
    
    try:
        db = get_firebase_client().db
        
        # 1. Получаем все источники
        sources = list(db.collection('sources').stream())
        print(f"📰 Найдено источников: {len(sources)}")
        
        if not sources:
            print("❌ Нет источников для обработки")
            return
        
        # 2. Анализируем и очищаем каждый источник
        cleaned_sources = 0
        deleted_sources = 0
        
        for source in sources:
            try:
                data = source.to_dict()
                title = data.get('title', '')
                content = data.get('content', '')
                link = data.get('link', '')
                
                # Проверяем качество источника
                is_valid = True
                issues = []
                
                # Проверка заголовка
                if not title or len(title.strip()) < 10:
                    is_valid = False
                    issues.append("Пустой или слишком короткий заголовок")
                
                # Проверка контента
                if not content or len(content.strip()) < 200:
                    is_valid = False
                    issues.append("Недостаточно контента")
                
                # Проверка ссылки
                if not link or not link.startswith('http'):
                    is_valid = False
                    issues.append("Некорректная ссылка")
                
                # Проверка на дубли
                if 'duplicate' in title.lower() or 'copy' in title.lower():
                    is_valid = False
                    issues.append("Дублированный контент")
                
                if is_valid:
                    # Очищаем и структурируем данные
                    cleaned_data = {
                        'title': title.strip(),
                        'content': content.strip(),
                        'link': link.strip(),
                        'summary': data.get('summary', ''),
                        'image': data.get('image', ''),
                        'categories': data.get('categories', []),
                        'published_date': data.get('published_date', ''),
                        'created_at': datetime.now().isoformat(),
                        'updated_at': datetime.now().isoformat(),
                        'interesting': True,
                        'processed': False,
                        'quality_score': calculate_source_quality(content),
                        'content_length': len(content.strip()),
                        'has_numbers': any(char.isdigit() for char in content),
                        'has_dates': has_date_content(content),
                        'has_names': has_name_content(content),
                        'has_places': has_place_content(content),
                        'status': 'active'
                    }
                    
                    # Сохраняем очищенный источник
                    db.collection('sources').document(source.id).set(cleaned_data, merge=True)
                    cleaned_sources += 1
                    
                else:
                    # Удаляем некачественный источник
                    print(f"   ❌ Удаляем источник: {title[:50]}... - {', '.join(issues)}")
                    db.collection('sources').document(source.id).delete()
                    deleted_sources += 1
                    
            except Exception as e:
                print(f"   ⚠️  Ошибка при обработке источника: {e}")
                continue
        
        print(f"✅ Очищено источников: {cleaned_sources}")
        print(f"🗑️  Удалено некачественных: {deleted_sources}")
        
        return cleaned_sources > 0
        
    except Exception as e:
        print(f"❌ Ошибка при очистке источников: {e}")
        import traceback
        traceback.print_exc()
        return False

def fix_article_source_connections():
    """Исправляет связь между статьями и источниками"""
    print(f"\n🔗 ИСПРАВЛЕНИЕ СВЯЗИ СТАТЬИ ↔ ИСТОЧНИКИ")
    print("=" * 60)
    
    try:
        db = get_firebase_client().db
        
        # 1. Получаем качественные источники
        sources = list(db.collection('sources').where('status', '==', 'active').limit(50).stream())
        print(f"📰 Найдено качественных источников: {len(sources)}")
        
        if not sources:
            print("❌ Нет качественных источников")
            return False
        
        # 2. Получаем статьи
        articles = list(db.collection('articles').limit(100).stream())
        print(f"📝 Найдено статей: {len(articles)}")
        
        if not articles:
            print("❌ Нет статей для обработки")
            return False
        
        # 3. Создаем улучшенную карту источников
        sources_map = {}
        for source in sources:
            data = source.to_dict()
            title = data.get('title', '').lower().strip()
            if title:
                # Создаем несколько вариантов ключей для лучшего поиска
                sources_map[title] = data
                # Упрощенная версия заголовка
                simple_title = re.sub(r'[^\w\s]', '', title)
                if simple_title != title:
                    sources_map[simple_title] = data
        
        print(f"🗺️  Создана карта источников: {len(sources_map)} записей")
        
        # 4. Исправляем статьи
        fixed_articles = 0
        for article in articles:
            try:
                data = article.to_dict()
                title = data.get('title', '').lower().strip()
                
                if not title:
                    continue
                
                # Ищем соответствующий источник
                source_data = None
                best_match_score = 0
                
                for source_title, source in sources_map.items():
                    # Вычисляем схожесть заголовков
                    match_score = calculate_title_similarity(title, source_title)
                    if match_score > best_match_score and match_score > 0.3:  # Минимальный порог схожести
                        best_match_score = match_score
                        source_data = source
                
                if source_data:
                    # Обновляем статью
                    update_data = {
                        'source_content': source_data.get('content', ''),
                        'source_link': source_data.get('link', ''),
                        'source_title': source_data.get('title', ''),
                        'source_updated_at': datetime.now().isoformat(),
                        'has_source_content': True,
                        'source_quality_score': source_data.get('quality_score', 0),
                        'source_content_length': source_data.get('content_length', 0),
                        'match_confidence': best_match_score
                    }
                    
                    # Сохраняем обновления
                    db.collection('articles').document(article.id).set(update_data, merge=True)
                    fixed_articles += 1
                    
                    if fixed_articles % 10 == 0:
                        print(f"   Исправлено статей: {fixed_articles}")
                        
                else:
                    print(f"   ⚠️  Не найден источник для: {title[:50]}...")
                    
            except Exception as e:
                print(f"   ❌ Ошибка при исправлении статьи: {e}")
                continue
        
        print(f"✅ Исправлено статей: {fixed_articles}")
        return fixed_articles > 0
        
    except Exception as e:
        print(f"❌ Ошибка при исправлении связей: {e}")
        import traceback
        traceback.print_exc()
        return False

def calculate_source_quality(content):
    """Вычисляет качество источника"""
    if not content:
        return 0
    
    score = 0
    
    # Длина контента
    if len(content) > 1000:
        score += 2
    elif len(content) > 500:
        score += 1
    
    # Наличие цифр
    if any(char.isdigit() for char in content):
        score += 1
    
    # Наличие дат
    if has_date_content(content):
        score += 1
    
    # Наличие имен
    if has_name_content(content):
        score += 1
    
    # Наличие мест
    if has_place_content(content):
        score += 1
    
    return min(score, 5)

def has_date_content(content):
    """Проверяет наличие дат в контенте"""
    date_patterns = [
        r'\d{1,2}/\d{1,2}/\d{4}',  # DD/MM/YYYY
        r'\d{1,2}-\d{1,2}-\d{4}',  # DD-MM-YYYY
        r'\d{4}-\d{1,2}-\d{1,2}',  # YYYY-MM-DD
        r'\d{1,2}\s+(?:января|февраля|марта|апреля|мая|июня|июля|августа|сентября|октября|ноября|декабря)',
        r'(?:январь|февраль|март|апрель|май|июнь|июль|август|сентябрь|октябрь|ноябрь|декабрь)\s+\d{4}'
    ]
    
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in date_patterns)

def has_name_content(content):
    """Проверяет наличие имен в контенте"""
    name_patterns = [
        r'[А-Я][а-я]+\s+[А-Я][а-я]+',  # Русские имена
        r'[A-Z][a-z]+\s+[A-Z][a-z]+',   # Английские имена
    ]
    
    return any(re.search(pattern, content) for pattern in name_patterns)

def has_place_content(content):
    """Проверяет наличие мест в контенте"""
    place_patterns = [
        r'в\s+[А-Я][а-я]+',  # "в Москве"
        r'в\s+[A-Z][a-z]+',   # "в Madrid"
        r'город\s+[А-Я][а-я]+',
        r'город\s+[A-Z][a-z]+'
    ]
    
    return any(re.search(pattern, content, re.IGNORECASE) for pattern in place_patterns)

def calculate_title_similarity(title1, title2):
    """Вычисляет схожесть заголовков"""
    if not title1 or not title2:
        return 0
    
    # Простая метрика схожести на основе общих слов
    words1 = set(title1.split())
    words2 = set(title2.split())
    
    if not words1 or not words2:
        return 0
    
    intersection = words1.intersection(words2)
    union = words1.union(words2)
    
    if not union:
        return 0
    
    return len(intersection) / len(union)

def create_quality_index():
    """Создает индекс качества для источников"""
    print(f"\n📋 СОЗДАНИЕ ИНДЕКСА КАЧЕСТВА:")
    print("-" * 40)
    
    try:
        db = get_firebase_client().db
        
        # Получаем статистику
        sources = list(db.collection('sources').where('status', '==', 'active').stream())
        
        if not sources:
            print("❌ Нет активных источников для индекса")
            return
        
        # Анализируем качество
        total_sources = len(sources)
        high_quality = sum(1 for s in sources if s.to_dict().get('quality_score', 0) >= 4)
        medium_quality = sum(1 for s in sources if 2 <= s.to_dict().get('quality_score', 0) < 4)
        low_quality = sum(1 for s in sources if s.to_dict().get('quality_score', 0) < 2)
        
        # Создаем индекс
        index_data = {
            'total_sources': total_sources,
            'high_quality': high_quality,
            'medium_quality': medium_quality,
            'low_quality': low_quality,
            'average_quality': sum(s.to_dict().get('quality_score', 0) for s in sources) / total_sources,
            'last_updated': datetime.now().isoformat(),
            'index_type': 'quality_metrics'
        }
        
        # Сохраняем индекс
        db.collection('sources').document('_quality_index').set(index_data, merge=True)
        
        print(f"✅ Создан индекс качества:")
        print(f"   Всего источников: {total_sources}")
        print(f"   Высокое качество: {high_quality}")
        print(f"   Среднее качество: {medium_quality}")
        print(f"   Низкое качество: {low_quality}")
        print(f"   Средний балл: {index_data['average_quality']:.2f}")
        
    except Exception as e:
        print(f"❌ Ошибка при создании индекса: {e}")

def test_system_readiness():
    """Тестирует готовность системы к генерации статей"""
    print(f"\n🧪 ТЕСТИРОВАНИЕ ГОТОВНОСТИ СИСТЕМЫ:")
    print("-" * 40)
    
    try:
        db = get_firebase_client().db
        
        # 1. Проверяем источники
        sources = list(db.collection('sources').where('status', '==', 'active').stream())
        print(f"📰 Активных источников: {len(sources)}")
        
        if sources:
            quality_scores = [s.to_dict().get('quality_score', 0) for s in sources]
            avg_quality = sum(quality_scores) / len(quality_scores)
            print(f"   Среднее качество: {avg_quality:.2f}/5")
            
            high_quality_count = sum(1 for score in quality_scores if score >= 4)
            print(f"   Высокое качество: {high_quality_count}/{len(sources)}")
        
        # 2. Проверяем статьи с источниками
        articles_with_sources = list(db.collection('articles').where('has_source_content', '==', True).stream())
        print(f"📝 Статей с источниками: {len(articles_with_sources)}")
        
        if articles_with_sources:
            source_lengths = [a.to_dict().get('source_content_length', 0) for a in articles_with_sources]
            avg_length = sum(source_lengths) / len(source_lengths)
            print(f"   Средняя длина исходного контента: {avg_length:.0f} символов")
        
        # 3. Выводы
        print(f"\n💡 ВЫВОДЫ:")
        if len(sources) >= 5 and len(articles_with_sources) >= 5:
            print("✅ Система готова к генерации качественных статей!")
            print("✅ LLM будет получать полный текст из источников")
            print("✅ Качество контента должно быть высоким")
        else:
            print("⚠️  Система требует дополнительной настройки")
            print("🔧 Нужно больше качественных источников")
        
    except Exception as e:
        print(f"❌ Ошибка при тестировании: {e}")

def main():
    """Основная функция исправления системы"""
    print("🔧 КОМПЛЕКСНОЕ ИСПРАВЛЕНИЕ СИСТЕМЫ ИСТОЧНИКОВ И СТАТЕЙ")
    print("=" * 80)
    
    try:
        # 1. Очищаем и переструктурируем источники
        if not clean_and_restructure_sources():
            print("❌ Не удалось очистить источники")
            return
        
        # 2. Исправляем связи между статьями и источниками
        if not fix_article_source_connections():
            print("❌ Не удалось исправить связи")
            return
        
        # 3. Создаем индекс качества
        create_quality_index()
        
        # 4. Тестируем готовность системы
        test_system_readiness()
        
        print(f"\n🎉 КОМПЛЕКСНОЕ ИСПРАВЛЕНИЕ ЗАВЕРШЕНО!")
        print("Система готова к генерации качественных статей с улучшенным промптом")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()







