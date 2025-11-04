#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ОБНОВЛЕННЫЙ генератор Telegram-постов для выбранных лучших статей
Использует улучшенный промпт версии 4.0 для устранения шаблонности
"""

import json
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import openai
import os
from dotenv import load_dotenv
import re

# Загружаем переменные окружения
load_dotenv()

# Импортируем новый промпт v4.0
try:
    from enhanced_telegram_prompt_v4 import get_enhanced_telegram_prompt_v4, validate_telegram_post_v4
    NEW_PROMPT_AVAILABLE = True
except ImportError:
    NEW_PROMPT_AVAILABLE = False
    logging.warning("Новый промпт v4.0 недоступен, используется старый")


class TelegramPostGeneratorV4:
    """Обновленный генератор Telegram-постов с улучшенным промптом v4.0"""
    
    def __init__(self):
        """Инициализация генератора"""
        self.openai_client = self._get_openai_client()
        
        # Кэшируем системный промпт
        self._system_prompt = self._create_system_prompt()
        
        # Кэш для промптов (чтобы не пересоздавать)
        self._prompt_cache = {}
        
        logging.info("TelegramPostGeneratorV4 инициализирован с улучшенным промптом v4.0")
    
    def _get_openai_client(self) -> Optional[openai.OpenAI]:
        """Получает OpenAI клиент"""
        try:
            api_key = os.getenv('OPENAI_API_KEY')
            if not api_key:
                logging.error("OPENAI_API_KEY не найден в переменных окружения")
                return None
            
            return openai.OpenAI(api_key=api_key)
        except Exception as e:
            logging.error(f"Ошибка инициализации OpenAI клиента: {e}")
            return None
    
    def _create_system_prompt(self) -> str:
        """Создает системный промпт (кэшируется)"""
        # Используем упрощенный, но четкий промпт для GPT-5-mini
        return """Ты пишешь посты для Telegram канала русскоязычных мигрантов в Испании.

КРИТИЧЕСКИ ВАЖНО: ВСЕГДА ПИШИ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ!

Требования:
- Максимум 1000 символов
- Живой русский язык
- Добавь эмодзи для категории
- Структурированные абзацы
- Обязательно включи ссылку на статью

Пиши как для друга, избегай канцеляризмов и шаблонов."""
    
    def generate_post(self, article: Dict[str, Any], article_url: str) -> Optional[str]:
        """Генерирует Telegram-пост для выбранной статьи с новым промптом v4.0"""
        if not self.openai_client:
            logging.error("OpenAI клиент не инициализирован")
            return None
        
        try:
            # Создаем промпты
            system_prompt = self._system_prompt
            
            # Используем упрощенный промпт для GPT-5-mini
            user_prompt = self._create_simple_prompt(article, article_url)
            
            # Отправляем запрос в OpenAI
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                max_completion_tokens=800,
                temperature=1
            )
            
            # Извлекаем сгенерированный пост
            generated_post = response.choices[0].message.content.strip()
            
            if not generated_post:
                logging.warning("⚠️ OpenAI вернул пустой ответ, пробую fallback промпт...")
                # Пробуем fallback промпт
                fallback_prompt = self._create_fallback_prompt(article, article_url)
                
                try:
                    fallback_response = self.openai_client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {"role": "system", "content": "Ты пишешь посты для Telegram. ВСЕГДА на русском языке!"},
                            {"role": "user", "content": fallback_prompt}
                        ],
                        max_completion_tokens=600,
                        temperature=1
                    )
                    
                    generated_post = fallback_response.choices[0].message.content.strip()
                    
                    if not generated_post:
                        logging.error("❌ Fallback промпт тоже не сработал")
                        return self._generate_manual_post(article, article_url)
                    else:
                        logging.info("✅ Fallback промпт сработал!")
                        
                except Exception as fallback_error:
                    logging.error(f"❌ Ошибка fallback промпта: {fallback_error}")
                    return self._generate_manual_post(article, article_url)
            
            # Проверяем длину поста
            post_length = len(generated_post)
            logging.info(f"📝 Сгенерирован пост длиной {post_length} символов")
            
            # Валидируем пост по новым стандартам v4.0
            if NEW_PROMPT_AVAILABLE:
                validation = validate_telegram_post_v4(generated_post)
                logging.info(f"📊 Валидация поста v4.0: {validation['score']}/{validation['max_score']} - {validation['level']}")
                
                if validation['issues']:
                    logging.warning(f"⚠️ Проблемы с постом: {', '.join(validation['issues'])}")
                
                # Если пост превышает лимит, пытаемся сократить
                if post_length > 1000:
                    logging.warning(f"⚠️ Пост превышает лимит в 1000 символов ({post_length}), пытаюсь сократить...")
                    shortened_post = self._shorten_post(generated_post)
                    if shortened_post:
                        generated_post = shortened_post
                        post_length = len(generated_post)
                        logging.info(f"✅ Пост сокращен до {post_length} символов")
            
            if post_length > 1000:
                logging.warning(f"⚠️ Пост все еще превышает лимит в 1000 символов ({post_length}), но НЕ обрезаем - убираем картинку")
            
            return generated_post
            
        except Exception as e:
            logging.error(f"❌ Ошибка генерации Telegram-поста: {e}")
            return None
    
    def _create_simple_prompt(self, article: Dict[str, Any], article_url: str) -> str:
        """Создает простой промпт для GPT-5-mini"""
        # Получаем информацию о посте
        post_info = self.get_post_info(article)
        emoji = post_info['emoji']
        
        # Получаем контент статьи для контекста
        content_sample = article.get('content', '')[:300] if article.get('content') else article.get('description', '')
        
        # Формируем заметку об изображении
        image_note = "📸 В посте будет картинка" if post_info['has_image'] else "📝 Только текст"
        
        return f"""Создай Telegram пост на русском языке:

ЗАГОЛОВОК: {article.get('title', '')}
ОПИСАНИЕ: {article.get('description', '')}
КОНТЕНТ: {content_sample}

ТРЕБОВАНИЯ:
- Максимум {post_info['max_length']} символов
- Только русский язык
- Структура: {emoji} Заголовок + 2-3 абзаца + ссылка
- Обязательно добавь: [Читать полную статью]({article_url})
- {image_note}

Пиши кратко, но информативно."""

    def get_post_info(self, article: Dict[str, Any]) -> Dict[str, Any]:
        """Получает информацию для поста, включая изображение"""
        info = {
            'has_image': bool(article.get('image', '')),
            'image_url': article.get('image', ''),
            'max_length': 900 if article.get('image') else 1000,
            'category': article.get('category', 'general'),
            'tags': article.get('tags', [])
        }
        
        # Определяем эмодзи
        emoji_map = {
            'economy': '💰', 'health': '🏥', 'transport': '🚗', 'housing': '🏠',
            'education': '🎓', 'tourism': '🏖️', 'crime': '🚨', 'fire': '🔥',
            'weather': '🌤️', 'general': '📢'
        }
        info['emoji'] = emoji_map.get(info['category'], '📢')
        
        return info

    def _generate_manual_post(self, article: Dict[str, Any], article_url: str) -> str:
        """Генерирует пост вручную, если OpenAI не сработал"""
        try:
            title = article.get('title', 'Новость')
            description = article.get('description', '')
            
            # Определяем эмодзи
            category = article.get('category', 'general')
            emoji_map = {
                'economy': '💰', 'health': '🏥', 'transport': '🚗', 'housing': '🏠',
                'education': '🎓', 'tourism': '🏖️', 'crime': '🚨', 'fire': '🔥',
                'weather': '🌤️', 'general': '📢'
            }
            emoji = emoji_map.get(category, '📢')
            
            # Создаем простой пост
            post = f"{emoji} {title}\n\n"
            
            if description:
                # Сокращаем описание до 200 символов
                short_desc = description[:200] + "..." if len(description) > 200 else description
                post += f"{short_desc}\n\n"
            
            post += f"🔗 [Читать полную статью]({article_url})"
            
            logging.info("✅ Создан ручной пост")
            return post
            
        except Exception as e:
            logging.error(f"❌ Ошибка создания ручного поста: {e}")
            # Возвращаем минимальный пост
            return f"📢 {article.get('title', 'Новость')}\n\n🔗 [Читать статью]({article_url})"

    def _create_fallback_prompt(self, article: Dict[str, Any], article_url: str) -> str:
        """Создает fallback промпт если новый недоступен"""
        # Определяем эмодзи
        category = article.get('category', 'general')
        emoji_map = {
            'economy': '💰', 'health': '🏥', 'transport': '🚗', 'housing': '🏠',
            'education': '🎓', 'tourism': '🏖️', 'crime': '🚨', 'fire': '🔥',
            'weather': '🌤️', 'general': '📢'
        }
        emoji = emoji_map.get(category, '📢')
        
        # Сокращаем контент
        content_sample = article.get('content', '')[:200] if article.get('content') else article.get('description', '')[:200]
        
        return f"""Напиши короткий Telegram пост:

{emoji} {article.get('title', '')}

{content_sample}

[Читать полную статью]({article_url})

Максимум 800 символов, только русский язык."""
    
    def _shorten_post(self, post: str) -> Optional[str]:
        """Пытается сократить пост до 1000 символов"""
        try:
            # Убираем менее важные части
            lines = post.split('\n')
            shortened_lines = []
            current_length = 0
            
            for line in lines:
                line_length = len(line)
                
                # Пропускаем пустые строки в конце
                if not line.strip() and current_length > 800:
                    continue
                
                # Если строка содержит запрещенные фразы - пропускаем
                forbidden_phrases = [
                    'почему это важно для русскоязычных жителей',
                    'практические советы:',
                    'берегите себя и своих близких',
                    'для получения дополнительной информации'
                ]
                
                if any(phrase in line.lower() for phrase in forbidden_phrases):
                    continue
                
                # Проверяем, не превысим ли лимит
                if current_length + line_length + 1 <= 1000:
                    shortened_lines.append(line)
                    current_length += line_length + 1
                else:
                    # Добавляем ссылку и завершаем
                    if current_length < 950:
                        shortened_lines.append(f"\n[Читать полную статью](#)")
                    break
            
            shortened_post = '\n'.join(shortened_lines)
            
            # Проверяем, что получилось
            if len(shortened_post) <= 1000:
                return shortened_post
            else:
                logging.warning(f"⚠️ Не удалось сократить пост до 1000 символов: {len(shortened_post)}")
                return None
                
        except Exception as e:
            logging.error(f"❌ Ошибка сокращения поста: {e}")
            return None
    
    def generate_posts_for_selected_articles(self, selected_articles: Dict[str, Dict[str, Any]], 
                                          base_url: str = "https://spain-que-pasa.com/news") -> Dict[str, str]:
        """Генерирует Telegram-посты для всех выбранных статей"""
        generated_posts = {}
        
        for article_id, article in selected_articles.items():
            try:
                # Генерируем URL для статьи
                slug = article.get('slug', '')
                if not slug:
                    # Если slug нет, создаем простой URL
                    article_url = f"{base_url}/{article_id}"
                else:
                    article_url = f"{base_url}/{slug}"
                
                # Генерируем пост
                post = self.generate_post(article, article_url)
                
                if post:
                    generated_posts[article_id] = post
                    logging.info(f"✅ Сгенерирован Telegram-пост для статьи {article_id}")
                else:
                    logging.error(f"❌ Не удалось сгенерировать Telegram-пост для статьи {article_id}")
                    
            except Exception as e:
                logging.error(f"Ошибка при генерации поста для статьи {article_id}: {e}")
                continue
        
        logging.info(f"Всего сгенерировано {len(generated_posts)} Telegram-постов из {len(selected_articles)} статей")
        return generated_posts
    
    def validate_post_quality(self, post: str) -> Dict[str, Any]:
        """Проверяет качество сгенерированного поста"""
        if NEW_PROMPT_AVAILABLE:
            # Используем новую валидацию v4.0
            return validate_telegram_post_v4(post)
        else:
            # Fallback валидация
            validation_result = {
                'score': 0,
                'level': 'неизвестно',
                'issues': [],
                'length': len(post),
                'has_emoji': bool(re.search(r'[🔥🚨🏥🏠🚗💰🎓🏖️]', post)),
                'has_bold': bool(re.search(r'\*\*.*?\*\*', post)),
                'has_list': bool(re.search(r'[•\-]\s', post)),
                'has_link': bool(re.search(r'https?://', post))
            }
            
            # Простая оценка
            score = 0
            
            # Длина
            if len(post) <= 1000:
                score += 30
            elif len(post) <= 1200:
                score += 20
            else:
                score += 10
            
            # Эмодзи
            if validation_result['has_emoji']:
                score += 20
            
            # Структура
            if '\n\n' in post:
                score += 20
            
            # Ссылки
            if validation_result['has_link']:
                score += 10
            
            # Форматирование
            if validation_result['has_bold'] or validation_result['has_list']:
                score += 20
            
            validation_result['score'] = score
            validation_result['max_score'] = 100
            
            # Уровень
            if score >= 80:
                validation_result['level'] = 'отличный'
            elif score >= 60:
                validation_result['level'] = 'хороший'
            elif score >= 40:
                validation_result['level'] = 'удовлетворительный'
            else:
                validation_result['level'] = 'требует доработки'
            
            return validation_result


def create_telegram_post_generator_v4():
    """Создает экземпляр обновленного генератора Telegram постов"""
    return TelegramPostGeneratorV4()


# Для обратной совместимости
def create_telegram_post_generator():
    """Создает экземпляр генератора Telegram постов (обновленная версия)"""
    return TelegramPostGeneratorV4()


if __name__ == "__main__":
    print("🚀 ОБНОВЛЕННЫЙ ГЕНЕРАТОР TELEGRAM ПОСТОВ V4.0 ГОТОВ!")
    print("Основные улучшения:")
    print("- Новый промпт v4.0 для устранения шаблонности")
    print("- Строгий контроль длины (до 1000 символов)")
    print("- Автоматическое сокращение длинных постов")
    print("- Валидация по новым стандартам")
    print("- Улучшенная обработка ошибок")



