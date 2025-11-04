#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Удаление устаревших RSS лент
"""
import os
import shutil
from datetime import datetime

def remove_old_feeds():
    """Удаляет устаревшие RSS ленты"""
    print("🗑️  УДАЛЕНИЕ УСТАРЕВШИХ RSS ЛЕНТ")
    print("=" * 60)
    
    # Проверяем наличие файла с лентами для удаления
    if not os.path.exists('feeds_to_remove.txt'):
        print("❌ Файл feeds_to_remove.txt не найден")
        print("💡 Сначала запустите: python analyze_rss_freshness.py")
        return
    
    # Создаем резервную копию оригинального файла
    backup_filename = f"feeds_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    if os.path.exists('feeds.txt'):
        shutil.copy2('feeds.txt', backup_filename)
        print(f"💾 Создана резервная копия: {backup_filename}")
    
    # Читаем ленты для удаления
    with open('feeds_to_remove.txt', 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Извлекаем URL лент для удаления
    urls_to_remove = []
    for line in content.split('\n'):
        line = line.strip()
        if line and not line.startswith('#') and line.startswith('http'):
            urls_to_remove.append(line)
    
    if not urls_to_remove:
        print("❌ Нет лент для удаления")
        return
    
    print(f"📋 Найдено {len(urls_to_remove)} лент для удаления:")
    for url in urls_to_remove:
        print(f"   ❌ {url}")
    
    # Читаем оригинальный файл feeds.txt
    if not os.path.exists('feeds.txt'):
        print("❌ Файл feeds.txt не найден")
        return
    
    with open('feeds.txt', 'r', encoding='utf-8') as f:
        original_feeds = f.readlines()
    
    # Фильтруем ленты, убирая те, что нужно удалить
    filtered_feeds = []
    removed_count = 0
    
    for line in original_feeds:
        line_stripped = line.strip()
        
        # Пропускаем пустые строки и комментарии
        if not line_stripped or line_stripped.startswith('#'):
            filtered_feeds.append(line)
            continue
        
        # Проверяем, нужно ли удалить эту ленту
        should_remove = False
        for url_to_remove in urls_to_remove:
            if url_to_remove in line_stripped:
                should_remove = True
                removed_count += 1
                print(f"🗑️  Удаляю: {line_stripped}")
                break
        
        if not should_remove:
            filtered_feeds.append(line)
    
    # Записываем очищенный файл
    with open('feeds.txt', 'w', encoding='utf-8') as f:
        f.writelines(filtered_feeds)
    
    print(f"\n✅ Удалено {removed_count} устаревших лент")
    print(f"📋 Осталось лент: {len([line for line in filtered_feeds if line.strip() and not line.strip().startswith('#')])}")
    
    # Показываем статистику
    print(f"\n📊 СТАТИСТИКА:")
    print(f"   🗑️  Удалено лент: {removed_count}")
    print(f"   💾 Резервная копия: {backup_filename}")
    print(f"   📁 Очищенный список: feeds.txt")
    
    # Предлагаем использовать свежий список
    if os.path.exists('feeds_fresh_only.txt'):
        print(f"\n💡 Также доступен файл feeds_fresh_only.txt с только свежими лентами")
        print(f"   Для замены выполните: cp feeds_fresh_only.txt feeds.txt")

if __name__ == "__main__":
    remove_old_feeds()







