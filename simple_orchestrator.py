#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Упрощенный оркестратор без кластеризации:
- Парсит RSS ленты каждые 2 часа
- Генерирует статьи на основе обработанных новостей каждые 10 минут после RSS
- Публикует в Telegram через планировщик
"""

import os
import time
from datetime import datetime, timedelta, timezone
import uuid
from typing import Optional
from dotenv import load_dotenv
import json

# Загружаем переменные окружения из .env файла
load_dotenv()

from firebase_client import get_firebase_client
from rss_parser import RSSParser
from jobs_scheduler_backup import PublicationScheduler
from daily_prioritization import DailyPrioritization
from news_clustering import create_clustering_pipeline
import openai


class SimpleOrchestrator:
    def __init__(self):
        """Инициализация упрощенного оркестратора"""
        self.db = get_firebase_client().db
        self.instance_id = str(uuid.uuid4())[:8]
        
        # Интервалы в секундах согласно требованиям
        self.rss_poll_interval = int(os.getenv('RSS_POLL_INTERVAL_SEC', '7200'))  # 2 часа - RSS парсинг
        self.article_generation_interval = int(os.getenv('ARTICLE_GENERATION_INTERVAL_SEC', '600'))  # 10 минут - генерация статей
        self.scheduler_interval = int(os.getenv('SCHEDULER_INTERVAL_SEC', '3600'))  # 1 час - публикация в Telegram
        self.prioritization_interval = int(os.getenv('PRIORITIZATION_INTERVAL_SEC', '86400'))  # 24 часа - приоритизация
        
        # Блокировка для предотвращения множественных экземпляров
        self._lock_lease_sec = int(os.getenv('ORCHESTRATOR_LOCK_LEASE_SEC', '600'))  # 10 минут
        
        # Временные метки
        self._last_rss_fetch_ts: float = 0.0
        self._last_article_generation_ts: float = 0.0
        self._last_scheduler_run_ts: float = 0.0
        self._last_prioritization_ts: float = 0.0
        
        # Компоненты
        self._rss_parser: Optional[RSSParser] = None
        self._scheduler: Optional[PublicationScheduler] = None
        self._prioritization: Optional[DailyPrioritization] = None
        
        print(f"[simple-orchestrator] start id={self.instance_id}")
        print(f"[simple-orchestrator] RSS_POLL={self.rss_poll_interval}s, ARTICLE_GEN={self.article_generation_interval}s, SCHEDULER={self.scheduler_interval}s, PRIORITIZATION={self.prioritization_interval}s")
        
        # Создаем папку для статей если её нет
        self.articles_dir = "articles"
        if not os.path.exists(self.articles_dir):
            os.makedirs(self.articles_dir)
            print(f"[simple-orchestrator] 📁 Создана папка {self.articles_dir}")

    def save_article_to_file(self, article_id: str, original_article: dict, generated_article: dict = None):
        """
        Сохраняет статью в файл
        
        Args:
            article_id: ID статьи из Firebase
            original_article: Оригинальная статья (на испанском)
            generated_article: Сгенерированная статья (на русском), опционально
        """
        try:
            filename = f"{article_id}.txt"
            filepath = os.path.join(self.articles_dir, filename)
            
            # Создаем содержимое файла
            content = []
            content.append("=" * 80)
            content.append(f"СТАТЬЯ ID: {article_id}")
            content.append(f"СОЗДАНА: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            content.append("=" * 80)
            content.append("")
            
            # Оригинальная статья (испанская)
            content.append("🇪🇸 ОРИГИНАЛЬНАЯ СТАТЬЯ (ИСПАНСКИЙ)")
            content.append("-" * 50)
            content.append(f"ЗАГОЛОВОК: {original_article.get('title', 'Не указан')}")
            content.append(f"ССЫЛКА: {original_article.get('link', 'Не указана')}")
            content.append(f"ИСТОЧНИК: {original_article.get('source', 'Не указан')}")
            content.append(f"ДАТА ПУБЛИКАЦИИ: {original_article.get('published_date', 'Не указана')}")
            content.append("")
            content.append("КРАТКОЕ ОПИСАНИЕ:")
            content.append(original_article.get('summary', 'Не указано'))
            content.append("")
            content.append("ПОЛНЫЙ ТЕКСТ:")
            content.append(original_article.get('content', original_article.get('summary', 'Нет содержимого')))
            content.append("")
            
            # Русская статья (если есть)
            if generated_article:
                content.append("🇷🇺 РУССКАЯ СТАТЬЯ")
                content.append("-" * 50)
                content.append(f"ЗАГОЛОВОК: {generated_article.get('title', 'Не указан')}")
                content.append("")
                content.append("СОДЕРЖАНИЕ:")
                content.append(generated_article.get('content', 'Не указано'))
                content.append("")
                content.append("ОПИСАНИЕ:")
                content.append(generated_article.get('description', 'Не указано'))
                content.append("")
                if generated_article.get('tags'):
                    content.append(f"ТЕГИ: {', '.join(generated_article.get('tags', []))}")
                    content.append("")
            
            # Метаданные
            content.append("📊 МЕТАДАННЫЕ")
            content.append("-" * 50)
            content.append(f"ПРИОРИТЕТ: {original_article.get('priority_score', 0)}")
            content.append(f"СРОЧНОСТЬ: {'Да' if original_article.get('urgent', False) else 'Нет'}")
            content.append(f"КАТЕГОРИИ: {', '.join(original_article.get('categories', []))}")
            content.append(f"ОБРАБОТАНО: {'Да' if original_article.get('processed', False) else 'Нет'}")
            content.append(f"ЭКСПОРТИРОВАНО: {'Да' if original_article.get('exported_to_site', False) else 'Нет'}")
            content.append(f"ОПУБЛИКОВАНО: {'Да' if original_article.get('published', False) else 'Нет'}")
            
            # Записываем в файл
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write('\n'.join(content))
            
            print(f"[simple-orchestrator] 💾 Статья сохранена в файл: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"[simple-orchestrator] ❌ Ошибка сохранения статьи в файл: {e}")
            return None

    def _acquire_lock(self) -> bool:
        """Приобретает блокировку для эксклюзивного запуска"""
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('orchestrator')
            lock_doc = locks.get()
            
            if lock_doc.exists:
                lock_data = lock_doc.to_dict()
                holder_id = lock_data.get('holder_id')
                exp = lock_data.get('expires_at')
                
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(exp)
                        # Убеждаемся что exp_dt имеет timezone
                        if exp_dt.tzinfo is None:
                            exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                        
                        # Если блокировка истекла, принудительно освобождаем её
                        if exp_dt <= now:
                            print(f"[simple-orchestrator] previous lock expired (holder: {holder_id}), clearing...")
                            locks.delete()
                        else:
                            # Проверяем, не слишком ли долго работает предыдущий экземпляр
                            started_at = lock_data.get('started_at')
                            if started_at:
                                try:
                                    start_dt = datetime.fromisoformat(started_at)
                                    if start_dt.tzinfo is None:
                                        start_dt = start_dt.replace(tzinfo=timezone.utc)
                                    
                                    # Если экземпляр работает больше 15 минут, считаем его зависшим
                                    if (now - start_dt).total_seconds() > 900:  # 15 минут
                                        print(f"[simple-orchestrator] previous instance seems stuck (running for {int((now - start_dt).total_seconds()/60)} minutes), forcing release...")
                                        locks.delete()
                                    else:
                                        print(f"[simple-orchestrator] another instance is active (holder: {holder_id}, expires: {exp})")
                                        return False
                                except Exception:
                                    print(f"[simple-orchestrator] invalid start timestamp, clearing lock...")
                                    locks.delete()
                            else:
                                print(f"[simple-orchestrator] another instance is active (holder: {holder_id}, expires: {exp})")
                                return False
                    except Exception:
                        print(f"[simple-orchestrator] invalid lock timestamp, clearing...")
                        locks.delete()
                else:
                    print(f"[simple-orchestrator] lock without expiration found (holder: {holder_id}), clearing...")
                    locks.delete()
            
            # Устанавливаем новую блокировку с уменьшенным временем жизни
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=300)).isoformat(),  # 5 минут вместо 10
                'started_at': now.isoformat()
            }, merge=True)
            print(f"[simple-orchestrator] lock acquired successfully")
            return True
        except Exception as e:
            print(f"[simple-orchestrator] error acquiring lock: {e}")
            return True

    def _update_lock(self):
        """Обновляет время жизни блокировки"""
        try:
            now = datetime.now(timezone.utc)
            locks = self.db.collection('locks').document('orchestrator')
            locks.update({
                'expires_at': (now + timedelta(seconds=300)).isoformat(),  # 5 минут
                'last_updated': now.isoformat()
            })
        except Exception as e:
            print(f"[simple-orchestrator] error updating lock: {e}")

    def _release_lock(self):
        """Освобождает блокировку"""
        try:
            locks = self.db.collection('locks').document('orchestrator')
            locks.delete()
            print(f"[simple-orchestrator] lock released")
        except Exception as e:
            print(f"[simple-orchestrator] error releasing lock: {e}")

    def _get_rss_parser(self) -> RSSParser:
        """Получает экземпляр RSS парсера"""
        if self._rss_parser is None:
            self._rss_parser = RSSParser()
        return self._rss_parser

    def _get_scheduler(self) -> PublicationScheduler:
        """Получает экземпляр планировщика публикаций"""
        if self._scheduler is None:
            self._scheduler = PublicationScheduler()
        return self._scheduler



    def _get_prioritization(self) -> DailyPrioritization:
        """Получает экземпляр системы приоритизации"""
        if self._prioritization is None:
            self._prioritization = DailyPrioritization()
        return self._prioritization

    def fetch_rss_if_due(self):
        """Парсит RSS ленты если пришло время (каждые 2 часа)"""
        now = time.time()
        if now - self._last_rss_fetch_ts < self.rss_poll_interval:
            return
        
        print(f"[simple-orchestrator] RSS fetch start: feeds.txt")
        self._last_rss_fetch_ts = now
        
        feeds_file = "feeds.txt"
        if not os.path.exists(feeds_file):
            print(f"[simple-orchestrator] feeds file not found: {feeds_file}")
            return
        
        try:
            parser = self._get_rss_parser()
            parser.process_multiple_feeds(feeds_file)
            print(f"[simple-orchestrator] RSS fetch completed")
        except Exception as e:
            print(f"[simple-orchestrator] RSS fetch error: {e}")

    def run_article_generation_if_due(self):
        """Генерирует статьи на основе обработанных RSS новостей если пришло время"""
        now = time.time()
        if now - self._last_article_generation_ts < self.article_generation_interval:
            return
        
        self._last_article_generation_ts = now
        
        try:
            # Получаем статьи, готовые к генерации: processed=True, exported_to_site=False, published=False
            articles_ref = self.db.collection('articles')
            
            print(f"[simple-orchestrator] 🔍 Ищу статьи для генерации...")
            
            # Используем fallback логику, так как индексы не работают
            print(f"[simple-orchestrator] 🔄 Использую fallback логику (индексы не работают)...")
            articles_docs = list(articles_ref.limit(500).stream())  # Увеличиваем лимит
            print(f"[simple-orchestrator] 🔍 Fallback: получено {len(articles_docs)} документов")

            articles = []
            processed_count = 0
            exported_count = 0
            published_count = 0
            
            for doc in articles_docs:
                data = doc.to_dict() or {}
                processed = data.get('processed', False)
                exported = data.get('exported_to_site', False)
                published = data.get('published', False)
                
                if processed:
                    processed_count += 1
                if exported:
                    exported_count += 1
                if published:
                    published_count += 1
                
                if (not published and not exported and processed):
                    data['id'] = doc.id
                    articles.append(data)
            
            print(f"[simple-orchestrator] 🔍 Статистика по документам:")
            print(f"[simple-orchestrator]   - processed=True: {processed_count}")
            print(f"[simple-orchestrator]   - exported_to_site=True: {exported_count}")
            print(f"[simple-orchestrator]   - published=True: {published_count}")
            print(f"[simple-orchestrator] 🔍 После фильтрации готово к генерации: {len(articles)} статей")
            
            if not articles:
                print(f"[simple-orchestrator] article generation skip: no articles ready for generation")
                return
            
            print(f"[simple-orchestrator] article generation start: {len(articles)} articles")
            
            # Генерируем статьи для каждой новости
            from content_generator import generate_article_from_news
            from firebase_client import get_firebase_client
            
            firebase_client = get_firebase_client()
            generated_count = 0
            
            for article in articles:
                try:
                    print(f"[simple-orchestrator] generating article for: {article['title'][:50]}...")
                    
                    # Проверяем наличие обязательных полей
                    title = article.get('title', '').strip()
                    summary = article.get('summary', '').strip()
                    link = article.get('link', '').strip()
                    
                    # Если summary пустое, пытаемся использовать альтернативные поля
                    if not summary:
                        content = article.get('content', '').strip()
                        description = article.get('description', '').strip()
                        
                        if content and len(content) > 50:
                            summary = content[:200].strip()
                            if len(content) > 200:
                                summary += "..."
                            print(f"[simple-orchestrator] 🔧 Использую content как summary для статьи {article['id']}")
                        elif description and len(description) > 20:
                            summary = description.strip()
                            print(f"[simple-orchestrator] 🔧 Использую description как summary для статьи {article['id']}")
                    
                    if not title or not summary or not link:
                        print(f"[simple-orchestrator] ⚠️  Пропускаю статью без обязательных полей: {article['id']}")
                        print(f"[simple-orchestrator]   - title: {'✓' if title else '✗'} ({len(title)} chars)")
                        print(f"[simple-orchestrator]   - summary: {'✓' if summary else '✗'} ({len(summary)} chars)")
                        print(f"[simple-orchestrator]   - link: {'✓' if link else '✗'} ({len(link)} chars)")
                        
                        # Дополнительная диагностика
                        content = article.get('content', '').strip()
                        description = article.get('description', '').strip()
                        print(f"[simple-orchestrator]   - content: {'✓' if content else '✗'} ({len(content)} chars)")
                        print(f"[simple-orchestrator]   - description: {'✓' if description else '✗'} ({len(description)} chars)")
                        continue
                    
                    # Генерируем статью напрямую из новости
                    article_data = {
                        'title': title,
                        'summary': summary,
                        'link': link,
                        'content': article.get('content', summary),
                        'image': article.get('image', ''),
                        'priority_score': article.get('priority_score', 0),
                        'urgent': article.get('urgent', False),
                        'source_article_id': article['id']
                    }
                    
                    # Логируем для отладки
                    content_length = len(article.get('content', ''))
                    summary_length = len(article.get('summary', ''))
                    print(f"[simple-orchestrator] 📄 Длина content: {content_length}, summary: {summary_length}")
                    print(f"[simple-orchestrator] 📄 Используем: {'content' if article.get('content') else 'summary'}")
                    
                    # Генерируем контент
                    article_id = generate_article_from_news(article_data, firebase_client)
                    
                    if article_id:
                        # Получаем сгенерированную статью из Firebase для сохранения в файл
                        generated_article = None
                        try:
                            generated_doc = self.db.collection('generated_articles').document(article_id).get()
                            if generated_doc.exists:
                                generated_article = generated_doc.to_dict()
                        except Exception as e:
                            print(f"[simple-orchestrator] ⚠️  Не удалось получить сгенерированную статью: {e}")
                        
                        # Сохраняем статью в файл
                        self.save_article_to_file(article['id'], article, generated_article)
                        
                        # Отмечаем статью как экспортированную
                        self.db.collection('articles').document(article['id']).update({
                            'exported_to_site': True,
                            'exported_at': datetime.now(timezone.utc).isoformat(),
                            'generated_article_id': article_id
                        })
                        generated_count += 1
                        print(f"[simple-orchestrator] article generated successfully: {article_id}")
                    else:
                        # Сохраняем только оригинальную статью, даже если генерация не удалась
                        self.save_article_to_file(article['id'], article, None)
                        print(f"[simple-orchestrator] failed to generate article for: {article['title'][:30]}...")
                        
                except Exception as e:
                    print(f"[simple-orchestrator] error generating article for {article['id']}: {e}")
            
            print(f"[simple-orchestrator] article generation completed: {generated_count}/{len(articles)} articles generated")
                
        except Exception as e:
            print(f"[simple-orchestrator] article generation error: {e}")



    def run_scheduler_if_due(self):
        """Запускает планировщик публикаций если пришло время"""
        now = time.time()
        if now - self._last_scheduler_run_ts < self.scheduler_interval:
            return
        
        self._last_scheduler_run_ts = now
        
        try:
            scheduler = self._get_scheduler()
            results = scheduler.run_scheduler()
            published = results.get('articles_published', 0)
            total_checked = results.get('total_articles_checked', 0)
            print(f"[simple-orchestrator] scheduler tick: published={published} total_checked={total_checked}")
        except Exception as e:
            print(f"[simple-orchestrator] scheduler error: {e}")

    def run_daily_prioritization_if_due(self):
        """Запускает ежедневную приоритизацию если пришло время"""
        now = time.time()
        if now - self._last_prioritization_ts < self.prioritization_interval:
            return
        
        self._last_prioritization_ts = now
        
        try:
            prioritization = self._get_prioritization()
            results = prioritization.update_all_article_priorities()
            updated = results.get('updated', 0)
            urgent = results.get('urgent', 0)
            print(f"[simple-orchestrator] daily prioritization completed: updated={updated}, urgent={urgent}")
        except Exception as e:
            print(f"[simple-orchestrator] prioritization error: {e}")

    def run_forever(self):
        """Основной цикл оркестратора"""
        print(f"[simple-orchestrator] starting main loop")
        
        last_lock_update = time.time()
        
        while True:
            try:
                # Проверяем и обновляем блокировку каждые 5 минут
                if not self._acquire_lock():
                    time.sleep(300)  # Ждем 5 минут если заблокировано
                    continue
                
                # Обновляем блокировку каждые 2 минуты
                current_time = time.time()
                if current_time - last_lock_update > 120:  # 2 минуты
                    self._update_lock()
                    last_lock_update = current_time
                
                # Выполняем основные задачи
                self.fetch_rss_if_due()
                self.run_article_generation_if_due()
                self.run_scheduler_if_due()
                self.run_daily_prioritization_if_due()
                
                # Ждем перед следующей итерацией
                time.sleep(60)  # Проверяем каждую минуту
                
            except KeyboardInterrupt:
                print(f"[simple-orchestrator] stopping...")
                break
            except Exception as e:
                print(f"[simple-orchestrator] unexpected error: {e}")
                time.sleep(60)
        
        self._release_lock()


def main():
    """Точка входа"""
    orchestrator = SimpleOrchestrator()
    orchestrator.run_forever()


if __name__ == "__main__":
    main()
