#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль планировщика публикаций для автоматического постинга в Telegram
Управляет очередью публикаций на основе расписания, приоритетов и срочности
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

from firebase_client import FirebaseClient, get_firebase_client


@dataclass
class PublishingWindow:
    """Окно публикации"""
    start: str  # "09:00"
    end: str    # "11:00"
    
    def is_active(self, current_time: datetime) -> bool:
        """Проверяет, активно ли окно в данное время"""
        current_time_str = current_time.strftime("%H:%M")
        return self.start <= current_time_str <= self.end


class PublicationScheduler:
    """Планировщик публикаций для автоматического постинга в Telegram"""
    
    def __init__(self, firebase_client: Optional[FirebaseClient] = None):
        """
        Инициализация планировщика
        
        Args:
            firebase_client: Клиент Firebase (если не указан, создается автоматически)
        """
        self.client = firebase_client or get_firebase_client()
        self.madrid_tz = pytz.timezone('Europe/Madrid')
        self.logger = self._setup_logging()
        
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logger = logging.getLogger('PublicationScheduler')
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
                    {"start": "14:00", "end": "16:00"},
                    {"start": "20:00", "end": "22:00"}
                ],
                "max_articles_per_window": 2,
                "min_post_interval_minutes": 30,
                "telegram_chat_id": os.getenv('TELEGRAM_CHAT_ID', ''),
                "llm_model": "gpt-4o-mini"
            }
    
    def _get_current_window(self, settings: Dict[str, Any]) -> Optional[PublishingWindow]:
        """Определяет текущее окно публикации"""
        current_time = datetime.now(self.madrid_tz)
        windows = settings.get('publishing_windows', [])
        
        for window_data in windows:
            window = PublishingWindow(
                start=window_data['start'],
                end=window_data['end']
            )
            if window.is_active(current_time):
                return window
        
        return None
    
    def _can_publish_now(self, settings: Dict[str, Any], is_urgent: bool = False) -> bool:
        """
        Проверяет, можно ли публиковать сейчас
        
        Args:
            settings: Настройки системы
            is_urgent: Срочная публикация
            
        Returns:
            True если можно публиковать
        """
        if is_urgent:
            # Срочные публикации всегда разрешены
            return True
        
        # Проверяем текущее окно
        current_window = self._get_current_window(settings)
        if not current_window:
            self.logger.info("Сейчас не время для публикации (вне окон)")
            return False
        
        # Проверяем интервал между постами
        last_post_time = self._get_last_post_time()
        if last_post_time:
            min_interval = settings.get('min_post_interval_minutes', 30)
            time_since_last = datetime.now(self.madrid_tz) - last_post_time
            if time_since_last < timedelta(minutes=min_interval):
                self.logger.info(f"Не прошло достаточно времени с последней публикации ({min_interval} мин)")
                return False
        
        # Проверяем лимит публикаций в текущем окне
        if not self._check_window_limit(settings):
            self.logger.info("Достигнут лимит публикаций в текущем окне")
            return False
        
        return True
    
    def _get_last_post_time(self) -> Optional[datetime]:
        """Получает время последней публикации (без серверной сортировки)"""
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
    
    def _check_window_limit(self, settings: Dict[str, Any]) -> bool:
        """Проверяет лимит публикаций в текущем окне"""
        try:
            current_window = self._get_current_window(settings)
            if not current_window:
                return False
            
            max_articles = settings.get('max_articles_per_window', 2)
            current_time = datetime.now(self.madrid_tz)
            
            # Получаем количество публикаций в текущем окне
            window_start = current_time.replace(
                hour=int(current_window.start.split(':')[0]),
                minute=int(current_window.start.split(':')[1]),
                second=0,
                microsecond=0
            )
            
            logs_ref = self.client.db.collection('log')
            query = logs_ref.where('message', '==', 'publication_success').where('timestamp', '>=', window_start.isoformat())
            docs = list(query.stream())
            
            return len(docs) < max_articles
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки лимита окна: {e}")
            return True  # В случае ошибки разрешаем публикацию
    
    def _check_post_interval(self, settings: Dict[str, Any]) -> bool:
        """Проверяет интервал между постами"""
        try:
            last_post_time = self._get_last_post_time()
            if last_post_time:
                min_interval = settings.get('min_post_interval_minutes', 30)
                time_since_last = datetime.now(self.madrid_tz) - last_post_time
                if time_since_last < timedelta(minutes=min_interval):
                    return False
            return True
        except Exception as e:
            self.logger.error(f"Ошибка проверки интервала: {e}")
            return True  # В случае ошибки разрешаем публикацию
    
    def _get_unpublished_articles(self) -> List[Dict[str, Any]]:
        """Получает неопубликованные статьи для публикации"""
        try:
            # Получаем обычные статьи
            articles_ref = self.client.db.collection('articles')
            docs = articles_ref.limit(500).stream()

            items: List[Dict[str, Any]] = []
            urgent_items: List[Dict[str, Any]] = []
            
            for d in docs:
                data = d.to_dict()
                data['article_id'] = d.id
                
                # Фильтруем неопубликованные статьи на клиенте
                if not data.get('published', False):
                    # Разделяем на срочные и обычные
                    if data.get('urgent', False):
                        urgent_items.append(data)
                    else:
                        items.append(data)
            
            # Получаем сгенерированные статьи
            generated_articles_ref = self.client.db.collection('generated_articles')
            generated_docs = generated_articles_ref.limit(100).stream()
            
            for d in generated_docs:
                data = d.to_dict()
                
                # Фильтруем неопубликованные сгенерированные статьи
                if not data.get('published', False):
                    # Преобразуем в формат для публикации
                    generated_article = {
                        'article_id': d.id,
                        'title': data.get('title', 'Сгенерированная статья'),
                        'summary': data.get('summary', ''),
                        'link': data.get('source_link', ''),
                        'image': data.get('image', ''),
                        'categories': ['сгенерированная_статья'],
                        'created_at': data.get('created_at', ''),
                        'published': data.get('published', False),
                        'urgent': data.get('urgent', False),
                        'priority_score': data.get('priority_score', 0),
                        'daily_priority_score': data.get('daily_priority_score', 0),
                        'source_type': 'generated_article'
                    }
                    
                    if generated_article.get('urgent', False):
                        urgent_items.append(generated_article)
                    else:
                        items.append(generated_article)

            # Сортируем обычные статьи: daily_priority_score desc (если есть), иначе priority_score desc, created_at asc
            def _created_key(a: Dict[str, Any]):
                created_at = a.get('created_at', '')
                if hasattr(created_at, 'isoformat'):
                    # Firebase datetime
                    return created_at.isoformat()
                elif isinstance(created_at, str):
                    return created_at
                else:
                    return '1970-01-01T00:00:00Z'  # Fallback для некорректных дат
                
            items.sort(key=_created_key)
            items.sort(key=lambda a: a.get('daily_priority_score', a.get('priority_score', 0)), reverse=True)
            
            # Сортируем срочные по времени создания (новые первые)
            urgent_items.sort(key=_created_key, reverse=True)
            
            # Срочные статьи идут первыми
            total_items = urgent_items + items
            self.logger.info(f"Найдено статей для публикации: {len(total_items)} (срочных: {len(urgent_items)}, обычных: {len(items)})")
            
            return total_items
        except Exception as e:
            self.logger.error(f"Ошибка получения неопубликованных статей: {e}")
            return []
    
    def _send_telegram_post(self, article: Dict[str, Any], settings: Dict[str, Any]) -> bool:
        """
        Отправляет Telegram-пост
        
        Args:
            article: Данные статьи
            settings: Настройки системы
            
        Returns:
            True если отправка успешна
        """
        try:
            # Получаем токен бота (сначала из Firebase, потом из переменных окружения)
            bot_token = settings.get('telegram_bot_token') or os.environ.get('TELEGRAM_BOT_TOKEN')
            
            # Если токен начинается с 'ENV:', берем из переменных окружения
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
            
            # Проверяем наличие Telegram-поста, создаем если нет
            telegram_post = article.get('telegram_post')
            if not telegram_post:
                self.logger.info("Создаю Telegram-пост для статьи")
                try:
                    from content_generator import generate_telegram_post
                    telegram_post = generate_telegram_post(article)
                    if telegram_post:
                        # Сохраняем в Firebase
                        article_ref = self.client.db.collection('articles').document(article['article_id'])
                        article_ref.set({'telegram_post': telegram_post}, merge=True)
                        article['telegram_post'] = telegram_post
                        self.logger.info("Telegram-пост создан и сохранен")
                    else:
                        self.logger.error("Не удалось создать Telegram-пост")
                        return False
                except Exception as e:
                    self.logger.error(f"Ошибка создания Telegram-поста: {e}")
                    return False
            
            # Получаем изображение
            image_url = article.get('image', '')
            
            # Создаем бота
            bot = Bot(token=bot_token)
            
            # Отправляем пост
            if image_url and self._is_valid_image_url(image_url):
                self.logger.info(f"Отправляю пост с изображением: {image_url[:100]}...")
                try:
                    # Используем синхронную версию через requests для стабильности
                    import requests
                    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
                    # Конвертируем Markdown в HTML для лучшей совместимости
                    html_caption = self._convert_markdown_to_html(telegram_post)
                    
                    data = {
                        'chat_id': chat_id,
                        'photo': image_url,
                        'caption': html_caption,
                        'parse_mode': 'HTML'
                    }
                    response = requests.post(url, data=data, timeout=30)
                    
                    if response.status_code == 200:
                        self.logger.info(f"Telegram-пост с изображением отправлен в чат {chat_id}")
                        return True
                    else:
                        self.logger.warning(f"Ошибка отправки изображения: {response.status_code} - {response.text[:200]}")
                        # Fallback: отправляем только текст
                        
                except Exception as e:
                    self.logger.warning(f"Не удалось отправить с изображением: {e}")
                    # Fallback: отправляем только текст
            
            # Отправляем только текст через requests API
            try:
                import requests
                
                # Конвертируем Markdown в HTML для лучшей совместимости с Telegram
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
                    self.logger.info(f"Telegram-пост отправлен в чат {chat_id}")
                    return True
                else:
                    self.logger.error(f"Ошибка отправки текста: {response.status_code} - {response.text[:200]}")
                    return False
                    
            except Exception as e:
                self.logger.error(f"Ошибка отправки в Telegram: {e}")
                return False
            
        except ImportError:
            self.logger.error("python-telegram-bot не установлен")
            return False
        except TelegramError as e:
            self.logger.error(f"Ошибка Telegram API: {e}")
            return False
        except Exception as e:
            self.logger.error(f"Ошибка при отправке Telegram-поста: {e}")
            return False
    
    def _is_valid_image_url(self, url: str) -> bool:
        """Проверяет валидность URL изображения"""
        if not url:
            return False
        
        # Простая проверка на HTTP/HTTPS URL
        return url.startswith(('http://', 'https://'))
    
    def _mark_article_as_published(self, article: Dict[str, Any]) -> bool:
        """Отмечает статью как опубликованную"""
        try:
            article_id = article.get('article_id')
            if not article_id:
                self.logger.error("ID статьи не найден")
                return False
            
            # Определяем тип источника и обновляем соответствующую коллекцию
            source_type = article.get('source_type', 'article')
            
            if source_type == 'cluster':
                # Обновляем кластер
                cluster_ref = self.client.db.collection('news_clusters').document(article_id)
                cluster_ref.update({
                    'published': True,
                    'published_at': datetime.now(self.madrid_tz).isoformat()
                })
            else:
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
            
            self.logger.info(f"Статья {article_id} отмечена как опубликованная")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка отметки статьи как опубликованной: {e}")
            return False
    
    def run_scheduler(self) -> Dict[str, Any]:
        """
        Основной метод планировщика
        Проверяет расписание публикаций и запускает публикацию по правилам
        
        Returns:
            Словарь с результатами выполнения
        """
        self.logger.info("Запуск планировщика публикаций")
        
        results = {
            'total_articles_checked': 0,
            'articles_published': 0,
            'urgent_published': 0,
            'regular_published': 0,
            'skipped_outside_window': 0,
            'skipped_interval': 0,
            'skipped_limit': 0,
            'skipped_duplicate_topic': 0,
            'errors': []
        }
        
        try:
            # Получаем настройки
            settings = self._get_settings()
            self.logger.info(f"Настройки загружены: {len(settings.get('publishing_windows', []))} окон")
            
            # Получаем неопубликованные статьи
            articles = self._get_unpublished_articles()
            results['total_articles_checked'] = len(articles)
            self.logger.info(f"Найдено {len(articles)} неопубликованных статей")
            
            if not articles:
                self.logger.info("Нет статей для публикации")
                return results
            
            # ЛОГИКА: Выбираем статьи для публикации раз в час
            published_this_session = 0
            max_articles_per_session = 1  # Максимум 1 статья за час (раз в час)
            
            # Проверяем, не публиковали ли мы уже похожие темы сегодня
            today_start = datetime.now(self.madrid_tz).replace(hour=0, minute=0, second=0, microsecond=0)
            published_today = self._get_published_articles_today(today_start)
            published_topics = [self._extract_topic(article) for article in published_today]
            
            # Разделяем на срочные и обычные (они уже отсортированы в _get_unpublished_articles)
            urgent_articles = [a for a in articles if a.get('urgent', False)]
            regular_articles = [a for a in articles if not a.get('urgent', False)]
            
            self.logger.info(f"Найдено срочных статей: {len(urgent_articles)}, обычных: {len(regular_articles)}")
            
            # Сначала публикуем срочные статьи (без лимитов)
            for article in urgent_articles:
                if published_this_session >= 10:  # Защита от спама даже для срочных
                    self.logger.warning("Достигнут максимальный лимит срочных статей за сессию (10)")
                    break
                    
                title = article.get('title', 'Unknown')
                safe_title = title.encode('ascii', 'ignore').decode('ascii')
                self.logger.info(f"🚨 Обрабатываю срочную статью: {safe_title}")
                
                try:
                    # Срочные статьи публикуются всегда (проверяем только базовые условия)
                    if self._can_publish_now(settings, True):
                        if self._send_telegram_post(article, settings):
                            if self._mark_article_as_published(article):
                                results['articles_published'] += 1
                                results['urgent_published'] += 1
                                published_this_session += 1
                                self.logger.info(f"✅ Срочная статья опубликована: {safe_title}")
                            else:
                                results['errors'].append(f"Failed to mark urgent article as published: {title}")
                        else:
                            results['errors'].append(f"Failed to send urgent Telegram post: {title}")
                    else:
                        self.logger.error(f"Не удалось опубликовать срочную статью: {safe_title}")
                        results['errors'].append(f"Failed to publish urgent article: {title}")
                        
                except Exception as e:
                    self.logger.error(f"Ошибка обработки срочной статьи {safe_title}: {e}")
                    results['errors'].append(f"Error processing urgent article {title}: {e}")
            
            # Проверяем есть ли активное окно для обычных статей
            current_window = self._get_current_window(settings)
            if not current_window:
                self.logger.info("Нет активного окна публикации для обычных статей")
                self.logger.info(f"Обычные статьи отложены: {len(regular_articles)}")
                results['skipped_outside_window'] = len(regular_articles)
            else:
                self.logger.info(f"✅ Активное окно: {current_window.start}-{current_window.end}")
                
                # Публикуем обычные статьи в активном окне
                regular_published_this_session = 0
                
                for article in regular_articles:
                    # Проверяем лимиты для обычных статей
                    if published_this_session >= max_articles_per_session:
                        self.logger.info(f"Достигнут лимит статей за сессию ({max_articles_per_session})")
                        break
                        
                    if regular_published_this_session >= max_articles_per_session:
                        self.logger.info(f"Достигнут лимит обычных статей за сессию ({max_articles_per_session})")
                        break
                    
                    # Проверяем дублирование темы
                    if self._is_topic_duplicate(article, published_topics):
                        results['skipped_duplicate_topic'] = results.get('skipped_duplicate_topic', 0) + 1
                        continue
                    
                    title = article.get('title', 'Unknown')
                    safe_title = title.encode('ascii', 'ignore').decode('ascii')
                    self.logger.info(f"📝 Публикую статью в активном окне: {safe_title}")
                    
                    try:
                        # Проверяем только интервал между постами (окно уже проверили)
                        if not self._check_post_interval(settings):
                            results['skipped_interval'] += 1
                            self.logger.info(f"Пропускаю статью (интервал не соблюден): {safe_title}")
                            continue
                        
                        # Отправляем в Telegram
                        if self._send_telegram_post(article, settings):
                            if self._mark_article_as_published(article):
                                results['articles_published'] += 1
                                results['regular_published'] += 1
                                published_this_session += 1
                                regular_published_this_session += 1
                                self.logger.info(f"✅ Обычная статья опубликована: {safe_title}")
                            else:
                                results['errors'].append(f"Failed to mark article as published: {title}")
                        else:
                            results['errors'].append(f"Failed to send Telegram post: {title}")
                        
                    except Exception as e:
                        self.logger.error(f"Ошибка обработки статьи {safe_title}: {e}")
                        results['errors'].append(f"Error processing article {title}: {e}")
            
            # Логируем итоги
            self.logger.info(f"📊 Итоги публикации: {results['articles_published']} опубликовано, {len(results['errors'])} ошибок")
            
        except Exception as e:
            error_msg = f"Критическая ошибка планировщика: {e}"
            self.logger.error(error_msg)
            results['errors'].append(error_msg)
        
        return results

    def _get_published_articles_today(self, today_start: datetime) -> List[Dict[str, Any]]:
        """Получает статьи, опубликованные сегодня"""
        try:
            articles_ref = self.client.db.collection('articles')
            generated_articles_ref = self.client.db.collection('generated_articles')
            
            # Пытаемся использовать составной индекс
            try:
                # Получаем обычные статьи
                articles_docs = articles_ref.where('published', '==', True).where('published_at', '>=', today_start.isoformat()).stream()
                articles = [doc.to_dict() for doc in articles_docs]
                
                # Получаем сгенерированные статьи
                generated_docs = generated_articles_ref.where('published', '==', True).where('published_at', '>=', today_start.isoformat()).stream()
                generated_articles = [doc.to_dict() for doc in generated_docs]
                
                self.logger.info(f"Получено {len(articles)} обычных и {len(generated_articles)} сгенерированных статей за сегодня")
                return articles + generated_articles
                
            except Exception as index_error:
                self.logger.warning(f"Составной индекс не работает, использую fallback логику: {index_error}")
                
                # Fallback: получаем все статьи и фильтруем локально
                all_articles_docs = list(articles_ref.limit(1000).stream())
                all_generated_docs = list(generated_articles_ref.limit(1000).stream())
                
                # Фильтруем локально
                today_articles = []
                for doc in all_articles_docs:
                    data = doc.to_dict()
                    if data.get('published') and data.get('published_at'):
                        try:
                            published_at = datetime.fromisoformat(data['published_at'])
                            if published_at >= today_start:
                                today_articles.append(data)
                        except:
                            continue
                
                today_generated = []
                for doc in all_generated_docs:
                    data = doc.to_dict()
                    if data.get('published') and data.get('published_at'):
                        try:
                            published_at = datetime.fromisoformat(data['published_at'])
                            if published_at >= today_start:
                                today_generated.append(data)
                        except:
                            continue
                
                self.logger.info(f"Fallback: получено {len(today_articles)} обычных и {len(today_generated)} сгенерированных статей за сегодня")
                return today_articles + today_generated
            
        except Exception as e:
            self.logger.error(f"Ошибка получения опубликованных статей за сегодня: {e}")
            return []
    
    def _extract_topic(self, article: Dict[str, Any]) -> str:
        """Извлекает основную тему статьи для проверки дублирования"""
        try:
            title = article.get('title', '').lower()
            summary = article.get('summary', '').lower()
            
            # Простые ключевые слова для определения темы
            topic_keywords = {
                'работа': ['работа', 'трудоустройство', 'вакансия', 'зарплата', 'контракт'],
                'недвижимость': ['недвижимость', 'жилье', 'квартира', 'дом', 'аренда', 'покупка'],
                'здоровье': ['здоровье', 'медицина', 'врач', 'больница', 'лечение'],
                'транспорт': ['транспорт', 'машина', 'автобус', 'метро', 'парковка'],
                'образование': ['образование', 'школа', 'университет', 'курсы', 'обучение'],
                'экономика': ['экономика', 'деньги', 'банк', 'кредит', 'инвестиции'],
                'туризм': ['туризм', 'путешествие', 'отдых', 'пляж', 'гостиница']
            }
            
            # Определяем тему по ключевым словам
            for topic, keywords in topic_keywords.items():
                if any(keyword in title or keyword in summary for keyword in keywords):
                    return topic
            
            return 'общее'
            
        except Exception as e:
            self.logger.error(f"Ошибка извлечения темы: {e}")
            return 'общее'
    
    def _is_topic_duplicate(self, article: Dict[str, Any], published_topics: List[str]) -> bool:
        """Проверяет, не дублирует ли статья уже опубликованную тему"""
        try:
            article_topic = self._extract_topic(article)
            
            # Если тема уже публиковалась сегодня, считаем дубликатом
            if article_topic in published_topics:
                self.logger.info(f"Статья '{article.get('title', '')}' пропущена: тема '{article_topic}' уже публиковалась сегодня")
                return True
            
            return False
            
        except Exception as e:
            self.logger.error(f"Ошибка проверки дублирования темы: {e}")
            return False

    def _convert_markdown_to_html(self, markdown_text: str) -> str:
        """
        Конвертирует Markdown форматирование в HTML для Telegram API
        
        Args:
            markdown_text: Текст с Markdown форматированием
            
        Returns:
            Текст с HTML форматированием
        """
        try:
            # Заменяем **жирный** на <b>жирный</b>
            html_text = markdown_text
            
            # Обработка жирного текста: **text** -> <b>text</b>
            import re
            html_text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', html_text)
            
            # Обработка курсива: *text* -> <i>text</i> (но не затрагиваем уже обработанный жирный)
            html_text = re.sub(r'(?<!\*)\*([^*]+?)\*(?!\*)', r'<i>\1</i>', html_text)
            
            # Экранируем специальные HTML символы (но сначала сохраняем уже обработанные теги)
            # Временно заменяем наши теги на плейсхолдеры
            html_text = html_text.replace('<b>', '___BOLD_START___').replace('</b>', '___BOLD_END___')
            html_text = html_text.replace('<i>', '___ITALIC_START___').replace('</i>', '___ITALIC_END___')
            
            # Экранируем HTML символы
            html_text = html_text.replace('&', '&amp;')
            html_text = html_text.replace('<', '&lt;').replace('>', '&gt;')
            
            # Восстанавливаем наши теги
            html_text = html_text.replace('___BOLD_START___', '<b>').replace('___BOLD_END___', '</b>')
            html_text = html_text.replace('___ITALIC_START___', '<i>').replace('___ITALIC_END___', '</i>')
            
            return html_text
            
        except Exception as e:
            self.logger.warning(f"Ошибка конвертации Markdown в HTML: {e}")
            # Возвращаем исходный текст без форматирования в случае ошибки
            return markdown_text.replace('**', '').replace('*', '')


def main():
    """Точка входа для запуска планировщика"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Планировщик публикаций для Telegram')
    parser.add_argument('--run', action='store_true', help='Запустить планировщик')
    parser.add_argument('--test', action='store_true', help='Тестовый режим')
    
    args = parser.parse_args()
    
    if args.run or args.test:
        scheduler = PublicationScheduler()
        results = scheduler.run_scheduler()
        
        print("\n📊 Результаты выполнения планировщика:")
        print(f"   Всего статей проверено: {results['total_articles_checked']}")
        print(f"   Опубликовано: {results['articles_published']}")
        print(f"   Срочных: {results['urgent_published']}")
        print(f"   Обычных: {results['regular_published']}")
        print(f"   Пропущено (вне окна): {results['skipped_outside_window']}")
        print(f"   Пропущено (интервал): {results['skipped_interval']}")
        print(f"   Пропущено (лимит): {results['skipped_limit']}")
        print(f"   Пропущено (дубликат темы): {results.get('skipped_duplicate_topic', 0)}")
        
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