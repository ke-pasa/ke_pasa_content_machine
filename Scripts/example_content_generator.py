#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Пример использования модуля content_generator.py
"""

import logging
from content_generator import generate_article, generate_telegram_post, generate_and_save_content
from workers.tools.firebase_client import get_firebase_client


def create_sample_cluster():
    """Создает тестовый кластер для демонстрации"""
    return {
        "cluster_id": "demo123",
        "topic_summary": "Новые правила получения визы в Испании для россиян",
        "combined_context": "Правительство Испании объявило о введении новых требований для получения визы гражданами России. Изменения касаются дополнительных документов, увеличения сроков рассмотрения заявлений и новых требований к финансовой обеспеченности. Эксперты отмечают, что эти меры связаны с текущей геополитической ситуацией и направлены на усиление контроля за въездом иностранных граждан.",
        "sources": [
            {
                "title": "Nuevas reglas de visa para rusos",
                "summary": "El gobierno español anuncia cambios en los requisitos de visa",
                "link": "https://example.com/news/visa-rules-russia",
                "image": "https://example.com/images/visa.jpg"
            },
            {
                "title": "Cambios en inmigración española",
                "summary": "Nuevos requisitos para ciudadanos rusos",
                "link": "https://example.com/news/immigration-changes",
                "image": ""
            }
        ],
        "priority_score": 92,
        "urgent": True
    }


def demonstrate_article_generation():
    """Демонстрирует генерацию статьи"""
    print("🎯 ДЕМОНСТРАЦИЯ ГЕНЕРАЦИИ СТАТЬИ")
    print("=" * 50)
    
    cluster = create_sample_cluster()
    
    # Генерируем статью
    article = generate_article(cluster)
    
    if article:
        print("✅ Статья успешно сгенерирована!")
        print(f"📝 Заголовок: {article['title']}")
        print(f"📄 Описание: {article['description']}")
        print(f"🏷️  Теги: {', '.join(article['tags'])}")
        print(f"🔗 Slug: {article['slug']}")
        print(f"📊 Meta title: {article['meta_title']}")
        print(f"📋 Meta description: {article['meta_description']}")
        print(f"🔑 Meta keywords: {', '.join(article['meta_keywords'])}")
        
        # Показываем начало контента
        content_preview = article['content'][:200] + "..." if len(article['content']) > 200 else article['content']
        print(f"📖 Контент (начало): {content_preview}")
        
        return article
    else:
        print("❌ Не удалось сгенерировать статью")
        return None


def demonstrate_telegram_post_generation(article):
    """Демонстрирует генерацию Telegram-поста"""
    print("\n📱 ДЕМОНСТРАЦИЯ ГЕНЕРАЦИИ TELEGRAM-ПОСТА")
    print("=" * 50)
    
    if not article:
        print("❌ Нет статьи для генерации Telegram-поста")
        return None
    
    # Генерируем Telegram-пост
    telegram_post = generate_telegram_post(article)
    
    if telegram_post:
        print("✅ Telegram-пост успешно сгенерирован!")
        print(f"📏 Длина: {len(telegram_post)} символов")
        print("\n📱 СОДЕРЖИМОЕ ПОСТА:")
        print("-" * 30)
        print(telegram_post)
        print("-" * 30)
        
        return telegram_post
    else:
        print("❌ Не удалось сгенерировать Telegram-пост")
        return None


def demonstrate_full_workflow():
    """Демонстрирует полный workflow с сохранением в Firebase"""
    print("\n🔄 ДЕМОНСТРАЦИЯ ПОЛНОГО WORKFLOW")
    print("=" * 50)
    
    try:
        # Получаем Firebase клиент
        firebase_client = get_firebase_client()
        print("✅ Firebase клиент подключен")
        
        cluster = create_sample_cluster()
        
        # Генерируем и сохраняем контент
        article_id = generate_and_save_content(cluster, firebase_client)
        
        if article_id:
            print(f"✅ Контент успешно сохранен в Firebase!")
            print(f"🆔 ID статьи: {article_id}")
        else:
            print("❌ Не удалось сохранить контент в Firebase")
            
    except Exception as e:
        print(f"❌ Ошибка при работе с Firebase: {e}")
        print("💡 Убедитесь, что файл firebase_key.json настроен правильно")


def demonstrate_cluster_processing():
    """Демонстрирует обработку нескольких кластеров"""
    print("\n📊 ДЕМОНСТРАЦИЯ ОБРАБОТКИ КЛАСТЕРОВ")
    print("=" * 50)
    
    # Создаем несколько тестовых кластеров
    clusters = [
        {
            "cluster_id": "cluster1",
            "topic_summary": "Изменения в налоговом законодательстве Испании",
            "combined_context": "Парламент Испании принял новый закон о налогообложении иностранных граждан. Основные изменения касаются ставок подоходного налога и новых льгот для инвесторов.",
            "sources": [{"title": "Tax law changes", "link": "https://example.com/tax-changes"}],
            "priority_score": 85,
            "urgent": False
        },
        {
            "cluster_id": "cluster2",
            "topic_summary": "Новые правила аренды жилья в Мадриде",
            "combined_context": "Мэрия Мадрида ввела новые правила для аренды жилья. Теперь арендодатели обязаны предоставлять дополнительные документы и соблюдать новые стандарты качества.",
            "sources": [{"title": "Madrid rental rules", "link": "https://example.com/rental-rules"}],
            "priority_score": 78,
            "urgent": False
        }
    ]
    
    print(f"📋 Обрабатываем {len(clusters)} кластеров...")
    
    for i, cluster in enumerate(clusters, 1):
        print(f"\n🔄 Кластер {i}: {cluster['topic_summary']}")
        
        # Генерируем статью
        article = generate_article(cluster)
        if article:
            print(f"   ✅ Статья: {article['title']}")
            
            # Генерируем Telegram-пост
            telegram_post = generate_telegram_post(article)
            if telegram_post:
                print(f"   📱 Telegram-пост: {len(telegram_post)} символов")
            else:
                print(f"   ❌ Telegram-пост не сгенерирован")
        else:
            print(f"   ❌ Статья не сгенерирована")


def main():
    """Основная функция демонстрации"""
    # Настраиваем логирование
    logging.basicConfig(level=logging.INFO)
    
    print("🚀 ДЕМОНСТРАЦИЯ МОДУЛЯ CONTENT_GENERATOR")
    print("=" * 60)
    
    # Демонстрируем генерацию статьи
    article = demonstrate_article_generation()
    
    # Демонстрируем генерацию Telegram-поста
    telegram_post = demonstrate_telegram_post_generation(article)
    
    # Демонстрируем обработку кластеров
    demonstrate_cluster_processing()
    
    # Демонстрируем полный workflow (только если настроен Firebase)
    print("\n💡 Для демонстрации сохранения в Firebase убедитесь, что:")
    print("   - Файл firebase_key.json настроен")
    print("   - Переменная OPENAI_API_KEY установлена")
    
    try:
        demonstrate_full_workflow()
    except Exception as e:
        print(f"⚠️  Firebase не настроен: {e}")
    
    print("\n✅ Демонстрация завершена!")


if __name__ == "__main__":
    main() 