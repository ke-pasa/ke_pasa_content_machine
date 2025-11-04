# Интеграция с Telegram

Документация по использованию функции генерации Telegram-постов с python-telegram-bot.

## 📦 Установка python-telegram-bot

```bash
pip install python-telegram-bot
```

## 🔧 Настройка Telegram-бота

### 1. Создание бота

1. Найдите [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям для создания бота
4. Сохраните полученный токен

### 2. Добавление бота в канал

1. Добавьте бота в ваш канал как администратора
2. Убедитесь, что у бота есть права на отправку сообщений

## 💻 Примеры использования

### Базовый пример

```python
from rss_parser import RSSParser
import telegram
import asyncio

async def send_telegram_post():
    # Создаем парсер
    parser = RSSParser()
    
    # Обработанная статья
    article = {
        "title": "Заголовок статьи",
        "description": "Описание статьи",
        "content": "Полный текст статьи",
        "tags": ["тег1", "тег2"],
        "slug": "article-slug"
    }
    
    # Генерируем Telegram-пост
    telegram_post = parser.generate_telegram_post(article)
    
    # Отправляем в Telegram
    bot = telegram.Bot(token='YOUR_BOT_TOKEN')
    await bot.send_message(
        chat_id='@your_channel_name',
        text=telegram_post,
        parse_mode='Markdown'
    )

# Запускаем
asyncio.run(send_telegram_post())
```

### Интеграция в существующий код

```python
from rss_parser import RSSParser
import telegram
import asyncio

class TelegramPublisher:
    def __init__(self, bot_token: str, channel_id: str):
        self.bot = telegram.Bot(token=bot_token)
        self.channel_id = channel_id
        self.parser = RSSParser()
    
    async def publish_article(self, article: dict):
        """Публикует статью в Telegram-канал"""
        
        # Генерируем пост
        telegram_post = self.parser.generate_telegram_post(article)
        
        # Отправляем в канал
        await self.bot.send_message(
            chat_id=self.channel_id,
            text=telegram_post,
            parse_mode='Markdown',
            disable_web_page_preview=False
        )
        
        print(f"✅ Статья опубликована в Telegram: {article['title']}")
    
    async def publish_multiple_articles(self, articles: list):
        """Публикует несколько статей с задержкой"""
        
        for i, article in enumerate(articles):
            await self.publish_article(article)
            
            # Задержка между постами (5 минут)
            if i < len(articles) - 1:
                await asyncio.sleep(300)
```

### Полная цепочка обработки

```python
from rss_parser import RSSParser
import telegram
import asyncio

async def process_and_publish_article(original_article: dict, bot_token: str, channel_id: str):
    """Полная цепочка: обработка статьи → сохранение → публикация в Telegram"""
    
    # Создаем парсер
    parser = RSSParser()
    
    # Обрабатываем статью
    processed_article = parser.process_article(original_article)
    
    if processed_article:
        # Сохраняем в Firebase
        parser.save_to_firebase(original_article, processed_article)
        
        # Генерируем Telegram-пост
        telegram_post = parser.generate_telegram_post(processed_article)
        
        # Отправляем в Telegram
        bot = telegram.Bot(token=bot_token)
        await bot.send_message(
            chat_id=channel_id,
            text=telegram_post,
            parse_mode='Markdown'
        )
        
        print(f"✅ Статья обработана и опубликована: {processed_article['title']}")
        return True
    
    return False

# Использование
async def main():
    bot_token = 'YOUR_BOT_TOKEN'
    channel_id = '@your_channel_name'
    
    # Пример оригинальной статьи
    original_article = {
        "title": "Spain Announces New Immigration Rules",
        "description": "New immigration rules for 2025...",
        "link": "https://example.com/article",
        # ... другие поля
    }
    
    success = await process_and_publish_article(original_article, bot_token, channel_id)
    
    if success:
        print("✅ Обработка завершена успешно")
    else:
        print("❌ Ошибка при обработке")

# Запуск
asyncio.run(main())
```

## 🔧 Конфигурация

### Переменные окружения

Добавьте в файл `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHANNEL_ID=@your_channel_name
```

### Загрузка конфигурации

```python
import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
```

## 📱 Формат постов

Сгенерированные посты имеют следующую структуру:

```
🧲 Заголовок статьи

🧾 Основной текст статьи (3-6 абзацев)
с ключевой информацией и деталями

🔗 Ссылка на полную статью: https://example.com/news/slug/

💬 Призыв к обсуждению в комментариях
```

### Особенности:

- **Длина**: Максимум 1000 символов
- **Формат**: Markdown
- **Эмодзи**: Умеренное использование
- **Ссылки**: Автоматически включаются
- **Адаптация**: Для русскоязычных мигрантов в Испании

## 🛠️ Обработка ошибок

```python
async def safe_publish_article(article: dict, bot_token: str, channel_id: str):
    """Безопасная публикация с обработкой ошибок"""
    
    try:
        parser = RSSParser()
        telegram_post = parser.generate_telegram_post(article)
        
        bot = telegram.Bot(token=bot_token)
        await bot.send_message(
            chat_id=channel_id,
            text=telegram_post,
            parse_mode='Markdown'
        )
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка при публикации: {e}")
        return False
```

## 📊 Мониторинг

### Логирование публикаций

```python
import logging
from datetime import datetime

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def publish_with_logging(article: dict, bot_token: str, channel_id: str):
    """Публикация с логированием"""
    
    start_time = datetime.now()
    
    try:
        # ... код публикации ...
        
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        logger.info(f"✅ Статья опубликована за {duration:.2f}с: {article['title']}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка публикации: {e}")
```

## 🔄 Автоматизация

### Планировщик публикаций

```python
import asyncio
import schedule
import time

async def scheduled_publishing():
    """Ежедневная публикация в определенное время"""
    
    bot_token = 'YOUR_BOT_TOKEN'
    channel_id = '@your_channel_name'
    
    # Получаем новые статьи
    parser = RSSParser()
    new_articles = parser.process_multiple_feeds()
    
    for article in new_articles:
        await publish_article(article, bot_token, channel_id)
        await asyncio.sleep(300)  # 5 минут между постами

# Планирование
schedule.every().day.at("10:00").do(lambda: asyncio.run(scheduled_publishing()))
schedule.every().day.at("18:00").do(lambda: asyncio.run(scheduled_publishing()))

while True:
    schedule.run_pending()
    time.sleep(60)
```

## 📝 Примечания

1. **Rate Limiting**: Telegram имеет ограничения на количество сообщений
2. **Markdown**: Используйте `parse_mode='Markdown'` для форматирования
3. **Ошибки**: Всегда обрабатывайте исключения при работе с API
4. **Тестирование**: Сначала тестируйте на приватном канале
5. **Модерация**: Проверяйте сгенерированные посты перед публикацией 