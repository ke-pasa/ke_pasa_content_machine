#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
УЛУЧШЕННЫЙ ПЛАНИРОВЩИК ПУБЛИКАЦИЙ
Логика: 1 пост в течение каждого разрешенного часа
Вместо: только в первые 5 минут часа
"""

import os
import logging
import pytz
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

# Добавляем текущую директорию в путь
import sys
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from workers.tools.firebase_client import get_firebase_client, FirebaseClient

@dataclass
class PublishingWindow:
    """Окно публикации"""
    start: str  # "09:00"
    end: str    # "10:00"
    
    def is_active(self, current_time: datetime) -> bool:
        """Проверяет, активно ли окно"""
        start_hour = int(self.start.split(':')[0])
        end_hour = int(self.end.split(':')[0])
        
        current_hour = current_time.hour
        
        # Проверяем, что текущий час входит в окно
        if start_hour <= end_hour:
            # Обычный случай: 9:00-10:00
            return start_hour <= current_hour < end_hour
        else:
            # Переход через полночь: 22:00-09:00
            return current_hour >= start_hour or current_hour < end_hour

class PublicationSchedulerImproved:
    """УЛУЧШЕННЫЙ планировщик публикаций с логикой "1 пост в час" """
    
    def __init__(self, firebase_client: Optional[FirebaseClient] = None):
        """
        Инициализация планировщика
        
        Args:
            firebase_client: Клиент Firebase (если не указан, создается автоматически)
        """
        self.client = firebase_client or get_firebase_client()
        self.madrid_tz = pytz.timezone('Europe/Madrid')
        self.logger = self._setup_logging()
        
        # Флаг для предотвращения повторных публикаций в течение часа
        self._last_publication_hour = None
        self._publication_lock = False
        
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logger = logging.getLogger('PublicationSchedulerImproved')
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
            # Сначала пробуем получить настройки из settings/main
            settings_ref = self.client.db.collection('settings').document('main')
            doc = settings_ref.get()
            
            if doc.exists:
                main_settings = doc.to_dict() or {}
                self.logger.info(f"✅ Настройки получены из settings/main")
                
                # Формируем настройки для планировщика
                scheduler_settings = {
                    "enabled": True,
                    "publishing_windows": main_settings.get('publishing_windows', [
                        {"start": "09:00", "end": "10:00"},
                        {"start": "10:00", "end": "11:00"},
                        {"start": "11:00", "end": "12:00"},
                        {"start": "12:00", "end": "13:00"},
                        {"start": "13:00", "end": "14:00"},
                        {"start": "14:00", "end": "15:00"},
                        {"start": "16:00", "end": "17:00"},
                        {"start": "17:00", "end": "18:00"},
                        {"start": "18:00", "end": "19:00"},
                        {"start": "20:00", "end": "21:00"},
                        {"start": "21:00", "end": "22:00"},
                        {"start": "22:00", "end": "23:00"}
                    ]),
                    "min_post_interval_minutes": main_settings.get('min_post_interval_minutes', 60),
                    "max_posts_per_window": main_settings.get('max_articles_per_post', 1),
                    "telegram_chat_id": main_settings.get('telegram_chat_id', ''),
                    "telegram_bot_token": main_settings.get('telegram_bot_token', '')
                }
                
                self.logger.info(f"📱 Telegram настройки: chat_id={bool(scheduler_settings['telegram_chat_id'])}, bot_token={bool(scheduler_settings['telegram_bot_token'])}")
                return scheduler_settings
            else:
                # Fallback: пробуем settings/telegram
                settings_ref = self.client.db.collection('settings').document('telegram')
                doc = settings_ref.get()
                
                if doc.exists:
                    self.logger.info(f"✅ Настройки получены из settings/telegram")
                    return doc.to_dict() or {}
                else:
                    # Возвращаем настройки по умолчанию
                    self.logger.warning(f"⚠️  Настройки не найдены, используем значения по умолчанию")
                    return {
                        "enabled": True,
                                            "publishing_windows": [
                        {"start": "09:00", "end": "10:00"},
                        {"start": "10:00", "end": "11:00"},
                        {"start": "11:00", "end": "12:00"},
                        {"start": "12:00", "end": "13:00"},
                        {"start": "13:00", "end": "14:00"},
                        {"start": "14:00", "end": "15:00"},
                        {"start": "16:00", "end": "17:00"},
                        {"start": "17:00", "end": "18:00"},
                        {"start": "18:00", "end": "19:00"},
                        {"start": "20:00", "end": "21:00"},
                        {"start": "21:00", "end": "22:00"},
                        {"start": "22:00", "end": "23:00"},
                        {"start": "23:00", "end": "00:00"}
                    ],
                        "min_post_interval_minutes": 60,
                        "max_posts_per_window": 1,
                        "telegram_chat_id": os.getenv('TELEGRAM_CHAT_ID', ''),
                        "telegram_bot_token": os.getenv('TELEGRAM_BOT_TOKEN', '')
                    }
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения настроек: {e}")
            return {}
    
    def _is_hourly_publication_time(self) -> bool:
        """
        УЛУЧШЕННАЯ проверка времени публикации
        Теперь: в течение всего разрешенного часа (не только первые 5 минут)
        """
        current_time = datetime.now(self.madrid_tz)
        current_hour = current_time.hour
        
        # Разрешенные часы публикации (каждый час = отдельное окно)
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22, 23]
        
        # Проверяем, что текущий час разрешен
        if current_hour not in allowed_hours:
            return False
        
        # ✅ УБИРАЕМ ограничение по минутам!
        # Теперь можно публиковать в любое время в течение часа
        return True
    
    def _check_publication_lock(self) -> bool:
        """
        УЛУЧШЕННАЯ проверка блокировки публикации
        Теперь: 1 пост в час, блокировка снимается в начале следующего часа
        """
        current_time = datetime.now(self.madrid_tz)
        current_hour = current_time.hour
        
        # Если это тот же час, что и последняя публикация - блокируем
        if self._last_publication_hour == current_hour:
            self.logger.info(f"🔒 Публикация заблокирована для часа {current_hour}:00 (уже публиковали)")
            return False
        
        # Если публикация заблокирована - снимаем блокировку в начале нового часа
        if self._publication_lock:
            # Снимаем блокировку в начале нового часа (любая минута)
            if self._last_publication_hour != current_hour:
                self._publication_lock = False
                self.logger.info(f"🔓 Блокировка публикации снята для часа {current_hour}:00")
            else:
                self.logger.info(f"🔒 Публикация заблокирована (активна блокировка)")
                return False
        
        return True
    
    def _can_publish_now(self, settings: Dict[str, Any], is_urgent: bool = False) -> bool:
        """
        УЛУЧШЕННАЯ проверка возможности публикации
        Теперь: можно публиковать в любое время разрешенного часа
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
        
        # Проверяем интервал между постами (если есть последняя публикация)
        last_post_time = self._get_last_post_time()
        if last_post_time:
            min_interval = settings.get('min_post_interval_minutes', 60)
            time_since_last = datetime.now(self.madrid_tz) - last_post_time
            
            # Если последняя публикация была в том же часу - блокируем
            if last_post_time.hour == datetime.now(self.madrid_tz).hour:
                self.logger.info(f"⏰ Уже публиковали в этом часу ({last_post_time.hour}:00)")
                return False
            
            # Проверяем минимальный интервал между постами
            if time_since_last < timedelta(minutes=min_interval):
                self.logger.info(f"⏰ Не прошло достаточно времени с последней публикации ({min_interval} мин)")
                return False
        
        return True
    
    def _get_last_post_time(self) -> Optional[datetime]:
        """Получает время последней публикации"""
        try:
            # Получаем последний опубликованный пост
            posts_ref = self.client.db.collection('telegram_posts')
            query = posts_ref.order_by('created_at', direction='DESCENDING').limit(1)
            docs = query.stream()
            
            for doc in docs:
                data = doc.to_dict()
                if data and 'created_at' in data:
                    # Конвертируем timestamp в datetime
                    if hasattr(data['created_at'], 'timestamp'):
                        return datetime.fromtimestamp(data['created_at'].timestamp(), self.madrid_tz)
                    else:
                        return data['created_at']
            
            return None
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка получения времени последней публикации: {e}")
            return None
    
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
                
                ranked_articles.append({
                    **article,
                    'ranking_score': ranking_score
                })
            
            # Сортируем по рейтингу (высокий в начале)
            ranked_articles.sort(key=lambda x: x['ranking_score'], reverse=True)
            
            # Возвращаем топ статьи
            max_posts = settings.get('max_posts_per_window', 1)
            return ranked_articles[:max_posts]
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка ранжирования статей: {e}")
            return articles  # Возвращаем исходный список при ошибке
    
    def run_hourly_publication(self) -> bool:
        """
        УЛУЧШЕННЫЙ запуск почасовой публикации
        Теперь: работает в течение всего разрешенного часа
        """
        self.logger.info("🚀 Запуск УЛУЧШЕННОЙ почасовой публикации")
        
        try:
            # Получаем настройки
            settings = self._get_settings()
            
            if not settings.get('enabled', True):
                self.logger.info("❌ Публикация отключена в настройках")
                return False
            
            # Проверяем, можно ли публиковать сейчас
            if not self._can_publish_now(settings):
                self.logger.info("⏰ Публикация не разрешена")
                return False
            
            # Получаем статьи для публикации
            articles = self._get_fresh_unpublished_articles()
            if not articles:
                self.logger.info("❌ Нет статей для публикации")
                return False
            
            # Ранжируем статьи
            ranked_articles = self._rank_articles_for_telegram(articles, settings)
            if not ranked_articles:
                self.logger.info("❌ Нет статей после ранжирования")
                return False
            
            # Берем лучшую статью
            best_article = ranked_articles[0]
            
            # Публикуем в Telegram
            success = self._publish_to_telegram(best_article, settings)
            
            if success:
                # Обновляем статус статьи
                self._mark_article_published(best_article['id'])
                
                # Устанавливаем блокировку на этот час
                current_hour = datetime.now(self.madrid_tz).hour
                self._last_publication_hour = current_hour
                self._publication_lock = True
                
                self.logger.info(f"✅ Пост успешно опубликован в {current_hour}:00")
                return True
            else:
                self.logger.error("❌ Ошибка публикации в Telegram")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка почасовой публикации: {e}")
            return False
    
    def _publish_to_telegram(self, article: Dict[str, Any], settings: Dict[str, Any]) -> bool:
        """Публикует статью в Telegram"""
        try:
            self.logger.info(f"📱 Публикация в Telegram: {article.get('title', 'Без заголовка')[:50]}...")
            
            # Получаем данные статьи
            title = article.get('title', 'Без заголовка')
            summary = article.get('summary', '')
            link = article.get('link', '')
            image = article.get('image', '')
            
            # Создаем пост для Telegram
            post_data = {
                'title': title,
                'summary': summary,
                'link': link,
                'image': image,
                'article_id': article.get('id', ''),
                'source': article.get('source', ''),
                'created_at': datetime.now(self.madrid_tz),
                'published_at': datetime.now(self.madrid_tz),
                'status': 'published',
                'telegram_chat_id': settings.get('telegram_chat_id', ''),
                'telegram_bot_token': settings.get('telegram_bot_token', '')
            }
            
            # Сохраняем пост в базу данных
            posts_ref = self.client.db.collection('telegram_posts')
            post_doc = posts_ref.add(post_data)
            
            if post_doc:
                self.logger.info(f"✅ Пост сохранен в базе с ID: {post_doc[1].id}")
                
                # РЕАЛЬНАЯ ОТПРАВКА В TELEGRAM
                telegram_sent = self._send_to_telegram(title, summary, link, image, settings)
                
                if telegram_sent:
                    self.logger.info(f"✅ Пост успешно отправлен в Telegram")
                    return True
                else:
                    self.logger.error(f"❌ Ошибка отправки в Telegram")
                    return False
            else:
                self.logger.error(f"❌ Не удалось сохранить пост в базу")
                return False
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка публикации в Telegram: {e}")
            return False
    
    def _send_to_telegram(self, title: str, summary: str, link: str, image: str, settings: Dict[str, Any]) -> bool:
        """Отправляет пост в Telegram через Bot API"""
        try:
            import requests
            
            bot_token = settings.get('telegram_bot_token')
            chat_id = settings.get('telegram_chat_id')
            
            if not bot_token or not chat_id:
                self.logger.error(f"❌ Отсутствуют настройки Telegram (bot_token: {bool(bot_token)}, chat_id: {bool(chat_id)})")
                return False
            
            # Формируем текст поста
            message_text = f"📰 {title}\n\n"
            if summary:
                message_text += f"{summary}\n\n"
            if link:
                message_text += f"🔗 {link}"
            
            # Отправляем сообщение
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': message_text,
                'parse_mode': 'HTML',
                'disable_web_page_preview': False
            }
            
            response = requests.post(url, data=data, timeout=30)
            
            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.logger.info(f"✅ Telegram API: сообщение отправлено (message_id: {result.get('result', {}).get('message_id')})")
                    return True
                else:
                    self.logger.error(f"❌ Telegram API ошибка: {result}")
                    return False
            else:
                self.logger.error(f"❌ HTTP ошибка Telegram API: {response.status_code} - {response.text}")
                return False
                
        except ImportError:
            self.logger.error(f"❌ Модуль requests не установлен. Установите: pip install requests")
            return False
        except Exception as e:
            self.logger.error(f"❌ Ошибка отправки в Telegram: {e}")
            return False
    
    def _mark_article_published(self, article_id: str) -> bool:
        """Отмечает статью как опубликованную"""
        try:
            article_ref = self.client.db.collection('articles').document(article_id)
            article_ref.update({
                'published': True,
                'published_at': datetime.now(self.madrid_tz),
                'published_in_telegram': True
            })
            
            self.logger.info(f"✅ Статья {article_id} отмечена как опубликованная")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка обновления статуса статьи: {e}")
            return False
    
    def run(self) -> Dict[str, Any]:
        """
        Основной метод запуска планировщика
        Возвращает результаты выполнения
        """
        try:
            self.logger.info("🚀 Запуск планировщика публикаций")
            
            # Получаем настройки
            settings = self._get_settings()
            
            if not settings.get('enabled', True):
                self.logger.info("❌ Публикация отключена в настройках")
                return {
                    'articles_published': 0,
                    'total_articles_checked': 0,
                    'status': 'disabled'
                }
            
            # Проверяем, можно ли публиковать сейчас
            if not self._can_publish_now(settings):
                self.logger.info("⏰ Публикация не разрешена")
                return {
                    'articles_published': 0,
                    'total_articles_checked': 0,
                    'status': 'not_allowed'
                }
            
            # Получаем статьи для публикации
            articles = self._get_fresh_unpublished_articles()
            if not articles:
                self.logger.info("❌ Нет статей для публикации")
                return {
                    'articles_published': 0,
                    'total_articles_checked': 0,
                    'status': 'no_articles'
                }
            
            # Ранжируем статьи
            ranked_articles = self._rank_articles_for_telegram(articles, settings)
            if not ranked_articles:
                self.logger.info("❌ Нет статей после ранжирования")
                return {
                    'articles_published': 0,
                    'total_articles_checked': len(articles),
                    'status': 'ranking_failed'
                }
            
            # Берем лучшую статью
            best_article = ranked_articles[0]
            
            # Публикуем в Telegram
            success = self._publish_to_telegram(best_article, settings)
            
            if success:
                # Обновляем статус статьи
                self._mark_article_published(best_article['id'])
                
                # Устанавливаем блокировку на этот час
                current_hour = datetime.now(self.madrid_tz).hour
                self._last_publication_hour = current_hour
                self._publication_lock = True
                
                self.logger.info(f"✅ Пост успешно опубликован в {current_hour}:00")
                return {
                    'articles_published': 1,
                    'total_articles_checked': len(articles),
                    'status': 'success',
                    'published_article_id': best_article['id'],
                    'published_article_title': best_article.get('title', 'Без заголовка')
                }
            else:
                self.logger.error("❌ Ошибка публикации в Telegram")
                return {
                    'articles_published': 0,
                    'total_articles_checked': len(articles),
                    'status': 'publication_failed'
                }
                
        except Exception as e:
            self.logger.error(f"❌ Ошибка планировщика: {e}")
            return {
                'articles_published': 0,
                'total_articles_checked': 0,
                'status': 'error',
                'error': str(e)
            }

def test_improved_scheduler():
    """Тестирует улучшенный планировщик"""
    print("🧪 ТЕСТ УЛУЧШЕННОГО ПЛАНИРОВЩИКА")
    print("=" * 50)
    
    try:
        # Создаем планировщик
        scheduler = PublicationSchedulerImproved()
        
        # Получаем настройки
        settings = scheduler._get_settings()
        
        print(f"✅ Планировщик создан успешно")
        print(f"✅ Настройки получены: {len(settings)} параметров")
        
        # Текущее время
        current_time = datetime.now(scheduler.madrid_tz)
        current_hour = current_time.hour
        current_minute = current_time.minute
        
        print(f"\n⏰ ТЕКУЩЕЕ ВРЕМЯ:")
        print(f"   Время (Madrid): {current_time.strftime('%H:%M:%S')}")
        print(f"   Час: {current_hour}:00")
        print(f"   Минута: {current_minute}")
        
        # Проверяем почасовое время (УЛУЧШЕННАЯ логика)
        is_hourly_time = scheduler._is_hourly_publication_time()
        print(f"\n📅 ПРОВЕРКА УЛУЧШЕННОГО ВРЕМЕНИ:")
        print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
        
        # Анализируем логику
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22]
        print(f"   Разрешенные часы: {allowed_hours}")
        print(f"   Текущий час разрешен: {'✅ ДА' if current_hour in allowed_hours else '❌ НЕТ'}")
        print(f"   ✅ УБРАНО ограничение по минутам (0-5)!")
        
        # Проверяем блокировку
        can_publish = scheduler._can_publish_now(settings)
        print(f"\n🔒 ПРОВЕРКА БЛОКИРОВКИ:")
        print(f"   Можно публиковать сейчас: {'✅ ДА' if can_publish else '❌ НЕТ'}")
        
        # Проверяем последнее время публикации
        last_post_time = scheduler._get_last_post_time()
        if last_post_time:
            print(f"   Последняя публикация: {last_post_time.strftime('%H:%M:%S')}")
            print(f"   В том же часу: {'✅ ДА' if last_post_time.hour == current_hour else '❌ НЕТ'}")
        else:
            print(f"   Последняя публикация: НЕТ (первый запуск)")
        
        # Проверяем блокировку по часам
        print(f"\n🔐 ПРОВЕРКА БЛОКИРОВКИ ПО ЧАСАМ:")
        print(f"   Последний час публикации: {scheduler._last_publication_hour}")
        print(f"   Блокировка активна: {'✅ ДА' if scheduler._publication_lock else '❌ НЕТ'}")
        
        # Проверяем статьи для публикации
        print(f"\n📰 ПРОВЕРКА СТАТЕЙ:")
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"   Доступных статей: {len(articles)}")
        
        if articles:
            print(f"   Примеры статей:")
            for i, article in enumerate(articles[:3]):
                title = article.get('title', 'Без заголовка')[:50]
                priority = article.get('priority_score', 0)
                print(f"     {i+1}. {title} (приоритет: {priority:.2f})")
        else:
            print(f"   ❌ Нет статей для публикации!")
        
        # Анализ улучшений
        print(f"\n🔍 АНАЛИЗ УЛУЧШЕНИЙ:")
        
        if is_hourly_time:
            if can_publish:
                print(f"   ✅ Система готова к публикации!")
                print(f"   ✅ Можно публиковать в любое время часа {current_hour}:00")
            else:
                print(f"   ⚠️  Время подходящее, но есть блокировка")
                if last_post_time and last_post_time.hour == current_hour:
                    print(f"   ❌ Уже публиковали в этом часу ({current_hour}:00)")
        else:
            print(f"   ❌ Текущий час {current_hour}:00 НЕ в списке разрешенных")
            next_allowed = [h for h in allowed_hours if h > current_hour]
            if next_allowed:
                print(f"   ⏰ Следующий разрешенный час: {next_allowed[0]}:00")
        
        # Рекомендации
        print(f"\n💡 РЕКОМЕНДАЦИИ:")
        
        if is_hourly_time and can_publish:
            print(f"   • Система готова к публикации в любое время часа {current_hour}:00")
            print(f"   • Будет опубликован 1 пост (лучший по приоритету)")
        elif is_hourly_time and not can_publish:
            print(f"   • Время подходящее, но есть блокировка - проверьте настройки")
        else:
            print(f"   • Дождитесь разрешенного часа: {allowed_hours}")
        
        print(f"\n🎯 СТАТУС:")
        if can_publish and articles:
            print(f"   ✅ Система готова к публикации!")
        elif can_publish and not articles:
            print(f"   ⚠️  Можно публиковать, но нет статей")
        elif not can_publish and is_hourly_time:
            print(f"   ⚠️  Время подходящее, но есть блокировка")
        else:
            print(f"   ❌ Сейчас не время для публикации")
        
        print(f"\n🚀 УЛУЧШЕНИЯ:")
        print(f"   ✅ Убрано ограничение по минутам (0-5)")
        print(f"   ✅ Можно публиковать в любое время разрешенного часа")
        print(f"   ✅ Логика: 1 пост в час вместо 1 пост в первые 5 минут")
        
    except ImportError as e:
        print(f"❌ Ошибка импорта: {e}")
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_improved_scheduler()
