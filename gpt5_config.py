# Конфигурация GPT-5-mini для системы генерации контента

# Модели OpenAI для разных задач
OPENAI_MODELS = {
    # Основные задачи генерации
    'generate_article': 'gpt-5-mini',           # Генерация статей
    'generate_telegram_post': 'gpt-5-mini',     # Генерация постов
    
    # Простые задачи (можно использовать GPT-5-nano)
    'filter_article': 'gpt-5-nano',             # Фильтрация новостей
    'cluster_batch': 'gpt-5-nano',              # Кластеризация
    'prioritize_clusters': 'gpt-5-nano',        # Приоритизация
    
    # Сложные задачи
    'complex_analysis': 'gpt-5',                 # Сложный анализ
    'creative_writing': 'gpt-5',                 # Творческое письмо
}

# Рекомендуемые параметры для GPT-5-mini
GPT5_MINI_PARAMS = {
    'temperature': 0.7,                          # Баланс креативности и точности
    'top_p': 0.9,                               # Разнообразие выбора
    'frequency_penalty': 0.1,                    # Снижение повторений
    'presence_penalty': 0.1,                     # Снижение повторений
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_tokens': 4000,                         # Увеличено для GPT-5-mini
    'temperature': 0.8,                          # Более креативно
    'top_p': 0.9,
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_tokens': 1000,                         # Оптимально для постов
    'temperature': 0.7,                          # Баланс
    'top_p': 0.9,
}

# Fallback модели (если GPT-5 недоступна)
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}
