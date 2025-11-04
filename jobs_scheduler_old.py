#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИСПРАВЛЕННЫЙ планировщик публикаций для автоматического постинга в Telegram
Строгий почасовой режим: только в определенные часы, с проверкой интервалов
"""

import os
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
import pytz
from telegram import Bot
from telegram.error import TelegramError

from workers.tools.firebase_client import FirebaseClient, get_firebase_client
from article_ranker import rank_for_telegram
from smart_post_selector import create_smart_post_selector
from telegram_post_generator import create_telegram_post_generator


@dataclass
class PublishingWindow:
    """Окно публикации"""
    start: str  # "09:00"
    end: str    # "11:00"
    
    def is_active(self, current_time: datetime) -> bool:
        """Проверяет, активно ли окно в данное время"""
        current_time_str = current_time.strftime("%H:%M")
        return self.start <= current_time_str <= self.end


class PublicationSchedulerFixed:
    """ИСПРАВЛЕННЫЙ планировщик публикаций с строгим почасовым режимом"""
    
    def __init__(self, firebase_client: Optional[FirebaseClient] = None):
        """
        Инициализация планировщика
        
        Args:
            firebase_client: Клиент Firebase (если не указан, создается автоматически)
        """
        self.client = firebase_client or get_firebase_client()
        self.madrid_tz = pytz.timezone('Europe/Madrid')
        self.logger = self._setup_logging()
        
        # Флаг для предотвращения повторных запусков в течение часа
        self._last_publication_hour = None
        self._publication_lock = False
        
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logger = logging.getLogger('PublicationSchedulerFixed')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
            # Настройка кодировки для Windows
            if hasattr(handler.stream, 'reconfigure'):
                try:
                    handler.stream.reconfigure(encoding='utf-8')
                except:
                    pass
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def _get_settings(self) -> Dict[str, Any]:
        """Получает настройки из Firebase"""
        try:
            settings = self.client.get_settings()
            return settings
        except Exception as e:
            self.logger.error(f"Ошибка получения настроек: {e}")
            # Возвращаем дефолтные настройки
            return {
                "publishing_windows": [
                    {"start": "09:00", "end": "11:00"},
                    {"start": "12:00", "end": "14:00"},
                    {"start": "16:00", "end": "18:00"},
                    {"start": "20:00", "end": "22:00"}
                ],
                "max_articles_per_window": 1,  # Только 1 статья за окно
                "min_post_interval_minutes": 60,  # Строго 1 час между постами
                "telegram_chat_id": os.getenv('TELEGRAM_CHAT_ID', ''),
                "llm_model": "gpt-5-mini",
                "tg_daily_limit": 8,  # Максимум 8 постов в день
                "tg_slots_local": ["09:00", "10:00", "11:00", "12:00", "13:00", "14:00", "16:00", "17:00", "18:00", "20:00", "21:00", "22:00"],
                "rank_topk_llm": 15,
                "max_articles_per_session": 1,
                "weights_simple": {
                    "priority": 0.40,
                    "usefulness": 0.25,
                    "emotional": 0.20,
                    "recency": 0.10,
                    "snack": 0.05
                }
            }
    
    def _is_hourly_publication_time(self) -> bool:
        """
        Проверяет, подходит ли текущее время для почасовой публикации
        Строго по часам: 9:00, 10:00, 11:00, 12:00, 13:00, 14:00, 16:00, 17:00, 18:00, 20:00, 21:00, 22:00
        """
        current_time = datetime.now(self.madrid_tz)
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        # Разрешенные часы публикации
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22]
        
        # Проверяем, что текущий час разрешен
        if current_hour not in allowed_hours:
            return False
        
        # Проверяем, что мы в начале часа (минуты 0-5)
        if current_minute > 5:
            return False
        
        return True
    
    def _check_publication_lock(self) -> bool:
        """
        Проверяет блокировку публикации
        Предотвращает повторные публикации в течение часа
        """
        current_time = datetime.now(self.madrid_tz)
        current_hour = current_time.hour
        
        # Если это тот же час, что и последняя публикация - блокируем
        if self._last_publication_hour == current_hour:
            self.logger.info(f"🔒 Публикация заблокирована для часа {current_hour}:00 (уже публиковали)")
            return False
        
        # Если публикация заблокирована - проверяем, не прошло ли время
        if self._publication_lock:
            # Снимаем блокировку в начале нового часа
            if current_minute < 5:
                self._publication_lock = False
                self.logger.info(f"🔓 Блокировка публикации снята для часа {current_hour}:00")
            else:
                self.logger.info(f"🔒 Публикация заблокирована (активна блокировка)")
                return False
        
        return True
    
    def _get_fresh_unpublished_articles(self) -> List[Dict[str, Any]]:
        """Возвращает кандидатов для Telegram-ранжирования"""
        try:
            articles_ref = self.client.db.collection('articles')

            # Строгий фильтр под новую логику:
            # - не опубликованы
            # - экспортированы на сайт (готовый контент)
            try:
                query = (
                    articles_ref
                    .where('published', '==', False)
                    .where('exported_to_site', '==', True)
                )
                docs = query.stream()
            except Exception:
                # На случай, если индексы не настроены — мягкий fallback: вручную фильтруем
                docs = articles_ref.stream()

            candidates: List[Dict[str, Any]] = []
            for doc in docs:
                data = doc.to_dict() or {}
                data['id'] = doc.id

                if not data.get('published', False) and data.get('exported_to_site', False):
                    candidates.append(data)

            self.logger.info(
                f"Кандидатов для ранжирования (экспортированные, не опубликованные): {len(candidates)}"
            )
            return candidates

        except Exception as e:
            self.logger.error(f"Ошибка получения статей для ранжирования: {e}")
            return []
    
    def _rank_articles_for_telegram(self, articles: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ранжирует статьи для публикации в Telegram"""
        try:
            if not articles:
                return []
            
            # Простое ранжирование по приоритету и срочности
            ranked_articles = []
            
            for article in articles:
                # Базовый рейтинг
                priority_score = float(article.get('priority_score', 0) or 0)
                urgent_bonus = 100 if article.get('urgent', False) else 0
                
                # Создаем рейтинг
                ranking_score = priority_score + urgent_bonus
                
                # Добавляем к статье
                article_copy = article.copy()
                article_copy['ranking_score'] = ranking_score
                ranked_articles.append(article_copy)
            
            # Сортируем по рейтингу (убывание)
            ranked_articles.sort(key=lambda x: x.get('ranking_score', 0), reverse=True)
            
            self.logger.info(f"📈 Ранжировано {len(ranked_articles)} статей")
            return ranked_articles
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка ранжирования статей: {e}")
            return articles  # Возвращаем исходный список при ошибке
    
    def _can_publish_now(self, settings: Dict[str, Any], is_urgent: bool = False) -> bool:
        """
        Проверяет, можно ли публиковать сейчас
        Строгая проверка времени и интервалов
        """
        if is_urgent:
            # Срочные публикации всегда разрешены
            return True
        
        # Проверяем, подходит ли время для почасовой публикации
        if not self._is_hourly_publication_time():
            self.logger.info("⏰ Сейчас не время для почасовой публикации")
            return False
        
        # Проверяем блокировку публикации
        if not self._check_publication_lock():
            return False
        
        # Проверяем интервал между постами
        last_post_time = self._get_last_post_time()
        if last_post_time:
            min_interval = settings.get('min_post_interval_minutes', 60)
            time_since_last = datetime.now(self.madrid_tz) - last_post_time
            if time_since_last < timedelta(minutes=min_interval):
                self.logger.info(f"⏰ Не прошло достаточно времени с последней публикации ({min_interval} мин)")
                return False
        
        return True
    
    def _get_last_post_time(self) -> Optional[datetime]:
        """Получает время последней публикации"""
        try:
            logs_ref = self.client.db.collection('log')
            docs = logs_ref.where('message', '==', 'publication_success').limit(500).stream()
            timestamps: List[str] = []
            for d in docs:
                data = d.to_dict()
                ts = data.get('timestamp')
                if ts:
                    # нормализуем к ISO
                    ts_norm = ts.replace('Z', '+00:00')
                    timestamps.append(ts_norm)
            if not timestamps:
                return None
            timestamps.sort(reverse=True)
            return datetime.fromisoformat(timestamps[0]).replace(tzinfo=pytz.UTC).astimezone(self.madrid_tz)
        except Exception as e:
            self.logger.error(f"Ошибка получения времени последней публикации: {e}")
            return None
    
    def _send_telegram_post(self, article: Dict[str, Any], settings: Dict[str, Any]) -> bool:
        """Отправляет Telegram-пост"""
        try:
            # Получаем токен бота
            bot_token = settings.get('telegram_bot_token') or os.environ.get('TELEGRAM_BOT_TOKEN')
            
            if bot_token and bot_token.startswith('ENV:'):
                env_var_name = bot_token.replace('ENV:', '')
                bot_token = os.environ.get(env_var_name)
            
            if not bot_token or bot_token == 'PLACEHOLDER_TOKEN':
                self.logger.error("TELEGRAM_BOT_TOKEN не установлен или является placeholder")
                return False
            
            # Получаем ID чата
            chat_id = settings.get('telegram_chat_id') or os.environ.get('TELEGRAM_CHAT_ID')
            if not chat_id:
                self.logger.error("TELEGRAM_CHAT_ID не установлен")
                return False
            
            # Проверяем наличие готового Telegram-поста
            telegram_post = article.get('telegram_post')
            if not telegram_post:
                self.logger.error("Telegram-пост не найден в статье")
                return False
            
            post_length = len(telegram_post)
            self.logger.info(f"📝 Использую готовый Telegram-пост ({post_length} символов)")
            
            # Проверяем длину поста для изображения
            if post_length > 1000:
                self.logger.warning(f"⚠️ Пост превышает лимит в 1000 символов ({post_length}), отправляю без изображения")
                has_image = False
            else:
                # Получаем изображение из источника
                image_url = article.get('image', '')
                has_image = image_url and self._is_valid_image_url(image_url)
                if has_image:
                    self.logger.info(f"🖼️ Найдено изображение: {image_url[:100]}...")
            
            # Создаем бота
            bot = Bot(token=bot_token)
            
            # Отправляем пост
            if has_image and post_length <= 1000:
                try:
                    import requests
                    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    html_caption = self._convert_markdown_to_html(telegram_post)
                    
                    data = {
                        'chat_id': chat_id,
                        'photo': image_url,
                        'caption': html_caption,
                        'parse_mode': 'HTML'
                    }
                    response = requests.post(url, data=data, timeout=30)
                    
                    if response.status_code == 200:
                        self.logger.info(f"✅ Telegram-пост с изображением отправлен в чат {chat_id}")
                        return True
                    else:
                        self.logger.warning(f"⚠️ Ошибка отправки изображения: {response.status_code}")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ Не удалось отправить с изображением: {e}")
            
            # Отправляем только текст (fallback)
            try:
                import requests
                html_post = self._convert_markdown_to_html(telegram_post)
                
                url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                data = {
                    'chat_id': chat_id,
                    'text': html_post,
                    'parse_mode': 'HTML',
                    'disable_web_page_preview': True
                }
                response = requests.post(url, data=data, timeout=30)
                
                if response.status_code == 200:
                    self.logger.info(f"✅ Telegram-пост отправлен в чат {chat_id} (без изображения)")
                    return True
                else:
                    self.logger.error(f"❌ Ошибка отправки текста: {response.status_code} - {response.text[:200]}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"❌ Ошибка отправки текста: {e}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка отправки: {e}")
            return False
    
    def _convert_markdown_to_html(self, markdown_text: str) -> str:
        """Конвертирует Markdown в HTML для Telegram"""
        try:
            # Простая конвертация основных элементов
            html = markdown_text
            
            # Жирный текст
            html = html.replace('**', '<b>').replace('**', '</b>')
            
            # Курсив
            html = html.replace('*', '<i>').replace('*', '</i>')
            
            # Списки
            html = html.replace('• ', '• ')
            html = html.replace('- ', '• ')
            
            # Ссылки (простая замена)
            html = html.replace('[', '').replace(']', '')
            
            return html
            
        except Exception as e:
            self.logger.warning(f"Ошибка конвертации Markdown в HTML: {e}")
            return markdown_text
    
    def _is_valid_image_url(self, url: str) -> bool:
        """Проверяет валидность URL изображения"""
        if not url:
            return False
        
        # Простые проверки
        if not url.startswith(('http://', 'https://')):
            return False
        
        # Проверяем расширения изображений
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp']
        if not any(ext in url.lower() for ext in image_extensions):
            return False
        
        return True
    
    def _mark_article_as_published(self, article: Dict[str, Any]) -> bool:
        """Отмечает статью как опубликованную"""
        try:
            # Пробуем получить ID статьи разными способами
            article_id = article.get('article_id') or article.get('id') or article.get('document_id')
            if not article_id:
                self.logger.error("ID статьи не найден в полях: article_id, id, document_id")
                return False
            
            # Обновляем обычную статью
            articles_ref = self.client.db.collection('articles').document(article_id)
            articles_ref.update({
                'published': True,
                'published_at': datetime.now(self.madrid_tz).isoformat()
            })
            
            # Сохраняем в коллекцию published
            published_data = {
                'article_id': article_id,
                'cluster_id': article.get('cluster_id'),
                'title': article.get('title'),
                'published_at': datetime.now(self.madrid_tz).isoformat(),
                'created_at': datetime.now(self.madrid_tz).isoformat()
            }
            
            self.client.db.collection('published').add(published_data)
            
            # Логируем успешную публикацию
            self.client.log_event(
                f"publication_success: {article.get('title', 'Unknown')}",
                "info"
            )
            
            self.logger.info(f"✅ Статья {article_id} отмечена как опубликованная")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка отметки статьи как опубликованной: {e}")
            return False
    
    def run_hourly_publication(self):
        """
        Запускает почасовую публикацию по 1 посту
        СТРОГО каждый час в разрешенное время
        """
        try:
            self.logger.info("🚀 Запуск почасовой публикации (ИСПРАВЛЕННАЯ ВЕРСИЯ)")
            
            # Получаем настройки
            settings = self._get_settings()
            
            # Проверяем, можем ли публиковать сейчас
            if not self._can_publish_now(settings, is_urgent=False):
                self.logger.info("⏰ Публикация не разрешена")
                return
            
            # Получаем текущее время
            current_time = datetime.now(self.madrid_tz)
            current_hour = current_time.hour
            
            self.logger.info(f"📝 Начинаю публикацию для часа {current_hour}:00")
            
            # Устанавливаем блокировку для этого часа
            self._publication_lock = True
            self._last_publication_hour = current_hour
            
            # Получаем неопубликованные статьи
            articles = self._get_fresh_unpublished_articles()
            if not articles:
                self.logger.warning("⚠️ Нет неопубликованных статей для публикации")
                return
            
            self.logger.info(f"📊 Найдено {len(articles)} кандидатов для публикации")
            
            # Ранжируем статьи
            ranked_articles = self._rank_articles_for_telegram(articles, settings)
            if not ranked_articles:
                self.logger.warning("⚠️ Не удалось ранжировать статьи")
                return
            
            self.logger.info(f"📈 Ранжировано {len(ranked_articles)} статей")
            
            # Выбираем 1 лучшую статью
            best_article = ranked_articles[0]
            self.logger.info(f"🏆 Выбрана лучшая статья: {best_article.get('title', 'Unknown')[:50]}")
            
            # Генерируем Telegram-пост
            telegram_generator = create_telegram_post_generator()
            
            # Создаем URL для статьи
            slug = best_article.get('slug', '')
            if not slug:
                # Создаем slug из заголовка
                title = best_article.get('title', '')
                if title:
                    import re
                    clean_title = re.sub(r'[^\w\sа-яёА-ЯЁ]', '', title)
                    title_words = clean_title.split()[:5]
                    slug = '-'.join(word.lower() for word in title_words if word)
                    if len(slug) > 60:
                        slug = slug[:60].rstrip('-')
                else:
                    slug = 'news'
            
            article_url = f"https://spain-que-pasa.com/news/{slug}/"
            
            # Генерируем пост
            telegram_post = telegram_generator.generate_post(best_article, article_url)
            if not telegram_post:
                self.logger.error("❌ Не удалось сгенерировать Telegram-пост")
                return
            
            # Добавляем пост к статье
            best_article['telegram_post'] = telegram_post
            
            # Публикуем пост
            if self._send_telegram_post(best_article, settings):
                self.logger.info(f"✅ Пост успешно опубликован в {current_hour}:00")
                
                # Отмечаем статью как опубликованную
                if self._mark_article_as_published(best_article):
                    self.logger.info("✅ Статья отмечена как опубликованную")
                else:
                    self.logger.warning("⚠️ Не удалось отметить статью как опубликованную")
            else:
                self.logger.error("❌ Ошибка публикации поста")
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка почасовой публикации: {e}")
            import traceback
            traceback.print_exc()

    def run(self):
        """
        Основной метод запуска планировщика
        Строго почасовая публикация
        """
        try:
            self.logger.info("🚀 Запуск ИСПРАВЛЕННОГО планировщика публикаций")
            
            # Запускаем почасовую публикацию
            self.run_hourly_publication()
            
            self.logger.info("✅ Планировщик завершил работу")
            
            return {
                'total_articles_checked': 1,
                'articles_published': 1 if self._publication_lock else 0,
                'urgent_published': 0,
                'regular_published': 1 if self._publication_lock else 0,
                'skipped_outside_window': 0,
                'skipped_interval': 0,
                'skipped_limit': 0,
                'errors': []
            }
            
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка планировщика: {e}")
            import traceback
            traceback.print_exc()
            
            return {
                'total_articles_checked': 0,
                'articles_published': 0,
                'urgent_published': 0,
                'regular_published': 0,
                'skipped_outside_window': 0,
                'skipped_interval': 0,
                'skipped_limit': 0,
                'errors': [str(e)]
            }


def main():
    """Точка входа для запуска исправленного планировщика"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ИСПРАВЛЕННЫЙ планировщик публикаций для Telegram')
    parser.add_argument('--run', action='store_true', help='Запустить планировщик')
    parser.add_argument('--test', action='store_true', help='Тестовый режим')
    
    args = parser.parse_args()
    
    if args.run or args.test:
        scheduler = PublicationSchedulerFixed()
        results = scheduler.run()
        
        print("\n📊 Результаты выполнения ИСПРАВЛЕННОГО планировщика:")
        print(f"   Всего статей проверено: {results['total_articles_checked']}")
        print(f"   Опубликовано: {results['articles_published']}")
        print(f"   Срочных: {results['urgent_published']}")
        print(f"   Обычных: {results['regular_published']}")
        print(f"   Пропущено (вне окна): {results['skipped_outside_window']}")
        print(f"   Пропущено (интервал): {results['skipped_interval']}")
        print(f"   Пропущено (лимит): {results['skipped_limit']}")
        
        if results['errors']:
            print(f"\n❌ Ошибки ({len(results['errors'])}):")
            for error in results['errors']:
                print(f"   - {error}")
        else:
            print("\n✅ Ошибок нет")
    else:
        print("Используйте --run для запуска планировщика или --test для тестового режима")


if __name__ == "__main__":
    main()
