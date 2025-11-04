#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RSS Parser - Парсер RSS-лент с поддержкой различных структур
Извлекает title, link, summary, published, image, categories из RSS-лент
С фильтрацией через LLM для русскоязычных мигрантов в Испании
С извлечением полного текста интересных статей
С переводом и адаптацией контента через LLM
"""

import feedparser
import argparse
import sys
import os
import re
import json
import time
import hashlib
from datetime import datetime
from dateutil import parser as date_parser
from urllib.parse import urlparse
import requests
from typing import Dict, List, Optional, Any
from openai import OpenAI
from bs4 import BeautifulSoup
from readability import Document
from slugify import slugify
from firebase_client import get_firebase_client
from content_generator import generate_and_save_content
from typing import Tuple


def load_env_file():
    """
    Загружает переменные окружения из файла .env
    """
    try:
        from dotenv import load_dotenv
        result = load_dotenv()
        if result:
            print("✅ .env файл загружен через python-dotenv")
        else:
            print("⚠️  .env файл не загружен")
        return result
    except Exception as e:
        print(f"⚠️  Ошибка при загрузке .env файла: {e}")
        return False


class ImprovedFeedParser:
    """Улучшенный парсер RSS лент с обработкой проблемных лент"""
    
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
        for attempt in range(max_retries):
            try:
                # Пробуем стандартный feedparser
                feed = feedparser.parse(feed_url)
                
                if not feed.bozo and feed.entries:
                    return feed
                
                # Пробуем ручной парсинг XML
                manual_feed = self._manual_xml_parse(feed_url)
                if manual_feed and manual_feed.get('entries'):
                    return manual_feed
                
                # Если не получилось, пробуем с исправлением URL
                if attempt == 0:
                    corrected_url = self._fix_feed_url(feed_url)
                    if corrected_url != feed_url:
                        feed = feedparser.parse(corrected_url)
                        if not feed.bozo and feed.entries:
                            return feed
                
                # Пауза между попытками
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Экспоненциальная задержка
                
            except Exception as e:
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)
        
        return None
    
    def _manual_xml_parse(self, feed_url):
        """Ручной парсинг XML для проблемных лент"""
        try:
            response = self.session.get(feed_url)
            response.raise_for_status()
            
            # Очищаем XML от некорректных элементов
            xml_content = self._clean_xml_content(response.text)
            
            # Парсим очищенный XML
            import xml.etree.ElementTree as ET
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
                    entry = self._create_feed_entry(item)
                    if entry:
                        feed_data['entries'].append(entry)
            
            return feed_data if feed_data['entries'] else None
            
        except Exception as e:
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
    
    def _create_feed_entry(self, item):
        """Создает объект записи для feedparser"""
        try:
            from types import SimpleNamespace
            
            entry = SimpleNamespace()
            entry.title = self._safe_text(item.find('title'))
            entry.link = self._safe_text(item.find('link'))
            entry.description = self._safe_text(item.find('description'))
            entry.published = self._safe_text(item.find('pubDate'))
            entry.guid = self._safe_text(item.find('guid'))
            
            # Проверяем валидность записи
            if self._is_valid_entry(entry):
                return entry
            
        except Exception:
            pass
        
        return None
    
    def _is_valid_entry(self, entry):
        """Проверяет валидность записи"""
        # Должен быть заголовок и ссылка
        if not entry.title or not entry.link:
            return False
        
        # Ссылка должна быть HTTP/HTTPS
        if not entry.link.startswith(('http://', 'https://')):
            return False
        
        # Фильтруем файлы архивов и XML
        if any(ext in entry.link.lower() for ext in ['.tar.gz', '.xml', '.zip']):
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
    
    def _process_improved_feed(self, improved_feed, feed_url):
        """Обрабатывает данные от улучшенного парсера"""
        feed_info = {
            'title': improved_feed.get('title', 'Без названия'),
            'description': improved_feed.get('description', 'Без описания'),
            'link': improved_feed.get('link', ''),
            'entries': []
        }
        
        # Обрабатываем каждую запись
        for entry in improved_feed.get('entries', []):
            # Извлекаем дату
            published = None
            if hasattr(entry, 'published') and entry.published:
                try:
                    published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                except:
                    published = entry.published
            
            # Создаем запись статьи для улучшенного парсера
            article = {
                'title': getattr(entry, 'title', ''),
                'link': getattr(entry, 'link', ''),
                'summary': getattr(entry, 'description', ''),
                'published': published,
                'image': None,  # Улучшенный парсер не извлекает изображения
                'categories': [],  # Улучшенный парсер не извлекает категории
                'category': 'news',  # По умолчанию
                'feed_title': feed_info['title'],  # Добавляем название RSS-ленты
                'feed_url': feed_url  # Добавляем URL RSS-ленты
            }
            
            feed_info['entries'].append(article)
        
        return feed_info


def get_full_text(link: str) -> Optional[str]:
    """
    Извлекает полный текст статьи по URL
    
    Args:
        link: URL статьи
        
    Returns:
        Полный текст статьи или None если не удалось извлечь
    """
    try:
        # Загружаем страницу
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(link, headers=headers, timeout=30)
        response.raise_for_status()
        
        # Определяем кодировку
        if response.encoding == 'ISO-8859-1':
            response.encoding = response.apparent_encoding
        
        # Парсим HTML
        soup = BeautifulSoup(response.content, 'html.parser')
        
        # Удаляем ненужные элементы
        for element in soup(['script', 'style', 'nav', 'header', 'footer', 'aside']):
            element.decompose()
        
        # Удаляем рекламные блоки
        ad_selectors = [
            '[class*="ad"]', '[class*="advertisement"]', '[class*="banner"]',
            '[id*="ad"]', '[id*="advertisement"]', '[id*="banner"]',
            '[class*="social"]', '[class*="share"]', '[class*="comment"]'
        ]
        for selector in ad_selectors:
            for element in soup.select(selector):
                element.decompose()
        
        # Пробуем найти основной контент через BeautifulSoup
        content_selectors = [
            'article',
            '[class*="content"]',
            '[class*="article"]',
            '[class*="post"]',
            '[class*="entry"]',
            '.main-content',
            '.article-content',
            '.post-content',
            '.entry-content',
            '#content',
            '#article',
            '#post'
        ]
        
        content = None
        for selector in content_selectors:
            elements = soup.select(selector)
            if elements:
                # Выбираем самый большой элемент
                largest_element = max(elements, key=lambda x: len(x.get_text()))
                if len(largest_element.get_text().strip()) > 100:
                    content = largest_element
                    break
        
        # Если BeautifulSoup не нашел контент, используем readability-lxml
        if not content:
            try:
                doc = Document(response.text)
                content_html = doc.summary()
                content_soup = BeautifulSoup(content_html, 'html.parser')
                content = content_soup
            except Exception as e:
                print(f"⚠️  readability-lxml не смог извлечь текст: {e}")
                return None
        
        if not content:
            return None
        
        # Извлекаем текст
        text = content.get_text(separator=' ', strip=True)
        
        # Очищаем текст
        text = re.sub(r'\s+', ' ', text)  # Убираем лишние пробелы
        text = re.sub(r'\n\s*\n', '\n', text)  # Убираем пустые строки
        text = text.strip()
        
        # Проверяем, что текст достаточно длинный
        if len(text) < 50:
            return None
        
        return text
        
    except Exception as e:
        print(f"⚠️  Ошибка при извлечении текста из {link}: {e}")
        return None


class RSSParser:
    """Класс для парсинга RSS-лент с фильтрацией через LLM"""
    
    def __init__(self):
        # Загружаем переменные из .env файла
        load_env_file()
        
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': os.getenv('RSS_USER_AGENT', 'Mozilla/5.0 (compatible; SpainQuePasaBot/1.0)')
        })
        # Anti-block: per-host delay, ETag/Last-Modified caches
        self._host_last_time = {}
        # Флаг для обхода кэша Firebase (дубликаты/пропуски) на один прогон
        self._bypass_db_cache = os.getenv('BYPASS_DB_CACHE', '0') == '1'
        try:
            self._per_host_delay_ms = int(os.getenv('RSS_PER_HOST_DELAY_MS', '1500'))
        except Exception:
            self._per_host_delay_ms = 1500
        self._etag_cache_path = os.getenv('RSS_ETAG_CACHE', 'rss_etag_cache.json')
        self._lm_cache_path = os.getenv('RSS_LM_CACHE', 'rss_lastmod_cache.json')
        self._etag_cache = self._load_json_cache(self._etag_cache_path)
        self._lm_cache = self._load_json_cache(self._lm_cache_path)
        
        # Инициализация OpenAI клиента
        api_key = os.getenv('OPENAI_API_KEY')
        if api_key:
            try:
                self.openai_client = OpenAI(api_key=api_key)
                print(f"✅ OpenAI API ключ найден: {api_key[:10]}...")
            except Exception as e:
                print(f"❌ Ошибка инициализации OpenAI: {e}")
                self.openai_client = None
        else:
            print("⚠️  OPENAI_API_KEY не найден в переменных окружения")
            self.openai_client = None
        
        # Инициализация Firebase
        try:
            self.db = get_firebase_client()
            print("✅ Firebase подключен успешно")
        except Exception as e:
            print(f"❌ Ошибка инициализации Firebase: {e}")
            self.db = None
        
        # Множество для отслеживания уникальных статей
        self.processed_articles = set()
        self._seen_links_runtime = set()
        
        # Кластеризация отключена (устаревшая логика)
        self.clustering_pipeline = None
        
        # Всегда используем прямые запросы (batch система удалена)
        self.use_batch = False
        
        # Кэшируем системный промпт для фильтрации
        self._filter_system_prompt = self._create_filter_system_prompt()
        self._filter_messages = [
            {"role": "system", "content": self._filter_system_prompt}
        ]
        print("✅ Системный промпт фильтрации кэширован")
    
    def _process_improved_feed(self, improved_feed, feed_url):
        """Обрабатывает данные от улучшенного парсера"""
        feed_info = {
            'title': improved_feed.get('title', 'Без названия'),
            'description': improved_feed.get('description', 'Без описания'),
            'link': improved_feed.get('link', ''),
            'entries': []
        }
        
        # Обрабатываем каждую запись
        for entry in improved_feed.get('entries', []):
            # Извлекаем дату
            published = None
            if hasattr(entry, 'published') and entry.published:
                try:
                    published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                except:
                    published = entry.published
            
            # Создаем запись статьи для улучшенного парсера
            article = {
                'title': getattr(entry, 'title', ''),
                'link': getattr(entry, 'link', ''),
                'summary': getattr(entry, 'description', ''),
                'published': published,
                'image': None,  # Улучшенный парсер не извлекает изображения
                'categories': [],  # Улучшенный парсер не извлекает категории
                'category': 'news',  # По умолчанию
                'feed_title': feed_info['title'],  # Добавляем название RSS-ленты
                'feed_url': feed_url  # Добавляем URL RSS-ленты
            }
            
            feed_info['entries'].append(article)
        
        return feed_info

    def _create_filter_system_prompt(self) -> str:
        """Создает системный промпт для фильтрации новостей"""
        return """Ты эксперт по оценке новостей для русскоязычных мигрантов в Испании. Твоя задача - оценить, насколько интересна и полезна будет новость для нашей целевой аудитории.

## 🎯 ЦЕЛЕВАЯ АУДИТОРИЯ (ЦА):
- **Русскоязычные мигранты в Испании**
- **Возраст**: 25-55 лет
- **Цели**: Адаптация, работа, бизнес, семья, документы
- **Боли**: Языковой барьер, незнание местных особенностей, сложности с документами
- **Интересы**: Практические советы, изменения в законах, возможности, культура

## 🚫 СТРОГО ИСКЛЮЧАТЬ:

### **НЕ ПУБЛИКОВАТЬ (0-59 баллов):**
- **РЕКЛАМА И ПРОДВИЖЕНИЕ** (курсы, услуги, продукты, бренды)
- Событие **не в Испании** и **не влияет** на её жителей
- Абстрактная международная политика без явной связи с Испанией
- Спортивные события **без культурной или социальной значимости**
- Мелкие преступления или происшествия без последствий
- Узкопрофессиональные или технические темы без массового интереса
- **ОБЩИЕ СОВЕТЫ И РЕКОМЕНДАЦИИ** без конкретных событий
- **ПРОСТЫЕ ИНФОРМАЦИОННЫЕ ЗАМЕТКИ** без новостной ценности
- **ТЕХНОЛОГИЧЕСКИЕ НОВИНКИ** (телевизоры, смартфоны, приложения) - если не связаны с Испанией
- **МЕЖДУНАРОДНЫЕ СЕРВИСЫ** (Spotify, Netflix, социальные сети) - если не касаются Испании

### ✅ ОДОБРЯЙ НОВОСТИ, если они касаются:

**🚨 КРИТИЧЕСКИЕ СИТУАЦИИ (приоритет 1):**
- Экстренные ситуации: пожары, жара, ливни, наводнения, штормы, землетрясения
- Крупные ДТП с жертвами, отключения электричества, перебои с водой
- Террористические угрозы, массовые беспорядки, кризисы безопасности

**💶 ФИНАНСОВЫЕ ИЗМЕНЕНИЯ (приоритет 2):**
- Значительные изменения цен (еда, бензин, аренда, ипотека)
- Новые налоги, штрафы, изменения в банковской сфере
- Крупные экономические кризисы, банкротства, слияния

**🏛️ ВАЖНЫЕ ЗАКОНЫ И РЕФОРМЫ (приоритет 3):**
- Новые законы, которые **НАПРЯМУЮ** влияют на повседневную жизнь
- Изменения в иммиграции, правах, пособиях
- Реформы в медицине, образовании, транспорте

**🎭 КУЛЬТУРНЫЕ СОБЫТИЯ (только если ОЧЕНЬ значимые И в Испании):**
- Крупные фестивали с международным участием **В ИСПАНИИ**
- События, которые привлекают внимание всей Испании
- Традиции, которые важны для понимания местной культуры

---

### 🔍 СТИЛЬ ОЦЕНКИ:
Представь, что ты отвечаешь на вопрос: **"Стоит ли делиться этой новостью в Telegram-канале для русскоязычных мигрантов в Испании?"**

**Цель — удивить, предупредить или помочь в критических ситуациях, связанных с жизнью в Испании.**

**ПРАВИЛО: Если новость не связана с Испанией или не влияет на жизнь мигрантов - ОТКЛОНЯЙ!**

---

### ✍️ ОЦЕНКА:
Оцени заголовок, краткое описание и категорию. Ответь строго в JSON:

```json
{
  "result": "✅ Интересно" или "❌ Не интересно"
}
```"""

    def _load_json_cache(self, path: str) -> dict:
        try:
            if os.path.exists(path):
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_json_cache(self, path: str, data: dict) -> None:
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
        except Exception:
            pass

    def _respect_per_host_delay(self, url: str) -> None:
        try:
            host = urlparse(url).netloc
            now = time.time()
            last = self._host_last_time.get(host, 0)
            delay_s = (self._per_host_delay_ms + int(200 * (os.urandom(1)[0] / 255))) / 1000.0
            wait = last + delay_s - now
            if wait > 0:
                time.sleep(wait)
            self._host_last_time[host] = time.time()
        except Exception:
            pass
    
    def is_duplicate_link(self, link: str) -> bool:
        """
        Проверяет, есть ли источник с такой ссылкой
        
        Args:
            link: URL источника
            
        Returns:
            True если источник уже существует
        """
        if not self.db:
            return False
        
        try:
            return self.db.is_duplicate_source(link)
        except Exception as e:
            print(f"⚠️ Ошибка проверки дубликата ссылки: {e}")
            return False
    
    def is_duplicate_hash(self, hash_value: str) -> bool:
        """
        Проверяет, есть ли источник с таким хешем
        
        Args:
            hash_value: Хеш источника
            
        Returns:
            True если источник уже существует
        """
        if not self.db:
            return False
        
        try:
            return self.db.is_duplicate_hash(hash_value)
        except Exception as e:
            print(f"⚠️ Ошибка проверки дубликата хеша: {e}")
            return False
    
    def save_parsed_source(self, link: str, hash_value: str, source_id: str, feed_url: str) -> None:
        """
        Сохраняет обработанный источник в Firebase
        
        Args:
            link: URL источника
            hash_value: Хеш источника
            source_id: ID источника
            feed_url: URL RSS-ленты
        """
        if not self.db:
            return
        
        try:
            self.db.save_source_hash(link, "", "", source_id, feed_url)
        except Exception as e:
            print(f"⚠️ Ошибка сохранения источника: {e}")
    
    def is_recent_enough(self, published_date: str) -> bool:
        """
        Проверяет, что новость не старше 2 дней
        
        Args:
            published_date: Дата публикации в любом формате
            
        Returns:
            True если новость не старше 2 дней, False иначе
        """
        if not published_date:
            return False
        
        try:
            # Парсим дату публикации
            article_date = date_parser.parse(published_date)
            current_date = datetime.now()
            
            # Разница в днях
            days_diff = (current_date - article_date).days
            
            # Возвращаем True только если новость не старше 2 дней
            is_recent = days_diff <= 2
            
            if not is_recent:
                print(f"    📅 Новость слишком старая: {days_diff} дней назад")
            
            return is_recent
            
        except Exception as e:
            print(f"    ⚠️  Ошибка парсинга даты '{published_date}': {e}")
            # Если не можем распарсить дату - считаем новость неактуальной
            return False

    def is_interesting(self, article: Dict[str, Any]) -> bool:
        """
        Определяет, интересна ли новость для русскоязычных жителей Испании
        используя OpenAI GPT-4o-mini с оптимизированным кэшированным промптом
        
        Args:
            article: Словарь с данными новости
            
        Returns:
            True если новость интересна, False иначе
        """
        # Сначала проверяем дату - если новость слишком старая, сразу отклоняем
        if not self.is_recent_enough(article.get('published', '')):
            return False
        
        if self.use_batch:
            # В батч-режиме не вызываем LLM синхронно: ставим задачу и пропускаем обработку сейчас
            try:
                from llm_batch_manager import LlmBatchManager
                LlmBatchManager().enqueue_filter_article(article)
                print("    📦 Задача фильтрации поставлена в очередь (Batch)")
            except Exception as e:
                print(f"    ⚠️ Не удалось поставить задачу в Batch: {e}")
            return False

        if not self.openai_client:
            # Если API ключ не установлен, используем базовую проверку
            return self._basic_relevance_check(article)
        
        title = article.get('title', '')
        summary = article.get('summary', '')
        tags = ', '.join(article.get('categories', []))
        url = article.get('link', '')
        
        if not title and not summary:
            return False
        
        # Формируем только данные новости (без полного промпта)
        user_message = f"""Заголовок: "{title}"
Описание: "{summary}"
Категории: {tags}
Ссылка: {url}"""
        
        try:
            # Используем кэшированный системный промпт
            messages = self._filter_messages + [{"role": "user", "content": user_message}]
            
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=messages,
                response_format={"type": "json_object"},
                max_completion_tokens=60,
                temperature=1
            )
            
            answer = response.choices[0].message.content.strip()
            
            # Пытаемся распарсить JSON
            try:
                import json
                result = json.loads(answer)
                
                if 'result' in result:
                    result_text = result['result']
                    
                    # Логируем результат для отладки
                    print(f"    🤖 LLM: {result_text}")
                    
                    return '✅' in result_text or 'Интересно' in result_text
                else:
                    print(f"    ⚠️  Неожиданный формат JSON: {answer}")
                    return self._fallback_decision(answer)
                    
            except json.JSONDecodeError:
                print(f"    ⚠️  Ошибка парсинга JSON: {answer}")
                return self._fallback_decision(answer)
            
        except Exception as e:
            print(f"⚠️  Ошибка при обращении к OpenAI API: {e}")
            return True  # В случае ошибки пропускаем новость
    
    def _basic_relevance_check(self, article: Dict[str, Any]) -> bool:
        """
        Базовая проверка релевантности новости для Испании без использования LLM
        
        Args:
            article: Словарь с данными новости
            
        Returns:
            True если новость релевантна для Испании, False иначе
        """
        title = article.get('title', '').lower()
        summary = article.get('summary', '').lower()
        tags = ', '.join(article.get('categories', [])).lower()
        
        # Ключевые слова, указывающие на Испанию
        spain_keywords = [
            'españa', 'spain', 'madrid', 'barcelona', 'valencia', 'sevilla', 'malaga',
            'andalucía', 'cataluña', 'galicia', 'castilla', 'aragón', 'navarra',
            'bilbao', 'zaragoza', 'murcia', 'alicante', 'granada', 'córdoba',
            'santiago', 'oviedo', 'santander', 'pamplona', 'logroño', 'vitoria',
            'san sebastián', 'la coruña', 'vigo', 'huelva', 'cádiz', 'jaén',
            'huesca', 'teruel', 'cuenca', 'albacete', 'toledo', 'ciudad real',
            'badajoz', 'cáceres', 'mérida', 'mallorca', 'menorca', 'ibiza',
            'tenerife', 'gran canaria', 'las palmas', 'ceuta', 'melilla'
        ]
        
        # Ключевые слова, указывающие на нерелевантность
        irrelevant_keywords = [
            'spotify', 'netflix', 'youtube', 'instagram', 'facebook', 'twitter',
            'lg', 'samsung', 'apple', 'iphone', 'android', 'windows', 'mac',
            'dj', 'música', 'televisor', 'smartphone', 'ordenador', 'software',
            'app', 'aplicación', 'tecnología', 'gadget', 'dispositivo'
        ]
        
        # Проверяем наличие ключевых слов Испании
        has_spain_relevance = any(keyword in title or keyword in summary or keyword in tags 
                                for keyword in spain_keywords)
        
        # Проверяем наличие нерелевантных ключевых слов
        has_irrelevant_content = any(keyword in title or keyword in summary or keyword in tags 
                                   for keyword in irrelevant_keywords)
        
        # Если есть нерелевантный контент и нет связи с Испанией - отклоняем
        if has_irrelevant_content and not has_spain_relevance:
            return False
        
        # Если есть связь с Испанией - одобряем
        if has_spain_relevance:
            return True
        
        # По умолчанию отклоняем неясные новости
        return False

    def _fallback_decision(self, answer: str) -> bool:
        """
        Fallback-логика для принятия решения при ошибке парсинга JSON
        
        Args:
            answer: Ответ от LLM
            
        Returns:
            True если новость интересна, False иначе
        """
        answer_lower = answer.lower()
        
        # Простые и надежные ключевые слова
        if '✅' in answer or 'интересно' in answer_lower or 'да' in answer_lower:
            return True
            
        if '❌' in answer or 'не интересно' in answer_lower or 'нет' in answer_lower:
            return False
        
        # Если не можем определить - одобряем новость (мягкий подход)
        return True
    
    def process_single_article(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Обрабатывает одну статью: генерирует контент и сохраняет в Firebase
        
        Args:
            article: Словарь с данными статьи
            
        Returns:
            ID созданной статьи или None при ошибке
        """
        try:
            # Создаем кластер из одной статьи для совместимости с content_generator
            cluster = {
                'cluster_id': f"single_{hashlib.md5(article.get('link', '').encode()).hexdigest()}",
                'topic_summary': article.get('title', ''),
                'combined_context': article.get('content', article.get('summary', '')),
                'sources': [article],
                'priority_score': 1.0,
                'urgent': False
            }
            
            # Генерируем контент и сохраняем в Firebase (прямые запросы)
            article_id = generate_and_save_content(cluster, self.db)
            
            if article_id:
                print(f"    ✅ Статья обработана и сохранена: {article_id}")
                return article_id
            else:
                print(f"    ❌ Не удалось обработать статью")
                return None
                
        except Exception as e:
            print(f"    ❌ Ошибка при обработке статьи: {e}")
            return None
    
    def save_article_for_clustering(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Сохраняет базовую статью в Firebase для последующей обработки
        
        Args:
            article: Данные статьи
            
        Returns:
            ID созданной статьи или None при ошибке
        """
        try:
            import hashlib
            from datetime import datetime
            
            # Создаем ID статьи
            article_id = hashlib.md5(f"{article['link']}{article['title']}".encode()).hexdigest()
            
            # Подготавливаем данные для сохранения
            article_data = {
                'article_id': article_id,
                'title': article['title'],
                'summary': article.get('summary', ''),
                'content': article.get('content', ''),
                'link': article['link'],
                'image': article.get('image', ''),
                'categories': article.get('categories', []),
                'published_date': article.get('published', ''),
                'source': article.get('source', ''),
                'created_at': datetime.now().isoformat(),
                'published': False,
                'processed': False,  # Флаг что статья еще не обработана через LLM фильтрацию
                'is_clustered': False,  # Флаг что статья еще не кластеризована (устарел)
                'urgent': article.get('urgent', False),
                'priority_score': 0
            }
            
            # Сохраняем в Firebase
            print(f"    💾 Сохраняю статью в Firebase с ID: {article_id}")
            print(f"    📊 Данные статьи: {list(article_data.keys())}")
            
            save_result = self.db.save_article(article_data)
            print(f"    🔍 Результат сохранения: {save_result}")
            
            if save_result:
                # Возвращаем ID статьи для последующего обновления
                print(f"    ✅ Статья успешно сохранена, возвращаю ID: {article_id}")
                return article_id
            else:
                print(f"    ❌ Ошибка сохранения статьи в Firebase")
                return None
                
        except Exception as e:
            print(f"❌ Ошибка сохранения базовой статьи: {e}")
            return None

    
    def save_article_md(self, article: Dict[str, Any]) -> Optional[str]:
        """
        Сохраняет статью в Markdown-файл (старый метод для совместимости)
        
        Args:
            article: Словарь с данными статьи
            
        Returns:
            Путь к сохраненному файлу или None при ошибке
        """
        if not article.get('translated'):
            print("⚠️  Статья не обработана через LLM")
            return None
        
        translated = article['translated']
        title = translated.get('title', '')
        description = translated.get('description', '')
        content = translated.get('content', '')
        tags = translated.get('tags', [])
        
        if not title or not content:
            print("⚠️  Недостаточно данных для сохранения")
            return None
        
        # Определяем категорию и директорию
        category = article.get('category', 'news')
        if category == 'article':
            save_dir = 'spain-news-portal/src/content/articles'
        else:
            save_dir = 'spain-news-portal/src/content/news'
        
        # Создаем директорию если не существует
        os.makedirs(save_dir, exist_ok=True)
        
        # Генерируем слаг из заголовка
        slug = slugify(title, max_length=50)
        
        # Получаем дату
        pub_date = article.get('published', datetime.now().strftime('%Y-%m-%d'))
        if isinstance(pub_date, str):
            try:
                # Парсим дату если она в строковом формате
                parsed_date = date_parser.parse(pub_date)
                pub_date = parsed_date.strftime('%Y-%m-%d')
            except:
                pub_date = datetime.now().strftime('%Y-%m-%d')
        
        # Формируем имя файла
        filename = f"{pub_date}-{slug}.md"
        filepath = os.path.join(save_dir, filename)
        
        # Проверяем, не существует ли уже файл
        if os.path.exists(filepath):
            print(f"⚠️  Файл уже существует: {filepath}")
            return None
        
        # Получаем изображение
        image_url = article.get('image', '')
        
        # Формируем frontmatter
        frontmatter = f"""---
title: "{title}"
description: "{description}"
pubDate: {pub_date}
tags: {tags}
slug: "{slug}"
image: "{image_url}"
author: "AI-перевод"
category: "{category}"
---

"""
        
        # Формируем полное содержимое файла
        file_content = frontmatter + content
        
        try:
            # Сохраняем файл
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(file_content)
            
            print(f"✅ Сохранено: {filepath}")
            return filepath
            
        except Exception as e:
            print(f"❌ Ошибка при сохранении файла: {e}")
            return None
    

    
    def parse_feed(self, feed_url: str) -> Dict[str, Any]:
        """
        Парсит RSS-ленту по URL
        
        Args:
            feed_url: URL RSS-ленты
            
        Returns:
            Словарь с данными RSS-ленты
        """
        try:
            print(f"   🔍 Начинаю парсинг RSS ленты...")
            
            # Anti-block: per-host delay + Conditional GET
            self._respect_per_host_delay(feed_url)
            headers = {}
            if feed_url in self._etag_cache:
                headers['If-None-Match'] = self._etag_cache[feed_url]
            if feed_url in self._lm_cache:
                headers['If-Modified-Since'] = self._lm_cache[feed_url]
            
            print(f"   📡 Отправляю HTTP запрос...")
            
            # Backoff loop
            attempt = 0
            final_url = feed_url
            while True:
                attempt += 1
                try:
                    response = self.session.get(feed_url, headers=headers, timeout=30, allow_redirects=True)
                    final_url = response.url  # Сохраняем финальный URL после редиректов
                    print(f"   ✅ HTTP запрос успешен: {response.status_code}")
                except Exception as e:
                    print(f"   ❌ HTTP запрос не удался (попытка {attempt}): {e}")
                    if attempt <= 3:
                        time.sleep(min(10, 2 ** attempt))
                        continue
                    raise e
                if response.status_code in (429, 503):
                    print(f"   ⚠️  HTTP {response.status_code}, повторяю...")
                    if attempt <= 3:
                        time.sleep(min(20, 2 ** attempt))
                        continue
                break
            
            # Если произошел редирект, выводим информацию
            if final_url != feed_url:
                print(f"   📍 Редирект: {feed_url} → {final_url}")
            if response.status_code == 304:
                # Not modified - пробуем улучшенный парсер
                print(f"   ⚠️  HTTP 304 (Not Modified), пробуем улучшенный парсер...")
                try:
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)
                    
                    if improved_feed and improved_feed.get('entries'):
                        print(f"   ✅ Улучшенный парсер сработал: {len(improved_feed['entries'])} записей")
                        return self._process_improved_feed(improved_feed, feed_url)
                    else:
                        print(f"   ❌ Улучшенный парсер не сработал")
                        return {'title': '', 'description': '', 'link': feed_url, 'entries': []}
                        
                except Exception as fallback_error:
                    print(f"   ❌ Fallback парсер не сработал: {fallback_error}")
                    return {'title': '', 'description': '', 'link': feed_url, 'entries': []}
            response.raise_for_status()
            # Save ETag/Last-Modified
            et = response.headers.get('ETag')
            lm = response.headers.get('Last-Modified')
            if et:
                self._etag_cache[feed_url] = et
                self._save_json_cache(self._etag_cache_path, self._etag_cache)
            if lm:
                self._lm_cache[feed_url] = lm
                self._save_json_cache(self._lm_cache_path, self._lm_cache)
            
            # Парсим RSS с улучшенной обработкой ошибок
            try:
                feed = feedparser.parse(response.content)
                
                # Если стандартный парсинг не удался, пробуем улучшенный
                if feed.bozo or len(feed.entries) == 0:
                    print(f"⚠️  Стандартный парсинг не удался, пробуем улучшенный...")
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)
                    
                    if improved_feed and improved_feed.get('entries'):
                        print(f"✅ Улучшенный парсинг успешен: {len(improved_feed['entries'])} записей")
                        feed = improved_feed
                    else:
                        print(f"❌ Улучшенный парсинг тоже не удался")
                        return None
                
            except Exception as parse_error:
                print(f"❌ Ошибка парсинга RSS {feed_url}: {parse_error}")
                
                # Пробуем улучшенный парсер как fallback
                print(f"🔄 Пробуем улучшенный парсер как fallback...")
                try:
                    improved_parser = ImprovedFeedParser()
                    improved_feed = improved_parser.parse_feed(feed_url)
                    
                    if improved_feed and improved_feed.get('entries'):
                        print(f"✅ Улучшенный парсер сработал: {len(improved_feed['entries'])} записей")
                        feed = improved_feed
                    else:
                        print(f"❌ Улучшенный парсер не сработал")
                        return None
                        
                except Exception as fallback_error:
                    print(f"❌ Fallback парсер тоже не сработал: {fallback_error}")
                    return None
            
            # Извлекаем метаданные ленты
            feed_info = {
                'title': '',
                'description': '',
                'link': '',
                'entries': []
            }
            
            # Проверяем тип feed (стандартный feedparser или улучшенный)
            if hasattr(feed, 'feed'):
                # Стандартный feedparser
                feed_info['title'] = feed.feed.get('title', 'Без названия')
                feed_info['description'] = feed.feed.get('description', 'Без описания')
                feed_info['link'] = feed.feed.get('link', '')
                entries = feed.entries
            else:
                # Улучшенный парсер
                feed_info['title'] = feed.get('title', 'Без названия')
                feed_info['description'] = feed.get('description', 'Без описания')
                feed_info['link'] = feed.get('link', '')
                entries = feed.get('entries', [])
            
            # Обрабатываем каждую запись
            for entry in entries:
                # Извлекаем дату
                published = None
                if hasattr(entry, 'get'):
                    # Стандартный feedparser entry
                    if entry.get('published'):
                        try:
                            published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                        except:
                            published = entry.published
                    elif entry.get('updated'):
                        try:
                            published = date_parser.parse(entry.updated).strftime('%Y-%m-%d')
                        except:
                            published = entry.updated
                    
                    # Извлекаем изображение
                    image = None
                    if entry.get('media_content'):
                        image = entry.media_content[0].get('url')
                    elif entry.get('media_thumbnail'):
                        image = entry.media_thumbnail[0].get('url')
                    elif entry.get('enclosures'):
                        for enclosure in entry.enclosures:
                            if enclosure.get('type', '').startswith('image/'):
                                image = enclosure.get('href')
                                break
                    elif entry.get('links'):
                        for link in entry.links:
                            if link.get('type', '').startswith('image/'):
                                image = link.get('href')
                                break
                    
                    # Извлекаем категории/теги
                    categories = []
                    if entry.get('tags'):
                        categories = [tag.term for tag in entry.tags]
                    elif entry.get('category'):
                        categories = [entry.category]
                    
                    # Создаем запись статьи
                    article = {
                        'title': entry.get('title', ''),
                        'link': entry.get('link', ''),
                        'summary': entry.get('summary', entry.get('description', '')),
                        'published': published,
                        'image': image,
                        'categories': categories,
                        'category': 'news',  # По умолчанию
                        'feed_title': feed_info['title'],  # Добавляем название RSS-ленты
                        'feed_url': feed_url  # Добавляем URL RSS-ленты
                    }
                else:
                    # Улучшенный парсер entry (SimpleNamespace)
                    if hasattr(entry, 'published') and entry.published:
                        try:
                            published = date_parser.parse(entry.published).strftime('%Y-%m-%d')
                        except:
                            published = entry.published
                    
                    # Создаем запись статьи для улучшенного парсера
                    article = {
                        'title': getattr(entry, 'title', ''),
                        'link': getattr(entry, 'link', ''),
                        'summary': getattr(entry, 'description', ''),
                        'published': published,
                        'image': None,  # Улучшенный парсер не извлекает изображения
                        'categories': [],  # Улучшенный парсер не извлекает категории
                        'category': 'news',  # По умолчанию
                        'feed_title': feed_info['title'],  # Добавляем название RSS-ленты
                        'feed_url': feed_url  # Добавляем URL RSS-ленты
                    }
                
                feed_info['entries'].append(article)
            
            return feed_info
            
        except Exception as e:
            print(f"❌ Ошибка при парсинге RSS-ленты {feed_url}: {e}")
            return None
    
    def _parse_entry(self, entry) -> Optional[Dict[str, Any]]:
        """
        Парсит отдельную новость из RSS
        
        Args:
            entry: Объект новости из feedparser
            
        Returns:
            Словарь с данными новости
        """
        try:
            # Извлекаем основные поля
            parsed_entry = {
                'title': entry.get('title', ''),
                'link': entry.get('link', ''),
                'summary': self._get_summary(entry),
                'published': self._get_published_date(entry),
                'image': self._get_image(entry),
                'categories': self._get_categories(entry)
            }
            
            # Удаляем пустые поля
            parsed_entry = {k: v for k, v in parsed_entry.items() if v}
            
            return parsed_entry
            
        except Exception as e:
            print(f"Ошибка при парсинге новости: {e}")
            return None
    
    def _get_summary(self, entry) -> Optional[str]:
        """Извлекает краткое описание новости"""
        # Пробуем разные поля для summary
        summary = entry.get('summary', '')
        if not summary:
            summary = entry.get('description', '')
        if not summary:
            # Пробуем content
            content = entry.get('content', [])
            if content and len(content) > 0:
                summary = content[0].get('value', '')
        
        return summary
    
    def _get_published_date(self, entry) -> Optional[str]:
        """Извлекает дату публикации в формате YYYY-MM-DD"""
        date_fields = ['published', 'pubDate', 'updated', 'date']
        
        for field in date_fields:
            date_str = entry.get(field, '')
            if date_str:
                try:
                    # Парсим дату с помощью dateutil
                    parsed_date = date_parser.parse(date_str)
                    return parsed_date.strftime('%Y-%m-%d')
                except:
                    continue
        
        return None
    
    def _get_image(self, entry) -> Optional[str]:
        """
        Извлекает URL изображения из различных источников RSS-записи
        
        Args:
            entry: Объект новости из feedparser
            
        Returns:
            URL изображения или None если не найдено
        """
        # 1. Пробуем media:content (самый надежный источник)
        media_content = entry.get('media_content', [])
        for media in media_content:
            media_type = media.get('type', '')
            if media_type.startswith('image/'):
                url = media.get('url')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 2. Пробуем media:thumbnail
        media_thumbnail = entry.get('media_thumbnail', [])
        if media_thumbnail:
            url = media_thumbnail[0].get('url')
            if url and self._is_valid_image_url(url):
                return url
        
        # 3. Пробуем enclosures (вложения)
        enclosures = entry.get('enclosures', [])
        for enclosure in enclosures:
            enclosure_type = enclosure.get('type', '')
            if enclosure_type.startswith('image/'):
                url = enclosure.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 4. Пробуем links с типом image
        links = entry.get('links', [])
        for link in links:
            link_type = link.get('type', '')
            if link_type.startswith('image/'):
                url = link.get('href')
                if url and self._is_valid_image_url(url):
                    return url
        
        # 5. Пробуем извлечь из summary/description (ищем img теги)
        summary = entry.get('summary', '') or entry.get('description', '')
        if summary:
            img_url = self._extract_image_from_html(summary)
            if img_url:
                return img_url
        
        # 6. Пробуем content с HTML
        content = entry.get('content', [])
        if content and len(content) > 0:
            content_value = content[0].get('value', '')
            if content_value:
                img_url = self._extract_image_from_html(content_value)
                if img_url:
                    return img_url
        
        # 7. Пробуем извлечь из заголовка (если есть HTML)
        title = entry.get('title', '')
        if title:
            img_url = self._extract_image_from_html(title)
            if img_url:
                return img_url
        
        return None
    
    def _is_valid_image_url(self, url: str) -> bool:
        """
        Проверяет, является ли URL валидным изображением
        
        Args:
            url: URL для проверки
            
        Returns:
            True если URL валидный, False в противном случае
        """
        if not url:
            return False
        
        # Проверяем расширение файла
        image_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg']
        url_lower = url.lower()
        
        # Проверяем расширение в URL
        for ext in image_extensions:
            if ext in url_lower:
                return True
        
        # Проверяем, что URL не содержит явно не-изображения
        non_image_patterns = ['/ads/', '/banner/', '/logo/', '/icon/']
        for pattern in non_image_patterns:
            if pattern in url_lower:
                return False
        
        return True
    
    def _extract_image_from_html(self, html_content: str) -> Optional[str]:
        """
        Извлекает URL изображения из HTML-контента
        
        Args:
            html_content: HTML-контент для поиска изображений
            
        Returns:
            URL первого найденного изображения или None
        """
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            
            # Ищем img теги
            img_tags = soup.find_all('img')
            for img in img_tags:
                src = img.get('src')
                if src and self._is_valid_image_url(src):
                    return src
                
                # Пробуем data-src (ленивая загрузка)
                data_src = img.get('data-src')
                if data_src and self._is_valid_image_url(data_src):
                    return data_src
                
                # Пробуем data-lazy-src
                data_lazy_src = img.get('data-lazy-src')
                if data_lazy_src and self._is_valid_image_url(data_lazy_src):
                    return data_lazy_src
            
            return None
            
        except Exception as e:
            print(f"⚠️  Ошибка при извлечении изображения из HTML: {e}")
            return None
    
    def _get_categories(self, entry) -> List[str]:
        """Извлекает категории/теги новости"""
        categories = []
        
        # Пробуем tags
        tags = entry.get('tags', [])
        for tag in tags:
            if tag.get('term'):
                categories.append(tag['term'])
        
        # Пробуем category
        category = entry.get('category', '')
        if category:
            categories.append(category)
        
        return list(set(categories))  # Убираем дубликаты
    
    def filter_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Фильтрует новости через LLM для русскоязычных мигрантов в Испании
        и сохраняет отфильтрованные анонсы для последующей кластеризации
        
        Args:
            articles: Список новостей для фильтрации
            
        Returns:
            Отфильтрованный список новостей (только анонсы, без генерации статей)
        """
        if not self.openai_client and not self.use_batch:
            print("⚠️  Фильтрация пропущена: OPENAI_API_KEY не установлен")
            return articles
        
        # Ограничиваем количество статей только для тестов (можно отключить)
        max_articles = None  # Установите число (например, 3) для ограничения в тестах
        if max_articles and len(articles) > max_articles:
            articles = articles[:max_articles]
            print(f"🔍 Фильтрую {len(articles)} новостей через LLM (ограничено для теста)...")
        else:
            print(f"🔍 Фильтрую {len(articles)} новостей через LLM...")
        
        filtered_articles = []
        saved_count = 0
        duplicate_count = 0
        
        # Предварительная дедупликация по нормализованной ссылке
        def _norm_link(u: str) -> str:
            try:
                pu = urlparse(u)
                return f"{pu.scheme}://{pu.netloc}{pu.path}"
            except Exception:
                return u or ''

        unique = {}
        for a in articles:
            k = _norm_link(a.get('link', '')) or a.get('title', '')
            if k and k not in unique:
                unique[k] = a
        articles = list(unique.values())

        # Если включён Batch-режим, только ставим задачи фильтрации и не зовём LLM синхронно
        if self.use_batch:
            try:
                from llm_batch_manager import LlmBatchManager
                manager = LlmBatchManager()
            except Exception as e:
                print(f"⚠️  Не удалось инициализировать LlmBatchManager: {e}")
                manager = None

            for i, article in enumerate(articles, 1):
                print(f"  (Batch) Кандидат {i}/{len(articles)}: {article.get('title', '')[:50]}...")
                article_link = article.get('link', '')
                article_title = article.get('title', '')

                # Локальный дубликат в текущем прогоне
                if article_link and article_link in self._seen_links_runtime:
                    print(f"    ⚠️  Дубликат ссылки в текущем прогоне, пропускаю")
                    duplicate_count += 1
                    continue
                self._seen_links_runtime.add(article_link)

                # Дубликат в Firebase по ссылке (можно отключить через BYPASS_DB_CACHE=1)
                if self.db and (not self._bypass_db_cache) and self.db.is_duplicate_by_link(article_link):
                    print(f"    🔁 Уже в базе по ссылке, пропускаю")
                    duplicate_count += 1
                    continue

                # Недавно отклонённые (можно отключить через BYPASS_DB_CACHE=1)
                if self.db and (not self._bypass_db_cache) and self.db.was_skipped_recently(article_link, article_title, article.get('summary', '')):
                    print(f"    🔁 Ранее отклонена (SKIPPED), пропускаю")
                    duplicate_count += 1
                    continue

                if manager:
                    manager.enqueue_filter_article(article)
                    print("    📦 Задача фильтрации поставлена (Batch)")
                    # Периодический флаш: после каждого чанка из 100 элементов — попытка отправки накопившихся задач
                    if i % 100 == 0:
                        try:
                            print("    ⏩ Флаш батчей после чанка 100")
                            import subprocess, sys, os as _os
                            py = _os.path.join(_os.getcwd(), '.venv', 'Scripts', 'python.exe')
                            subprocess.Popen([py, '-u', 'batch_worker.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        except Exception:
                            pass

            print(f"📊 (Batch) Передано в LLM-фильтрацию: {len(articles) - duplicate_count}")
            # Финальный флаш по окончании ленты
            try:
                print("   ⏩ Финальный флаш батчей для ленты")
                import subprocess, sys, os as _os
                py = _os.path.join(_os.getcwd(), '.venv', 'Scripts', 'python.exe')
                subprocess.Popen([py, '-u', 'batch_worker.py'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except Exception:
                pass
            return []

        for i, article in enumerate(articles, 1):
            print(f"  Проверяю новость {i}/{len(articles)}: {article.get('title', '')[:50]}...")
            
            # Проверяем уникальность статьи по ссылке и заголовку
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            article_key = (article_link, article_title)
            
            if article_key in self.processed_articles:
                print(f"    ⚠️  Дубликат: {article_title[:30]}...")
                duplicate_count += 1
                continue
            
            # Локальный дубликат в текущем прогоне
            if article_link and article_link in self._seen_links_runtime:
                print(f"    ⚠️  Дубликат ссылки в текущем прогоне, пропускаю")
                duplicate_count += 1
                continue
            self._seen_links_runtime.add(article_link)

            # Проверяем дубликат в Firebase (по ссылке — можно отключить BYPASS_DB_CACHE=1)
            if self.db and (not self._bypass_db_cache) and self.db.is_duplicate_by_link(article_link):
                print(f"    🔁 Уже в базе по ссылке, пропускаю без LLM")
                duplicate_count += 1
                continue

            # Проверка: недавно отклонённые (можно отключить BYPASS_DB_CACHE=1)
            if self.db and (not self._bypass_db_cache) and self.db.was_skipped_recently(article_link, article_title, article.get('summary', '')):
                print(f"    🔁 Ранее отклонена (кэш SKIPPED), пропускаю без LLM")
                duplicate_count += 1
                continue

            # Проверяем дубликат в Firebase (комбинированный), можно отключить BYPASS_DB_CACHE=1
            if (not self._bypass_db_cache) and self.is_duplicate(article):
                duplicate_count += 1
                continue
            
            if self.is_interesting(article):
                # Извлекаем полный текст для интересных статей
                print(f"    ✅ Интересна - извлекаю полный текст...")
                if article.get('link'):
                    full_text = get_full_text(article['link'])
                    if full_text:
                        article['content'] = full_text
                        print(f"    📄 Полный текст извлечен ({len(full_text)} символов)")
                        
                        # Сохраняем базовую статью в Firebase для последующей обработки
                        print(f"    💾 Сохраняю базовую статью для обработки...")
                        article_id = self.save_article_for_clustering(article)
                        
                        if article_id:
                            article['article_id'] = article_id
                            saved_count += 1
                            print(f"    ✅ Базовая статья сохранена для обработки")
                            
                            # ОТМЕЧАЕМ СТАТЬЮ КАК ОБРАБОТАННУЮ ЧЕРЕЗ LLM!
                            print(f"    🔄 Пытаюсь обновить поле processed для статьи {article_id[:8]}...")
                            try:
                                success = self.db.update_article_field(article_id, 'processed', True)
                                if success:
                                    print(f"    ✅ Статья отмечена как processed=True")
                                else:
                                    print(f"    ❌ update_article_field вернул False")
                            except Exception as e:
                                print(f"    ⚠️  Не удалось обновить processed: {e}")
                                import traceback
                                traceback.print_exc()
                        else:
                            print(f"    ❌ Не удалось сохранить статью")
                            
                        # Добавляем в множество обработанных статей
                        self.processed_articles.add(article_key)
                    else:
                        print(f"    ⚠️  Не удалось извлечь полный текст")
                else:
                    print(f"    ⚠️  Нет ссылки для извлечения текста")
                
                filtered_articles.append(article)
            else:
                print(f"    ❌ Не интересна")
                if self.db:
                    self.db.mark_skipped(article_link, article_title, article.get('summary', ''), "LLM: not interesting")
        
        print(f"📊 Результат фильтрации: {len(filtered_articles)} из {len(articles)} новостей")
        print(f"💾 Сохранено для обработки: {saved_count} статей")
        print(f"🔄 Пропущено дубликатов: {duplicate_count}")
        print(f"ℹ️  Следующий шаг: генерация статей из отфильтрованных новостей")
        return filtered_articles
    
    def display_feed(self, articles: List[Dict[str, Any]], show_all: bool = False):
        """
        Выводит данные RSS-ленты в читаемом виде
        
        Args:
            articles: Список новостей для отображения
            show_all: Показывать все новости, включая неинтересные
        """
        if not articles:
            print("Нет данных для отображения")
            return
        
        print("=" * 80)
        print(f"ЛЕНТА: {articles[0].get('feed_title', 'Без названия')}") # Assuming feed_title is added by parse_feed
        if articles[0].get('feed_description'):
            print(f"Описание: {articles[0].get('feed_description')}")
        if articles[0].get('feed_link'):
            print(f"Ссылка: {articles[0].get('feed_link')}")
        print("=" * 80)
        print()
        
        for i, article in enumerate(articles, 1):
            print(f"НОВОСТЬ #{i}")
            print("-" * 40)
            
            # Показываем переведенную версию если есть
            if article.get('translated'):
                translated = article['translated']
                print(f"🌐 ПЕРЕВЕДЕННАЯ ВЕРСИЯ:")
                print(f"Заголовок: {translated.get('title', '')}")
                print(f"Теги: {', '.join(translated.get('tags', []))}")
                
                content = translated.get('content', '')
                if len(content) > 500:
                    content = content[:500] + "..."
                print(f"Текст: {content}")
                print()
                
                # Показываем оригинальную ссылку
                if article.get('link'):
                    print(f"Оригинал: {article['link']}")
            else:
                # Показываем оригинальную версию
                if article.get('title'):
                    print(f"Заголовок: {article['title']}")
                
                if article.get('link'):
                    print(f"Ссылка: {article['link']}")
                
                if article.get('published'):
                    print(f"Дата: {article['published']}")
                
                if article.get('summary'):
                    # Обрезаем длинное описание
                    summary = article['summary']
                    if len(summary) > 200:
                        summary = summary[:200] + "..."
                    print(f"Описание: {summary}")
                
                if article.get('image'):
                    print(f"Изображение: {article['image']}")
                
                if article.get('categories'):
                    print(f"Категории: {', '.join(article['categories'])}")
                
                # Показываем полный текст (обрезанный до 500 символов)
                if article.get('content'):
                    content = article['content']
                    if len(content) > 500:
                        content = content[:500] + "..."
                    print(f"Полный текст: {content}")
            
            print()
    
    def process_multiple_feeds(self, feeds_file: str = 'feeds.txt') -> List[Dict[str, Any]]:
        """
        Обрабатывает множество RSS-лент из файла
        
        Args:
            feeds_file: Путь к файлу со списком RSS-лент
            
        Returns:
            Список отфильтрованных анонсов для кластеризации
        """
        if not os.path.exists(feeds_file):
            print(f"❌ Файл {feeds_file} не найден")
            return []
        
        # Загружаем список RSS-лент
        feeds = self.load_feeds_from_file(feeds_file)
        if not feeds:
            print(f"❌ Не удалось загрузить RSS-ленты из {feeds_file}")
            return []
        
        print(f"📋 Найдено {len(feeds)} RSS-лент для обработки")
        print("=" * 60)
        
        all_articles = []
        total_processed = 0
        total_saved = 0
        
        for i, feed_url in enumerate(feeds, 1):
            print(f"\n🔄 [{i}/{len(feeds)}] Загружаю RSS: {feed_url}")
            
            try:
                # Парсим RSS-ленту
                feed_data = self.parse_feed(feed_url)
                if not feed_data or not feed_data.get('entries'):
                    print(f"   ⚠️  Не удалось загрузить RSS-ленту")
                    continue
                
                articles = feed_data['entries']
                # Ограничение числа элементов на одну ленту, чтобы не блокировать оркестратор слишком долго
                try:
                    max_per_feed = int(os.getenv('RSS_MAX_ITEMS_PER_FEED', '0') or '0')
                except Exception:
                    max_per_feed = 0
                total_in_feed = len(articles)
                if max_per_feed and total_in_feed > max_per_feed:
                    print(f"   ⚖️ Ограничиваю {total_in_feed} → {max_per_feed} элементов для этой ленты (RSS_MAX_ITEMS_PER_FEED)")
                    articles = articles[:max_per_feed]
                print(f"   ✅ Найдено {len(articles)} статей")
                
                # Фильтруем и обрабатываем статьи
                filtered_articles = self.filter_articles(articles)
                
                # Подсчитываем статистику
                processed_in_feed = len(filtered_articles)
                saved_in_feed = len([a for a in filtered_articles if a.get('content')])
                
                total_processed += processed_in_feed
                total_saved += saved_in_feed
                
                all_articles.extend(filtered_articles)
                
                print(f"   📊 Обработано: {processed_in_feed}, Сохранено: {saved_in_feed}")
                
            except Exception as e:
                print(f"   ❌ Ошибка при обработке {feed_url}: {e}")
                continue
        
        print("\n" + "=" * 60)
        print(f"🎯 ИТОГОВАЯ СТАТИСТИКА:")
        print(f"   📋 RSS-лент обработано: {len(feeds)}")
        print(f"   📰 Статей найдено: {len(all_articles)}")
        print(f"   🤖 Статей обработано через LLM: {total_processed}")
        print(f"   💾 Статей сохранено для генерации: {total_saved}")
        print(f"   🔄 Уникальных статей: {len(self.processed_articles)}")
        print(f"   ℹ️  Следующий шаг: генерация статей из отфильтрованных анонсов")
        
        return all_articles

    def load_feeds_from_file(self, filename: str) -> List[str]:
        """
        Загружает список RSS-лент из файла
        
        Args:
            filename: Имя файла со списком URL
            
        Returns:
            Список URL RSS-лент
        """
        try:
            with open(filename, 'r', encoding='utf-8') as f:
                feeds = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            return feeds
        except Exception as e:
            print(f"❌ Ошибка при загрузке файла {filename}: {e}")
            return []

    def is_duplicate(self, article: Dict[str, Any]) -> bool:
        """
        Проверяет, есть ли статья в базе данных Firebase
        
        Args:
            article: Словарь с данными статьи
            
        Returns:
            True если статья уже есть в базе, False если новая
        """
        if not self.db:
            return False
        
        try:
            article_link = article.get('link', '')
            article_title = article.get('title', '')
            
            # Проверяем дубликат через новый Firebase клиент
            is_duplicate = self.db.is_duplicate_article(article_link, article_title)
            
            if is_duplicate:
                print(f"    🔁 Уже публиковалась, пропускаем")
                return True
            else:
                print(f"    ✅ Новая статья, сохраняем")
                return False
                
        except Exception as e:
            print(f"    ⚠️  Ошибка проверки дубликата: {e}")
            return False

    def save_to_firebase(self, article: Dict[str, Any], translated: Dict[str, Any]) -> bool:
        """
        Сохраняет статью в базу данных Firebase
        
        Args:
            article: Словарь с данными статьи
            translated: Словарь с переведенными данными статьи
            
        Returns:
            True если сохранение прошло успешно, False иначе
        """
        if not self.db:
            print("⚠️  Firebase не инициализирован, невозможно сохранить статью.")
            return False
        
        try:
            # Формируем данные для сохранения
            data_to_save = {
                'title': translated['title'],
                'description': translated['description'],
                'content': translated['content'],
                'tags': translated['tags'],
                'link': article['link'],
                'published': article['published'],
                'image': article['image'],
                'category': article['category'],
                'source_feed': article['feed_title'], # Добавляем ссылку на RSS-ленту
                'source_link': article['link'], # Добавляем ссылку на оригинальную статью
                'created_at': datetime.now().isoformat()
            }
            
            # Сохраняем через новый Firebase клиент
            success = self.db.save_article(data_to_save)
            
            if success:
                print(f"✅ Статья сохранена в Firebase")
                return True
            else:
                print(f"❌ Ошибка при сохранении статьи в Firebase")
                return False
            
        except Exception as e:
            print(f"❌ Ошибка при сохранении статьи в Firebase: {e}")
            return False



    def send_telegram_post(self, article: Dict[str, Any], chat_id: str = None) -> bool:
        """
        Отправляет Telegram-пост в канал
        
        Args:
            article: Словарь с данными статьи (должен содержать telegram_post)
            chat_id: ID чата/канала для отправки (если не указан, берется из TELEGRAM_CHAT_ID)
            
        Returns:
            True если пост отправлен успешно, False в противном случае
        """
        try:
            from telegram import Bot
            from telegram.error import TelegramError
            
            # Получаем токен бота
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if not bot_token:
                print("❌ TELEGRAM_BOT_TOKEN не установлен")
                return False
            
            # Получаем ID чата
            if not chat_id:
                chat_id = os.environ.get('TELEGRAM_CHAT_ID')
                if not chat_id:
                    print("❌ TELEGRAM_CHAT_ID не установлен")
                    return False
            
            # Проверяем наличие Telegram-поста
            telegram_post = article.get('telegram_post')
            if not telegram_post:
                print("❌ Telegram-пост не найден в статье")
                return False
            
            # Получаем изображение из статьи
            image_url = article.get('image', '')
            translated_image_url = ''
            
            # Проверяем, есть ли изображение в переведенной статье
            if 'translated' in article and article['translated']:
                translated_image_url = article['translated'].get('image', '')
            
            # Используем изображение из переведенной статьи или оригинальное
            final_image_url = translated_image_url if translated_image_url else image_url
            
            # Создаем бота
            bot = Bot(token=bot_token)
            
            # Проверяем длину поста
            post_length = len(telegram_post)
            print(f"📏 Длина поста: {post_length} символов")
            
            # Отправляем пост
            if final_image_url and self._is_valid_image_url(final_image_url):
                print("🖼️  Отправляю пост с изображением...")
                try:
                    bot.send_photo(
                        chat_id=chat_id,
                        photo=final_image_url,
                        caption=telegram_post,
                        parse_mode='Markdown'
                    )
                    print(f"✅ Telegram-пост с изображением отправлен в чат {chat_id}")
                    return True
                except TelegramError as e:
                    print(f"⚠️  Не удалось отправить с изображением: {e}")
                    # Fallback: отправляем только текст
                    print("📝 Отправляю только текст...")
            
            # Отправляем только текст
            bot.send_message(
                chat_id=chat_id,
                text=telegram_post,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            print(f"✅ Telegram-пост отправлен в чат {chat_id}")
            return True
            
        except ImportError:
            print("❌ python-telegram-bot не установлен. Установите: pip install python-telegram-bot")
            return False
        except TelegramError as e:
            print(f"❌ Ошибка Telegram API: {e}")
            return False
        except Exception as e:
            print(f"❌ Ошибка при отправке Telegram-поста: {e}")
            return False
    
    def send_telegram_post_with_continuation(self, article: Dict[str, Any], chat_id: str = None) -> bool:
        """
        Отправляет Telegram-пост с продолжением в комментариях (альтернативный подход)
        
        Args:
            article: Словарь с данными статьи (должен содержать telegram_post)
            chat_id: ID чата/канала для отправки
            
        Returns:
            True если пост отправлен успешно, False в противном случае
        """
        try:
            from telegram import Bot
            from telegram.error import TelegramError
            
            # Получаем токен бота
            bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
            if not bot_token:
                print("❌ TELEGRAM_BOT_TOKEN не установлен")
                return False
            
            # Получаем ID чата
            if not chat_id:
                chat_id = os.environ.get('TELEGRAM_CHAT_ID')
                if not chat_id:
                    print("❌ TELEGRAM_CHAT_ID не установлен")
                    return False
            
            # Проверяем наличие Telegram-поста
            telegram_post = article.get('telegram_post')
            if not telegram_post:
                print("❌ Telegram-пост не найден в статье")
                return False
            
            # Создаем бота
            bot = Bot(token=bot_token)
            
            # Отправляем основной пост
            main_message = bot.send_message(
                chat_id=chat_id,
                text=telegram_post,
                parse_mode='Markdown',
                disable_web_page_preview=True
            )
            
            # Если пост длинный, отправляем продолжение в комментарии
            if len(telegram_post) > 800:
                continuation_text = f"📖 **Продолжение:**\n\n{article.get('content', '')[:1000]}...\n\n🔗 Полная статья: https://example.com/news/{article.get('slug', '')}/"
                
                try:
                    bot.send_message(
                        chat_id=chat_id,
                        text=continuation_text,
                        parse_mode='Markdown',
                        reply_to_message_id=main_message.message_id
                    )
                    print("✅ Продолжение отправлено в комментариях")
                except TelegramError as e:
                    print(f"⚠️  Не удалось отправить продолжение: {e}")
            
            print(f"✅ Telegram-пост с продолжением отправлен в чат {chat_id}")
            return True
            
        except ImportError:
            print("❌ python-telegram-bot не установлен. Установите: pip install python-telegram-bot")
            return False
        except TelegramError as e:
            print(f"❌ Ошибка Telegram API: {e}")
            return False
        except Exception as e:
            print(f"❌ Ошибка при отправке Telegram-поста: {e}")
            return False

    def cluster_articles(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Кластеризация отключена. Возвращаем исходные статьи."""
        print("ℹ️  Кластеризация отключена — возвращаю исходные статьи без изменений")
        return articles
    
    def get_clustered_articles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Кластеризация отключена. Возвращаем пустой список."""
        print("ℹ️  Кластеризация отключена — get_clustered_articles() вернет пустой список")
        return []
    
    def mark_cluster_as_published(self, cluster_id: str):
        """Отмечает кластер как опубликованный"""
        try:
            self.clustering_pipeline.mark_cluster_as_published(cluster_id)
        except Exception as e:
            print(f"❌ Ошибка при отметке кластера как опубликованного: {e}")



def main():
    parser = argparse.ArgumentParser(description='RSS Parser для русскоязычных мигрантов в Испании')
    parser.add_argument('url', nargs='?', help='URL RSS-ленты для парсинга')
    parser.add_argument('--feeds', '-f', default='feeds.txt', help='Файл со списком RSS-лент (по умолчанию: feeds.txt)')
    parser.add_argument('--no-filter', action='store_true', help='Пропустить фильтрацию через LLM')
    parser.add_argument('--display-all', action='store_true', help='Показать все новости, включая неинтересные')
    parser.add_argument('--send-telegram', action='store_true', help='Отправить Telegram-посты в канал')
    # Кластеризация отключена
    parser.add_argument('--cluster', action='store_true', help='(ОТКЛЮЧЕНО) Включить кластеризацию новостей')
    parser.add_argument('--clustered-only', action='store_true', help='(ОТКЛЮЧЕНО) Работать только с кластеризованными новостями')
    
    args = parser.parse_args()
    
    rss_parser = RSSParser()
    
    if args.url:
        # Обработка одной RSS-ленты
        print(f"Загружаю RSS-ленту: {args.url}")
        feed_data = rss_parser.parse_feed(args.url)
        
        if feed_data and feed_data.get('entries'):
            print(f"✅ Загружено {len(feed_data['entries'])} новостей")
            print("=" * 80)
            print(f"ЛЕНТА: {feed_data.get('title', 'Без названия')}")
            print(f"Описание: {feed_data.get('description', 'Без описания')}")
            print(f"Ссылка: {feed_data.get('link', 'Без ссылки')}")
            print("=" * 80)
            
            if args.no_filter:
                rss_parser.display_feed(feed_data['entries'], show_all=True)
            else:
                filtered_articles = rss_parser.filter_articles(feed_data['entries'])
                rss_parser.display_feed(filtered_articles, show_all=args.display_all)
        else:
            print("❌ Не удалось загрузить RSS-ленту")
    else:
        # Обработка множественных RSS-лент
        print("🚀 Запуск обработки множественных RSS-лент")
        print("=" * 60)
        
        if args.no_filter:
            print("⚠️  Режим --no-filter не поддерживается для множественных RSS-лент")
            return
        
        # Обычная обработка RSS-лент (кластеризация отключена)
        all_articles = rss_parser.process_multiple_feeds(args.feeds)
        
        if all_articles:
            print(f"\n📰 Всего обработано статей: {len(all_articles)}")
        else:
            print("❌ Не удалось обработать RSS-ленты")
            return
        
        # Отправляем Telegram-посты если включена опция
        if args.send_telegram:
            print("\n📱 ОТПРАВКА TELEGRAM-ПОСТОВ:")
            print("=" * 60)
            telegram_sent = 0
            for i, article in enumerate(all_articles, 1):
                if article.get('telegram_post'):
                    print(f"\n{i}. Отправляю пост: {article.get('title', 'Без заголовка')[:50]}...")
                    if rss_parser.send_telegram_post(article):
                        telegram_sent += 1
                    else:
                        print(f"   ❌ Не удалось отправить пост")
                else:
                    print(f"\n{i}. Пропускаю: {article.get('title', 'Без заголовка')[:50]}... (нет Telegram-поста)")
            
            print(f"\n📊 Telegram-постов отправлено: {telegram_sent} из {len(all_articles)}")
        
        if args.display_all:
            print("\n📋 ВСЕ ОБРАБОТАННЫЕ СТАТЬИ:")
            print("=" * 60)
            for i, article in enumerate(all_articles, 1):
                print(f"\n{i}. {article.get('title', 'Без заголовка')}")
                if article.get('content'):
                    print(f"   📝 Контент готов")
                if article.get('telegram_post'):
                    print(f"   📱 Telegram-пост готов")
                print(f"   🔗 {article.get('link', '')}")


if __name__ == "__main__":
    main() 