#!/usr/bin/env python3
# temp_count_articles.py
"""
Temporary helper: count articles and sample a few docs from Firestore.
This script is temporary and safe to run locally. It instantiates a
FirebaseClient directly so you can pass a custom credentials path via
$env:FIREBASE_CREDENTIALS if needed.

Usage (PowerShell):
  $env:FIREBASE_CREDENTIALS = 'C:\path\to\service-account.json'  # optional
  python .\temp_count_articles.py

If FIREBASE_CREDENTIALS is not set the script will use 'firebase_key.json'
from the repository root.
"""
import os
import traceback

try:
    # Import the FirebaseClient class directly so we can pass a credentials path
    from workers.tools.firebase_client import FirebaseClient
except Exception as e:
    print("ERROR: could not import FirebaseClient from workers.tools.firebase_client:")
    traceback.print_exc()
    raise SystemExit(1)


def main():
    cred_path = os.getenv('FIREBASE_CREDENTIALS', 'firebase_key.json')
    print(f"Using credentials path: {cred_path}")

    try:
        client = FirebaseClient(credentials_path=cred_path)
    except Exception as e:
        print("ERROR: failed to initialize FirebaseClient:")
        traceback.print_exc()
        return

    # Show verbose flag if present
    verbose = getattr(client, '_verbose', None)
    print('FIREBASE_VERBOSE =', verbose)

    # Count articles using helper
    try:
        count = client.count_articles()
        print('articles_count:', count)
    except Exception as e:
        print('Error calling client.count_articles():')
        traceback.print_exc()

    # Sample up to 5 docs using the underlying db
    try:
        db = client.db
        if not db:
            print('client.db is None; cannot sample documents')
            return

        print('\nSample up to 5 article documents (id and keys):')
        docs = db.collection('articles').limit(5).stream()
        n = 0
        for d in docs:
            n += 1
            try:
                data = d.to_dict() or {}
                print(f" - id={d.id} keys={list(data.keys())}")
            except Exception:
                print(f" - id={d.id} (could not read fields)")
        if n == 0:
            print(' (no documents streamed)')
    except Exception as e:
        print('Error sampling documents:')
        traceback.print_exc()


if __name__ == '__main__':
    main()
