#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Перегенерация статей с улучшенным промптом
"""
import os
import sys
from dotenv import load_dotenv
from datetime import datetime

# Добавляем текущую директорию в путь
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from content_generator import generate_article
from firebase_client import get_firebase_client

def regenerate_articles_with_new_prompt():
	"""Перегенерирует все статьи с улучшенным промптом"""
	print("🔄 ПЕРЕГЕНЕРАЦИЯ СТАТЕЙ С УЛУЧШЕННЫМ ПРОМПТОМ")
	print("=" * 60)
	
	# Загружаем переменные окружения
	load_dotenv()
	
	try:
		firebase_client = get_firebase_client()
		articles_ref = firebase_client.db.collection('articles')
		
		# Получаем все статьи для перегенерации
		print("🔍 Ищу статьи для перегенерации...")
		articles = list(articles_ref.where('processed', '==', True).limit(50).stream())
		
		if not articles:
			print("❌ Нет статей для перегенерации")
			return
		
		print(f"📄 Найдено {len(articles)} статей для перегенерации")
		print()
		
		success_count = 0
		error_count = 0
		
		for i, article_doc in enumerate(articles, 1):
			article_data = article_doc.to_dict() or {}
			article_id = article_doc.id
			
			print(f"🔄 [{i}/{len(articles)}] Перегенерирую: {article_data.get('title', 'N/A')[:60]}...")
			
			# Создаем кластер для перегенерации
			cluster = {
				'topic_summary': article_data.get('title', ''),
				'combined_context': article_data.get('content', article_data.get('summary', '')),
				'sources': [{
					'title': article_data.get('title', ''),
					'summary': article_data.get('summary', ''),
					'link': article_data.get('link', ''),
					'date': article_data.get('date', ''),
					'region': article_data.get('region', 'spain')
				}],
				'category_hint': article_data.get('category', 'general'),
				'region_hint': article_data.get('region', 'spain'),
				'urgent': article_data.get('urgent', False)
			}
			
			try:
				# Генерируем новую статью
				new_article = generate_article(cluster, as_markdown=False)
				
				if new_article:
					# Обновляем статью в базе
					update_data = {
						'title': new_article.get('title', article_data.get('title')),
						'description': new_article.get('description', article_data.get('description')),
						'content': new_article.get('content', article_data.get('content')),
						'tags': new_article.get('tags', article_data.get('tags')),
						'keywords': new_article.get('keywords', article_data.get('keywords')),
						'category': new_article.get('category', article_data.get('category')),
						'region': new_article.get('region', article_data.get('region')),
						'meta_title': new_article.get('meta_title', article_data.get('meta_title')),
						'meta_description': new_article.get('meta_description', article_data.get('meta_description')),
						'regenerated_with_new_prompt': True,
						'regeneration_date': datetime.now().isoformat()
					}
					
					# Обновляем документ
					articles_ref.document(article_id).update(update_data)
					
					print(f"   ✅ Перегенерирована успешно")
					print(f"   📝 Новый заголовок: {new_article.get('title', 'N/A')[:50]}...")
					success_count += 1
					
				else:
					print(f"   ❌ Не удалось сгенерировать новую статью")
					error_count += 1
					
			except Exception as e:
				print(f"   ❌ Ошибка при перегенерации: {e}")
				error_count += 1
			
			print()
		
		print("=" * 60)
		print(f"📊 ИТОГИ ПЕРЕГЕНЕРАЦИИ:")
		print(f"   ✅ Успешно: {success_count}")
		print(f"   ❌ Ошибки: {error_count}")
		print(f"   📄 Всего обработано: {len(articles)}")
		
	except Exception as e:
		print(f"❌ Ошибка: {e}")
		import traceback
		traceback.print_exc()

if __name__ == "__main__":
	regenerate_articles_with_new_prompt()
