# Обновленная конфигурация GPT-5-mini
# ВАЖНО: GPT-5-mini использует max_completion_tokens вместо max_tokens

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

# Параметры для GPT-5-mini (ВАЖНО: max_completion_tokens!)
GPT5_MINI_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 4000,              # НЕ max_tokens!
    'temperature': 0.7,                          # Баланс креативности
    'top_p': 0.9,                               # Разнообразие
    'frequency_penalty': 0.1,                    # Снижение повторений
    'presence_penalty': 0.1,                     # Снижение повторений
}

# Параметры для генерации статей
ARTICLE_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 5000,              # Увеличено для GPT-5-mini
    'temperature': 0.8,                          # Более креативно
    'top_p': 0.9,
}

# Параметры для генерации постов
POST_GENERATION_PARAMS = {
    'model': 'gpt-5-mini',
    'max_completion_tokens': 1000,              # Оптимально для постов
    'temperature': 0.7,                          # Баланс
    'top_p': 0.9,
}

# Fallback модели
FALLBACK_MODELS = {
    'gpt-5-mini': 'gpt-4o-mini',
    'gpt-5-nano': 'gpt-4o-mini',
    'gpt-5': 'gpt-4o',
}

# Пример использования:

# ПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_completion_tokens=4000,  # ✅ Правильно
    temperature=0.7
)

# НЕПРАВИЛЬНО для GPT-5-mini:
response = client.chat.completions.create(
    model="gpt-5-mini",
    messages=[...],
    max_tokens=4000,             # ❌ Ошибка!
    temperature=0.7
)
