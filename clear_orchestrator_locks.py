#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ОЧИСТКА БЛОКИРОВОК ОРКЕСТРАТОРА
Удаляет старые блокировки, чтобы можно было перезапустить систему
"""

from workers.tools.firebase_client import get_firebase_client

def clear_orchestrator_locks():
    """Очищает все блокировки оркестратора"""
    
    print("🧹 ОЧИСТКА БЛОКИРОВОК ОРКЕСТРАТОРА")
    print("=" * 50)
    
    try:
        # Получаем клиент Firebase
        firebase_client = get_firebase_client()
        
        # Удаляем блокировку оркестратора
        locks_ref = firebase_client.db.collection('locks').document('orchestrator')
        lock_doc = locks_ref.get()
        
        if lock_doc.exists:
            lock_data = lock_doc.to_dict()
            holder_id = lock_data.get('holder_id', 'unknown')
            expires_at = lock_data.get('expires_at', 'unknown')
            
            print(f"🔐 Найдена блокировка:")
            print(f"   ID экземпляра: {holder_id}")
            print(f"   Истекает: {expires_at}")
            
            # Удаляем блокировку
            locks_ref.delete()
            print(f"✅ Блокировка удалена")
        else:
            print(f"ℹ️  Блокировок не найдено")
        
        print(f"\n🚀 Теперь можно запустить оркестратор заново!")
        
    except Exception as e:
        print(f"❌ Ошибка очистки блокировок: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    clear_orchestrator_locks()

