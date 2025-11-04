#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ПРОВЕРКА НАСТРОЕК TELEGRAM
Показывает текущие настройки бота и чата
"""

from workers.tools.firebase_client import get_firebase_client

def check_telegram_settings():
    """Проверяет настройки Telegram в Firebase"""
    
    print("🔍 ПРОВЕРКА НАСТРОЕК TELEGRAM")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Проверяем настройки Telegram
        settings_ref = firebase_client.db.collection('settings').document('telegram')
        doc = settings_ref.get()
        
        if doc.exists:
            settings = doc.to_dict() or {}
            print(f"✅ Настройки Telegram найдены")
            print(f"   Количество параметров: {len(settings)}")
            
            # Показываем ключевые настройки
            print(f"\n📱 КЛЮЧЕВЫЕ НАСТРОЙКИ:")
            
            bot_token = settings.get('telegram_bot_token', '')
            chat_id = settings.get('telegram_chat_id', '')
            
            print(f"   Bot Token: {'✅ Установлен' if bot_token else '❌ НЕ УСТАНОВЛЕН'}")
            if bot_token:
                print(f"      Токен: {bot_token[:10]}...{bot_token[-10:] if len(bot_token) > 20 else ''}")
            
            print(f"   Chat ID: {'✅ Установлен' if chat_id else '❌ НЕ УСТАНОВЛЕН'}")
            if chat_id:
                print(f"      ID чата: {chat_id}")
            
            # Другие настройки
            enabled = settings.get('enabled', True)
            print(f"   Публикация включена: {'✅ ДА' if enabled else '❌ НЕТ'}")
            
            windows = settings.get('publishing_windows', [])
            print(f"   Окна публикации: {len(windows)}")
            
            max_posts = settings.get('max_posts_per_window', 1)
            print(f"   Максимум постов в окне: {max_posts}")
            
            # Проверяем переменные окружения
            print(f"\n🌍 ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ:")
            import os
            env_bot_token = os.getenv('TELEGRAM_BOT_TOKEN', '')
            env_chat_id = os.getenv('TELEGRAM_CHAT_ID', '')
            
            print(f"   TELEGRAM_BOT_TOKEN: {'✅ Установлена' if env_bot_token else '❌ НЕ УСТАНОВЛЕНА'}")
            print(f"   TELEGRAM_CHAT_ID: {'✅ Установлена' if env_chat_id else '❌ НЕ УСТАНОВЛЕНА'}")
            
            # Рекомендации
            print(f"\n💡 РЕКОМЕНДАЦИИ:")
            
            if not bot_token:
                print(f"   • Установите telegram_bot_token в настройках Firebase")
                print(f"   • Или установите переменную окружения TELEGRAM_BOT_TOKEN")
            
            if not chat_id:
                print(f"   • Установите telegram_chat_id в настройках Firebase")
                print(f"   • Или установите переменную окружения TELEGRAM_CHAT_ID")
            
            if bot_token and chat_id:
                print(f"   • ✅ Все настройки установлены")
                print(f"   • Система готова к публикации в Telegram")
            else:
                print(f"   • ❌ Настройки неполные")
                print(f"   • Публикация в Telegram не будет работать")
            
        else:
            print(f"❌ Настройки Telegram не найдены")
            print(f"   Создайте документ settings/telegram в Firebase")
            
            # Показываем структуру по умолчанию
            print(f"\n📋 СТРУКТУРА НАСТРОЕК ПО УМОЛЧАНИЮ:")
            default_settings = {
                "enabled": True,
                "telegram_bot_token": "YOUR_BOT_TOKEN_HERE",
                "telegram_chat_id": "YOUR_CHAT_ID_HERE",
                "publishing_windows": [
                    {"start": "09:00", "end": "10:00"},
                    {"start": "10:00", "end": "11:00"}
                ],
                "max_posts_per_window": 1
            }
            
            for key, value in default_settings.items():
                print(f"   {key}: {value}")
        
    except Exception as e:
        print(f"❌ Ошибка проверки настроек: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    check_telegram_settings()

