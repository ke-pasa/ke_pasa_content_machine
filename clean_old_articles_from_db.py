#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Очистка базы данных от старых новостей из удаленных RSS лент
"""
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from workers.tools.firebase_client import get_firebase_client

def clean_old_articles_from_db():
    """Очищает базу данных от старых новостей"""
    print("🧹 ОЧИСТКА БАЗЫ ДАННЫХ ОТ СТАРЫХ НОВОСТЕЙ")
    print("=" * 60)
    
    load_dotenv()
    
    try:
        firebase_client = get_firebase_client()
        db = firebase_client.db
        
        # Получаем текущее время
        current_time = datetime.now()
        
        print("🔍 Анализирую базу данных...")
        
        # Анализируем коллекцию articles
        articles_ref = db.collection('articles')
        articles = list(articles_ref.stream())
        
        print(f"📊 Найдено статей в базе: {len(articles)}")
        
        # Анализируем даты и источники
        old_articles = []
        articles_by_source = {}
        total_content_length = 0
        
        for article in articles:
            data = article.to_dict() or {}
            article_id = article.id
            
            # Получаем дату публикации
            pub_date = None
            if data.get('published_date'):
                try:
                    if hasattr(data['published_date'], 'timestamp'):
                        pub_date = data['published_date']
                    else:
                        pub_date = datetime.fromisoformat(str(data['published_date']).replace('Z', '+00:00'))
                except:
                    pass
            
            # Получаем источник
            source_link = data.get('link', '')
            source_domain = extract_domain(source_link)
            
            if source_domain:
                if source_domain not in articles_by_source:
                    articles_by_source[source_domain] = []
                articles_by_source[source_domain].append({
                    'id': article_id,
                    'title': data.get('title', 'N/A'),
                    'pub_date': pub_date,
                    'source_link': source_link
                })
            
            # Проверяем возраст статьи
            if pub_date:
                if hasattr(pub_date, 'timestamp'):
                    days_old = (current_time - pub_date).days
                else:
                    days_old = (current_time - pub_date.replace(tzinfo=None)).days
                
                # Статья считается старой, если старше 90 дней
                if days_old > 90:
                    old_articles.append({
                        'id': article_id,
                        'title': data.get('title', 'N/A'),
                        'days_old': days_old,
                        'source_link': source_link,
                        'source_domain': source_domain
                    })
            
            # Считаем общую длину контента
            content = data.get('content', '') or data.get('summary', '')
            total_content_length += len(content)
        
        # Анализируем источники
        print(f"\n📊 АНАЛИЗ ПО ИСТОЧНИКАМ:")
        print("-" * 60)
        
        for domain, articles_list in articles_by_source.items():
            print(f"🌐 {domain}: {len(articles_list)} статей")
        
        # Показываем старые статьи
        print(f"\n📅 СТАРЫЕ СТАТЬИ (>90 дней):")
        print("-" * 60)
        
        if old_articles:
            old_articles.sort(key=lambda x: x['days_old'], reverse=True)
            for article in old_articles[:20]:  # Показываем первые 20
                print(f"📄 {article['title'][:60]}...")
                print(f"   ID: {article['id']}")
                print(f"   Возраст: {article['days_old']} дней")
                print(f"   Источник: {article['source_domain']}")
                print()
            
            if len(old_articles) > 20:
                print(f"... и еще {len(old_articles) - 20} старых статей")
        else:
            print("✅ Старых статей не найдено")
        
        # Статистика по контенту
        print(f"\n📊 СТАТИСТИКА КОНТЕНТА:")
        print("-" * 60)
        print(f"📝 Общая длина контента: {total_content_length:,} символов")
        print(f"📝 Средняя длина статьи: {total_content_length // len(articles) if articles else 0:,} символов")
        
        # Предлагаем очистку
        if old_articles:
            print(f"\n🗑️  РЕКОМЕНДАЦИИ ПО ОЧИСТКЕ:")
            print("-" * 60)
            print(f"❌ Старых статей (>90 дней): {len(old_articles)}")
            
            # Группируем по источникам
            old_by_source = {}
            for article in old_articles:
                domain = article['source_domain']
                if domain not in old_by_source:
                    old_by_source[domain] = []
                old_by_source[domain].append(article)
            
            print(f"\n📋 СТАРЫЕ СТАТЬИ ПО ИСТОЧНИКАМ:")
            for domain, articles_list in old_by_source.items():
                print(f"   🌐 {domain}: {len(articles_list)} статей")
            
            # Спрашиваем пользователя
            response = input(f"\n❓ Удалить {len(old_articles)} старых статей? (y/N): ").strip().lower()
            
            if response == 'y':
                print(f"\n🗑️  УДАЛЯЮ СТАРЫЕ СТАТЬИ...")
                
                deleted_count = 0
                for article in old_articles:
                    try:
                        articles_ref.document(article['id']).delete()
                        deleted_count += 1
                        print(f"   ✅ Удалена: {article['title'][:50]}...")
                    except Exception as e:
                        print(f"   ❌ Ошибка удаления {article['id']}: {e}")
                
                print(f"\n✅ Удалено {deleted_count} старых статей")
                
                # Обновляем статистику
                remaining_articles = list(articles_ref.stream())
                print(f"📊 Осталось статей в базе: {len(remaining_articles)}")
                
            else:
                print("❌ Очистка отменена пользователем")
        else:
            print("\n✅ Очистка не требуется - старых статей не найдено")
        
        # Создаем отчет
        create_cleanup_report(old_articles, articles_by_source, total_content_length)
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()

def extract_domain(url):
    """Извлекает домен из URL"""
    if not url:
        return None
    
    try:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.lower()
        
        # Убираем www. если есть
        if domain.startswith('www.'):
            domain = domain[4:]
        
        return domain
    except:
        return None

def create_cleanup_report(old_articles, articles_by_source, total_content_length):
    """Создает отчет об очистке"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    report_content = f"""# Отчет об анализе базы данных новостей

## 📊 Общая информация
**Дата анализа:** {timestamp}
**Всего статей:** {sum(len(articles) for articles in articles_by_source.values())}
**Общая длина контента:** {total_content_length:,} символов

## 🌐 Статьи по источникам
"""
    
    for domain, articles_list in articles_by_source.items():
        report_content += f"- **{domain}**: {len(articles_list)} статей\n"
    
    if old_articles:
        report_content += f"""
## 🗑️ Старые статьи (>90 дней)
**Всего старых статей:** {len(old_articles)}

### Группировка по источникам:
"""
        
        # Группируем по источникам
        old_by_source = {}
        for article in old_articles:
            domain = article['source_domain']
            if domain not in old_by_source:
                old_by_source[domain] = []
            old_by_source[domain].append(article)
        
        for domain, articles_list in old_by_source.items():
            report_content += f"- **{domain}**: {len(articles_list)} статей\n"
        
        report_content += f"""
### Детальный список старых статей:
"""
        
        for article in old_articles:
            report_content += f"- **{article['title']}** (ID: {article['id']}, возраст: {article['days_old']} дней, источник: {article['source_domain']})\n"
    
    else:
        report_content += """
## ✅ Старые статьи
Старых статей (>90 дней) не найдено.
"""
    
    # Сохраняем отчет
    filename = f"db_analysis_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"💾 Отчет сохранен в {filename}")

if __name__ == "__main__":
    clean_old_articles_from_db()







