#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Проверка последних постов в Telegram канале
"""

import os
from dotenv import load_dotenv

# Загружаем переменные окружения
load_dotenv()

def check_telegram_channel():
    """Проверяет последние посты в канале"""
    print("🔍 Проверяю последние посты в Telegram канале...")
    
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        chat_id = os.getenv('TELEGRAM_CHAT_ID')
        
        if not bot_token:
            print("❌ TELEGRAM_BOT_TOKEN не найден")
            return
            
        if not chat_id:
            print("❌ TELEGRAM_CHAT_ID не найден")
            return
        
        print(f"📱 Проверяю канал: {chat_id}")
        print(f"🤖 Бот: {bot_token[:10]}...")
        
        # Получаем последние сообщения из канала
        import requests
        
        url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
        params = {
            'chat_id': chat_id,
            'limit': 10,
            'timeout': 30
        }
        
        response = requests.get(url, params=params, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('ok'):
                updates = data.get('result', [])
                print(f"✅ Получено обновлений: {len(updates)}")
                
                if updates:
                    print("\n📝 Последние сообщения:")
                    for i, update in enumerate(updates[-5:]):  # Последние 5
                        message = update.get('message', {})
                        if message:
                            chat = message.get('chat', {})
                            text = message.get('text', '')
                            date = message.get('date', 0)
                            
                            if chat.get('type') == 'channel':
                                print(f"  {i+1}. Канал: {chat.get('title', 'Unknown')}")
                                print(f"     Дата: {date}")
                                print(f"     Текст: {text[:100]}...")
                                print()
                else:
                    print("📝 Сообщений не найдено")
            else:
                print(f"❌ Ошибка API: {data.get('description', 'Unknown')}")
        else:
            print(f"❌ Ошибка HTTP: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Ошибка проверки канала: {e}")
        import traceback
        traceback.print_exc()

def test_bot_connection():
    """Тестирует подключение к боту"""
    print("\n🔗 Тестирую подключение к боту...")
    
    try:
        bot_token = os.getenv('TELEGRAM_BOT_TOKEN')
        
        if not bot_token:
            print("❌ TELEGRAM_BOT_TOKEN не найден")
            return
        
        # Получаем информацию о боте
        import requests
        
        url = f"https://api.telegram.org/bot{bot_token}/getMe"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get('ok'):
                bot_info = data.get('result', {})
                print(f"✅ Бот подключен:")
                print(f"   Имя: {bot_info.get('first_name', 'Unknown')}")
                print(f"   Username: @{bot_info.get('username', 'Unknown')}")
                print(f"   ID: {bot_info.get('id', 'Unknown')}")
                print(f"   Может читать сообщения: {'Да' if bot_info.get('can_read_all_group_messages') else 'Нет'}")
            else:
                print(f"❌ Ошибка API: {data.get('description', 'Unknown')}")
        else:
            print(f"❌ Ошибка HTTP: {response.status_code}")
            
    except Exception as e:
        print(f"❌ Ошибка тестирования бота: {e}")

if __name__ == "__main__":
    test_bot_connection()
    check_telegram_channel()


