#!/usr/bin/env python3
"""
Temporary helper to add/ensure a `status` field on all documents in the `articles`
collection.

By default this script performs a dry-run and prints how many documents *would*
be updated. Pass `--yes` to actually commit changes. Use `--force` to overwrite
an existing `status` value; otherwise only documents without `status` are
updated.

Usage (PowerShell):

    python .\temp_update_articles_status.py        # dry-run
    python .\temp_update_articles_status.py --yes  # commit changes

This script uses the repository's Firebase credentials discovery (defaults to
`firebase_key.json` or environment overrides used by your existing Firebase
client). It uses batch writes (500 ops per batch) for efficiency.
"""
import argparse
import sys
from typing import Optional

try:
    # Import the project's Firebase client wrapper
    from workers.tools.firebase_client import get_firebase_client, COLLECTIONS
except Exception as e:
    print(f"Failed to import firebase client: {e}")
    raise


def confirm_or_exit(force_yes: bool) -> None:
    if force_yes:
        return
    answer = input("Proceed to commit updates to Firestore? (y/N): ").strip().lower()
    if answer not in ("y", "yes"):
        print("Aborting — no changes were made.")
        sys.exit(1)


def main(dry_run: bool, force_overwrite: bool, batch_size: int, limit: Optional[int]):
    client = get_firebase_client()
    db = client.db
    if not db:
        print("Firebase is not initialized. Check credentials and try again.")
        return

    articles_coll = db.collection(COLLECTIONS['ARTICLES'])
    # Stream documents; use limit when provided for quick tests
    docs_iter = articles_coll.stream()

    planned_updates = []
    total = 0
    to_update_count = 0

    for d in docs_iter:
        total += 1
        if limit and total > limit:
            break
        data = d.to_dict() or {}
        has_status = 'status' in data and data.get('status') not in (None, '')
        if force_overwrite or not has_status:
            planned_updates.append(d.reference)
            to_update_count += 1

    print(f"Total scanned documents: {total}")
    print(f"Documents to update (status->'NEW'): {to_update_count}")

    if to_update_count == 0:
        print("Nothing to do.")
        return

    if dry_run:
        print("Dry-run mode; no changes will be committed. Re-run with --yes to commit.")
        # Print a small sample of ids
        sample = planned_updates[:5]
        print("Sample document ids to update:")
        for r in sample:
            print(f" - {r.id}")
        return

    # If not dry-run, ask for confirmation
    confirm_or_exit(force_yes=False)

    # Commit in batches
    committed = 0
    batch = db.batch()
    ops = 0
    for ref in planned_updates:
        # Use set(..., merge=True) so we don't remove other fields
        batch.set(ref, {"status": "NEW"}, merge=True)
        ops += 1
        if ops >= batch_size:
            batch.commit()
            committed += ops
            print(f"Committed {committed} updates...")
            batch = db.batch()
            ops = 0

    if ops > 0:
        batch.commit()
        committed += ops
        print(f"Committed {committed} updates (final batch).")

    print("Done.")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Update articles: add status='NEW' to documents")
    parser.add_argument('--yes', action='store_true', help='Confirm and commit updates (otherwise dry-run)')
    parser.add_argument('--force', action='store_true', help='Overwrite existing status fields')
    parser.add_argument('--batch-size', type=int, default=250, help='Number of writes per batch (<=500)')
    parser.add_argument('--limit', type=int, default=0, help='Optional: only scan this many documents (for testing)')

    args = parser.parse_args()
    dry_run = not args.yes
    force = args.force
    batch_size = max(1, min(500, args.batch_size))
    limit = args.limit if args.limit and args.limit > 0 else None

    if dry_run:
        print("*** DRY RUN (no changes will be made). Use --yes to commit. ***)")

    main(dry_run=dry_run, force_overwrite=force, batch_size=batch_size, limit=limit)
