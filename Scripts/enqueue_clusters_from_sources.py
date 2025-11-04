#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from datetime import datetime
from typing import List, Dict

# Ensure project root on path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from workers.tools.firebase_client import get_firebase_client
from llm_batch_manager import LlmBatchManager


def load_env_file() -> None:
    try:
        env_path = os.path.join(PROJECT_ROOT, '.env')
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        k, v = line.split('=', 1)
                        os.environ[k.strip()] = v.strip()
    except Exception:
        pass


def main() -> None:
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--limit', type=int, default=50, help='Макс. кол-во анонсов из sources')
    args = p.parse_args()

    load_env_file()
    db = get_firebase_client().db

    try:
        # Берём интересные записи; фильтр по cluster_enqueued делаем на клиенте
        docs = list(db.collection('sources').where('interesting', '==', True).limit(500).stream())
    except Exception:
        docs = []
    announcements: List[Dict] = []
    refs_to_mark = []
    for d in docs:
        try:
            data = d.to_dict() or {}
            if data.get('cluster_enqueued', False):
                continue
            ann = {
                'title': data.get('title', ''),
                'summary': data.get('summary', ''),
                'link': data.get('link', ''),
                'date': data.get('date', '') or data.get('published_at', '') or data.get('checked_at', ''),
                'tags': data.get('categories', []) or []
            }
            announcements.append(ann)
            refs_to_mark.append(d.reference)
            if len(announcements) >= args.limit:
                break
        except Exception:
            continue

    if not announcements:
        print('no announcements to enqueue')
        return

    batch_id = LlmBatchManager().enqueue_cluster_batch(announcements)
    print('cluster_batch enqueued for', len(announcements), 'announcements')
    # помечаем источники
    for ref in refs_to_mark:
        try:
            ref.set({'cluster_enqueued': True, 'cluster_enqueued_at': datetime.utcnow().isoformat()}, merge=True)
        except Exception:
            continue


if __name__ == '__main__':
    main()













