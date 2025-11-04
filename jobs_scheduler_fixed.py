#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ИСПРАВЛЕННЫЙ ПЛАНИРОВЩИК ПУБЛИКАЦИЙ
ПРАВИЛЬНАЯ логика: 1 пост в час, но в любое время часа
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

from firebase_client import get_firebase_client, FirebaseClient

class PublicationSchedulerFixed:
    """ИСПРАВЛЕННЫЙ планировщик с правильной логикой блокировки"""
    
    def __init__(self, firebase_client: Optional[FirebaseClient] = None):
        """Инициализация планировщика"""
        self.client = firebase_client or get_firebase_client()
        self.madrid_tz = pytz.timezone('Europe/Madrid')
        self.logger = self._setup_logging()
        
        # УБИРАЕМ локальные флаги блокировки - они создают путаницу!
        # self._last_publication_hour = None
        # self._publication_lock = False
        
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования"""
        logger = logging.getLogger('PublicationSchedulerFixed')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.StreamHandler()
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
                        {"start": "22:00", "end": "23:00"},
                        {"start": "23:00", "end": "00:00"}
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
        """Проверяет, подходит ли время для публикации"""
        current_time = datetime.now(self.madrid_tz)
        current_hour = current_time.hour
        
        # Разрешенные часы публикации
        allowed_hours = [9, 10, 11, 12, 13, 14, 16, 17, 18, 20, 21, 22, 23]
        
        # Проверяем, что текущий час разрешен
        if current_hour not in allowed_hours:
            return False
        
        # ✅ ВАЖНО: Убираем ограничение по минутам!
        # Можно публиковать в любое время разрешенного часа
        return True
    
    def _can_publish_now(self, settings: Dict[str, Any], is_urgent: bool = False) -> bool:
        """
        ИСПРАВЛЕННАЯ проверка возможности публикации
        НОВАЯ логика: 1 пост в час, но в любое время часа
        """
        if is_urgent:
            # Срочные публикации всегда разрешены
            return True
        
        # Проверяем, подходит ли время для почасовой публикации
        if not self._is_hourly_publication_time():
            self.logger.info("⏰ Сейчас не время для почасовой публикации")
            return False
        
        # ✅ ИСПРАВЛЕНИЕ: Проверяем только время последней публикации в базе
        # НЕ используем локальные флаги блокировки!
        last_post_time = self._get_last_post_time()
        
        if last_post_time:
            current_time = datetime.now(self.madrid_tz)
            
            # ✅ НОВАЯ ЛОГИКА: Если последняя публикация была в том же часу - блокируем
            if last_post_time.hour == current_time.hour:
                self.logger.info(f"⏰ Уже публиковали в этом часу ({last_post_time.hour}:00)")
                return False
            
            # Проверяем минимальный интервал между постами
            min_interval = settings.get('min_post_interval_minutes', 60)
            time_since_last = current_time - last_post_time
            
            if time_since_last < timedelta(minutes=min_interval):
                self.logger.info(f"⏰ Не прошло достаточно времени с последней публикации ({min_interval} мин)")
                return False
        
        # ✅ Если все проверки пройдены - можно публиковать!
        return True
    
    def _get_last_post_time(self) -> Optional[datetime]:
        """Получает время последней публикации из базы данных"""
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
        """Возвращает кандидатов для публикации"""
        try:
            # ✅ ВОССТАНАВЛИВАЕМ ПРАВИЛЬНУЮ ЛОГИКУ: Берем готовые статьи с нашего сайта
            articles_ref = self.client.db.collection('articles')
            
            # Получаем все статьи (не ограничиваем RSS-фильтрами)
            docs = articles_ref.limit(500).stream()

            candidates: List[Dict[str, Any]] = []
            
            for doc in docs:
                data = doc.to_dict() or {}
                data['id'] = doc.id
                data['article_id'] = doc.id  # Добавляем для совместимости
                
                # ✅ ПРАВИЛЬНАЯ ЛОГИКА: Берем готовые статьи с нашего сайта
                # - не опубликованы
                # - экспортированы на сайт (готовый контент)
                # - есть заголовок и контент
                if (not data.get('published', False) and 
                    data.get('exported_to_site', False) and
                    data.get('title') and
                    (data.get('generated_content') or data.get('content'))):
                    
                    # Добавляем метаданные для совместимости
                    article_data = {
                        **data,
                        'source_type': 'article',
                        'priority_score': data.get('priority_score', 0),
                        'daily_priority_score': data.get('daily_priority_score', 0),
                        'urgent': data.get('urgent', False),
                        'created_at': data.get('created_at', ''),
                        'link': data.get('link', ''),
                        'image': data.get('image', ''),
                        'summary': data.get('summary', ''),
                        'categories': data.get('categories', [])
                    }
                    
                    candidates.append(article_data)

            self.logger.info(f"Кандидатов для публикации (готовые статьи): {len(candidates)}")
            return candidates

        except Exception as e:
            self.logger.error(f"Ошибка получения статей: {e}")
            return []
    
    def _rank_articles_for_telegram(self, articles: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Ранжирует статьи для публикации"""
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
            return articles
    
    def _publish_to_telegram(self, article: Dict[str, Any], settings: Dict[str, Any]) -> bool:
        """Публикует статью в Telegram"""
        try:
            self.logger.info(f"📱 Публикация в Telegram: {article.get('title', 'Без заголовка')[:50]}...")
            
            # ✅ ВОССТАНАВЛИВАЕМ ПРАВИЛЬНУЮ ЛОГИКУ: Используем готовые статьи с нашего сайта
            title = article.get('title', 'Без заголовка')
            
            # Приоритет: 1) готовый контент с сайта, 2) generated_content, 3) summary
            if article.get('content'):
                # Используем готовый контент с сайта (на испанском)
                content = article['content']
                # Берем первые 200 символов как summary
                summary = str(content)[:200] + "..." if len(str(content)) > 200 else str(content)
                self.logger.info(f"✅ Используем готовый контент с сайта (длина: {len(str(content))})")
            elif article.get('generated_content'):
                # Используем сгенерированный контент (на испанском)
                content = article['generated_content']
                # Берем первые 200 символов как summary
                summary = str(content)[:200] + "..." if len(str(content)) > 200 else str(content)
                self.logger.info(f"✅ Используем сгенерированный контент (длина: {len(str(content))})")
            elif article.get('summary'):
                # Fallback: используем summary
                summary = article['summary']
                self.logger.info(f"⚠️  Используем summary (длина: {len(str(summary))})")
            else:
                # Нет контента
                summary = ""
                self.logger.warning(f"⚠️  Нет контента для публикации")
            
            # Получаем ссылку на нашу статью на сайте
            link = article.get('link', '')
            if not link and article.get('exported_to_site'):
                # Если ссылки нет, но статья экспортирована на сайт, создаем ссылку
                link = f"https://spain-que-pasa.com/articles/{article.get('id', '')}"
                self.logger.info(f"✅ Создана ссылка на статью на сайте: {link}")
            
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
                'telegram_bot_token': settings.get('telegram_bot_token', ''),
                'content_type': 'site_article' if article.get('content') else 'generated' if article.get('generated_content') else 'rss'  # ✅ ДОБАВЛЯЕМ: тип контента
            }
            
            # Сохраняем пост в базу данных
            posts_ref = self.client.db.collection('telegram_posts')
            post_doc = posts_ref.add(post_data)
            
            if post_doc:
                self.logger.info(f"✅ Пост сохранен в базе с ID: {post_doc[1].id}")
                
                # Отправляем в Telegram
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
    
    def _clean_html_tags(self, text: str) -> str:
        """Очищает текст от HTML-тегов для Telegram"""
        if not text:
            return ""
        
        import re
        
        # Убираем HTML-теги
        clean_text = re.sub(r'<[^>]+>', '', text)
        
        # Убираем множественные пробелы и переносы
        clean_text = re.sub(r'\s+', ' ', clean_text)
        
        # Убираем лишние пробелы в начале и конце
        clean_text = clean_text.strip()
        
        return clean_text
    
    def _send_to_telegram(self, title: str, summary: str, link: str, image: str, settings: Dict[str, Any]) -> bool:
        """Отправляет пост в Telegram через Bot API"""
        try:
            import requests
            
            bot_token = settings.get('telegram_bot_token')
            chat_id = settings.get('telegram_chat_id')
            
            if not bot_token or not chat_id:
                self.logger.error(f"❌ Отсутствуют настройки Telegram (bot_token: {bool(bot_token)}, chat_id: {bool(chat_id)})")
                return False
            
            # ✅ ИСПРАВЛЕНИЕ: Очищаем текст от HTML-тегов
            clean_title = self._clean_html_tags(title)
            clean_summary = self._clean_html_tags(summary)
            
            # Формируем текст поста
            message_text = f"📰 {clean_title}\n\n"
            if clean_summary:
                message_text += f"{clean_summary}\n\n"
            if link:
                message_text += f"🔗 {link}"
            
            # Логируем для отладки
            self.logger.info(f"📝 Текст поста (очищенный): {message_text[:100]}...")
            
            # Отправляем сообщение
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {
                'chat_id': chat_id,
                'text': message_text,
                'parse_mode': 'HTML',  # Оставляем HTML для простого форматирования
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
        """Основной метод запуска планировщика"""
        try:
            self.logger.info("🚀 Запуск ИСПРАВЛЕННОГО планировщика публикаций")
            
            # Получаем настройки
            settings = self._get_settings()
            
            if not settings.get('enabled', True):
                self.logger.info("❌ Публикация отключена в настройках")
                return {
                    'articles_published': 0,
                    'total_articles_checked': 0,
                    'status': 'disabled'
                }
            
            # ✅ ИСПРАВЛЕНИЕ: Проверяем возможность публикации
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
                
                self.logger.info(f"✅ Пост успешно опубликован!")
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

def test_fixed_scheduler():
    """Тестирует исправленный планировщик"""
    print("🧪 ТЕСТ ИСПРАВЛЕННОГО ПЛАНИРОВЩИКА")
    print("=" * 50)
    
    try:
        # Создаем планировщик
        scheduler = PublicationSchedulerFixed()
        
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
        
        # Проверяем время публикации
        is_hourly_time = scheduler._is_hourly_publication_time()
        print(f"\n📅 ПРОВЕРКА ВРЕМЕНИ:")
        print(f"   Подходит для публикации: {'✅ ДА' if is_hourly_time else '❌ НЕТ'}")
        
        # Проверяем возможность публикации
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
        
        # Проверяем статьи
        print(f"\n📰 ПРОВЕРКА СТАТЕЙ:")
        articles = scheduler._get_fresh_unpublished_articles()
        print(f"   Доступных статей: {len(articles)}")
        
        # Итоговая оценка
        print(f"\n🎯 ИТОГОВАЯ ОЦЕНКА:")
        if can_publish and articles:
            print(f"   ✅ СИСТЕМА ГОТОВА К ПУБЛИКАЦИИ!")
        elif not can_publish:
            print(f"   ⚠️  СИСТЕМА ЗАБЛОКИРОВАНА")
        elif not articles:
            print(f"   ❌ НЕТ СТАТЕЙ ДЛЯ ПУБЛИКАЦИИ")
        
        print(f"\n🚀 ИСПРАВЛЕНИЯ:")
        print(f"   ✅ Убраны локальные флаги блокировки")
        print(f"   ✅ Блокировка только по времени последней публикации в базе")
        print(f"   ✅ Логика: 1 пост в час, но в любое время часа")
        
    except Exception as e:
        print(f"❌ Ошибка тестирования: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_fixed_scheduler()



