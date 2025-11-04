#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Миграция: перевод queued-задач типов cluster_batch и prioritize_clusters на модель gpt-4o-mini
для использования чатового эндпоинта (/v1/chat/completions) и обхода лимита enqueued tokens для gpt-5.
"""

import os
import sys
from typing import List, Dict

# Добавляем родительскую директорию (корень проекта) в sys.path, чтобы импорты работали при запуске из scripts/
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from firebase_client import get_firebase_client


def load_env_file() -> None:
    try:
        if os.path.exists('.env'):
            with open('.env', 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()
    except Exception:
        pass


def main() -> None:
    load_env_file()
    db = get_firebase_client().db
    tasks_ref = db.collection('llm_tasks')
    # Читаем локально без order_by для избежания индексов
    docs = list(tasks_ref.where('status', '==', 'queued').limit(1000).stream())
    target_types = {'cluster_batch', 'prioritize_clusters', 'filter_article'}
    updated = 0
    for d in docs:
        try:
            data = d.to_dict() or {}
            t = data.get('type')
            m = (data.get('model') or '').strip()
            # Переводим задачи целевых типов и любые queued с моделью gpt-5-* на чатовый эндпоинт
            if (t in target_types) or m.startswith('gpt-5'):
                d.reference.update({'model': 'gpt-4o-mini'})
                updated += 1
        except Exception:
            continue
    print(f"updated={updated}")


if __name__ == '__main__':
    main()


