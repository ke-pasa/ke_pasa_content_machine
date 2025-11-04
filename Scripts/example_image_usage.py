#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования функциональности извлечения изображений из RSS-лент
Демонстрирует полный цикл: извлечение → обработка → отправка в Telegram
"""

import os
import sys
from rss_parser import RSSParser


def main():
    """Демонстрация функциональности извлечения изображений"""
    print("🖼️ Демонстрация извлечения изображений из RSS-лент")
    print("=" * 60)
    
    # Создаем парсер
    rss_parser = RSSParser()
    
    # Пример 1: Обработка RSS-ленты с изображениями
    print("\n1️⃣ Обработка RSS-ленты с изображениями")
    print("-" * 40)
    
    # Используем тестовую RSS-ленту
    test_feed_url = "http://feeds.bbci.co.uk/news/rss.xml"
    
    try:
        print(f"📡 Загружаю RSS-ленту: {test_feed_url}")
        feed_data = rss_parser.parse_feed(test_feed_url)
        
        if feed_data and feed_data.get('entries'):
            print(f"✅ Загружено {len(feed_data['entries'])} записей")
            
            # Обрабатываем первые 2 записи с изображениями
            processed_count = 0
            for entry in feed_data['entries']:
                if processed_count >= 2:
                    break
                
                # Извлекаем изображение
                img_url = rss_parser._get_image(entry)
                if img_url:
                    print(f"\n📰 Запись {processed_count + 1}: {entry.get('title', 'Без заголовка')[:50]}...")
                    print(f"   🖼️  Изображение: {img_url}")
                    
                    # Создаем тестовую статью
                    test_article = {
                        'title': entry.get('title', 'Test Title'),
                        'description': entry.get('summary', 'Test description'),
                        'content': entry.get('summary', 'Test content') * 10,
                        'image': img_url,
                        'tags': ['test', 'rss'],
                        'slug': f'test-article-{processed_count}',
                        'link': entry.get('link', 'https://example.com')
                    }
                    
                    # Обрабатываем через LLM
                    print("   🤖 Обрабатываю через LLM...")
                    translated = rss_parser.process_article(test_article)
                    
                    if translated:
                        print("   ✅ Статья обработана")
                        print(f"   📝 Заголовок: {translated.get('title', 'N/A')[:50]}...")
                        print(f"   🖼️  Изображение сохранено: {translated.get('image', 'N/A')}")
                        
                        # Генерируем Telegram-пост
                        print("   📱 Генерирую Telegram-пост...")
                        test_article['translated'] = translated
                        telegram_post = rss_parser.generate_telegram_post(test_article)
                        
                        if telegram_post:
                            print("   ✅ Telegram-пост готов")
                            print(f"   📏 Длина: {len(telegram_post)} символов")
                            
                            # Показываем часть поста
                            print(f"   📄 Начало поста: {telegram_post[:100]}...")
                        else:
                            print("   ❌ Не удалось сгенерировать пост")
                    else:
                        print("   ❌ Не удалось обработать статью")
                    
                    processed_count += 1
                else:
                    print(f"   ⚠️  Пропускаю запись без изображения: {entry.get('title', 'Без заголовка')[:50]}...")
        else:
            print("❌ Не удалось загрузить RSS-ленту")
            
    except Exception as e:
        print(f"❌ Ошибка при обработке RSS-ленты: {e}")
    
    # Пример 2: Тестирование валидации изображений
    print("\n2️⃣ Тестирование валидации изображений")
    print("-" * 40)
    
    test_urls = [
        "https://example.com/image.jpg",
        "https://example.com/photo.png",
        "https://example.com/ads/banner.jpg",
        "https://example.com/logo/icon.png",
        "https://example.com/document.pdf"
    ]
    
    for url in test_urls:
        is_valid = rss_parser._is_valid_image_url(url)
        status = "✅" if is_valid else "❌"
        print(f"   {status} {url}: {is_valid}")
    
    # Пример 3: Извлечение из HTML
    print("\n3️⃣ Тестирование извлечения из HTML")
    print("-" * 40)
    
    html_samples = [
        '<img src="https://example.com/image1.jpg" alt="Test">',
        '<img data-src="https://example.com/image2.png" alt="Lazy">',
        '<p>Text</p><img src="https://example.com/ads/banner.jpg"><p>More text</p>'
    ]
    
    for i, html in enumerate(html_samples, 1):
        img_url = rss_parser._extract_image_from_html(html)
        print(f"   HTML {i}: {img_url}")
    
    print("\n🎉 Демонстрация завершена!")
    print("\n📋 Резюме возможностей:")
    print("✅ Извлечение изображений из 7 источников RSS")
    print("✅ Валидация и фильтрация изображений")
    print("✅ Сохранение в переведенных статьях")
    print("✅ Генерация Telegram-постов с изображениями")
    print("✅ Отправка фото с подписями в Telegram")


if __name__ == "__main__":
    main() 