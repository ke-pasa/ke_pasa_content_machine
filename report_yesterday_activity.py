#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отчёт по выполненным шагам системы за вчера (по данным Firebase)
Собирает метрики по этапам: статьи, кластеризация, генерация статей, экспорт,
ранжирование, телеграм-посты и публикации.
"""

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from dotenv import load_dotenv


def to_dt(value: Any) -> Optional[datetime]:
	"""Приводит произвольное поле даты к timezone-aware datetime (UTC)."""
	try:
		if value is None:
			return None
		# Firestore Timestamp-like
		if hasattr(value, 'timestamp') and hasattr(value, 'tzinfo'):
			# Похоже на datetime
			dt = value
			if dt.tzinfo is None:
				return dt.replace(tzinfo=timezone.utc)
			return dt.astimezone(timezone.utc)
		# Строка ISO
		if isinstance(value, str):
			s = value.strip()
			if not s:
				return None
			# Заменим Z на +00:00
			s = s.replace('Z', '+00:00')
			return datetime.fromisoformat(s).astimezone(timezone.utc)
		# Число (unix epoch)
		if isinstance(value, (int, float)):
			return datetime.fromtimestamp(float(value), tz=timezone.utc)
		return None
	except Exception:
		return None


def in_range(dt: Optional[datetime], start: datetime, end: datetime) -> bool:
	"""Проверяет, что dt попадает в [start, end)."""
	if dt is None:
		return False
	return start <= dt < end


def main():
	load_dotenv()
	from firebase_client import get_firebase_client
	from firebase_admin import firestore  # noqa: F401

	client = get_firebase_client()

	# Вчера в мадридском времени, но считаем в UTC для простоты
	madrid_offset = timedelta(hours=2)  # летнее время CEST; если нужно точно, можно взять pytz
	today_utc = datetime.now(timezone.utc)
	yesterday_madrid_start = (today_utc + madrid_offset).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
	yesterday_madrid_end = yesterday_madrid_start + timedelta(days=1)
	# Переводим обратно в UTC диапазон
	y_start = (yesterday_madrid_start - madrid_offset).astimezone(timezone.utc)
	y_end = (yesterday_madrid_end - madrid_offset).astimezone(timezone.utc)

	print("📅 Отчёт за:", y_start.isoformat(), "→", y_end.isoformat(), "(UTC)")

	articles_col = client.db.collection('articles')
	clusters_col = client.db.collection('news_clusters')
	rankings_col = client.db.collection('article_rankings')
	logs_col = client.db.collection('log')

	# Статьи
	articles = list(articles_col.limit(1000).stream())
	art_stats = {
		'total_created': 0,
		'processed': 0,
		'clustered': 0,
		'exported': 0,
	}
	for doc in articles:
		data: Dict[str, Any] = doc.to_dict() or {}
		created = to_dt(data.get('created_at') or data.get('published') or data.get('published_date'))
		if not in_range(created, y_start, y_end):
			continue
		art_stats['total_created'] += 1
		if data.get('processed'):
			art_stats['processed'] += 1
		if data.get('is_clustered'):
			art_stats['clustered'] += 1
		if data.get('exported_to_site') or data.get('exported'):
			art_stats['exported'] += 1

	# Кластеры
	clusters = list(clusters_col.limit(1000).stream())
	cl_stats = {
		'total_created': 0,
		'articles_generated': 0,
	}
	for doc in clusters:
		data = doc.to_dict() or {}
		created = to_dt(data.get('clustered_at') or data.get('created_at'))
		if not in_range(created, y_start, y_end):
			continue
		cl_stats['total_created'] += 1
		if data.get('articles_generated'):
			cl_stats['articles_generated'] += 1

	# Рейтинги
	rankings = list(rankings_col.limit(2000).stream())
	r_stats = {
		'total_ranked': 0,
	}
	for doc in rankings:
		data = doc.to_dict() or {}
		created = to_dt(data.get('created_at') or data.get('ranked_at'))
		if not in_range(created, y_start, y_end):
			continue
		r_stats['total_ranked'] += 1

	# Публикации в Telegram
	pub_logs = list(logs_col.where('message', '==', 'publication_success').limit(2000).stream())
	p_stats = {
		'publications': 0,
	}
	for doc in pub_logs:
		data = doc.to_dict() or {}
		ts = to_dt(data.get('timestamp') or data.get('created_at'))
		if in_range(ts, y_start, y_end):
			p_stats['publications'] += 1

	print("\n📰 Статьи (созданы вчера):")
	print(f"  всего: {art_stats['total_created']}")
	print(f"  обработаны LLM: {art_stats['processed']}")
	print(f"  отмечены как кластеризованные: {art_stats['clustered']}")
	print(f"  экспортированы на сайт: {art_stats['exported']}")

	print("\n🔗 Кластеры (созданы вчера):")
	print(f"  всего: {cl_stats['total_created']}")
	print(f"  сгенерированы статьи: {cl_stats['articles_generated']}")

	print("\n⭐ Ранжирование (создано вчера):")
	print(f"  записей ранжирования: {r_stats['total_ranked']}")

	print("\n📣 Телеграм публикации (вчера):")
	print(f"  опубликовано постов: {p_stats['publications']}")

	# Вывод краткого вердикта по цепочке
	print("\n📊 Вердикт по этапам за вчера:")
	print(f"  1) RSS/фильтрация → статей создано: {art_stats['total_created']} (LLM-обработано: {art_stats['processed']})")
	print(f"  2) Кластеризация → кластеров: {cl_stats['total_created']}")
	print(f"  3) Написание статей → кластеров со статьями: {cl_stats['articles_generated']}")
	print(f"  4) Экспорт → экспортировано статей: {art_stats['exported']}")
	print(f"  5) Оценка/ранжирование → записей: {r_stats['total_ranked']}")
	print(f"  6-8) Выбор/написание/публикация → телеграм постов: {p_stats['publications']}")


if __name__ == '__main__':
	main()







