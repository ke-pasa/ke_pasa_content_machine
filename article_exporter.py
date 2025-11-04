#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модуль для экспорта статей из Firebase в Markdown-файлы для сайта Astro
Экспортирует статьи из коллекции 'articles' в структуру папок сайта
"""

import os
import json
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path
from workers.tools.firebase_client import FirebaseClient


class ArticleExporter:
    """Экспортер статей из Firebase в Markdown для Astro"""
    
    def __init__(self, firebase_client: FirebaseClient, output_dir: str = "spain-news-portal/src/content"):
        """
        Инициализация экспортера
        
        Args:
            firebase_client: Клиент Firebase
            output_dir: Директория для сохранения файлов
        """
        self.firebase_client = firebase_client
        self.output_dir = Path(output_dir)
        self.setup_logging()
        
        # Создаем директории если их нет
        self._ensure_directories()
    
    def setup_logging(self):
        """Настройка логирования"""
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler('article_exporter.log'),
                logging.StreamHandler()
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def _ensure_directories(self):
        """Создает необходимые директории"""
        collections = ['news', 'articles', 'guides', 'legal', 'catalog']
        for collection in collections:
            collection_dir = self.output_dir / collection
            collection_dir.mkdir(parents=True, exist_ok=True)
            self.logger.info(f"Создана директория: {collection_dir}")
    
    def get_articles_from_firebase(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Получает статьи из Firebase
        
        Args:
            limit: Максимальное количество статей
            
        Returns:
            Список статей
        """
        try:
            # Получаем все документы из коллекции articles
            articles_ref = self.firebase_client.db.collection('articles')
            docs = articles_ref.limit(limit).stream()
            
            articles = []
            for doc in docs:
                article_data = doc.to_dict()
                article_data['id'] = doc.id
                articles.append(article_data)
            
            self.logger.info(f"Получено {len(articles)} статей из Firebase")
            return articles
            
        except Exception as e:
            self.logger.error(f"Ошибка получения статей из Firebase: {e}")
            return []
    
    def determine_collection(self, article: Dict[str, Any]) -> str:
        """
        Определяет коллекцию для статьи на основе категории
        
        Args:
            article: Данные статьи
            
        Returns:
            Название коллекции
        """
        category = article.get('category', 'news').lower()
        
        category_mapping = {
            'news': 'news',
            'society': 'news',
            'migration': 'articles',
            'economy': 'news',
            'law': 'legal',
            'guides': 'guides',
            'education': 'guides',
            'health': 'guides',
            'culture': 'articles',
            'catalog': 'catalog'
        }
        
        return category_mapping.get(category, 'news')
    
    def format_frontmatter(self, article: Dict[str, Any]) -> str:
        """
        Формирует frontmatter для Astro
        
        Args:
            article: Данные статьи
            
        Returns:
            Строка с frontmatter
        """
        # Базовые поля
        frontmatter = {
            'title': article.get('title', 'Без заголовка'),
            'description': article.get('description', ''),
            'pubDate': article.get('pubDate', datetime.now().strftime('%Y-%m-%d')),
            'author': article.get('author', 'Авто-редакция'),
            'slug': article.get('slug', ''),
            'category': article.get('category', 'news'),
            'region': article.get('region', 'unknown'),
            'tags': article.get('tags', [])
        }
        
        # Изображение
        if article.get('image'):
            frontmatter['image'] = article['image']
        
        # SEO поля
        seo_data = {}
        if article.get('meta_title'):
            seo_data['title'] = article['meta_title']
        if article.get('meta_description'):
            seo_data['description'] = article['meta_description']
        if article.get('meta_keywords'):
            seo_data['keywords'] = article['meta_keywords']
        
        if seo_data:
            frontmatter['seo'] = seo_data
        
        # Telegram пост
        if article.get('telegram_post'):
            frontmatter['telegram_post'] = article['telegram_post']
        
        # Форматируем в YAML
        yaml_lines = ['---']
        
        for key, value in frontmatter.items():
            if key == 'tags':
                # Массив тегов
                if value:
                    yaml_lines.append(f'{key}: {json.dumps(value, ensure_ascii=False)}')
                else:
                    yaml_lines.append(f'{key}: []')
            elif key == 'seo':
                # Вложенный объект SEO
                yaml_lines.append(f'{key}:')
                for seo_key, seo_value in value.items():
                    if isinstance(seo_value, list):
                        yaml_lines.append(f'  {seo_key}: {json.dumps(seo_value, ensure_ascii=False)}')
                    else:
                        yaml_lines.append(f'  {seo_key}: "{seo_value}"')
            elif isinstance(value, str):
                # Строковые значения в кавычках
                yaml_lines.append(f'{key}: "{value}"')
            else:
                # Остальные значения как есть
                yaml_lines.append(f'{key}: {value}')
        
        yaml_lines.append('---')
        return '\n'.join(yaml_lines)
    
    def format_content(self, article: Dict[str, Any]) -> str:
        """
        Форматирует контент статьи
        
        Args:
            article: Данные статьи
            
        Returns:
            Отформатированный контент
        """
        content = article.get('content', '')
        
        # Если контент уже в Markdown, возвращаем как есть
        if content.strip().startswith('#'):
            return content
        
        # Иначе форматируем как простой текст
        title = article.get('title', 'Без заголовка')
        return f"# {title}\n\n{content}"
    
    def generate_filename(self, article: Dict[str, Any]) -> str:
        """
        Генерирует имя файла для статьи
        
        Args:
            article: Данные статьи
            
        Returns:
            Имя файла
        """
        # Используем slug если есть
        slug = article.get('slug', '')
        if slug:
            return f"{slug}.md"
        
        # Иначе генерируем из заголовка
        title = article.get('title', 'untitled')
        # Убираем специальные символы и заменяем пробелы на дефисы
        filename = "".join(c for c in title if c.isalnum() or c in (' ', '-', '_')).rstrip()
        filename = filename.replace(' ', '-').lower()
        filename = filename[:50]  # Ограничиваем длину
        
        return f"{filename}.md"
    
    def save_article(self, article: Dict[str, Any]) -> bool:
        """
        Сохраняет статью в Markdown файл
        
        Args:
            article: Данные статьи
            
        Returns:
            True если сохранение прошло успешно
        """
        try:
            # Определяем коллекцию
            collection = self.determine_collection(article)
            collection_dir = self.output_dir / collection
            
            # Генерируем имя файла
            filename = self.generate_filename(article)
            file_path = collection_dir / filename
            
            # Проверяем, не существует ли уже файл
            if file_path.exists():
                self.logger.warning(f"Файл уже существует: {file_path}")
                # Добавляем timestamp к имени файла
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                name_without_ext = filename[:-3]
                filename = f"{name_without_ext}_{timestamp}.md"
                file_path = collection_dir / filename
            
            # Формируем frontmatter и контент
            frontmatter = self.format_frontmatter(article)
            content = self.format_content(article)
            
            # Собираем полный файл
            full_content = f"{frontmatter}\n\n{content}"
            
            # Сохраняем файл
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(full_content)
            
            self.logger.info(f"Сохранена статья: {file_path}")
            return True
            
        except Exception as e:
            self.logger.error(f"Ошибка сохранения статьи: {e}")
            return False
    
    def export_articles(self, limit: int = 100, dry_run: bool = False) -> Dict[str, Any]:
        """
        Экспортирует статьи из Firebase
        
        Args:
            limit: Максимальное количество статей
            dry_run: Если True, только показывает что будет экспортировано
            
        Returns:
            Статистика экспорта
        """
        self.logger.info(f"Начинаем экспорт статей (limit: {limit}, dry_run: {dry_run})")
        
        # Получаем статьи из Firebase
        articles = self.get_articles_from_firebase(limit)
        
        if not articles:
            self.logger.warning("Статьи не найдены")
            return {'total': 0, 'success': 0, 'failed': 0, 'collections': {}}
        
        # Статистика
        stats = {
            'total': len(articles),
            'success': 0,
            'failed': 0,
            'collections': {}
        }
        
        for article in articles:
            try:
                collection = self.determine_collection(article)
                
                if collection not in stats['collections']:
                    stats['collections'][collection] = 0
                
                if not dry_run:
                    if self.save_article(article):
                        stats['success'] += 1
                        stats['collections'][collection] += 1
                    else:
                        stats['failed'] += 1
                else:
                    # В режиме dry_run просто считаем
                    stats['success'] += 1
                    stats['collections'][collection] += 1
                    
            except Exception as e:
                self.logger.error(f"Ошибка обработки статьи {article.get('title', 'Unknown')}: {e}")
                stats['failed'] += 1
        
        # Логируем результаты
        self.logger.info(f"Экспорт завершен:")
        self.logger.info(f"  Всего статей: {stats['total']}")
        self.logger.info(f"  Успешно: {stats['success']}")
        self.logger.info(f"  Ошибок: {stats['failed']}")
        
        for collection, count in stats['collections'].items():
            self.logger.info(f"  {collection}: {count} статей")
        
        return stats
    
    def export_single_article(self, article_id: str) -> bool:
        """
        Экспортирует одну статью по ID
        
        Args:
            article_id: ID статьи в Firebase
            
        Returns:
            True если экспорт прошел успешно
        """
        try:
            # Получаем статью из Firebase
            doc_ref = self.firebase_client.db.collection('articles').document(article_id)
            doc = doc_ref.get()
            
            if not doc.exists:
                self.logger.error(f"Статья с ID {article_id} не найдена")
                return False
            
            article_data = doc.to_dict()
            article_data['id'] = doc.id
            
            # Сохраняем статью
            return self.save_article(article_data)
            
        except Exception as e:
            self.logger.error(f"Ошибка экспорта статьи {article_id}: {e}")
            return False


def main():
    """Основная функция для запуска экспорта"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Экспорт статей из Firebase в Markdown')
    parser.add_argument('--limit', type=int, default=100, help='Максимальное количество статей')
    parser.add_argument('--dry-run', action='store_true', help='Показать что будет экспортировано без сохранения')
    parser.add_argument('--output-dir', default='spain-news-portal/src/content', help='Директория для сохранения')
    parser.add_argument('--article-id', help='Экспортировать конкретную статью по ID')
    
    args = parser.parse_args()
    
    try:
        # Инициализируем Firebase клиент
        firebase_client = FirebaseClient()
        
        # Создаем экспортер
        exporter = ArticleExporter(firebase_client, args.output_dir)
        
        if args.article_id:
            # Экспортируем одну статью
            success = exporter.export_single_article(args.article_id)
            if success:
                print(f"✅ Статья {args.article_id} успешно экспортирована")
            else:
                print(f"❌ Ошибка экспорта статьи {args.article_id}")
        else:
            # Экспортируем все статьи
            stats = exporter.export_articles(args.limit, args.dry_run)
            
            if args.dry_run:
                print("🔍 Режим предварительного просмотра:")
            else:
                print("📤 Экспорт завершен:")
            
            print(f"  Всего статей: {stats['total']}")
            print(f"  Успешно: {stats['success']}")
            print(f"  Ошибок: {stats['failed']}")
            
            for collection, count in stats['collections'].items():
                print(f"  {collection}: {count} статей")
    
    except Exception as e:
        print(f"❌ Ошибка: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main()) 