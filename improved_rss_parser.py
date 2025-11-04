#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Улучшенный RSS парсер с лучшей обработкой проблемных лент
"""
import feedparser
import requests
import time
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
from urllib.parse import urlparse
import re

class ImprovedRSSParser:
    """Улучшенный RSS парсер с обработкой проблемных лент"""
    
    def __init__(self):
        self.session = requests.Session()
        # Увеличиваем таймауты для медленных серверов
        self.session.timeout = (30, 60)  # (connect_timeout, read_timeout)
        
        # User-Agent для лучшей совместимости
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
    
    def parse_feed(self, feed_url, max_retries=3):
        """Парсит RSS ленту с улучшенной обработкой ошибок"""
        print(f"🔍 Парсинг: {feed_url}")
        
        for attempt in range(max_retries):
            try:
                print(f"   Попытка {attempt + 1}/{max_retries}")
                
                # Пробуем стандартный feedparser
                feed = feedparser.parse(feed_url)
                
                if not feed.bozo and feed.entries:
                    print(f"   ✅ Стандартный парсинг успешен: {len(feed.entries)} записей")
                    return self._clean_feed_data(feed)
                
                print(f"   ⚠️  Стандартный парсинг не удался, пробуем ручной парсинг...")
                
                # Пробуем ручной парсинг XML
                manual_feed = self._manual_xml_parse(feed_url)
                if manual_feed and manual_feed.get('entries'):
                    print(f"   ✅ Ручной парсинг успешен: {len(manual_feed['entries'])} записей")
                    return manual_feed
                
                # Если не получилось, пробуем с исправлением URL
                if attempt == 0:
                    print(f"   🔧 Пробуем исправить URL...")
                    corrected_url = self._fix_feed_url(feed_url)
                    if corrected_url != feed_url:
                        print(f"   📝 Исправленный URL: {corrected_url}")
                        feed = feedparser.parse(corrected_url)
                        if not feed.bozo and feed.entries:
                            print(f"   ✅ Исправленный URL работает: {len(feed.entries)} записей")
                            return self._clean_feed_data(feed)
                
                # Пауза между попытками
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Экспоненциальная задержка
                
            except Exception as e:
                print(f"   ❌ Ошибка попытки {attempt + 1}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        print(f"   ❌ Все попытки парсинга не удались")
        return None
    
    def _manual_xml_parse(self, feed_url):
        """Ручной парсинг XML для проблемных лент"""
        try:
            response = self.session.get(feed_url)
            response.raise_for_status()
            
            # Очищаем XML от некорректных элементов
            xml_content = self._clean_xml_content(response.text)
            
            # Парсим очищенный XML
            root = ET.fromstring(xml_content)
            
            feed_data = {
                'title': '',
                'link': '',
                'description': '',
                'entries': []
            }
            
            # Извлекаем информацию о канале
            channel = root.find('channel')
            if channel is not None:
                feed_data['title'] = self._safe_text(channel.find('title'))
                feed_data['link'] = self._safe_text(channel.find('link'))
                feed_data['description'] = self._safe_text(channel.find('description'))
                
                # Извлекаем записи
                for item in channel.findall('item'):
                    entry = {
                        'title': self._safe_text(item.find('title')),
                        'link': self._safe_text(item.find('link')),
                        'description': self._safe_text(item.find('description')),
                        'published': self._safe_text(item.find('pubDate')),
                        'guid': self._safe_text(item.find('guid'))
                    }
                    
                    # Фильтруем некорректные записи
                    if self._is_valid_entry(entry):
                        feed_data['entries'].append(entry)
            
            return feed_data if feed_data['entries'] else None
            
        except Exception as e:
            print(f"   ❌ Ручной парсинг XML не удался: {e}")
            return None
    
    def _clean_xml_content(self, xml_content):
        """Очищает XML от некорректных элементов"""
        # Убираем div элементы внутри rss
        xml_content = re.sub(r'<div[^>]*>.*?</div>', '', xml_content, flags=re.DOTALL)
        
        # Убираем HTML комментарии
        xml_content = re.sub(r'<!--.*?-->', '', xml_content, flags=re.DOTALL)
        
        # Убираем лишние пробелы и переносы строк
        xml_content = re.sub(r'\s+', ' ', xml_content)
        
        return xml_content.strip()
    
    def _safe_text(self, element):
        """Безопасно извлекает текст из XML элемента"""
        if element is not None and element.text:
            return element.text.strip()
        return ''
    
    def _is_valid_entry(self, entry):
        """Проверяет валидность записи"""
        # Должен быть заголовок и ссылка
        if not entry.get('title') or not entry.get('link'):
            return False
        
        # Ссылка должна быть HTTP/HTTPS
        if not entry['link'].startswith(('http://', 'https://')):
            return False
        
        # Фильтруем файлы архивов и XML
        if any(ext in entry['link'].lower() for ext in ['.tar.gz', '.xml', '.zip']):
            return False
        
        return True
    
    def _fix_feed_url(self, original_url):
        """Пытается исправить URL RSS ленты"""
        parsed = urlparse(original_url)
        
        # Убираем лишние параметры
        if '?' in original_url:
            base_url = original_url.split('?')[0]
            return base_url
        
        # Пробуем альтернативные пути
        if 'aemet.es' in original_url:
            # Для AEMET пробуем основной URL
            return 'https://www.aemet.es/es/eltiempo/prediccion/avisos'
        
        return original_url
    
    def _clean_feed_data(self, feed):
        """Очищает данные feedparser"""
        clean_entries = []
        
        for entry in feed.entries:
            # Проверяем валидность записи
            if self._is_valid_entry({
                'title': getattr(entry, 'title', ''),
                'link': getattr(entry, 'link', ''),
                'description': getattr(entry, 'description', '')
            }):
                clean_entries.append(entry)
        
        feed.entries = clean_entries
        return feed

def test_problematic_feeds():
    """Тестирует проблемные RSS ленты"""
    print("🧪 ТЕСТИРОВАНИЕ ПРОБЛЕМНЫХ RSS ЛЕНТ")
    print("=" * 60)
    
    parser = ImprovedRSSParser()
    
    # Тестируем проблемные ленты
    test_feeds = [
        "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAE_RSS.xml",
        "https://www.aemet.es/documentos_d/eltiempo/prediccion/avisos/rss/CAP_AFAC61_RSS.xml"
    ]
    
    for feed_url in test_feeds:
        print(f"\n🔍 Тестирую: {feed_url}")
        result = parser.parse_feed(feed_url)
        
        if result and result.get('entries'):
            print(f"✅ Успешно: {len(result['entries'])} записей")
            print(f"   Заголовок: {result.get('title', 'N/A')}")
            
            # Показываем первые 3 записи
            for i, entry in enumerate(result['entries'][:3]):
                print(f"   {i+1}. {entry.get('title', 'N/A')[:60]}...")
        else:
            print(f"❌ Не удалось распарсить")
        
        print("-" * 40)

if __name__ == "__main__":
    test_problematic_feeds()
