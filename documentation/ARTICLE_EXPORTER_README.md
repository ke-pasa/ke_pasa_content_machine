# Article Exporter - Экспорт статей из Firebase в Markdown

Модуль `article_exporter.py` предназначен для экспорта статей из Firebase Firestore в Markdown-файлы, совместимые с сайтом Astro.

## Возможности

✅ **Подключение к Firebase** - автоматическое подключение к коллекции `articles`  
✅ **Совместимость с Astro** - генерация правильного frontmatter  
✅ **Автоматическая категоризация** - распределение по папкам на основе категории  
✅ **SEO-оптимизация** - поддержка meta-тегов и ключевых слов  
✅ **Региональная навигация** - поддержка всех 19 регионов Испании  
✅ **Гибкая настройка** - возможность экспорта одной статьи или пакетного экспорта  
✅ **Предварительный просмотр** - режим dry-run для проверки  
✅ **Логирование** - подробные логи процесса экспорта  

## Установка и настройка

### 1. Зависимости

```bash
pip install firebase-admin pathlib
```

### 2. Настройка Firebase

Убедитесь, что у вас есть файл `firebase_key.json` с ключами Firebase:

```json
{
  "type": "service_account",
  "project_id": "your-project-id",
  "private_key_id": "...",
  "private_key": "...",
  "client_email": "...",
  "client_id": "...",
  "auth_uri": "https://accounts.google.com/o/oauth2/auth",
  "token_uri": "https://oauth2.googleapis.com/token",
  "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
  "client_x509_cert_url": "..."
}
```

### 3. Структура проекта

```
spain-news-portal/
├── src/
│   └── content/
│       ├── news/          # Новости
│       ├── articles/      # Статьи
│       ├── guides/        # Гайды
│       ├── legal/         # Юридические статьи
│       └── catalog/       # Каталоги
```

## Использование

### Базовый экспорт

```python
from firebase_client import FirebaseClient
from article_exporter import ArticleExporter

# Инициализация
firebase_client = FirebaseClient()
exporter = ArticleExporter(firebase_client)

# Экспорт всех статей
stats = exporter.export_articles(limit=100)
print(f"Экспортировано: {stats['success']} статей")
```

### Командная строка

```bash
# Экспорт всех статей
python article_exporter.py

# Предварительный просмотр (без сохранения)
python article_exporter.py --dry-run

# Ограничение количества статей
python article_exporter.py --limit 50

# Экспорт одной статьи по ID
python article_exporter.py --article-id "your_article_id"

# Пользовательская директория
python article_exporter.py --output-dir "custom/path"
```

### Примеры использования

```python
# Предварительный просмотр
stats = exporter.export_articles(limit=10, dry_run=True)

# Экспорт одной статьи
success = exporter.export_single_article("article_id")

# Пользовательская директория
exporter = ArticleExporter(firebase_client, output_dir="my_articles")
```

## Структура frontmatter

Модуль автоматически генерирует frontmatter в формате Astro:

```yaml
---
title: "Заголовок статьи"
description: "Описание статьи"
pubDate: "2025-01-15"
author: "Авто-редакция"
image: "/images/news/article-image.jpg"
slug: "url-friendly-slug"
category: "news"
region: "Catalonia"
tags: ["тег1", "тег2", "тег3"]
seo:
  title: "SEO заголовок"
  description: "SEO описание"
  keywords: ["ключевое", "слово", "поиск"]
telegram_post: "Ссылка на Telegram пост"
---
```

## Категоризация статей

Статьи автоматически распределяются по папкам на основе категории:

| Категория | Папка | Описание |
|-----------|-------|----------|
| `news` | `news/` | Новости |
| `society` | `news/` | Общественные новости |
| `migration` | `articles/` | Статьи о миграции |
| `economy` | `news/` | Экономические новости |
| `law` | `legal/` | Юридические статьи |
| `guides` | `guides/` | Гайды и инструкции |
| `education` | `guides/` | Образовательные материалы |
| `health` | `guides/` | Здоровье |
| `culture` | `articles/` | Культурные статьи |
| `catalog` | `catalog/` | Каталоги |

## Поддерживаемые регионы

Все 19 регионов Испании поддерживаются:

1. **Andalusia** (Андалусия)
2. **Catalonia** (Каталония)
3. **Madrid** (Мадрид)
4. **Valencia** (Валенсия)
5. **Galicia** (Галисия)
6. **Castile and León** (Кастилия и Леон)
7. **Basque Country** (Страна Басков)
8. **Castile-La Mancha** (Кастилия-Ла-Манча)
9. **Canary Islands** (Канарские острова)
10. **Murcia** (Мурсия)
11. **Aragon** (Арагон)
12. **Extremadura** (Эстремадура)
13. **Balearic Islands** (Балеарские острова)
14. **Asturias** (Астурия)
15. **Navarre** (Наварра)
16. **Cantabria** (Кантабрия)
17. **La Rioja** (Риоха)
18. **Ceuta** (Сеута)
19. **Melilla** (Мелилья)

## Обработка файлов

### Именование файлов

1. **Приоритет slug** - если есть slug, используется он
2. **Генерация из заголовка** - иначе генерируется из заголовка
3. **Обработка дубликатов** - добавляется timestamp при конфликте

### Примеры имен файлов

```
# Из slug
kak-iskat-kvartiru-v-barcelone.md

# Из заголовка
ekonomicheskii-rost-ispanii-prevysil-ozhidaniia.md

# При дубликате
article-title_20250115_143022.md
```

## Логирование

Модуль ведет подробные логи:

- **Файл**: `article_exporter.log`
- **Консоль**: вывод в реальном времени
- **Уровни**: INFO, WARNING, ERROR

### Пример логов

```
2025-01-15 14:30:22 - INFO - Создана директория: spain-news-portal/src/content/news
2025-01-15 14:30:23 - INFO - Получено 25 статей из Firebase
2025-01-15 14:30:24 - INFO - Сохранена статья: spain-news-portal/src/content/news/article.md
2025-01-15 14:30:25 - INFO - Экспорт завершен: Всего статей: 25, Успешно: 25, Ошибок: 0
```

## Обработка ошибок

### Типичные ошибки

1. **Firebase не подключен**
   ```
   ❌ Ошибка: Файл firebase_key.json не найден
   ```

2. **Нет статей в коллекции**
   ```
   ⚠️ Статьи не найдены
   ```

3. **Файл уже существует**
   ```
   ⚠️ Файл уже существует: path/to/file.md
   ```

### Рекомендации

1. **Проверьте подключение** - убедитесь, что Firebase настроен правильно
2. **Используйте dry-run** - для предварительной проверки
3. **Мониторьте логи** - для отслеживания процесса
4. **Резервное копирование** - перед массовым экспортом

## Интеграция с Astro

### Совместимость

Модуль генерирует файлы, полностью совместимые с Astro:

- ✅ Правильный frontmatter
- ✅ Поддержка всех полей схемы
- ✅ Корректная структура папок
- ✅ SEO-оптимизация

### После экспорта

1. **Проверьте файлы** - убедитесь в корректности frontmatter
2. **Запустите Astro** - `npm run dev` для проверки
3. **Проверьте навигацию** - регионы и категории должны работать
4. **SEO-анализ** - проверьте meta-теги

## Примеры

### Полный пример использования

```python
#!/usr/bin/env python3
from firebase_client import FirebaseClient
from article_exporter import ArticleExporter

def main():
    # Инициализация
    firebase_client = FirebaseClient()
    exporter = ArticleExporter(firebase_client)
    
    # Предварительный просмотр
    print("🔍 Предварительный просмотр:")
    stats = exporter.export_articles(limit=10, dry_run=True)
    print(f"Найдено статей: {stats['total']}")
    
    # Экспорт
    print("\n📤 Экспорт статей:")
    stats = exporter.export_articles(limit=50)
    print(f"Экспортировано: {stats['success']} статей")
    
    # Статистика по коллекциям
    for collection, count in stats['collections'].items():
        print(f"  {collection}: {count} статей")

if __name__ == "__main__":
    main()
```

### Запуск из командной строки

```bash
# Базовый экспорт
python article_exporter.py

# С ограничениями
python article_exporter.py --limit 20 --dry-run

# Одна статья
python article_exporter.py --article-id "abc123"
```

## Поддержка

### Требования

- Python 3.7+
- Firebase Admin SDK
- Доступ к Firebase проекту

### Файлы

- `article_exporter.py` - основной модуль
- `example_article_exporter.py` - примеры использования
- `firebase_client.py` - клиент Firebase
- `firebase_key.json` - ключи Firebase

### Логи

- `article_exporter.log` - файл логов
- Консольный вывод в реальном времени 