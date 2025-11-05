"""
Categorization Worker - thin CLI wrapper.

This module provides a small command-line entrypoint that imports the
CategorizationWorker implementation from workers/categorization/worker_impl.py
and exposes simple actions: categorize, prioritize, stats.
"""

import sys
from pathlib import Path
from dotenv import load_dotenv
import argparse

from .config import CategorizationConfig

# Ensure repo root is importable
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()

# Expose helpers used by tests and the implementation class
from workers.tools.firebase_client import get_firebase_client
from workers.tools.openai_client import get_openai_client, chat_completion, parse_json_from_text

# Re-export CategorizationWorker implementation (implementation lives in CategorizationWorker.py)
from .CategorizationWorker import CategorizationWorker


def main() -> None:
    parser = argparse.ArgumentParser(description='Categorization worker CLI')
    parser.add_argument('--batch-size', type=int, default=None, help='Batch size for categorization (default: config or 10)')
    parser.add_argument('--action', choices=['categorize', 'prioritize', 'stats'], default='categorize')
    args = parser.parse_args()

    config = CategorizationConfig.from_env()
    worker = CategorizationWorker(config=config, batch_size=args.batch_size)

    if args.action == 'categorize':
        result = worker.categorize_new_articles()
        print(result)
    elif args.action == 'prioritize':
        result = worker.update_priorities()
        print(result)
    elif args.action == 'stats':
        result = worker.get_statistics()
        print(result)


if __name__ == '__main__':
    main()
