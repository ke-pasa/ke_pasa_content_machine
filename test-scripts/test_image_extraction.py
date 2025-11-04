#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тест извлечения изображений из RSS-лент
Проверяет улучшенную логику извлечения изображений из различных источников RSS
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser
import feedparser
from bs4 import BeautifulSoup


def test_image_extraction_methods():
    """Тестирует методы извлечения изображений"""
    print("🧪 Тестирование методов извлечения изображений")
    print("=" * 60)
    
    rss_parser = RSSParser()
    
    # Тест 1: Проверка валидации URL изображений
    print("\n1️⃣ Тест валидации URL изображений:")
    
    valid_urls = [
        "https://example.com/image.jpg",
        "https://example.com/photo.png",
        "https://example.com/pic.gif",
        "https://example.com/img.webp",
        "https://example.com/logo.svg"
    ]
    
    invalid_urls = [
        "https://example.com/ads/banner.jpg",
        "https://example.com/logo/icon.png",
        "https://example.com/banner/ad.gif",
        "https://example.com/document.pdf",
        "https://example.com/video.mp4"
    ]
    
    print("✅ Валидные URL:")
    for url in valid_urls:
        is_valid = rss_parser._is_valid_image_url(url)
        print(f"   {url}: {is_valid}")
    
    print("\n❌ Невалидные URL:")
    for url in invalid_urls:
        is_valid = rss_parser._is_valid_image_url(url)
        print(f"   {url}: {is_valid}")
    
    # Тест 2: Извлечение изображений из HTML
    print("\n2️⃣ Тест извлечения изображений из HTML:")
    
    html_samples = [
        '<img src="https://example.com/image1.jpg" alt="Test">',
        '<img data-src="https://example.com/image2.png" alt="Lazy">',
        '<img data-lazy-src="https://example.com/image3.gif" alt="Lazy2">',
        '<p>Text</p><img src="https://example.com/ads/banner.jpg"><p>More text</p>',
        '<div><img src="https://example.com/valid.jpg"><img src="https://example.com/logo/icon.png"></div>'
    ]
    
    for i, html in enumerate(html_samples, 1):
        img_url = rss_parser._extract_image_from_html(html)
        print(f"   HTML {i}: {img_url}")
    
    # Тест 3: Симуляция RSS-записи с изображениями
    print("\n3️⃣ Тест симуляции RSS-записи:")
    
    # Создаем тестовую RSS-запись
    test_entry = {
        'title': 'Test Article',
        'link': 'https://example.com/article',
        'summary': '<p>Test content</p><img src="https://example.com/summary.jpg">',
        'media_content': [
            {'type': 'image/jpeg', 'url': 'https://example.com/media.jpg'},
            {'type': 'video/mp4', 'url': 'https://example.com/video.mp4'}
        ],
        'media_thumbnail': [
            {'url': 'https://example.com/thumbnail.png'}
        ],
        'enclosures': [
            {'type': 'image/png', 'href': 'https://example.com/enclosure.png'}
        ],
        'links': [
            {'type': 'image/gif', 'href': 'https://example.com/link.gif'}
        ]
    }
    
    img_url = rss_parser._get_image(test_entry)
    print(f"   Извлеченное изображение: {img_url}")
    
    print("\n✅ Тестирование завершено!")


def test_real_rss_feed():
    """Тестирует извлечение изображений из реальной RSS-ленты"""
    print("\n🌐 Тестирование реальной RSS-ленты")
    print("=" * 60)
    
    # Используем тестовую RSS-ленту (BBC News)
    test_feed_url = "http://feeds.bbci.co.uk/news/rss.xml"
    
    try:
        print(f"📡 Загружаю RSS-ленту: {test_feed_url}")
        feed = feedparser.parse(test_feed_url)
        
        if feed.entries:
            print(f"✅ Загружено {len(feed.entries)} записей")
            
            rss_parser = RSSParser()
            
            # Проверяем первые 5 записей
            for i, entry in enumerate(feed.entries[:5], 1):
                print(f"\n📰 Запись {i}: {entry.get('title', 'Без заголовка')[:50]}...")
                
                # Извлекаем изображение
                img_url = rss_parser._get_image(entry)
                if img_url:
                    print(f"   🖼️  Изображение: {img_url}")
                else:
                    print(f"   ❌ Изображение не найдено")
                
                # Показываем доступные поля
                print(f"   📋 Доступные поля:")
                if hasattr(entry, 'media_content') and entry.media_content:
                    print(f"      media_content: {len(entry.media_content)} элементов")
                if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    print(f"      media_thumbnail: {len(entry.media_thumbnail)} элементов")
                if hasattr(entry, 'enclosures') and entry.enclosures:
                    print(f"      enclosures: {len(entry.enclosures)} элементов")
                if hasattr(entry, 'links') and entry.links:
                    print(f"      links: {len(entry.links)} элементов")
        else:
            print("❌ Не удалось загрузить RSS-ленту")
            
    except Exception as e:
        print(f"❌ Ошибка при тестировании RSS-ленты: {e}")


def test_multiple_rss_feeds():
    """Тестирует извлечение изображений из различных RSS-лент"""
    print("\n🌐 Тестирование различных RSS-лент")
    print("=" * 60)
    
    # Список RSS-лент для тестирования
    test_feeds = [
        "http://feeds.bbci.co.uk/news/rss.xml",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/ultimas-noticias/portada",
        "https://www.20minutos.es/rss/",
        "https://www.abc.es/rss/feeds/abc_ultima.xml"
    ]
    
    rss_parser = RSSParser()
    
    for feed_url in test_feeds:
        try:
            print(f"\n📡 Тестирую: {feed_url}")
            feed = feedparser.parse(feed_url)
            
            if feed.entries:
                print(f"   ✅ Загружено {len(feed.entries)} записей")
                
                # Проверяем первые 3 записи
                image_count = 0
                for i, entry in enumerate(feed.entries[:3], 1):
                    img_url = rss_parser._get_image(entry)
                    if img_url:
                        image_count += 1
                        print(f"   🖼️  Запись {i}: {img_url}")
                    else:
                        print(f"   ❌ Запись {i}: изображение не найдено")
                
                print(f"   📊 Найдено изображений: {image_count}/3")
            else:
                print("   ❌ Не удалось загрузить RSS-ленту")
                
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")


def test_article_processing_with_images():
    """Тестирует обработку статей с изображениями"""
    print("\n📝 Тестирование обработки статей с изображениями")
    print("=" * 60)
    
    rss_parser = RSSParser()
    
    # Создаем тестовую статью с изображением
    test_article = {
        'title': 'Test Article with Image',
        'description': 'Test description',
        'content': 'This is a test article content.',
        'image': 'https://example.com/test-image.jpg',
        'tags': ['test', 'image'],
        'slug': 'test-article'
    }
    
    print("📄 Тестовая статья:")
    print(f"   Заголовок: {test_article['title']}")
    print(f"   Изображение: {test_article['image']}")
    
    # Проверяем валидность изображения
    is_valid = rss_parser._is_valid_image_url(test_article['image'])
    print(f"   Валидность изображения: {is_valid}")
    
    print("\n✅ Тестирование завершено!")


def main():
    """Основная функция тестирования"""
    print("🖼️ Тест извлечения изображений из RSS-лент")
    print("=" * 80)
    
    # Запускаем все тесты
    test_image_extraction_methods()
    test_real_rss_feed()
    test_multiple_rss_feeds()  # Добавляем новый тест
    test_article_processing_with_images()
    
    print("\n🎉 Все тесты завершены!")


if __name__ == "__main__":
    main() 