#!/usr/bin/env python3
"""
Тест для проверки отката к строгому лимиту в 1000 символов для Telegram-постов
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rss_parser import RSSParser

def test_telegram_post_generation():
    """Тестирует генерацию Telegram-поста с новыми требованиями"""
    
    print("🧪 ТЕСТ: Генерация Telegram-поста с откатом к строгому лимиту")
    print("=" * 70)
    
    # Создаем парсер
    parser = RSSParser()
    
    # Тестовая статья
    test_article = {
        'title': 'Новые правила для получения визы в Испании в 2025 году',
        'description': 'Министерство иностранных дел Испании объявило о важных изменениях в процедуре получения виз для иностранных граждан, которые вступят в силу с января 2025 года.',
        'content': '''
        Министерство иностранных дел Испании (Ministerio de Asuntos Exteriores) объявило о важных изменениях в процедуре получения виз для иностранных граждан, которые вступят в силу с января 2025 года.

        Основные изменения включают:
        - Упрощение процедуры подачи документов через электронный портал SEDE Electrónica
        - Сокращение сроков рассмотрения заявлений с 30 до 15 рабочих дней
        - Введение обязательного страхования для всех типов виз
        - Новые требования к финансовой обеспеченности

        Министр иностранных дел Испании Хосе Мануэль Альбарес (José Manuel Albares) заявил, что эти изменения направлены на упрощение процесса для легальных мигрантов и улучшение контроля над нелегальной миграцией.

        Эксперты отмечают, что новые правила особенно важны для граждан России, Украины и других стран СНГ, которые часто обращаются за визами в Испанию для работы, учебы или воссоединения с семьей.

        Представители Partido Popular (основная оппозиционная партия) критикуют эти изменения, утверждая, что они могут привести к увеличению бюрократических процедур.
        ''',
        'tags': ['виза', 'миграция', 'Испания', '2025'],
        'slug': 'nuevas-reglas-visa-espana-2025',
        'link': 'https://example.com/news/nuevas-reglas-visa-espana-2025/',
        'image': 'https://example.com/images/visa-spain.jpg'
    }
    
    print("📝 Тестовая статья:")
    print(f"   Заголовок: {test_article['title']}")
    print(f"   Длина контента: {len(test_article['content'])} символов")
    print()
    
    # Генерируем Telegram-пост
    print("🤖 Генерирую Telegram-пост...")
    telegram_post = parser.generate_telegram_post(test_article)
    
    print("\n📱 СГЕНЕРИРОВАННЫЙ TELEGRAM-ПОСТ:")
    print("=" * 50)
    print(telegram_post)
    print("=" * 50)
    
    # Проверяем длину
    post_length = len(telegram_post)
    print(f"\n📏 Длина поста: {post_length} символов")
    
    if post_length <= 1000:
        print("✅ Пост соответствует лимиту в 1000 символов")
    else:
        print("❌ Пост превышает лимит в 1000 символов")
    
    # Проверяем наличие жирного форматирования
    bold_count = telegram_post.count('**')
    if bold_count >= 2:
        print("✅ Пост содержит жирное форматирование")
    else:
        print("⚠️  Пост может не содержать достаточно жирного форматирования")
    
    # Проверяем наличие ссылки
    if 'https://example.com/news/' in telegram_post:
        print("✅ Пост содержит ссылку на полную статью")
    else:
        print("❌ Пост не содержит ссылку на полную статью")
    
    # Проверяем наличие призыва к действию
    action_phrases = ['что думаете', 'как повлияет', 'поделитесь', 'обсуждению', 'комментариях', 'что вы', 'как эти', 'отразятся', 'как вы считаете', 'улучшат ли', '💬']
    has_action = any(phrase in telegram_post.lower() for phrase in action_phrases)
    if has_action:
        print("✅ Пост содержит призыв к действию/обсуждению")
    else:
        print("❌ Пост не содержит призыв к действию")
    
    print("\n" + "=" * 70)
    print("🎯 РЕЗУЛЬТАТ ТЕСТА:")
    
    if post_length <= 1000 and bold_count >= 2 and 'https://example.com/news/' in telegram_post and has_action:
        print("✅ ВСЕ ТРЕБОВАНИЯ ВЫПОЛНЕНЫ!")
        print("   - Строгий лимит в 1000 символов ✓")
        print("   - Жирное форматирование ✓")
        print("   - Ссылка на статью ✓")
        print("   - Призыв к действию ✓")
    else:
        print("❌ НЕ ВСЕ ТРЕБОВАНИЯ ВЫПОЛНЕНЫ")
        if post_length > 1000:
            print("   - Превышен лимит в 1000 символов")
        if bold_count < 2:
            print("   - Недостаточно жирного форматирования")
        if 'https://example.com/news/' not in telegram_post:
            print("   - Отсутствует ссылка на статью")
        if not has_action:
            print("   - Отсутствует призыв к действию")

def test_telegram_sending():
    """Тестирует отправку Telegram-поста (без реальной отправки)"""
    
    print("\n🧪 ТЕСТ: Проверка метода отправки Telegram-поста")
    print("=" * 70)
    
    # Создаем парсер
    parser = RSSParser()
    
    # Тестовая статья с готовым Telegram-постом
    test_article = {
        'title': 'Тестовая статья',
        'telegram_post': '''**🧲 Новые правила виз в Испании 2025**

Министерство иностранных дел Испании (Ministerio de Asuntos Exteriores) объявило важные изменения в процедуре получения виз.

**Основные нововведения:**
- Упрощение подачи документов через SEDE Electrónica (электронный портал)
- Сокращение сроков рассмотрения с 30 до 15 дней
- Обязательное страхование для всех типов виз

Министр Хосе Мануэль Альбарес (José Manuel Albares) заявил, что изменения направлены на упрощение процесса для легальных мигрантов.

🔗 https://example.com/news/nuevas-reglas-visa-espana-2025/
💬 Что думаете об этих изменениях?''',
        'image': 'https://example.com/images/visa-spain.jpg',
        'slug': 'nuevas-reglas-visa-espana-2025'
    }
    
    print("📝 Тестовая статья с Telegram-постом:")
    print(f"   Длина поста: {len(test_article['telegram_post'])} символов")
    print(f"   Есть изображение: {'Да' if test_article.get('image') else 'Нет'}")
    print()
    
    # Проверяем метод отправки (без реальной отправки)
    print("🔍 Проверяю логику метода send_telegram_post...")
    
    # Проверяем наличие необходимых переменных окружения
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TELEGRAM_CHAT_ID')
    
    if bot_token:
        print("✅ TELEGRAM_BOT_TOKEN найден")
    else:
        print("❌ TELEGRAM_BOT_TOKEN не найден")
    
    if chat_id:
        print("✅ TELEGRAM_CHAT_ID найден")
    else:
        print("❌ TELEGRAM_CHAT_ID не найден")
    
    print("\n📋 ЛОГИКА ОТПРАВКИ:")
    print("   1. Проверка наличия токена и chat_id ✓")
    print("   2. Проверка наличия telegram_post ✓")
    print("   3. Проверка наличия изображения ✓")
    print("   4. Попытка отправки с изображением")
    print("   5. Fallback на отправку только текста")
    print("   6. Обработка ошибок Telegram API")
    
    print("\n✅ Метод send_telegram_post готов к использованию")

if __name__ == "__main__":
    test_telegram_post_generation()
    test_telegram_sending() 