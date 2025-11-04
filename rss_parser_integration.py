#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Интеграция улучшенного RSS парсера в существующую систему
Обратная совместимость с текущим RSSParser
"""

from improved_rss_parser import ImprovedRSSParser
from typing import Dict, List, Optional, Any
import os
import logging

class EnhancedRSSParserWrapper:
    """
    Обертка для улучшенного RSS парсера с совместимостью с существующим API
    """
    
    def __init__(self):
        """Инициализация с сохранением совместимости"""
        
        # Инициализируем улучшенный парсер
        self.improved_parser = ImprovedRSSParser()
        
        # Настройки для совместимости
        self.session = self.improved_parser.session
        self.openai_client = None  # Будет установлен позже если нужен
        self.db = None  # Будет установлен позже если нужен
        
        # Статистика для совместимости
        self.processed_articles = set()
        
        # Настройка логирования
        self.logger = logging.getLogger(__name__)
    
    def set_openai_client(self, client):
        """Установка OpenAI клиента для совместимости"""
        self.openai_client = client
    
    def set_database(self, db):
        """Установка базы данных для совместимости"""
        self.db = db
    
    def parse_feed(self, feed_url: str) -> Dict[str, Any]:
        """
        Парсинг RSS ленты с улучшенными возможностями
        Совместимый API с оригинальным парсером
        
        Args:
            feed_url: URL RSS ленты
            
        Returns:
            Словарь с данными RSS ленты в формате оригинального парсера
        """
        try:
            # Используем улучшенный парсер
            result = self.improved_parser.parse_feed(feed_url)
            
            if not result.get('success'):
                self.logger.warning(f"Не удалось распарсить {feed_url}: {result.get('error')}")
                return None
            
            # Преобразуем результат в формат оригинального парсера
            compatible_result = {
                'title': result.get('title', ''),
                'description': result.get('description', ''),
                'link': result.get('link', feed_url),
                'entries': []
            }
            
            # Преобразуем записи в совместимый формат
            for entry in result.get('entries', []):
                compatible_entry = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'summary': entry.get('summary', ''),
                    'published': entry.get('published', ''),
                    'image': entry.get('image', ''),
                    'categories': entry.get('categories', []),
                    'category': 'news',  # По умолчанию
                    'feed_title': result.get('title', ''),
                    'feed_url': feed_url,
                    'author': entry.get('author', '')
                }
                
                # Убираем пустые поля
                compatible_entry = {k: v for k, v in compatible_entry.items() if v}
                compatible_result['entries'].append(compatible_entry)
            
            return compatible_result
            
        except Exception as e:
            self.logger.error(f"Ошибка при парсинге {feed_url}: {e}")
            return None
    
    def load_feeds_from_file(self, filename: str) -> List[str]:
        """
        Загрузка списка RSS лент из файла
        Совместимый метод
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            return feeds
        except Exception as e:
            self.logger.error(f"Ошибка при загрузке файла {filename}: {e}")
            return []
    
    def process_multiple_feeds(self, feeds_file: str = 'feeds.txt') -> List[Dict[str, Any]]:
        """
        Обработка множественных RSS лент
        Совместимый метод с улучшенными возможностями
        
        Args:
            feeds_file: Путь к файлу со списком RSS лент
            
        Returns:
            Список всех обработанных статей
        """
        if not os.path.exists(feeds_file):
            self.logger.error(f"Файл {feeds_file} не найден")
            return []
        
        # Загружаем список RSS лент
        feeds = self.load_feeds_from_file(feeds_file)
        if not feeds:
            self.logger.error(f"Не удалось загрузить RSS ленты из {feeds_file}")
            return []
        
        self.logger.info(f"📋 Найдено {len(feeds)} RSS лент для обработки")
        
        # Используем улучшенный парсер для массовой обработки
        results = self.improved_parser.parse_multiple_feeds(feeds)
        
        # Преобразуем результаты в совместимый формат
        all_articles = []
        
        for feed_data in results.get('successful_feeds', []):
            for entry in feed_data.get('entries', []):
                compatible_entry = {
                    'title': entry.get('title', ''),
                    'link': entry.get('link', ''),
                    'summary': entry.get('summary', ''),
                    'published': entry.get('published', ''),
                    'image': entry.get('image', ''),
                    'categories': entry.get('categories', []),
                    'category': 'news',
                    'feed_title': feed_data.get('title', ''),
                    'feed_url': entry.get('feed_url', ''),
                    'author': entry.get('author', '')
                }
                
                # Убираем пустые поля
                compatible_entry = {k: v for k, v in compatible_entry.items() if v}
                all_articles.append(compatible_entry)
        
        # Выводим статистику в совместимом формате
        stats = results.get('stats', {})
        self.logger.info(f"🎯 ИТОГОВАЯ СТАТИСТИКА:")
        self.logger.info(f"   📋 RSS лент обработано: {stats.get('total_feeds', 0)}")
        self.logger.info(f"   ✅ Успешных лент: {stats.get('successful_feeds', 0)}")
        self.logger.info(f"   ❌ Неудачных лент: {stats.get('failed_feeds', 0)}")
        self.logger.info(f"   📰 Статей найдено: {len(all_articles)}")
        self.logger.info(f"   📈 Успешность: {stats.get('success_rate', 0):.1f}%")
        self.logger.info(f"   ⏱️ Общее время: {stats.get('total_time', 0):.2f}s")
        
        # Показываем детали неудачных лент
        failed_feeds = results.get('failed_feeds', [])
        if failed_feeds:
            self.logger.warning(f"❌ НЕРАБОТАЮЩИЕ ЛЕНТЫ ({len(failed_feeds)}):")
            for failed in failed_feeds[:5]:  # Показываем только первые 5
                error = failed.get('error', 'unknown error')
                status = failed.get('status_code', '')
                status_text = f" (HTTP {status})" if status else ""
                self.logger.warning(f"   {failed['url']}: {error}{status_text}")
            
            if len(failed_feeds) > 5:
                self.logger.warning(f"   ... и еще {len(failed_feeds) - 5} лент")
        
        return all_articles
    
    def get_stats(self) -> Dict[str, Any]:
        """Получение статистики работы парсера"""
        base_stats = self.improved_parser.get_stats()
        
        # Добавляем дополнительную статистику для совместимости
        base_stats.update({
            'processed_articles_count': len(self.processed_articles),
            'has_openai_client': self.openai_client is not None,
            'has_database': self.db is not None
        })
        
        return base_stats
    
    def display_feed(self, articles: List[Dict[str, Any]], show_all: bool = False):
        """
        Вывод данных RSS ленты в читаемом виде
        Совместимый метод
        """
        if not articles:
            print("Нет данных для отображения")
            return
        
        print("=" * 80)
        print(f"РЕЗУЛЬТАТЫ ПАРСИНГА: {len(articles)} статей")
        print("=" * 80)
        print()
        
        for i, article in enumerate(articles[:10], 1):  # Показываем первые 10
            print(f"СТАТЬЯ #{i}")
            print("-" * 40)
            
            if article.get('title'):
                print(f"Заголовок: {article['title']}")
            
            if article.get('link'):
                print(f"Ссылка: {article['link']}")
            
            if article.get('published'):
                print(f"Дата: {article['published']}")
            
            if article.get('summary'):
                summary = article['summary']
                if len(summary) > 200:
                    summary = summary[:200] + "..."
                print(f"Описание: {summary}")
            
            if article.get('image'):
                print(f"Изображение: {article['image']}")
            
            if article.get('categories'):
                print(f"Категории: {', '.join(article['categories'])}")
            
            if article.get('feed_title'):
                print(f"Источник: {article['feed_title']}")
            
            print()
        
        if len(articles) > 10:
            print(f"... и еще {len(articles) - 10} статей")


# Создаем глобальный экземпляр для обратной совместимости
enhanced_parser = EnhancedRSSParserWrapper()


def create_enhanced_parser():
    """Фабричная функция для создания улучшенного парсера"""
    return EnhancedRSSParserWrapper()


def migrate_to_enhanced_parser():
    """
    Функция для миграции существующего кода на улучшенный парсер
    """
    print("🔄 Миграция на улучшенный RSS парсер")
    print("=" * 50)
    print()
    print("Преимущества улучшенного парсера:")
    print("✅ Лучший обход блокировок (CloudFlare, anti-bot)")
    print("✅ Множественные User-Agent стратегии")
    print("✅ Автоматическое исправление кодировок")
    print("✅ Улучшенная обработка ошибок XML")
    print("✅ Кэширование ETag/Last-Modified")
    print("✅ Интеллектуальные задержки между запросами")
    print("✅ Подробная статистика и логирование")
    print("✅ Полная обратная совместимость")
    print()
    print("Для использования:")
    print("1. Замените 'from rss_parser import RSSParser'")
    print("   на 'from rss_parser_integration import enhanced_parser'")
    print("2. Или используйте create_enhanced_parser()")
    print()


if __name__ == "__main__":
    # Демонстрация использования
    migrate_to_enhanced_parser()
    
    # Пример использования
    parser = create_enhanced_parser()
    
    # Тестируем на нескольких лентах
    test_feeds = [
        "https://www.lavanguardia.com/rss/politica.xml",
        "https://feeds.elpais.com/mrss-s/pages/ep/site/elpais.com/section/economia/portada",
        "https://www.abc.es/rss/feeds/abc_Economia.xml"
    ]
    
    print("🧪 Тестирование улучшенного парсера...")
    
    for feed_url in test_feeds:
        print(f"\n📡 Тестируем: {feed_url}")
        result = parser.parse_feed(feed_url)
        
        if result:
            print(f"   ✅ Успешно: {len(result.get('entries', []))} записей")
            print(f"   📝 Заголовок: {result.get('title', 'н/д')}")
        else:
            print(f"   ❌ Неудача")
    
    print(f"\n📊 Статистика: {parser.get_stats()}")
