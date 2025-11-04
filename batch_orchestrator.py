#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Авто-оркестратор Batch API:
- Собирает queued задачи (llm_tasks), отправляет батч при достижении порога или таймаута
- Пуллит незавершённые батчи и применяет результаты автоматически

Настройка через переменные окружения:
- MIN_BATCH_SIZE (int, по умолчанию 50)
- BATCH_MAX_WAIT_SEC (int, по умолчанию 300)
- ORCHESTRATOR_POLL_INTERVAL_SEC (int, по умолчанию 60)
"""

import os
import json
import time
from datetime import datetime, timedelta
import uuid
from typing import List, Dict, Optional

from openai import OpenAI
from workers.tools.firebase_client import get_firebase_client
from llm_batch_manager import LlmBatchManager
from batch_worker import collect_queued_tasks, build_jsonl, submit_batch, mark_submitted
from batch_results_processor import process_batch_results
from rss_parser import load_env_file, RSSParser
from jobs_scheduler import PublicationScheduler


class BatchOrchestrator:
    def __init__(self):
        # Загружаем .env при старте
        try:
            load_env_file()
        except Exception:
            pass
        self.db = get_firebase_client().db
        self.min_batch_size = int(os.getenv('MIN_BATCH_SIZE', '50'))
        self.max_wait_sec = int(os.getenv('BATCH_MAX_WAIT_SEC', '300'))
        self.poll_interval = int(os.getenv('ORCHESTRATOR_POLL_INTERVAL_SEC', '60'))
        self.rss_poll_interval = int(os.getenv('RSS_POLL_INTERVAL_SEC', '1800'))
        self._last_rss_fetch_ts: float = 0.0
        self._rss_parser: Optional[RSSParser] = None
        self.instance_id = str(uuid.uuid4())[:8]
        print(f"[orchestrator] start id={self.instance_id}; MIN_BATCH_SIZE={self.min_batch_size}, MAX_WAIT={self.max_wait_sec}, POLL={self.poll_interval}, RSS_POLL={self.rss_poll_interval}")
        self._lock_lease_sec = int(os.getenv('ORCHESTRATOR_LOCK_LEASE_SEC', '600'))
        # Периодический бэкфилл завершённых батчей OpenAI
        self._backfill_interval_sec = int(os.getenv('BACKFILL_POLL_INTERVAL_SEC', '600'))
        self._last_backfill_ts: float = 0.0
        # Параметры кластеризации из источников
        self.cluster_min_size = int(os.getenv('CLUSTER_MIN_SIZE', '20'))
        self.cluster_max_wait_sec = int(os.getenv('CLUSTER_MAX_WAIT_SEC', '600'))
        # Ежедневная приоритизация
        self._daily_prioritization_interval = int(os.getenv('DAILY_PRIORITIZATION_INTERVAL_SEC', '3600'))  # 1 час
        self._last_prioritization_ts: float = 0.0
        self._last_cluster_enqueue_ts: float = 0.0

    def _ensure_rss_parser(self) -> RSSParser:
        if not self._rss_parser:
            self._rss_parser = RSSParser()
        return self._rss_parser

    def fetch_rss_if_due(self) -> None:
        now = time.time()
        if now - self._last_rss_fetch_ts < self.rss_poll_interval:
            return
        # Не тянем новые RSS, если система занята: queued задачи или активные батчи
        if not self._can_fetch_now():
            return
        self._last_rss_fetch_ts = now
        try:
            parser = self._ensure_rss_parser()
            feeds_file = os.getenv('FEEDS_FILE', 'feeds.txt')
            print(f"[orchestrator] RSS fetch start: {feeds_file}")
            parser.process_multiple_feeds(feeds_file)
        except Exception as e:
            print(f"[orchestrator] RSS fetch error: {e}")

    def _can_fetch_now(self) -> bool:
        try:
            # Если есть queued задачи или активные батчи, откладываем загрузку RSS
            queued = list(self.db.collection('llm_tasks').where('status', '==', 'queued').limit(1).stream())
            if queued:
                return False
            active_statuses = {'submitted', 'validating', 'in_progress', 'finalizing'}
            active = [d for d in self.db.collection('llm_batches').limit(50).stream() if (d.to_dict() or {}).get('status') in active_statuses]
            if active:
                return False
            return True
        except Exception:
            return True

    def _get_oldest_queued_created_at(self) -> datetime:
        try:
            tasks_ref = self.db.collection('llm_tasks')
            # Без order_by, чтобы не требовался индекс
            docs = tasks_ref.where('status', '==', 'queued').limit(200).stream()
            for d in docs:
                data = d.to_dict()
                ts = data.get('created_at')
                if ts:
                    try:
                        return datetime.fromisoformat(ts)
                    except Exception:
                        return datetime.utcnow()
            return None
        except Exception:
            return None

    def submit_if_needed(self) -> None:
        tasks = collect_queued_tasks(limit=1000)
        if not tasks:
            return
        oldest = self._get_oldest_queued_created_at()
        age_ok = False
        if oldest:
            age_ok = (datetime.utcnow() - oldest) >= timedelta(seconds=self.max_wait_sec)

        if len(tasks) >= self.min_batch_size or age_ok:
            # Отправляем раздельно по эндпоинтам (chat/completions и responses)
            from batch_worker import submit_tasks_partitioned, partition_tasks_by_endpoint
            buckets = partition_tasks_by_endpoint(tasks)
            mapping = submit_tasks_partitioned(tasks)
            # Регистрируем батчи
            for endpoint, batch_id in mapping.items():
                try:
                    self.db.collection('llm_batches').document(batch_id).set({
                        'batch_id': batch_id,
                        'status': 'submitted',
                        'endpoint': endpoint,
                        'created_at': datetime.utcnow().isoformat()
                    }, merge=True)
                except Exception:
                    pass
                size = len(buckets.get(endpoint, []))
                print(f"[orchestrator] submitted batch {batch_id} endpoint={endpoint} with {size} tasks")
        else:
            print(f"[orchestrator] queued={len(tasks)} (waiting for size/time)")

    def poll_batches(self) -> None:
        try:
            batches_ref = self.db.collection('llm_batches')
            # Берём последние N батчей без фильтра по статусу и фильтруем локально
            docs_all = list(batches_ref.limit(200).stream())
        except Exception:
            docs_all = []
        if not docs_all:
            return
        # Оставляем только активные статусы
        active_statuses = {'submitted', 'validating', 'in_progress', 'finalizing'}
        docs = [d for d in docs_all if (d.to_dict() or {}).get('status') in active_statuses]
        if not docs:
            return
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        for d in docs:
            data = d.to_dict() or {}
            batch_id = data.get('batch_id')
            if not batch_id:
                continue
            try:
                b = client.batches.retrieve(batch_id)
                status = getattr(b, 'status', None)
                # Обновляем статус
                self.db.collection('llm_batches').document(batch_id).set({
                    'status': status,
                    'updated_at': datetime.utcnow().isoformat()
                }, merge=True)
                if status == 'completed':
                    # Пропускаем батчи без файла результата
                    if not getattr(b, 'output_file_id', None):
                        print(f"[orchestrator] batch {batch_id} completed but no output_file_id; skip")
                        self.db.collection('llm_batches').document(batch_id).set({
                            'status': 'completed',
                            'updated_at': datetime.utcnow().isoformat()
                        }, merge=True)
                    else:
                        process_batch_results(batch_id)
                    self.db.collection('llm_batches').document(batch_id).set({
                        'status': 'completed',
                        'completed_at': datetime.utcnow().isoformat()
                    }, merge=True)
                    print(f"[orchestrator] processed results for batch {batch_id}")
                elif status in {'failed', 'cancelled', 'expired'}:
                    print(f"[orchestrator] batch {batch_id} terminal status={status}")
                    # Проверяем, нужно ли повторить failed батч
                    if status == 'failed':
                        self._handle_failed_batch(batch_id, b)
                else:
                    print(f"[orchestrator] batch {batch_id} status={status}")
            except Exception as e:
                print(f"[orchestrator] error polling batch {batch_id}: {e}")
                continue

    def _handle_failed_batch(self, batch_id: str, openai_batch) -> None:
        """Обрабатывает failed батч и решает, нужно ли его повторить"""
        try:
            # Получаем информацию о батче из Firebase
            firebase_doc = self.db.collection('llm_batches').document(batch_id).get()
            if not firebase_doc.exists:
                print(f"[orchestrator] batch {batch_id} not found in Firebase")
                return
            
            firebase_data = firebase_doc.to_dict()
            retry_count = firebase_data.get('retry_count', 0)
            max_retries = 3  # Максимум 3 попытки
            
            # Проверяем ошибку
            error_message = ""
            should_retry = False
            
            if hasattr(openai_batch, 'errors') and openai_batch.errors:
                try:
                    # Пытаемся извлечь сообщение об ошибке
                    if hasattr(openai_batch.errors, 'data') and openai_batch.errors.data:
                        error_message = openai_batch.errors.data[0].message
                    else:
                        error_message = str(openai_batch.errors)
                except:
                    error_message = "Unknown error"
            
            # Определяем, стоит ли повторять
            if retry_count < max_retries and 'token limit' in error_message.lower():
                should_retry = True
                print(f"[orchestrator] batch {batch_id} failed with token limit, scheduling retry {retry_count + 1}/{max_retries}")
            elif retry_count >= max_retries:
                print(f"[orchestrator] batch {batch_id} exceeded max retries ({max_retries})")
            
            # Обновляем информацию в Firebase
            update_data = {
                'status': 'failed',
                'error_message': error_message,
                'retry_count': retry_count + 1,
                'should_retry': should_retry,
                'updated_at': datetime.utcnow().isoformat()
            }
            
            self.db.collection('llm_batches').document(batch_id).set(update_data, merge=True)
            
            if should_retry:
                # Помечаем задачи для повторной отправки
                self._requeue_batch_tasks(batch_id)
                
        except Exception as e:
            print(f"[orchestrator] error handling failed batch {batch_id}: {e}")
    
    def _requeue_batch_tasks(self, batch_id: str) -> None:
        """Помечает задачи из failed батча для повторной отправки"""
        try:
            # Находим задачи этого батча
            tasks_query = self.db.collection('llm_tasks').where('batch_id', '==', batch_id)
            tasks = list(tasks_query.stream())
            
            requeued_count = 0
            for task_doc in tasks:
                task_data = task_doc.to_dict()
                if task_data.get('status') in ['submitted', 'done']:
                    # Возвращаем задачу в очередь
                    self.db.collection('llm_tasks').document(task_doc.id).set({
                        'status': 'queued',
                        'batch_id': None,
                        'requeued_at': datetime.utcnow().isoformat()
                    }, merge=True)
                    requeued_count += 1
            
            print(f"[orchestrator] requeued {requeued_count} tasks from batch {batch_id}")
            
        except Exception as e:
            print(f"[orchestrator] error requeuing tasks from batch {batch_id}: {e}")

    def _collect_interesting_sources(self, limit: int = 200):
        try:
            # Берём интересные источники; флаг cluster_enqueued фильтруем на клиенте,
            # чтобы захватить документы, где поле отсутствует
            docs = list(self.db.collection('sources').where('interesting', '==', True).limit(limit).stream())
        except Exception:
            docs = []
        items = []
        for d in docs:
            try:
                data = d.to_dict() or {}
                # Пропускаем уже отправленные в кластеризацию
                if data.get('cluster_enqueued', False):
                    continue
                title = data.get('title', '')
                summary = data.get('summary', '')
                link = data.get('link', '')
                date = data.get('date', '') or data.get('published_at', '') or data.get('checked_at', '')
                tags = data.get('categories', []) or []
                items.append({
                    'doc_ref': d.reference,
                    'announcement': {
                        'title': title,
                        'summary': summary,
                        'link': link,
                        'date': date,
                        'tags': tags
                    },
                    'created_at': data.get('checked_at', '')
                })
            except Exception:
                continue
        return items

    def enqueue_clusters_if_due(self) -> None:
        items = self._collect_interesting_sources(limit=500)
        if not items:
            return
        # Условия: накопили достаточно или ждали достаточно долго
        oldest_iso = min([i.get('created_at') or '' for i in items]) or None
        age_ok = False
        if oldest_iso:
            try:
                age_ok = (datetime.utcnow() - datetime.fromisoformat(oldest_iso)) >= timedelta(seconds=self.cluster_max_wait_sec)
            except Exception:
                age_ok = False
        if len(items) < self.cluster_min_size and not age_ok:
            return
        announcements = [i['announcement'] for i in items]
        try:
            from llm_batch_manager import LlmBatchManager
            LlmBatchManager().enqueue_cluster_batch(announcements)
            # помечаем источники как отправленные в кластеризацию
            for i in items:
                try:
                    i['doc_ref'].set({'cluster_enqueued': True, 'cluster_enqueued_at': datetime.utcnow().isoformat()}, merge=True)
                except Exception:
                    continue
            print(f"[orchestrator] cluster_batch enqueued: {len(announcements)} announcements")
        except Exception as e:
            print(f"[orchestrator] enqueue cluster_batch failed: {e}")

    def run_daily_prioritization_if_due(self) -> None:
        """Запускает ежедневную приоритизацию если пришло время"""
        now_ts = time.time()
        if now_ts - self._last_prioritization_ts >= self._daily_prioritization_interval:
            try:
                print("[orchestrator] running daily prioritization...")
                from daily_prioritization import DailyPrioritization
                
                prioritizer = DailyPrioritization()
                results = prioritizer.update_all_article_priorities()
                
                print(f"[orchestrator] daily prioritization completed: updated={results.get('updated_count', 0)}, urgent={results.get('urgent_count', 0)}")
                self._last_prioritization_ts = now_ts
                
            except Exception as e:
                print(f"[orchestrator] daily prioritization failed: {e}")

    def run_forever(self) -> None:
        if not self._acquire_lock():
            print("[orchestrator] another instance is active; exiting")
            return
        # Одноразовый бэкфил завершенных батчей при старте
        try:
            self._backfill_recent_completed_batches()
        except Exception as e:
            print(f"[orchestrator] backfill error: {e}")
        while True:
            try:
                # Периодическая загрузка RSS и постановка задач фильтрации в Batch
                self.fetch_rss_if_due()
                self.submit_if_needed()
                self.poll_batches()
                self.enqueue_clusters_if_due()
                self.run_daily_prioritization_if_due()
                # Периодически пробуем добрать завершённые батчи, которых нет в Firestore
                try:
                    now_ts = time.time()
                    if now_ts - self._last_backfill_ts >= self._backfill_interval_sec:
                        self._backfill_recent_completed_batches()
                        self._last_backfill_ts = now_ts
                except Exception as e:
                    print(f"[orchestrator] periodic backfill error: {e}")
                # Периодически пытаемся публиковать готовые статьи
                try:
                    res = PublicationScheduler().run()
                    if isinstance(res, dict):
                        print(f"[orchestrator] scheduler tick: published={res.get('articles_published',0)} total_checked={res.get('total_articles_checked',0)}")
                except Exception as e:
                    print(f"[orchestrator] scheduler error: {e}")
                self._renew_lock()
            except Exception as e:
                print(f"[orchestrator] loop error: {e}")
            time.sleep(self.poll_interval)

    def _backfill_recent_completed_batches(self) -> None:
        """Обрабатывает последние завершённые батчи OpenAI, которых нет в Firestore."""
        try:
            client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        except Exception as e:
            print(f"[orchestrator] OpenAI init failed: {e}")
            return
        try:
            existing = {d.id for d in self.db.collection('llm_batches').limit(500).stream()}
        except Exception:
            existing = set()
        try:
            batches = client.batches.list(limit=25)
        except Exception as e:
            print(f"[orchestrator] list batches failed: {e}")
            return
        for b in getattr(batches, 'data', []) or []:
            b_id = getattr(b, 'id', None)
            b_status = getattr(b, 'status', None)
            if not b_id or b_id in existing or b_status != 'completed':
                continue
            try:
                process_batch_results(b_id)
                self.db.collection('llm_batches').document(b_id).set({
                    'batch_id': b_id,
                    'status': 'completed',
                    'completed_at': datetime.utcnow().isoformat(),
                    'backfilled': True
                }, merge=True)
                print(f"[orchestrator] backfilled batch {b_id}")
            except Exception as e:
                print(f"[orchestrator] backfill batch {b_id} error: {e}")

    # -------- Single-instance lock --------
    def _acquire_lock(self) -> bool:
        try:
            locks = self.db.collection('locks').document('orchestrator')
            doc = locks.get()
            now = datetime.utcnow()
            if doc.exists:
                data = doc.to_dict() or {}
                exp = data.get('expires_at')
                holder_id = data.get('holder_id', 'unknown')
                
                if exp:
                    try:
                        exp_dt = datetime.fromisoformat(exp)
                        if exp_dt > now:
                            print(f"[orchestrator] another instance is active (holder: {holder_id}, expires: {exp})")
                            return False
                        else:
                            print(f"[orchestrator] previous lock expired (holder: {holder_id}), acquiring...")
                    except Exception:
                        print(f"[orchestrator] invalid lock timestamp, clearing...")
                else:
                    print(f"[orchestrator] lock without expiration found (holder: {holder_id}), clearing...")
            
            # Устанавливаем новую блокировку
            locks.set({
                'holder_id': self.instance_id,
                'acquired_at': now.isoformat(),
                'expires_at': (now + timedelta(seconds=self._lock_lease_sec)).isoformat(),
                'started_at': now.isoformat()
            }, merge=True)
            return True
        except Exception:
            return True

    def _renew_lock(self) -> None:
        try:
            locks = self.db.collection('locks').document('orchestrator')
            now = datetime.utcnow()
            locks.set({
                'holder_id': self.instance_id,
                'expires_at': (now + timedelta(seconds=self._lock_lease_sec)).isoformat(),
                'updated_at': now.isoformat()
            }, merge=True)
        except Exception:
            pass


def main():
    orchestrator = BatchOrchestrator()
    orchestrator.run_forever()


if __name__ == '__main__':
    main()


