# Ke-Pasa Content Machine

Автоматизированная система для сбора, обработки и публикации новостного контента о Испании на русском языке.

## Архитектура

Система состоит из 6 независимых workers, работающих в Docker контейнерах:

- **RSS Worker** - парсинг RSS feeds из испанских источников (каждые 40 минут)
- **Categorization Worker** - категоризация статей через OpenAI (каждые 40 минут)
- **Article Generator Worker** - перевод и генерация статей (каждые 30 минут)
- **Publisher Worker** - публикация в социальные сети (каждые 45 минут с 9:00 до 23:00 Madrid time)
- **Digest Worker** - генерация еженедельных дайджестов (по расписанию)
- **Events Importer Worker** - импорт событий из Telegram каналов (каждые 4 часа)

Каждый worker управляется Supervisor для автоматического перезапуска и планирования.

## Публикация в Социальные Сети

Publisher Worker автоматически публикует статьи на **6 платформах**:

| Платформа | Формат контента | Особенности |
|-----------|----------------|-------------|
| **Telegram** | HTML (bold, italic, links) | Основная платформа, полный текст |
| **X (Twitter)** | `description_ru` + ссылка | Краткое описание, до 280 символов |
| **Instagram** | Изображение 4:5 + plain text | **Авто-обработка**: 1080×1350px, title overlay (Bebas Neue 50pt) |
| **Facebook** | `telegram_final` → plain text | Полный текст с кликабельной ссылкой |
| **Threads** | `description_ru` + ссылка | Формат как X, использует Facebook credentials |
| **Сайт** | Полная статья | ke-pasa.es |

> **Instagram Image Processing:** Изображения автоматически обрабатываются перед публикацией:
> - Формат: 4:5 (1080×1350px) - оптимален для Instagram feed
> - Title overlay: заголовок накладывается поверх с шрифтом Bebas Neue (50pt, bold)
> - Градиент: полупрозрачный фон для читаемости текста
> - High-score статьи (>95): публикуются как видео (REELS)
> - Подробнее: [docs/instagram_image_setup.md](docs/instagram_image_setup.md)

### Credentials для социальных сетей

**Telegram:**
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

**X (Twitter):**
- `X_CLIENT_ID`
- `X_CLIENT_SECRET`
- OAuth 2.0 tokens (auto-refresh)

**Meta Platforms (Facebook/Instagram/Threads):**
- `FACEBOOK_APP_ID` - используется для всех Meta платформ
- `FACEBOOK_APP_SECRET` - используется для всех Meta платформ
- `FACEBOOK_PAGE_ID` - Facebook Page ID
- `FACEBOOK_PAGE_ACCESS_TOKEN` - long-lived token для Facebook
- `INSTAGRAM_USER_ID` - Instagram Business User ID
- `INSTAGRAM_ACCESS_TOKEN` - Instagram Business Access Token
- `THREADS_USER_ID` - Threads User ID (отличается от Instagram ID)
- `THREADS_ACCESS_TOKEN` - Threads API Access Token

> **Note:** Threads требует отдельный User ID, который отличается от Instagram User ID даже для одного и того же аккаунта. Используйте `tools/get_threads_user_id.py` для получения вашего Threads User ID.

### Health Check

Проверить работоспособность всех интеграций:

```bash
# На сервере
docker exec ke-pasa-publisher-worker python -m workers.publisher.worker --health-check

# Локально
python -m workers.publisher.worker --health-check
```

Результат:
```
🏥 Starting Integrations Health Check
================================================

📱 Checking Telegram...
✅ Telegram: OK (bot: @kepasa_bot)

𝕏 Checking X (Twitter)...
✅ X (Twitter): OK (token valid)

🟣 Checking Instagram...
✅ Instagram: OK (user: @kepasa.es)

🔵 Checking Facebook...
✅ Facebook: OK (page: Ke-Pasa)

🧵 Checking Threads...
✅ Threads: OK (user: @kepasa.es, using Facebook credentials)

🗄️ Checking Database (PostgreSQL)...
✅ Database: OK (15 articles ready to publish)

================================================
📊 HEALTH CHECK SUMMARY
================================================
Overall Status: HEALTHY
Healthy Platforms: 6/6
  ✅ Telegram: healthy
  ✅ X: healthy
  ✅ Instagram: healthy
  ✅ Facebook: healthy
  ✅ Threads: healthy
  ✅ Database: healthy
```

## Развертывание

### Требования

- Docker Engine 20.10+
- Docker Compose v2.0+
- Минимум 2GB RAM (рекомендуется 4GB)
- 10GB свободного места

### Быстрый старт

1. **Настройте GitHub Secrets** в репозитории:

   **Обязательные:**
   - `DEPLOY_SERVER_HOST` - IP сервера
   - `DEPLOY_SERVER_USER` - SSH пользователь
   - `DEPLOY_SSH_KEY` - SSH приватный ключ
   - `POSTGRES_URL` - PostgreSQL connection string
   - `OPENAI_API_KEY` - OpenAI API key
   - `TELEGRAM_BOT_TOKEN` - Telegram bot token
   - `TELEGRAM_CHAT_ID` - Telegram chat ID

   **Для X (Twitter):**
   - `X_CLIENT_ID` - OAuth 2.0 Client ID
   - `X_CLIENT_SECRET` - OAuth 2.0 Client Secret
   - `X_TOKENS_BASE64` - Base64-encoded tokens JSON (auto-refresh)

   **Для Meta (Facebook/Instagram/Threads):**
   - `FACEBOOK_APP_ID` - Facebook App ID
   - `FACEBOOK_APP_SECRET` - Facebook App Secret
   - `FACEBOOK_PAGE_ID` - Facebook Page ID
   - `FACEBOOK_PAGE_ACCESS_TOKEN` - Long-lived Page Access Token
   - `INSTAGRAM_USER_ID` - Instagram Business Account ID

   **Для Telethon (опционально):**
   - `TELETHON_API_ID` - Telegram API ID
   - `TELETHON_API_HASH` - Telegram API Hash
   - `TELETHON_SESSION_STRING` - String session (для импорта событий)

   Note: Для генерации string session:
   ```bash
   python - <<'PY'
   from telethon import TelegramClient
   from telethon.sessions import StringSession
   import os
   api_id = int(os.environ['TELETHON_API_ID'])
   api_hash = os.environ['TELETHON_API_HASH']
   with TelegramClient(StringSession(), api_id, api_hash) as client:
      print('TELETHON_SESSION_STRING=' + client.session.save())
   PY
   ```

2. **Установите Docker на сервере:**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

3. **Задеплойте workers:**
   - Push на `main` - деплоит все workers
   - Или вручную: Actions → Deploy Workers → Run workflow → выберите workers для деплоя

## Управление Контейнерами

### Проверка Статуса

```bash
# SSH к серверу
ssh user@server-ip
cd ~/ke-pasa-workers

# Статус всех контейнеров
docker compose ps

# Только работающие
docker ps | grep ke-pasa

# Использование ресурсов
docker stats --no-stream
```

**Ожидаемый вывод:**
```
NAME                               STATUS
ke-pasa-rss-worker                 Up 2 hours
ke-pasa-categorization-worker      Up 2 hours
ke-pasa-article-generator-worker   Up 2 hours
ke-pasa-publisher-worker           Up 2 hours
ke-pasa-digest-worker              Up 2 hours
ke-pasa-events-importer-worker     Up 2 hours
```

### Просмотр Логов

#### Docker Logs (рекомендуется)

```bash
# Все workers вместе (live)
docker compose logs -f

# Последние 100 строк всех workers
docker compose logs --tail=100

# Конкретный worker
docker compose logs -f rss-worker
docker compose logs -f categorization-worker
docker compose logs -f article-generator-worker
docker compose logs -f publisher-worker
docker compose logs -f digest-worker
docker compose logs -f events-importer-worker

# С временными метками
docker compose logs -f --timestamps publisher-worker

# Сохранить в файл
docker compose logs publisher-worker > publisher-logs.txt
```

#### Supervisor Logs (внутри контейнера)

```bash
# Зайти в контейнер
docker exec -it ke-pasa-publisher-worker bash

# Посмотреть логи
tail -100 /var/log/supervisor/publisher-worker.log

# Live logs
tail -f /var/log/supervisor/publisher-worker.log

# Статус процессов supervisor
supervisorctl status

# Выйти из контейнера
exit
```

### Фильтрация Логов

```bash
# Только ошибки
docker compose logs | grep -i error

# Только предупреждения
docker compose logs | grep -i warn

# Успешные публикации
docker compose logs publisher-worker | grep "✅ Published"

# Логи публикаций в Threads
docker compose logs publisher-worker | grep "🧵"

# Логи за последние 24 часа
docker compose logs --since="24h"
```

### Перезапуск Workers

```bash
# Перезапустить все workers
docker compose restart

# Перезапустить конкретный worker
docker compose restart publisher-worker

# Остановить и запустить с перестройкой
docker compose down
docker compose up -d

# Пересобрать и перезапустить (после обновления кода)
docker compose build --no-cache publisher-worker
docker compose up -d publisher-worker
```

## Расписание Workers

| Worker | Интервал | Время работы | Описание |
|--------|----------|--------------|----------|
| RSS Worker | 40 минут | 24/7 | Парсит RSS feeds испанских источников |
| Categorization Worker | 40 минут | 24/7 | Категоризирует статьи через OpenAI |
| Article Generator Worker | 30 минут | 24/7 | Переводит статьи на русский |
| Publisher Worker | 45 минут | **9:00-23:00 Madrid** | Публикует в 6 социальных сетей |
| Digest Worker | По расписанию | Выходные | Генерирует еженедельные дайджесты |
| Events Importer Worker | 4 часа | 24/7 | Импортирует события из Telegram |

> **Note:** Publisher Worker автоматически пропускает ночные часы (23:00-09:00 Madrid time) для соблюдения "тишины".

## Troubleshooting

### Publisher Worker не публикует

```bash
# Проверить health check
docker exec ke-pasa-publisher-worker python -m workers.publisher.worker --health-check

# Проверить логи
docker compose logs --tail=200 publisher-worker

# Проверить статус социальных сетей в логах
docker compose logs publisher-worker | grep -E "(✅|❌)"
```

### Ошибки публикации в Threads

```bash
# Проверить Facebook credentials (Threads использует их)
docker compose config | grep -E "(FACEBOOK_|INSTAGRAM_USER_ID)"

# Threads API может требовать время для обработки
# Проверить логи на наличие "Failed to create Threads container"
docker compose logs publisher-worker | grep "🧵"
```

### X (Twitter) token истек

```bash
# Проверить логи
docker compose logs publisher-worker | grep "X token"

# X tokens обновляются автоматически
# Если нужно обновить вручную, используйте tools/x_oauth_refresh.py
```

### Ошибки Meta platforms (Facebook/Instagram/Threads)

```bash
# Все Meta платформы используют одинаковые credentials
# Проверить long-lived token
docker compose config | grep FACEBOOK_PAGE_ACCESS_TOKEN

# Проверить срок действия токена через Graph API Explorer
# https://developers.facebook.com/tools/explorer/
```

## Мониторинг

### Базовый мониторинг

```bash
# Создать скрипт для проверки
cat > ~/check-workers.sh << 'EOF'
#!/bin/bash
cd ~/ke-pasa-workers
echo "=== Worker Status ==="
docker compose ps
echo ""
echo "=== Resource Usage ==="
docker stats --no-stream | grep ke-pasa
echo ""
echo "=== Recent Publications ==="
docker compose logs --since="1h" publisher-worker | grep "✅ Published" | tail -10
echo ""
echo "=== Recent Errors ==="
docker compose logs --since="1h" | grep -i error | tail -20
EOF

chmod +x ~/check-workers.sh

# Запускать периодически
~/check-workers.sh
```

### Проверка публикаций

```bash
# Сколько статей опубликовано за последние 24 часа
docker compose logs --since="24h" publisher-worker | grep "✅ Published" | wc -l

# Статистика по платформам
docker compose logs --since="24h" publisher-worker | grep -E "(Telegram|Instagram|Facebook|Threads|Twitter)" | grep "successful"
```

## Полезные Команды

```bash
# Посмотреть все образы
docker images | grep ke-pasa

# Удалить старые образы
docker image prune -f

# Размер контейнеров
docker ps -s

# Экспорт логов за день
docker compose logs --since="24h" > logs-$(date +%Y%m%d).txt

# Бэкап конфигурации
tar -czf ke-pasa-backup-$(date +%Y%m%d).tar.gz ~/ke-pasa-workers/docker-compose.yml ~/ke-pasa-workers/.env

# Проверить переменные окружения publisher worker
docker exec ke-pasa-publisher-worker env | grep -E "(FACEBOOK|INSTAGRAM|THREADS|TELEGRAM|X_)"
```

## Обновление Workers

### Автоматическое (через GitHub Actions)

1. Внеси изменения в код
2. Commit и push на `main`
3. GitHub Actions автоматически задеплоит обновления

### Ручное обновление на сервере

```bash
cd ~/ke-pasa-workers

# Получить последний код
git pull origin main

# Пересобрать образы
docker compose build --no-cache

# Перезапустить workers
docker compose down
docker compose up -d

# Проверить статус
docker compose ps
docker compose logs --tail=50
```

### Обновление только Publisher Worker

```bash
cd ~/ke-pasa-workers

# Остановить publisher
docker compose stop publisher-worker

# Пересобрать
docker compose build --no-cache publisher-worker

# Запустить
docker compose up -d publisher-worker

# Проверить
docker compose logs -f publisher-worker
```

## Структура Проекта

```
ke-pasa-content-machine/
├── docker/                      # Docker конфигурации
│   ├── Dockerfile.base         # Базовый образ
│   ├── Dockerfile.rss          # RSS Worker
│   ├── Dockerfile.categorization
│   ├── Dockerfile.article_generator
│   ├── Dockerfile.publisher    # Publisher Worker (6 социальных сетей)
│   ├── Dockerfile.digest
│   └── Dockerfile.events_importer
├── workers/
│   ├── rss/                    # RSS Worker
│   ├── categorization/         # Categorization Worker
│   ├── article_generator/      # Article Generator Worker
│   ├── publisher/              # Publisher Worker
│   │   ├── worker.py          # Main worker с health check
│   │   └── config.py          # Configuration
│   ├── digest/                # Digest Worker
│   ├── events_importer/       # Events Importer Worker
│   └── tools/
│       ├── telegram_helper.py  # Telegram API
│       ├── x_helper.py         # X (Twitter) API с auto-refresh
│       ├── instagram_helper.py # Instagram API
│       ├── facebook_helper.py  # Facebook API
│       ├── threads_helper.py   # Threads API (uses Facebook creds)
│       └── pg_client.py        # PostgreSQL client
├── deploy/
│   └── docker/
│       └── supervisord.conf.*  # Supervisor configs
├── .github/
│   └── workflows/
│       └── deploy-workers.yml  # CI/CD pipeline
├── docker-compose.yml          # Docker Compose config
├── .env                        # Environment variables (не в git)
└── README.md                   # Эта документация
```

## Дополнительная Документация

- [docs/deployment.md](docs/deployment.md) - Подробная инструкция по развертыванию
- [.github/workflows/deploy-workers.yml](.github/workflows/deploy-workers.yml) - GitHub Actions workflow
- [workers/publisher/README.md](workers/publisher/README.md) - Документация Publisher Worker

## Поддержка

При возникновении проблем:

1. **Проверьте health check:** `docker exec ke-pasa-publisher-worker python -m workers.publisher.worker --health-check`
2. **Проверьте логи:** `docker compose logs publisher-worker`
3. **Проверьте статус:** `docker compose ps`
4. **Проверьте переменные окружения:** `docker compose config`
5. **Пересоберите образы:** `docker compose build --no-cache`

## License

Proprietary - Ke-Pasa Project