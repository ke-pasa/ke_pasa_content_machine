#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys

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
    ref = db.collection('locks').document('orchestrator')
    try:
        ref.delete()
        print('lock deleted')
    except Exception as e:
        print('lock delete error:', e)


if __name__ == '__main__':
    main()













