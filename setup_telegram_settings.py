#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
НАСТРОЙКА TELEGRAM В FIREBASE
Создает необходимые настройки для публикации в Telegram
"""

from firebase_client import get_firebase_client

def setup_telegram_settings():
    """Настраивает Telegram в Firebase"""
    
    print("🔧 НАСТРОЙКА TELEGRAM В FIREBASE")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Проверяем существующие настройки
        settings_ref = firebase_client.db.collection('settings').document('telegram')
        doc = settings_ref.get()
        
        if doc.exists:
            print(f"⚠️  Настройки Telegram уже существуют")
            current_settings = doc.to_dict() or {}
            
            bot_token = current_settings.get('telegram_bot_token', '')
            chat_id = current_settings.get('telegram_chat_id', '')
            
            print(f"   Текущие настройки:")
            print(f"   Bot Token: {'✅ Установлен' if bot_token else '❌ НЕ УСТАНОВЛЕН'}")
            print(f"   Chat ID: {'✅ Установлен' if chat_id else '❌ НЕ УСТАНОВЛЕН'}")
            
            if not bot_token or not chat_id:
                print(f"\n❌ Настройки неполные!")
                print(f"   Нужно добавить недостающие параметры")
            else:
                print(f"\n✅ Все настройки установлены")
                return
            
        # Создаем базовые настройки
        print(f"\n📋 СОЗДАНИЕ НАСТРОЕК TELEGRAM:")
        
        # Запрашиваем у пользователя
        print(f"\n🔑 ВВЕДИТЕ НАСТРОЙКИ TELEGRAM:")
        print(f"   (или оставьте пустым для пропуска)")
        
        bot_token = input("   Bot Token: ").strip()
        chat_id = input("   Chat ID: ").strip()
        
        # Создаем настройки
        telegram_settings = {
            "enabled": True,
            "telegram_bot_token": bot_token if bot_token else "YOUR_BOT_TOKEN_HERE",
            "telegram_chat_id": chat_id if chat_id else "YOUR_CHAT_ID_HERE",
            "publishing_windows": [
                {"start": "09:00", "end": "10:00"},
                {"start": "10:00", "end": "11:00"},
                {"start": "11:00", "end": "12:00"},
                {"start": "12:00", "end": "13:00"},
                {"start": "13:00", "end": "14:00"},
                {"start": "14:00", "end": "15:00"},
                {"start": "16:00", "end": "17:00"},
                {"start": "17:00", "end": "18:00"},
                {"start": "18:00", "end": "19:00"},
                {"start": "20:00", "end": "21:00"},
                {"start": "21:00", "end": "22:00"},
                {"start": "22:00", "end": "23:00"}
            ],
            "max_posts_per_window": 1,
            "min_post_interval_minutes": 60
        }
        
        # Сохраняем в Firebase
        settings_ref.set(telegram_settings)
        
        print(f"\n✅ Настройки Telegram сохранены в Firebase")
        print(f"   Документ: settings/telegram")
        
        # Проверяем результат
        saved_doc = settings_ref.get()
        if saved_doc.exists:
            saved_settings = saved_doc.to_dict()
            print(f"   Параметров сохранено: {len(saved_settings)}")
            
            # Показываем статус
            bot_token_saved = saved_settings.get('telegram_bot_token', '')
            chat_id_saved = saved_settings.get('telegram_chat_id', '')
            
            print(f"\n📱 СТАТУС НАСТРОЕК:")
            print(f"   Bot Token: {'✅ Установлен' if bot_token_saved and bot_token_saved != 'YOUR_BOT_TOKEN_HERE' else '❌ НЕ УСТАНОВЛЕН'}")
            print(f"   Chat ID: {'✅ Установлен' if chat_id_saved and chat_id_saved != 'YOUR_CHAT_ID_HERE' else '❌ НЕ УСТАНОВЛЕН'}")
            
            if bot_token_saved and bot_token_saved != 'YOUR_BOT_TOKEN_HERE' and chat_id_saved and chat_id_saved != 'YOUR_CHAT_ID_HERE':
                print(f"\n🎉 ВСЕ НАСТРОЙКИ УСТАНОВЛЕНЫ!")
                print(f"   Система готова к публикации в Telegram")
            else:
                print(f"\n⚠️  НАСТРОЙКИ НЕПОЛНЫЕ!")
                print(f"   Установите реальные Bot Token и Chat ID")
                print(f"   Или используйте переменные окружения:")
                print(f"   TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID")
        
    except Exception as e:
        print(f"❌ Ошибка настройки Telegram: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    setup_telegram_settings()

