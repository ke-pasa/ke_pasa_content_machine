#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import argparse
from datetime import datetime

# Ensure project root
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from firebase_client import get_firebase_client


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
    parser = argparse.ArgumentParser()
    parser.add_argument('--batch-id', required=True)
    parser.add_argument('--endpoint', default='/v1/chat/completions')
    args = parser.parse_args()

    load_env_file()
    db = get_firebase_client().db
    db.collection('llm_batches').document(args.batch_id).set({
        'batch_id': args.batch_id,
        'status': 'submitted',
        'endpoint': args.endpoint,
        'created_at': datetime.utcnow().isoformat(),
        'registered_manually': True
    }, merge=True)
    print('registered', args.batch_id, args.endpoint)


if __name__ == '__main__':
    main()













