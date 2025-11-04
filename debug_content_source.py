#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ДИАГНОСТИКА ИСТОЧНИКА КОНТЕНТА
Проверяет, откуда планировщик берет контент для публикации
"""

from jobs_scheduler_fixed import PublicationSchedulerFixed
from workers.tools.firebase_client import get_firebase_client

def debug_content_source():
    """Диагностирует источник контента"""
    
    print("🔍 ДИАГНОСТИКА ИСТОЧНИКА КОНТЕНТА")
    print("=" * 60)
    
    try:
        # Создаем планировщик
        scheduler = PublicationSchedulerFixed()
        
        print("✅ Планировщик создан успешно")
        
        # Получаем статьи для публикации
        print(f"\n📰 ПРОВЕРКА СТАТЕЙ ДЛЯ ПУБЛИКАЦИИ:")
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"   Доступных статей: {len(articles)}")
        
        if not articles:
            print(f"   ❌ Нет статей для публикации")
            return
        
        # Показываем детали первых 3 статей
        print(f"\n📋 ДЕТАЛИ СТАТЕЙ:")
        for i, article in enumerate(articles[:3]):
            print(f"\n   {i+1}. СТАТЬЯ:")
            print(f"      ID: {article.get('id', 'N/A')}")
            print(f"      Заголовок: {article.get('title', 'Без заголовка')[:80]}")
            print(f"      Язык: {article.get('language', 'N/A')}")
            print(f"      Источник: {article.get('source', 'N/A')}")
            print(f"      URL: {article.get('link', 'N/A')}")
            print(f"      Экспортирована на сайт: {article.get('exported_to_site', False)}")
            print(f"      Опубликована: {article.get('published', False)}")
            print(f"      Приоритет: {article.get('priority_score', 0)}")
            
            # Проверяем, есть ли сгенерированный контент
            if 'generated_content' in article:
                print(f"      ✅ Есть сгенерированный контент")
                content = article['generated_content']
                print(f"         Длина: {len(str(content))} символов")
                print(f"         Начало: {str(content)[:100]}...")
            else:
                print(f"      ❌ НЕТ сгенерированного контента")
            
            # Проверяем, есть ли summary
            if 'summary' in article:
                print(f"      ✅ Есть summary")
                summary = article['summary']
                print(f"         Длина: {len(str(summary))} символов")
                print(f"         Начало: {str(summary)[:100]}...")
            else:
                print(f"      ❌ НЕТ summary")
        
        # Проверяем общую статистику
        print(f"\n📊 СТАТИСТИКА ПО ИСТОЧНИКАМ:")
        
        sources = {}
        languages = {}
        has_generated = 0
        has_summary = 0
        
        for article in articles:
            source = article.get('source', 'Unknown')
            language = article.get('language', 'Unknown')
            
            sources[source] = sources.get(source, 0) + 1
            languages[language] = languages.get(language, 0) + 1
            
            if 'generated_content' in article:
                has_generated += 1
            if 'summary' in article:
                has_summary += 1
        
        print(f"   Источники:")
        for source, count in sorted(sources.items(), key=lambda x: x[1], reverse=True):
            print(f"      {source}: {count}")
        
        print(f"   Языки:")
        for lang, count in sorted(languages.items(), key=lambda x: x[1], reverse=True):
            print(f"      {lang}: {count}")
        
        print(f"   Сгенерированный контент: {has_generated}/{len(articles)}")
        print(f"   Summary: {has_summary}/{len(articles)}")
        
        # Проверяем, есть ли статьи с нашего сайта
        print(f"\n🌐 ПРОВЕРКА СТАТЕЙ С НАШЕГО САЙТА:")
        
        our_site_articles = []
        for article in articles:
            if article.get('exported_to_site', False):
                our_site_articles.append(article)
        
        print(f"   Экспортировано на сайт: {len(our_site_articles)}")
        
        if our_site_articles:
            print(f"   Примеры статей с сайта:")
            for i, article in enumerate(our_site_articles[:3]):
                title = article.get('title', 'Без заголовка')[:60]
                language = article.get('language', 'N/A')
                has_content = 'generated_content' in article
                print(f"     {i+1}. {title}")
                print(f"        Язык: {language}, Контент: {'✅' if has_content else '❌'}")
        else:
            print(f"   ❌ НЕТ статей, экспортированных на сайт!")
        
        # Итоговая оценка
        print(f"\n🎯 ИТОГОВАЯ ОЦЕНКА:")
        
        if has_generated > 0:
            print(f"   ✅ Есть сгенерированные статьи")
        else:
            print(f"   ❌ НЕТ сгенерированных статей")
        
        if has_summary > 0:
            print(f"   ✅ Есть summary для постов")
        else:
            print(f"   ❌ НЕТ summary для постов")
        
        if our_site_articles:
            print(f"   ✅ Есть статьи с нашего сайта")
        else:
            print(f"   ❌ НЕТ статей с нашего сайта")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        if not has_generated:
            print(f"   • Нужно запустить генерацию статей")
            print(f"   • Проверить процесс генерации контента")
        
        if not has_summary:
            print(f"   • Нужно создать summary для статей")
            print(f"   • Или использовать сгенерированный контент")
        
        if not our_site_articles:
            print(f"   • Нужно экспортировать статьи на сайт")
            print(f"   • Проверить процесс экспорта")
        
    except Exception as e:
        print(f"❌ Ошибка диагностики: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    debug_content_source()

