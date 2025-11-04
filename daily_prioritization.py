#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль ежедневной приоритизации статей
"""

from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from workers.tools.firebase_client import get_firebase_client


class DailyPrioritization:
    def __init__(self):
        self.db = get_firebase_client().db

    def update_all_article_priorities(self) -> Dict[str, Any]:
        """
        Обновляет приоритеты всех статей на основе их возраста и других факторов
        
        Returns:
            Словарь с результатами обновления
        """
        results = {
            'updated': 0,
            'urgent': 0,
            'errors': 0
        }
        
        try:
            # Получаем все статьи
            articles_ref = self.db.collection('articles')
            articles = list(articles_ref.limit(1000).stream())
            
            now = datetime.now(timezone.utc)
            
            for doc in articles:
                try:
                    data = doc.to_dict()
                    if not data:
                        continue
                    
                    # Получаем дату создания
                    created_at = data.get('created_at')
                    if not created_at:
                        continue
                    
                    # Парсим дату и приводим к UTC
                    if isinstance(created_at, str):
                        try:
                            # Пробуем разные форматы даты
                            if 'T' in created_at:
                                if created_at.endswith('Z'):
                                    created_dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                                elif '+' in created_at or created_at.endswith('00:00'):
                                    created_dt = datetime.fromisoformat(created_at)
                                else:
                                    # Добавляем UTC если нет timezone
                                    created_dt = datetime.fromisoformat(created_at).replace(tzinfo=timezone.utc)
                            else:
                                # Простой формат даты
                                created_dt = datetime.fromisoformat(created_at).replace(tzinfo=timezone.utc)
                        except Exception as e:
                            print(f"Ошибка парсинга строковой даты {created_at}: {e}")
                            continue
                    elif hasattr(created_at, 'isoformat'):
                        # Firebase datetime object
                        try:
                            created_dt = created_at
                            if created_dt.tzinfo is None:
                                created_dt = created_dt.replace(tzinfo=timezone.utc)
                        except Exception as e:
                            print(f"Ошибка обработки Firebase datetime {created_at}: {e}")
                            continue
                    elif hasattr(created_at, 'timestamp'):
                        # Firebase Timestamp
                        try:
                            created_dt = created_at.replace(tzinfo=timezone.utc) if created_at.tzinfo is None else created_at
                        except Exception as e:
                            print(f"Ошибка обработки timestamp {created_at}: {e}")
                            continue
                    else:
                        # Неизвестный тип - пропускаем
                        print(f"Неизвестный тип даты {type(created_at)}: {created_at}")
                        continue
                    
                    # Убеждаемся что обе даты в UTC
                    if created_dt.tzinfo is None:
                        created_dt = created_dt.replace(tzinfo=timezone.utc)
                    
                    # Вычисляем возраст в днях
                    age_days = (now - created_dt).days
                    
                    # Базовый приоритет
                    base_priority = data.get('priority_score', 0.5)
                    
                    # Снижаем приоритет с возрастом
                    if age_days <= 1:
                        daily_priority = base_priority
                    elif age_days <= 3:
                        daily_priority = base_priority * 0.8
                    elif age_days <= 7:
                        daily_priority = base_priority * 0.6
                    else:
                        daily_priority = base_priority * 0.2
                    
                    # Обновляем приоритет
                    doc.reference.update({
                        'daily_priority_score': daily_priority,
                        'priority_updated_at': now.isoformat()
                    })
                    
                    results['updated'] += 1
                    
                    # Проверяем на срочность
                    if data.get('urgent', False):
                        results['urgent'] += 1
                    
                    # Логируем значительные изменения
                    if abs(daily_priority - base_priority) > 0.1:
                        title = data.get('title', 'Unknown')[:50] + '...'
                        print(f"Обновлен приоритет: {title} {base_priority:.3f} -> {daily_priority:.3f}")
                    
                except Exception as e:
                    print(f"Ошибка обновления приоритета статьи {doc.id}: {e}")
                    results['errors'] += 1
            
            print(f"✅ Обновление приоритетов завершено")
            print(f"  Обновлено: {results['updated']} статей")
            print(f"  Срочных: {results['urgent']} статей")
            print(f"  Ошибок: {results['errors']}")
            
        except Exception as e:
            print(f"Критическая ошибка приоритизации: {e}")
            results['errors'] += 1
        
        return results