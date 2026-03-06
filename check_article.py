#!/usr/bin/env python
"""Check article data from database"""
from workers.tools.pg_client import get_pg_client

article_id = 'b8035166a6c47dbb024f0568e74abf81'

pg = get_pg_client()
conn, pooled = pg._get_conn()
cur = conn.cursor()

try:
    cur.execute(
        'SELECT id, title_ru, telegram_final FROM public.articles_ru WHERE id = %s',
        (article_id,)
    )
    row = cur.fetchone()
    
    if row:
        print(f'ID: {row[0]}')
        print(f'Title: {row[1]}')
        print(f'Telegram_final length: {len(row[2]) if row[2] else 0}')
        print(f'\nTelegram_final content:')
        print('=' * 80)
        print(row[2] if row[2] else 'EMPTY')
        print('=' * 80)
    else:
        print(f'Article {article_id} not found')
finally:
    cur.close()
    pg._put_conn(conn, pooled)
