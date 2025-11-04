#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from content_generator import generate_article_url
from pathlib import Path

def debug_generate_article_url(article, website_dir="spain-news-portal"):
    """Упрощенная версия generate_article_url для отладки"""
    print("🔍 ОТЛАДКА generate_article_url:")
    
    category = article.get('category', 'news').lower()
    collection = 'news'  # Упрощаем
    title = article.get('title', '')
    slug = article.get('slug', '')
    
    print(f"  📂 Категория: {category}")
    print(f"  📂 Коллекция: {collection}")
    print(f"  📰 Заголовок: {title}")
    print(f"  🔗 Slug: {slug}")
    
    # Проверяем точный файл
    file_path = Path(website_dir) / "src" / "content" / collection / f"{slug}.md"
    print(f"  📁 Точный путь: {file_path}")
    print(f"  📁 Файл существует: {file_path.exists()}")
    
    if file_path.exists():
        print(f"  ✅ Возвращаем точную ссылку")
        return f"https://spain-que-pasa.com/{collection}/{slug}/"
    
    # Ищем файл по slug в имени
    collection_dir = Path(website_dir) / "src" / "content" / collection
    if collection_dir.exists():
        files = sorted(collection_dir.glob("*.md"), key=lambda x: x.stat().st_mtime, reverse=True)
        
        for file in files:
            print(f"  🔍 Проверяем файл: {file.name}")
            if slug in file.stem:
                file_slug = file.stem.strip()
                print(f"  ✅ Найден файл с slug: {file_slug}")
                result_url = f"https://spain-que-pasa.com/{collection}/{file_slug}/"
                print(f"  🔗 Результат: {result_url}")
                return result_url
        
        print(f"  ❌ Файл с slug '{slug}' не найден")
        if files:
            newest_file = files[0]
            file_slug = newest_file.stem.strip()
            print(f"  📁 Используем самый новый файл: {file_slug}")
            result_url = f"https://spain-que-pasa.com/{collection}/{file_slug}/"
            print(f"  🔗 Результат: {result_url}")
            return result_url
    
    # Fallback
    print(f"  ⚠️ Используем fallback")
    result_url = f"https://spain-que-pasa.com/{collection}/{slug}/"
    print(f"  🔗 Результат: {result_url}")
    return result_url

def debug_url_generation():
    print("🔍 ОТЛАДКА ГЕНЕРАЦИИ ССЫЛОК")
    print("=" * 50)
    
    # Тестовая статья с данными из последнего файла
    test_article = {
        'title': 'Ситуация с занятостью в Испании: что происходит?',
        'category': 'news',
        'slug': 'situatsiya-s-zanyatostyu-v-ispanii'
    }
    
    print(f"📰 Заголовок: {test_article['title']}")
    print(f"📂 Категория: {test_article['category']}")
    print(f"🔗 Slug: '{test_article['slug']}'")
    print(f"🔗 Slug (repr): {repr(test_article['slug'])}")
    print(f"🔗 Slug.strip(): '{test_article['slug'].strip()}'")
    print(f"🔗 Slug.strip() (repr): {repr(test_article['slug'].strip())}")
    
    # Проверяем, существует ли файл
    website_dir = "spain-news-portal"
    collection = "news"
    slug = test_article['slug']
    file_path = Path(website_dir) / "src" / "content" / collection / f"{slug}.md"
    
    print(f"📁 Путь к файлу: {file_path}")
    print(f"📁 Файл существует: {file_path.exists()}")
    
    # Проверяем директорию
    collection_dir = Path(website_dir) / "src" / "content" / collection
    print(f"📁 Директория существует: {collection_dir.exists()}")
    
    if collection_dir.exists():
        files = list(collection_dir.glob("*.md"))
        print(f"📁 Всего файлов в директории: {len(files)}")
        
        # Сортируем по времени создания
        files_sorted = sorted(files, key=lambda x: x.stat().st_mtime, reverse=True)
        print(f"📁 Самый новый файл: {files_sorted[0].name}")
        
        # Ищем файл с нашим slug
        target_file = None
        for file in files_sorted:
            if slug in file.stem:
                target_file = file
                break
        
        if target_file:
            print(f"✅ Найден файл: {target_file.name}")
            print(f"📁 file.stem: '{target_file.stem}'")
            print(f"📁 file.stem (repr): {repr(target_file.stem)}")
            print(f"📁 file.stem.strip(): '{target_file.stem.strip()}'")
            print(f"📁 file.stem.strip() (repr): {repr(target_file.stem.strip())}")
            print(f"📁 file.name: {target_file.name}")
        else:
            print(f"❌ Файл с slug '{slug}' не найден")
            
            # Показываем первые несколько файлов
            print("📁 Первые 5 файлов:")
            for i, file in enumerate(files_sorted[:5]):
                print(f"  {i+1}. {file.name}")
    
    # Тестируем нашу отладочную функцию
    print("\n🧪 ТЕСТИРОВАНИЕ debug_generate_article_url:")
    url = debug_generate_article_url(test_article)
    print(f"🔗 Сгенерированная ссылка: {url}")
    print(f"🔗 Длина ссылки: {len(url)}")
    print(f"🔗 Количество слешей: {url.count('/')}")
    
    if '//' in url and url.count('/') > 4:
        print("❌ ОШИБКА: Двойной слеш в ссылке!")
        # Показываем, где именно двойной слеш
        for i, char in enumerate(url):
            if char == '/' and i > 0 and url[i-1] == '/':
                print(f"❌ Двойной слеш на позиции {i-1}-{i}: '{url[i-1:i+1]}'")
    elif 'spain-que-pasa.com' in url and slug in url:
        print("✅ Ссылка сгенерирована правильно!")
    else:
        print("⚠️ Ссылка может быть некорректной")
    
    # Тестируем оригинальную функцию
    print("\n🧪 ТЕСТИРОВАНИЕ оригинальной generate_article_url:")
    url2 = generate_article_url(test_article)
    print(f"🔗 Сгенерированная ссылка: {url2}")
    print(f"🔗 Длина ссылки: {len(url2)}")
    print(f"🔗 Количество слешей: {url2.count('/')}")

if __name__ == "__main__":
    debug_url_generation() 