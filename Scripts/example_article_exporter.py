#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования модуля article_exporter.py
Демонстрирует различные способы экспорта статей из Firebase
"""

from firebase_client import FirebaseClient
from article_exporter import ArticleExporter


def example_basic_export():
    """Базовый пример экспорта всех статей"""
    print("🚀 Пример базового экспорта")
    
    # Инициализируем Firebase клиент
    firebase_client = FirebaseClient()
    
    # Создаем экспортер
    exporter = ArticleExporter(firebase_client)
    
    # Экспортируем все статьи (максимум 100)
    stats = exporter.export_articles(limit=100)
    
    print(f"📊 Результаты экспорта:")
    print(f"  Всего статей: {stats['total']}")
    print(f"  Успешно: {stats['success']}")
    print(f"  Ошибок: {stats['failed']}")
    
    for collection, count in stats['collections'].items():
        print(f"  {collection}: {count} статей")


def example_dry_run():
    """Пример предварительного просмотра без сохранения"""
    print("\n🔍 Пример предварительного просмотра (dry run)")
    
    firebase_client = FirebaseClient()
    exporter = ArticleExporter(firebase_client)
    
    # Показываем что будет экспортировано без сохранения
    stats = exporter.export_articles(limit=50, dry_run=True)
    
    print(f"📋 Что будет экспортировано:")
    print(f"  Всего статей: {stats['total']}")
    
    for collection, count in stats['collections'].items():
        print(f"  {collection}: {count} статей")


def example_single_article():
    """Пример экспорта одной статьи по ID"""
    print("\n📄 Пример экспорта одной статьи")
    
    firebase_client = FirebaseClient()
    exporter = ArticleExporter(firebase_client)
    
    # Замените на реальный ID статьи из Firebase
    article_id = "example_article_id"
    
    success = exporter.export_single_article(article_id)
    
    if success:
        print(f"✅ Статья {article_id} успешно экспортирована")
    else:
        print(f"❌ Ошибка экспорта статьи {article_id}")


def example_custom_output_dir():
    """Пример экспорта в пользовательскую директорию"""
    print("\n📁 Пример экспорта в пользовательскую директорию")
    
    firebase_client = FirebaseClient()
    
    # Экспортируем в другую директорию
    custom_dir = "exported_articles"
    exporter = ArticleExporter(firebase_client, output_dir=custom_dir)
    
    stats = exporter.export_articles(limit=10)
    
    print(f"📊 Экспорт в {custom_dir}:")
    print(f"  Успешно: {stats['success']} статей")


def example_article_preview():
    """Пример предварительного просмотра статей из Firebase"""
    print("\n👀 Пример предварительного просмотра статей")
    
    firebase_client = FirebaseClient()
    exporter = ArticleExporter(firebase_client)
    
    # Получаем статьи из Firebase
    articles = exporter.get_articles_from_firebase(limit=5)
    
    print(f"📰 Найдено {len(articles)} статей:")
    
    for i, article in enumerate(articles, 1):
        title = article.get('title', 'Без заголовка')
        category = article.get('category', 'unknown')
        region = article.get('region', 'unknown')
        
        print(f"  {i}. {title}")
        print(f"     Категория: {category}")
        print(f"     Регион: {region}")
        print(f"     ID: {article.get('id', 'N/A')}")
        print()


def main():
    """Запуск всех примеров"""
    print("📚 Примеры использования article_exporter.py")
    print("=" * 50)
    
    try:
        # Проверяем подключение к Firebase
        firebase_client = FirebaseClient()
        print("✅ Подключение к Firebase успешно")
        
        # Запускаем примеры
        example_article_preview()
        example_dry_run()
        example_basic_export()
        example_custom_output_dir()
        
        print("\n🎉 Все примеры выполнены успешно!")
        
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        print("\n💡 Убедитесь, что:")
        print("  1. Файл firebase_key.json существует")
        print("  2. Firebase проект настроен правильно")
        print("  3. В коллекции 'articles' есть данные")


if __name__ == "__main__":
    main() 