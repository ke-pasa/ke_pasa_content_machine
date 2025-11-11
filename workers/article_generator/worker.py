"""Thin CLI wrapper for the ArticleGenerator worker."""

import argparse
import json
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure repository root is importable before loading env
root_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(root_dir))

load_dotenv()


from .ArticleGenerator import ArticleGenerator


def main() -> None:
    parser = argparse.ArgumentParser(description='Article generator worker CLI')
    parser.add_argument('--batch-size', type=int, default=None, help='How many categorized articles to process in this run')
    args = parser.parse_args()

    # Always configure logging to stdout so CI (GitHub Actions) captures worker logs
    import logging, sys, os
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s')
    handler.setFormatter(formatter)
    # ensure not to add multiple StreamHandlers
    if not any(isinstance(h, logging.StreamHandler) for h in root_logger.handlers):
        root_logger.addHandler(handler)

    # pre-scan will always run (no skip flag)

    worker = ArticleGenerator(batch_size=args.batch_size)
    result = worker.translated()

    print(json.dumps(result, ensure_ascii=False, indent=2))

    exit_code = 0 if result.get('status') == 'success' else 1
    sys.exit(exit_code)


if __name__ == '__main__':
    main()
