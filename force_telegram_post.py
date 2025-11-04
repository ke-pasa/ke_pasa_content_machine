#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Принудительная отправка поста в Telegram
Обходит все проверки времени планировщика
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

from firebase_client import get_firebase_client
from telegram_post_generator import create_telegram_post_generator

def force_telegram_post():
    """Принудительно отправляет пост в Telegram"""
    print("🚀 Принудительная отправка поста в Telegram...")
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Получаем неопубликованные статьи
        articles_ref = firebase_client.db.collection('articles')
        query = (
            articles_ref
            .where('published', '==', False)
            .where('exported_to_site', '==', True)
        )
        docs = query.stream()
        
        articles = []
        for doc in docs:
            data = doc.to_dict() or {}
            data['id'] = doc.id
            if not data.get('published', False) and data.get('exported_to_site', False):
                articles.append(data)
        
        print(f"📰 Найдено статей для публикации: {len(articles)}")
        
        if not articles:
            print("❌ Нет статей для публикации")
            return
        
        # Выбираем первую статью
        article = articles[0]
        print(f"🏆 Выбрана статья: {article.get('title', 'Unknown')[:60]}...")
        
        # Генерируем Telegram-пост
        telegram_generator = create_telegram_post_generator()
        
        # Создаем URL для статьи
        slug = article.get('slug', '')
        if not slug:
            title = article.get('title', '')
            if title:
                import re
                clean_title = re.sub(r'[^\w\sа-яёА-ЯЁ]', '', title)
                title_words = clean_title.split()[:5]
                slug = '-'.join(word.lower() for word in title_words if word)
                if len(slug) > 60:
                    slug = slug[:60].rstrip('-')
            else:
                slug = 'news'
        
        article_url = f"https://spain-que-pasa.com/news/{slug}/"
        
        # Генерируем пост
        telegram_post = telegram_generator.generate_post(article, article_url)
        if not telegram_post:
            print("❌ Не удалось сгенерировать Telegram-пост")
            return
        
        print(f"📝 Telegram-пост сгенерирован ({len(telegram_post)} символов)")
        
        # Отправляем в Telegram
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token:
            print("❌ TELEGRAM_BOT_TOKEN не найден")
            return
            
        if not chat_id:
            print("❌ TELEGRAM_CHAT_ID не найден")
            return
        
        print(f"📤 Отправляю пост в Telegram...")
        print(f"   Бот: {bot_token[:10]}...")
        print(f"   Чат: {chat_id}")
        
        # Отправляем через API Telegram
        import requests
        
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        data = {
            'chat_id': chat_id,
            'text': telegram_post,
            'parse_mode': 'Markdown',
            'disable_web_page_preview': True
        }
        
        response = requests.post(url, data=data, timeout=30)
        
        if response.status_code == 200:
            print("✅ Пост успешно отправлен в Telegram!")
            
            # Отмечаем статью как опубликованную
            from datetime import datetime, timezone
            firebase_client.db.collection('articles').document(article['id']).update({
                'published': True,
                'published_at': datetime.now(timezone.utc).isoformat(),
                'telegram_post': telegram_post
            })
            print("✅ Статья отмечена как опубликованная")
            
            # Логируем успех
            firebase_client.db.collection('log').add({
                'message': 'publication_success',
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'article_id': article['id'],
                'title': article.get('title', 'Unknown'),
                'source': 'force_telegram_post'
            })
            print("✅ Успех записан в лог")
            
        else:
            print(f"❌ Ошибка отправки: {response.status_code} - {response.text[:200]}")
        
    except Exception as e:
        print(f"❌ Ошибка принудительной публикации: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    force_telegram_post()
