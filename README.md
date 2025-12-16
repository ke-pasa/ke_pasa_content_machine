# Ke-Pasa Content Machine

Автоматизированная система для сбора, обработки и публикации новостного контента.

## Архитектура

Система состоит из 4 независимых workers, работающих в Docker контейнерах:

- **RSS Worker** - парсинг RSS feeds (каждые 2 часа)
- **Categorization Worker** - категоризация статей (каждые 2 часа)
- **Article Generator Worker** - генерация переведенных статей (каждые 30 минут)
- **Publisher Worker** - публикация в Telegram (каждый час с 9:00 до 23:00)

Каждый worker управляется Supervisor для автоматического перезапуска и планирования.

## Развертывание

### Требования

- Docker Engine 20.10+
- Docker Compose v2.0+
- Минимум 2GB RAM (рекомендуется 4GB)
- 10GB свободного места

### Быстрый старт

1. **Настройте GitHub Secrets** в репозитории:
   - `DEPLOY_SERVER_HOST` - IP сервера
   - `DEPLOY_SERVER_USER` - SSH пользователь
   - `DEPLOY_SSH_KEY` - SSH приватный ключ
   - `POSTGRES_URL` - PostgreSQL connection string
   - `OPENAI_API_KEY` - OpenAI API key
   - `TELEGRAM_BOT_TOKEN` - Telegram bot token
   - `TELEGRAM_CHAT_ID` - Telegram chat ID

2. **Установите Docker на сервере:**
   ```bash
   curl -fsSL https://get.docker.com -o get-docker.sh
   sudo sh get-docker.sh
   sudo usermod -aG docker $USER
   ```

3. **Задеплойте workers:**
   - Push на `main` - деплоит все workers
   - Или вручную: Actions → Deploy Workers → Run workflow

> Примечание: Dockerfile'ы перемещены в директорию `docker/`. Workflow и `docker-compose.yml` обновлены, чтобы использовать `docker/Dockerfile.*`. При ручной сборке используйте `docker build -f docker/Dockerfile.<name> .` или `docker compose build`.

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

# С временными метками
docker compose logs -f --timestamps rss-worker

# Сохранить в файл
docker compose logs rss-worker > rss-logs.txt
```

#### Supervisor Logs (внутри контейнера)

```bash
# Зайти в контейнер
docker exec -it ke-pasa-rss-worker bash

# Посмотреть логи
tail -100 /var/log/supervisor/rss-worker.log

# Live logs
tail -f /var/log/supervisor/rss-worker.log

# Статус процессов supervisor
supervisorctl status

# Выйти из контейнера
exit
```

#### Быстрая проверка логов без входа в контейнер

```bash
# Логи supervisor напрямую
docker exec ke-pasa-rss-worker tail -100 /var/log/supervisor/rss-worker.log

# Статус процессов
docker exec ke-pasa-rss-worker supervisorctl status

# Перезапустить процесс в supervisor
docker exec ke-pasa-rss-worker supervisorctl restart rss-worker
```

### Фильтрация Логов

```bash
# Только ошибки
docker compose logs | grep -i error

# Только предупреждения
docker compose logs | grep -i warn

# Поиск по тексту
docker compose logs | grep "RSS Worker"

# Логи за последние 24 часа
docker compose logs --since="24h"

# Логи между датами
docker compose logs --since="2024-12-06T10:00:00" --until="2024-12-06T12:00:00"
```

### Перезапуск Workers

```bash
# Перезапустить все workers
docker compose restart

# Перезапустить конкретный worker
docker compose restart rss-worker
docker compose restart categorization-worker
docker compose restart article-generator-worker
docker compose restart publisher-worker

# Остановить и запустить с перестройкой
docker compose down
docker compose up -d

# Пересобрать и перезапустить
docker compose build --no-cache
docker compose up -d
```

### Управление Отдельными Контейнерами

```bash
# Остановить worker
docker compose stop rss-worker

# Запустить остановленный worker
docker compose start rss-worker

# Удалить и пересоздать
docker compose rm -f rss-worker
docker compose up -d rss-worker

# Следить за ресурсами конкретного worker
docker stats ke-pasa-rss-worker
```

## Troubleshooting

### Worker не запускается

```bash
# Проверить логи
docker compose logs --tail=200 rss-worker

# Проверить внутри контейнера
docker exec -it ke-pasa-rss-worker bash
supervisorctl status
cat /var/log/supervisor/rss-worker.log
exit
```

### Worker падает сразу после старта

```bash
# Проверить переменные окружения
docker compose config

# Проверить образ
docker images | grep ke-pasa

# Пересобрать образ
docker compose build --no-cache rss-worker
docker compose up -d rss-worker
```

### Нет логов или логи не обновляются

```bash
# Проверить что контейнер работает
docker ps | grep ke-pasa-rss

# Проверить supervisor логи внутри
docker exec ke-pasa-rss-worker cat /var/log/supervisor/rss-worker.log

# Проверить процессы
docker exec ke-pasa-rss-worker ps aux
```

### Ошибки подключения к базе данных

```bash
# Проверить POSTGRES_URL
docker compose config | grep POSTGRES_URL

# Тест подключения изнутри контейнера
docker exec -it ke-pasa-rss-worker bash
python -c "import psycopg2; conn = psycopg2.connect('$POSTGRES_URL'); print('Connected!')"
exit
```

### Высокое использование памяти

```bash
# Проверить использование ресурсов
docker stats --no-stream

# Перезапустить worker
docker compose restart article-generator-worker

# Ограничить память (в docker-compose.yml)
# deploy:
#   resources:
#     limits:
#       memory: 512M
```

## Расписание Workers

| Worker | Интервал | Описание |
|--------|----------|----------|
| RSS Worker | 2 часа | Парсит RSS feeds, проверяет валидность, сохраняет статьи |
| Categorization Worker | 2 часа | Категоризирует новые статьи через OpenAI |
| Article Generator Worker | 30 минут | Генерирует переводы статей |
| Publisher Worker | Каждый час (9:00-23:00) | Публикует готовые статьи в Telegram |

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
echo "=== Recent Errors ==="
docker compose logs --since="1h" | grep -i error | tail -20
EOF

chmod +x ~/check-workers.sh

# Запускать периодически
~/check-workers.sh
```

### Автоматические уведомления о проблемах

```bash
# Добавить в crontab для проверки каждые 5 минут
crontab -e

# Добавить строку:
# */5 * * * * cd ~/ke-pasa-workers && docker compose ps | grep -q "Restarting" && echo "Worker restarting!" | mail -s "Worker Issue" your@email.com
```

## Полезные Команды

```bash
# Посмотреть все образы
docker images | grep ke-pasa

# Удалить старые образы
docker image prune -f

# Размер контейнеров
docker ps -s

# Очистить все (будьте осторожны!)
docker system prune -a

# Экспорт логов за день
docker compose logs --since="24h" > logs-$(date +%Y%m%d).txt

# Бэкап конфигурации
tar -czf ke-pasa-backup-$(date +%Y%m%d).tar.gz ~/ke-pasa-workers/docker-compose.yml ~/ke-pasa-workers/.env
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

## Дополнительная Документация

- [docs/deployment.md](docs/deployment.md) - Подробная инструкция по развертыванию
- [.github/workflows/deploy-workers.yml](.github/workflows/deploy-workers.yml) - GitHub Actions workflow

## Поддержка

При возникновении проблем:

1. Проверьте логи: `docker compose logs`
2. Проверьте статус: `docker compose ps`
3. Проверьте переменные окружения: `docker compose config`
4. Пересоберите образы: `docker compose build --no-cache`