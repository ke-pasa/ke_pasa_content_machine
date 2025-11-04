#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from workers.tools.firebase_client import get_firebase_client

def check_status():
    try:
        db = get_firebase_client().db
        
        # Проверяем количество задач в очереди
        queued_tasks = list(db.collection('llm_tasks').where('status', '==', 'queued').limit(1000).stream())
        print(f"Задач в очереди: {len(queued_tasks)}")
        
        # Проверяем активные батчи
        active_batches = list(db.collection('llm_batches').where('status', 'in', ['submitted', 'validating', 'in_progress', 'finalizing']).stream())
        print(f"Активных батчей: {len(active_batches)}")
        
        # Проверяем завершенные батчи
        completed_batches = list(db.collection('llm_batches').where('status', '==', 'completed').limit(100).stream())
        print(f"Завершенных батчей: {len(completed_batches)}")
        
        # Проверяем количество статей
        articles = list(db.collection('articles').limit(1000).stream())
        print(f"Всего статей: {len(articles)}")
        
        # Показываем несколько задач из очереди
        if queued_tasks:
            print("\nПримеры задач в очереди:")
            for i, task in enumerate(queued_tasks[:5]):
                data = task.to_dict()
                print(f"{i+1}. {data.get('title', 'No title')} - {data.get('status', 'No status')}")
        
        # Показываем несколько активных батчей
        if active_batches:
            print("\nАктивные батчи:")
            for batch in active_batches[:3]:
                data = batch.to_dict()
                print(f"- {data.get('batch_id', 'No ID')}: {data.get('status', 'No status')}")
                
    except Exception as e:
        print(f"Ошибка при проверке статуса: {e}")

if __name__ == "__main__":
    check_status()







