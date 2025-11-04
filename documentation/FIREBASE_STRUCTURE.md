# 🔥 Структура Firebase для новостного ИИ-бота

## 📁 Фиксированные коллекции

Система использует строго фиксированную структуру коллекций без динамического создания:

### 1. `clusters` - Кластеры новостей
```json
{
  "cluster_id": "abc123def456",
  "topic_summary": "Изменения в визах для неработающих резидентов",
  "sources": [
    {
      "title": "Новые правила для виз",
      "link": "https://example.com/news1",
      "summary": "Описание новости..."
    }
  ],
  "combined_context": "Объединенный текст всех источников...",
  "created_at": "2025-01-29T12:00:00Z",
  "published": false,
  "source_count": 3
}
```

### 2. `articles` - Обработанные статьи
```json
{
  "title": "Переведенный заголовок",
  "description": "Описание статьи",
  "content": "Полный текст статьи",
  "tags": ["виза", "миграция"],
  "link": "https://original-article.com",
  "published": "2025-01-29",
  "image": "https://image-url.com",
  "category": "news",
  "source_feed": "Название RSS-ленты",
  "source_link": "https://original-article.com",
  "created_at": "2025-01-29T12:00:00Z"
}
```

### 3. `published` - Опубликованные кластеры
```json
{
  "cluster_id": "abc123def456",
  "published_at": "2025-01-29T12:00:00Z",
  "created_at": "2025-01-29T12:00:00Z"
}
```

### 4. `sources` - Антидублирование RSS-анонсов
```json
{
  "link": "https://example.com/news/123",
  "hash": "a1b2c3d4e5f6...",
  "title": "Заголовок новости",
  "summary": "Описание новости",
  "source_id": "diariosur",
  "feed_url": "https://diariosur.es/rss/2.0/portada/",
  "parsed_at": "2025-01-29T10:00:00Z",
  "created_at": "2025-01-29T10:00:00Z"
}
```

### 5. `skipped` - Пропущенные новости
```json
{
  "link": "https://example.com/skipped-news",
  "reason": "Не интересно для мигрантов",
  "title": "Заголовок",
  "summary": "Описание",
  "skipped_at": "2025-01-29T10:00:00Z",
  "created_at": "2025-01-29T10:00:00Z"
}
```

### 6. `jobs` - Задачи и задания
```json
{
  "job_id": "job_123",
  "type": "clustering",
  "status": "completed",
  "data": {...},
  "created_at": "2025-01-29T10:00:00Z",
  "completed_at": "2025-01-29T10:05:00Z"
}
```

### 7. `log` - Логи системы
```json
{
  "message": "Кластер сохранен: abc123def456",
  "level": "info",
  "timestamp": "2025-01-29T10:00:00Z",
  "created_at": "2025-01-29T10:00:00Z"
}
```

### 8. `settings` - Настройки системы
```json
{
  "cluster_batch_size": 20,
  "llm_model": "gpt-4o-mini",
  "publishing_times": ["09:00", "14:00", "20:00"],
  "max_articles_per_post": 2,
  "rss_check_interval_minutes": 30,
  "telegram_chat_id": "-1001234567890",
  "openai_api_key": "sk-...",
  "created_at": "2025-01-29T10:00:00Z",
  "updated_at": "2025-01-29T10:00:00Z"
}
```

## 🔧 Firebase Client API

### Основные методы

#### `save_cluster(cluster: dict) -> bool`
Сохраняет кластер в коллекцию `clusters`

#### `get_unpublished_clusters(limit=10) -> list`
Получает неопубликованные кластеры

#### `mark_cluster_as_published(cluster_id: str) -> bool`
Отмечает кластер как опубликованный

#### `is_duplicate_source(link: str) -> bool`
Проверяет дубликат источника по ссылке

#### `is_duplicate_hash(hash: str) -> bool`
Проверяет дубликат источника по хешу

#### `save_source_hash(link, title, summary, source_id, feed_url) -> bool`
Сохраняет хеш источника для антидублирования

#### `get_settings() -> dict`
Получает настройки с кэшированием

#### `log_event(message: str, level="info") -> None`
Логирует событие в коллекцию `log`

## 🔐 Индексы Firestore

Создайте следующие составные индексы в Firebase Console:

### Коллекция `clusters`
- **Поля**: `published` (по убыванию), `created_at` (по убыванию)
- **Назначение**: Получение свежих неопубликованных кластеров

### Коллекция `sources`
- **Поля**: `link` (по возрастанию)
- **Назначение**: Быстрая проверка дубликатов по ссылке
- **Поля**: `hash` (по возрастанию)
- **Назначение**: Быстрая проверка дубликатов по хешу

### Коллекция `articles`
- **Поля**: `created_at` (по убыванию)
- **Назначение**: Хронологическая сортировка статей

### Коллекция `published`
- **Поля**: `cluster_id` (по возрастанию)
- **Назначение**: Проверка опубликованных кластеров

## 📊 Настройки по умолчанию

При первом запуске система создает документ настроек в коллекции `settings`:

```json
{
  "cluster_batch_size": 20,
  "llm_model": "gpt-4o-mini",
  "publishing_times": ["09:00", "14:00", "20:00"],
  "max_articles_per_post": 2,
  "rss_check_interval_minutes": 30,
  "telegram_chat_id": "",
  "openai_api_key": ""
}
```

## 🧪 Тестирование

Запустите тесты Firebase клиента:

```bash
python test_firebase_client.py
```

Тесты покрывают:
- Сохранение и чтение кластеров
- Обнаружение дубликатов источников
- Получение настроек
- Сохранение хешей источников
- Отметку кластеров как опубликованных

## ⚠️ Важные особенности

1. **Фиксированные коллекции**: Не создаются динамически
2. **Проверка дубликатов**: Перед записью проверяются по link и hash
3. **Обработка ошибок**: Все операции обернуты в try/except
4. **Константы**: Все имена коллекций и ключей - константы
5. **Кэширование**: Настройки кэшируются на 5 минут
6. **Логирование**: Все важные события логируются в коллекцию `log` 