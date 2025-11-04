# ФИНАЛЬНАЯ КОНФИГУРАЦИЯ GPT-5-MINI
# ВАЖНО: Учитывает все ограничения модели

# Модели OpenAI для разных задач
OPENAI_MODELS = {
    # Основные задачи генерации
    'generate_article': 'gpt-5-mini',           # Генерация статей
    'generate_telegram_post': 'gpt-5-mini',     # Генерация постов
    
    # Простые задачи
    'filter_article': 'gpt-5-nano',             # Фильтрация новостей
    'cluster_batch': 'gpt-5-nano',              # Кластеризация
    'prioritize_clusters': 'gpt-5-nano',        # Приоритизация
    
    # Сложные задачи
    'complex_analysis': 'gpt-5',                 # Сложный анализ
    'creative_writing': 'gpt-5',                 # Творческое письмо
}

# Параметры для GPT-5-mini (УЧИТЫВАЕМ ОГРАНИЧЕНИЯ!)
GPT5_MINI_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 4000,              # ОБЯЗАТЕЛЬНО!
    'temperature': 1,                            # ТОЛЬКО 1 (фиксированное)
    'top_p': 0.9,                               # Поддерживается
    'frequency_penalty': 0.1,                    # Поддерживается
    'presence_penalty': 0.1,                     # Поддерживается
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 5000,              # Увеличено для GPT-5-mini
    'temperature': 1,                            # ТОЛЬКО 1
    'top_p': 0.9,                               # Для разнообразия
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 1000,              # Оптимально для постов
    'temperature': 1,                            # ТОЛЬКО 1
    'top_p': 0.9,                               # Для разнообразия
}

# Fallback модели
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}

# ПРАВИЛЬНОЕ ИСПОЛЬЗОВАНИЕ GPT-5-MINI:

# ✅ ПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_completion_tokens=4000,  # ОБЯЗАТЕЛЬНО
    temperature=1,                # ТОЛЬКО 1
    top_p=0.9,                   # Для разнообразия
    frequency_penalty=0.1,        # Снижение повторений
    presence_penalty=0.1          # Снижение повторений
)

# ❌ НЕПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_tokens=4000,             # Ошибка!
    temperature=0.7,              # Ошибка!
    top_p=0.9
)
