# Настройка генерации Telegram-постов

Пошаговая инструкция по настройке и использованию функции генерации Telegram-постов для RSS-парсера.

## 🚀 Быстрый старт

### 1. Установка зависимостей

```bash
pip install python-telegram-bot==20.7
```

### 2. Создание Telegram-бота

1. Найдите [@BotFather](https://t.me/botfather) в Telegram
2. Отправьте команду `/newbot`
3. Следуйте инструкциям:
   - Введите имя бота (например: "Spain News Bot")
   - Введите username бота (например: "spain_news_bot")
4. Сохраните полученный токен

### 3. Настройка канала

1. Создайте канал в Telegram
2. Добавьте бота в канал как администратора
3. Дайте боту права на отправку сообщений
4. Запомните username канала (например: `@spain_news`)

### 4. Настройка переменных окружения

Добавьте в файл `.env`:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHANNEL_ID=@your_channel_name
```

## 💻 Использование

### Базовый пример

```python
from rss_parser import RSSParser

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
print(telegram_post)
```

### Отправка в Telegram

```python
import asyncio
import telegram
from rss_parser import RSSParser

async def send_to_telegram():
    # Настройки
    bot_token = "YOUR_BOT_TOKEN"
    channel_id = "@your_channel"
    
    # Создаем парсер
    parser = RSSParser()
    
    # Обработанная статья
    article = {
        "title": "Новые правила миграции в Испании",
        "description": "Описание...",
        "content": "Полный текст...",
        "tags": ["миграция", "Испания"],
        "slug": "migration-rules-2025"
    }
    
    # Генерируем пост
    telegram_post = parser.generate_telegram_post(article)
    
    # Отправляем в Telegram
    bot = telegram.Bot(token=bot_token)
    await bot.send_message(
        chat_id=channel_id,
        text=telegram_post,
        parse_mode='Markdown'
    )

# Запускаем
asyncio.run(send_to_telegram())
```

## 🔄 Интеграция в существующий код

### После сохранения статьи

```python
# Существующий код обработки
processed_article = parser.process_article(original_article)

if processed_article:
    # Сохраняем в Firebase
    parser.save_to_firebase(original_article, processed_article)
    
    # НОВАЯ ФУНКЦИЯ: Генерируем Telegram-пост
    telegram_post = parser.generate_telegram_post(processed_article)
    
    # Отправляем в Telegram
    await bot.send_message(
        chat_id=channel_id,
        text=telegram_post,
        parse_mode='Markdown'
    )
```

## 📱 Формат генерируемых постов

### Структура поста:

```
🧲 Заголовок статьи

🧾 Основной текст статьи (3-6 абзацев)
с ключевой информацией и деталями

🔗 Ссылка на полную статью: https://example.com/news/slug/

💬 Призыв к обсуждению в комментариях
```

### Особенности:

- **Длина**: Максимум 1000 символов (автоматически обрезается)
- **Формат**: Markdown с эмодзи
- **Адаптация**: Для русскоязычных мигрантов в Испании
- **Fallback**: Работает даже без OpenAI API

## 🧪 Тестирование

### Запуск тестов

```bash
# Тест генерации постов
python test-scripts/test_telegram_post.py

# Тест интеграции
python test-scripts/test_integration.py

# Полный тест
python test-scripts/test_full_telegram_integration.py
```

### Пример использования

```bash
python example_telegram_usage.py
```

## 🔧 Настройка промпта

Функция использует следующий промпт для LLM:

```yaml
Ты пишешь посты для Telegram-канала, где публикуются новости для русскоязычных мигрантов в Испании.

На основе следующей статьи создай информативный, живой и цепляющий пост, который:

✅ Полностью передаёт суть и смысл статьи  
✅ Даёт читателю ясную картину ситуации  
✅ Интересно и легко читается  
✅ Подходит для Telegram (до 1000 символов)  
✅ Написан живо, но без "воды", канцелярита или сухости  
✅ Содержит в конце ссылку на полную статью  
✅ Завершается вопросом или призывом к обсуждению
```

## 🛠️ Обработка ошибок

### Fallback-режим

Если OpenAI API недоступен, функция создает простой пост:

```python
def _generate_fallback_post(self, article: Dict[str, Any]) -> str:
    """Создает простой Telegram-пост без использования LLM"""
    
    title = article.get('title', 'Новая статья')
    description = article.get('description', '')
    slug = article.get('slug', '')
    
    post = f"""🧲 {title}

🧾 {description[:300]}{'...' if len(description) > 300 else ''}

🔗 Читайте полную статью: https://example.com/news/{slug}/

💬 Что думаете об этой новости? Поделитесь в комментариях!"""
    
    return post
```

### Обработка исключений

```python
try:
    telegram_post = parser.generate_telegram_post(article)
    # Отправляем в Telegram
except Exception as e:
    print(f"❌ Ошибка при генерации поста: {e}")
    # Используем fallback или пропускаем
```

## 📊 Мониторинг

### Логирование

Функция выводит подробные логи:

```
✅ Telegram-пост сгенерирован (972 символов)
⚠️  Telegram-пост слишком длинный (1080 символов). Обрезаем...
❌ Ошибка при генерации Telegram-поста: ...
```

### Проверка элементов

```python
# Проверяем наличие обязательных элементов
checks = [
    ("🧲", "Заголовок"),
    ("🧾", "Основной текст"), 
    ("🔗", "Ссылка"),
    ("💬", "Призыв к обсуждению")
]

for element, description in checks:
    if element in telegram_post:
        print(f"✅ {description}")
    else:
        print(f"❌ {description} - не найден")
```

## 🔄 Автоматизация

### Планировщик публикаций

```python
import schedule
import asyncio
import time

async def daily_publishing():
    """Ежедневная публикация новых статей"""
    
    parser = RSSParser()
    articles = parser.process_multiple_feeds()
    
    for article in articles:
        telegram_post = parser.generate_telegram_post(article)
        # Отправляем в Telegram
        await asyncio.sleep(300)  # 5 минут между постами

# Планирование
schedule.every().day.at("10:00").do(lambda: asyncio.run(daily_publishing()))
schedule.every().day.at("18:00").do(lambda: asyncio.run(daily_publishing()))

while True:
    schedule.run_pending()
    time.sleep(60)
```

## 📝 Примечания

1. **Rate Limiting**: Telegram имеет ограничения на количество сообщений
2. **Markdown**: Используйте `parse_mode='Markdown'` для форматирования
3. **Тестирование**: Сначала тестируйте на приватном канале
4. **Модерация**: Проверяйте сгенерированные посты перед публикацией
5. **Fallback**: Функция работает даже без OpenAI API

## 🆘 Устранение неполадок

### Ошибка OpenAI API

```
❌ Ошибка при генерации Telegram-поста: ...
```

**Решение**: Проверьте правильность API ключа в файле `.env`

### Ошибка Telegram API

```
❌ Ошибка при отправке в Telegram: ...
```

**Решение**: 
- Проверьте правильность токена бота
- Убедитесь, что бот добавлен в канал как администратор
- Проверьте права бота на отправку сообщений

### Пост слишком длинный

```
⚠️  Telegram-пост слишком длинный (1080 символов). Обрезаем...
```

**Решение**: Функция автоматически обрезает посты до 1000 символов

## 📚 Дополнительные ресурсы

- [Документация python-telegram-bot](https://python-telegram-bot.readthedocs.io/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- [Примеры интеграции](TELEGRAM_INTEGRATION.md) 