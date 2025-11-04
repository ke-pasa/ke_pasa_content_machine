#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from collections import Counter, defaultdict

# Ensure project root in path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from workers.tools.firebase_client import get_firebase_client


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
    load_env_file()
    db = get_firebase_client().db
    docs = list(db.collection('llm_tasks').where('status', '==', 'queued').limit(1000).stream())
    by_type = Counter()
    by_model = Counter()
    sample_by_type = defaultdict(list)
    for d in docs:
        data = d.to_dict() or {}
        t = data.get('type') or 'unknown'
        m = data.get('model') or 'unknown'
        by_type[t] += 1
        by_model[m] += 1
        if len(sample_by_type[t]) < 3:
            sample_by_type[t].append({'task_id': data.get('task_id'), 'model': m})
    print('queued_total', len(docs))
    print('by_type', dict(by_type))
    print('by_model', dict(by_model))
    for t, items in sample_by_type.items():
        print('sample', t, items)


if __name__ == '__main__':
    main()













