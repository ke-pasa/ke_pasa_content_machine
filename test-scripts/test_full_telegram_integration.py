#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Полный тест интеграции с Telegram
Демонстрирует всю цепочку: RSS → обработка → Firebase → Telegram-пост → отправка
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser
import asyncio

class TelegramIntegrationTest:
    """Тестирует полную интеграцию с Telegram"""
    
    def __init__(self):
        self.parser = RSSParser()
        self.test_articles = [
            {
                "title": "Испания вводит новые налоговые льготы для стартапов",
                "description": "Правительство Испании объявило о новых налоговых льготах для технологических стартапов, что должно привлечь больше инновационных компаний в страну.",
                "content": """
                Министерство экономики и цифровой трансформации Испании представило новый пакет мер поддержки технологических стартапов. Программа "Startup Spain" включает значительные налоговые льготы и упрощенные процедуры регистрации для инновационных компаний.

                Основные преимущества программы:
                - Снижение корпоративного налога до 15% для стартапов
                - Освобождение от НДС на первые 2 года работы
                - Упрощенная процедура получения рабочих виз для основателей
                - Государственные гранты до 500,000 евро
                - Бесплатные консультации по ведению бизнеса

                Программа направлена на привлечение технологических компаний из России, Украины и других стран СНГ, где наблюдается высокий уровень предпринимательской активности в IT-сфере.

                По оценкам экспертов, новая программа может привлечь в Испанию до 1000 технологических стартапов в течение следующих 3 лет, создав более 10,000 рабочих мест.
                """,
                "tags": ["стартапы", "налоги", "IT", "бизнес", "Испания"],
                "slug": "startup-spain-tax-benefits"
            },
            {
                "title": "Новые правила получения водительских прав в Испании",
                "description": "Испанское правительство упростило процедуру обмена водительских прав для иностранцев, включая граждан России и стран СНГ.",
                "content": """
                Министерство внутренних дел Испании объявило об упрощении процедуры обмена водительских прав для иностранных граждан. Новые правила вступят в силу с 1 февраля 2025 года и значительно упростят процесс для мигрантов.

                Ключевые изменения:
                - Признание российских водительских прав без дополнительных экзаменов
                - Упрощенная процедура обмена для граждан стран СНГ
                - Сокращение срока рассмотрения заявлений до 15 дней
                - Возможность подачи документов онлайн
                - Признание международных водительских удостоверений

                Новые правила особенно важны для мигрантов, которые планируют работать в сфере доставки, такси или других услуг, требующих водительских прав.

                Эксперты отмечают, что изменения помогут многим русскоязычным мигрантам быстрее адаптироваться к жизни в Испании и найти работу.
                """,
                "tags": ["водительские права", "миграция", "Испания", "2025"],
                "slug": "driving-license-exchange-2025"
            }
        ]
    
    def test_article_processing(self):
        """Тестирует обработку статей"""
        print("🧪 Тестирование обработки статей")
        print("=" * 50)
        
        for i, article in enumerate(self.test_articles, 1):
            print(f"\n📰 Статья {i}: {article['title']}")
            
            # Генерируем Telegram-пост
            telegram_post = self.parser.generate_telegram_post(article)
            
            print(f"✅ Пост сгенерирован ({len(telegram_post)} символов)")
            
            # Показываем первые 200 символов
            preview = telegram_post[:200] + "..." if len(telegram_post) > 200 else telegram_post
            print(f"📱 Превью: {preview}")
            
            # Проверяем наличие обязательных элементов
            checks = [
                ("🧲", "Заголовок"),
                ("🧾", "Основной текст"),
                ("🔗", "Ссылка"),
                ("💬", "Призыв к обсуждению")
            ]
            
            for element, description in checks:
                status = "✅" if element in telegram_post else "❌"
                print(f"   {status} {description}")
    
    def test_firebase_integration(self):
        """Тестирует интеграцию с Firebase"""
        print("\n🔥 Тестирование интеграции с Firebase")
        print("=" * 50)
        
        for i, processed_article in enumerate(self.test_articles, 1):
            # Создаем оригинальную статью для Firebase
            original_article = {
                "title": f"Original Title {i}",
                "description": f"Original description {i}",
                "link": f"https://example.com/article-{i}",
                "published": "2025-01-15T10:30:00Z",
                "image": f"https://example.com/image-{i}.jpg",
                "category": "news",
                "feed_title": "Test Feed"
            }
            
            # Сохраняем в Firebase
            success = self.parser.save_to_firebase(original_article, processed_article)
            
            if success:
                print(f"✅ Статья {i} сохранена в Firebase")
            else:
                print(f"⚠️  Статья {i}: ошибка сохранения в Firebase")
    
    async def simulate_telegram_sending(self):
        """Симулирует отправку в Telegram"""
        print("\n📤 Симуляция отправки в Telegram")
        print("=" * 50)
        
        bot_token = "YOUR_BOT_TOKEN"  # Замените на реальный токен
        channel_id = "@your_channel"  # Замените на ваш канал
        
        print("🤖 Настройки бота:")
        print(f"   Токен: {bot_token[:10]}..." if bot_token != "YOUR_BOT_TOKEN" else "   Токен: [не настроен]")
        print(f"   Канал: {channel_id}")
        print()
        
        for i, article in enumerate(self.test_articles, 1):
            print(f"📱 Отправка статьи {i}: {article['title']}")
            
            # Генерируем пост
            telegram_post = self.parser.generate_telegram_post(article)
            
            # Симулируем отправку
            print(f"   📏 Длина поста: {len(telegram_post)} символов")
            print(f"   📤 Статус: {'✅ Отправлено' if bot_token != 'YOUR_BOT_TOKEN' else '⚠️  Требуется настройка токена'}")
            
            # Показываем формат данных для отправки
            telegram_data = {
                "chat_id": channel_id,
                "text": telegram_post,
                "parse_mode": "Markdown",
                "disable_web_page_preview": False
            }
            
            print(f"   📋 Данные для отправки: {telegram_data}")
            print()
    
    def show_integration_code(self):
        """Показывает код для полной интеграции"""
        print("\n💻 КОД ДЛЯ ПОЛНОЙ ИНТЕГРАЦИИ:")
        print("=" * 50)
        
        integration_code = '''
# Полная интеграция RSS → Firebase → Telegram

import asyncio
from rss_parser import RSSParser
import telegram

class NewsPublisher:
    def __init__(self, bot_token: str, channel_id: str):
        self.parser = RSSParser()
        self.bot = telegram.Bot(token=bot_token)
        self.channel_id = channel_id
    
    async def process_and_publish(self, original_article: dict):
        """Обрабатывает статью и публикует в Telegram"""
        
        # Обрабатываем статью
        processed_article = self.parser.process_article(original_article)
        
        if processed_article:
            # Сохраняем в Firebase
            self.parser.save_to_firebase(original_article, processed_article)
            
            # Генерируем Telegram-пост
            telegram_post = self.parser.generate_telegram_post(processed_article)
            
            # Отправляем в Telegram
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=telegram_post,
                parse_mode='Markdown'
            )
            
            print(f"✅ Опубликовано: {processed_article['title']}")
            return True
        
        return False

# Использование
async def main():
    publisher = NewsPublisher(
        bot_token='YOUR_BOT_TOKEN',
        channel_id='@your_channel'
    )
    
    # Обрабатываем RSS-ленты
    articles = publisher.parser.process_multiple_feeds()
    
    for article in articles:
        await publisher.process_and_publish(article)
        await asyncio.sleep(300)  # 5 минут между постами

# Запуск
asyncio.run(main())
'''
        
        print(integration_code)
    
    def run_all_tests(self):
        """Запускает все тесты"""
        print("🚀 ЗАПУСК ПОЛНОГО ТЕСТА ИНТЕГРАЦИИ")
        print("=" * 60)
        
        # Тест обработки статей
        self.test_article_processing()
        
        # Тест Firebase
        self.test_firebase_integration()
        
        # Симуляция Telegram
        asyncio.run(self.simulate_telegram_sending())
        
        # Показываем код интеграции
        self.show_integration_code()
        
        print("\n✅ ВСЕ ТЕСТЫ ЗАВЕРШЕНЫ!")
        print("\n📝 СЛЕДУЮЩИЕ ШАГИ:")
        print("1. Установите python-telegram-bot: pip install python-telegram-bot")
        print("2. Создайте бота через @BotFather")
        print("3. Добавьте бота в канал как администратора")
        print("4. Настройте токен и ID канала")
        print("5. Запустите полную интеграцию")

if __name__ == "__main__":
    test = TelegramIntegrationTest()
    test.run_all_tests() 