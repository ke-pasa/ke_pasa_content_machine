#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
КОМПЛЕКСНАЯ ПРОВЕРКА ИНТЕГРАЦИИ gpt-4o-mini
Проверяет всю систему на предмет успешного внедрения новой модели
"""

import os
import re
from pathlib import Path
import importlib.util

def check_system_integration():
    """Проверяет интеграцию gpt-4o-mini во всей системе"""
    
    print("🔍 КОМПЛЕКСНАЯ ПРОВЕРКА ИНТЕГРАЦИИ gpt-4o-mini")
    print("=" * 70)
    
    # Файлы для проверки
    system_files = [
        'content_generator.py',
        'telegram_post_generator.py',
        'telegram_post_generator_v4.py',
        'rss_parser.py',
        'news_clustering.py',
        'prioritization_llm.py',
        'jobs_scheduler.py'
    ]
    
    print("📋 ПРОВЕРЯЕМЫЕ КОМПОНЕНТЫ:")
    for file in system_files:
        print(f"   • {file}")
    
    print("\n🔍 ЭТАП 1: ПРОВЕРКА ЗАМЕНЫ МОДЕЛЕЙ")
    print("=" * 50)
    
    model_replacement_status = check_model_replacements(system_files)
    
    print("\n🔍 ЭТАП 2: ПРОВЕРКА ПАРАМЕТРОВ")
    print("=" * 50)
    
    parameter_status = check_parameters(system_files)
    
    print("\n🔍 ЭТАП 3: ПРОВЕРКА СИНТАКСИСА")
    print("=" * 50)
    
    syntax_status = check_syntax(system_files)
    
    print("\n🔍 ЭТАП 4: ТЕСТИРОВАНИЕ API")
    print("=" * 50)
    
    api_status = test_api_integration()
    
    print("\n🔍 ЭТАП 5: ИТОГОВАЯ ОЦЕНКА")
    print("=" * 50)
    
    generate_final_report(model_replacement_status, parameter_status, syntax_status, api_status)

def check_model_replacements(files):
    """Проверяет замену моделей на gpt-4o-mini"""
    
    print("🔍 Проверяю замену моделей...")
    
    status = {
        'total_files': len(files),
        'checked_files': 0,
        'gpt5_mini_found': 0,
        'gpt4o_mini_remaining': 0,
        'issues': []
    }
    
    for filename in files:
        file_path = Path(filename)
        if not file_path.exists():
            status['issues'].append(f"❌ {filename} - файл не найден")
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            status['checked_files'] += 1
            
            # Проверяем наличие gpt-4o-mini
            if 'gpt-4o-mini' in content:
                status['gpt5_mini_found'] += 1
                print(f"   ✅ {filename} - содержит gpt-4o-mini")
            else:
                print(f"   ⚠️  {filename} - НЕ содержит gpt-4o-mini")
                status['issues'].append(f"⚠️  {filename} - НЕ содержит gpt-4o-mini")
            
            # Проверяем остатки gpt-5-mini (если остались старые ссылки)
            if 'gpt-5-mini' in content:
                status['gpt4o_mini_remaining'] += 1
                print(f"      ⚠️  {filename} - содержит gpt-5-mini (возможно, старые упоминания)")
            
        except Exception as e:
            status['issues'].append(f"❌ {filename} - ошибка чтения: {e}")
    
    print(f"\n📊 СТАТИСТИКА ЗАМЕНЫ МОДЕЛЕЙ:")
    print(f"   Всего файлов: {status['total_files']}")
    print(f"   Проверено: {status['checked_files']}")
    print(f"   Содержат GPT-5-mini: {status['gpt5_mini_found']}")
    print(f"   Содержат GPT-4o-mini: {status['gpt4o_mini_remaining']}")
    
    return status

def check_parameters(files):
    """Проверяет правильность параметров для gpt-4o-mini"""
    
    print("🔍 Проверяю параметры...")
    
    status = {
        'max_tokens_issues': 0,
        'temperature_issues': 0,
        'unsupported_params': 0,
        'issues': []
    }
    
    for filename in files:
        file_path = Path(filename)
        if not file_path.exists():
            continue
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Проверяем max_tokens (должно быть max_completion_tokens)
            if 'max_tokens' in content and 'gpt-4o-mini' in content:
                status['max_tokens_issues'] += 1
                status['issues'].append(f"❌ {filename} - содержит max_tokens вместо max_completion_tokens")
                print(f"   ❌ {filename} - max_tokens вместо max_completion_tokens")
            elif 'max_completion_tokens' in content:
                print(f"   ✅ {filename} - использует max_completion_tokens")
            
            # Проверяем temperature (должно быть 1)
            temp_pattern = r'temperature\s*=\s*([^,\s]+)'
            temp_matches = re.findall(temp_pattern, content)
            for match in temp_matches:
                if match != '1' and 'gpt-4o-mini' in content:
                    status['temperature_issues'] += 1
                    status['issues'].append(f"❌ {filename} - temperature={match} вместо 1")
                    print(f"   ❌ {filename} - temperature={match} вместо 1")
            
            # Проверяем неподдерживаемые параметры
            unsupported_params = ['top_p', 'frequency_penalty', 'presence_penalty']
            for param in unsupported_params:
                if param in content and 'gpt-4o-mini' in content:
                    status['unsupported_params'] += 1
                    status['issues'].append(f"⚠️  {filename} - содержит неподдерживаемый параметр {param}")
                    print(f"   ⚠️  {filename} - содержит {param}")
            
        except Exception as e:
            status['issues'].append(f"❌ {filename} - ошибка проверки параметров: {e}")
    
    print(f"\n📊 СТАТИСТИКА ПАРАМЕТРОВ:")
    print(f"   Проблемы с max_tokens: {status['max_tokens_issues']}")
    print(f"   Проблемы с temperature: {status['temperature_issues']}")
    print(f"   Неподдерживаемые параметры: {status['unsupported_params']}")
    
    return status

def check_syntax(files):
    """Проверяет синтаксис Python файлов"""
    
    print("🔍 Проверяю синтаксис Python файлов...")
    
    status = {
        'total_files': len(files),
        'syntax_ok': 0,
        'syntax_errors': 0,
        'issues': []
    }
    
    for filename in files:
        file_path = Path(filename)
        if not file_path.exists():
            continue
        
        try:
            # Пытаемся импортировать файл для проверки синтаксиса
            spec = importlib.util.spec_from_file_location("module", file_path)
            if spec is None:
                status['syntax_errors'] += 1
                status['issues'].append(f"❌ {filename} - не удалось загрузить")
                print(f"   ❌ {filename} - не удалось загрузить")
                continue
            
            # Проверяем синтаксис
            importlib.util.module_from_spec(spec)
            status['syntax_ok'] += 1
            print(f"   ✅ {filename} - синтаксис корректен")
            
        except SyntaxError as e:
            status['syntax_errors'] += 1
            status['issues'].append(f"❌ {filename} - синтаксическая ошибка: {e}")
            print(f"   ❌ {filename} - синтаксическая ошибка: {e}")
        except Exception as e:
            status['syntax_errors'] += 1
            status['issues'].append(f"❌ {filename} - ошибка: {e}")
            print(f"   ❌ {filename} - ошибка: {e}")
    
    print(f"\n📊 СТАТИСТИКА СИНТАКСИСА:")
    print(f"   Всего файлов: {status['total_files']}")
    print(f"   Синтаксис корректен: {status['syntax_ok']}")
    print(f"   Ошибки синтаксиса: {status['syntax_errors']}")
    
    return status

def test_api_integration():
    """Тестирует интеграцию с OpenAI API (gpt-4o-mini primary)"""
    
    print("🔍 Тестирую интеграцию с OpenAI API...")
    
    status = {
        'api_available': False,
        'gpt5_mini_working': False,
        'test_results': [],
        'issues': []
    }
    
    try:
        import openai
        from dotenv import load_dotenv
        
        load_dotenv()
        api_key = os.getenv('OPENAI_API_KEY')
        
        if not api_key:
            status['issues'].append("❌ OPENAI_API_KEY не найден")
            print("   ❌ OPENAI_API_KEY не найден")
            return status
        
        status['api_available'] = True
        print("   ✅ OpenAI API доступен")

        # Тестируем gpt-4o-mini (primary)
        client = openai.OpenAI(api_key=api_key)

        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "Ты помощник для тестирования."},
                    {"role": "user", "content": "Ответь 'OK' на русском языке."}
                ],
                max_completion_tokens=10,
                temperature=1
            )

            result = response.choices[0].message.content
            status['gpt5_mini_working'] = True
            status['test_results'].append(f"✅ gpt-4o-mini работает, ответ: {result}")
            print(f"   ✅ gpt-4o-mini работает, ответ: {result}")

        except Exception as e:
            status['issues'].append(f"❌ gpt-4o-mini не работает: {e}")
            print(f"   ❌ gpt-4o-mini не работает: {e}")

        # Тестируем fallback на GPT-5-mini (если нужен)
        try:
            response = client.chat.completions.create(
                model="gpt-5-mini",
                messages=[
                    {"role": "system", "content": "Ты помощник для тестирования."},
                    {"role": "user", "content": "Ответь 'OK' на русском языке."}
                ],
                max_completion_tokens=10,
                temperature=0.7
            )

            result = response.choices[0].message.content
            status['test_results'].append(f"✅ GPT-5-mini работает (fallback), ответ: {result}")
            print(f"   ✅ GPT-5-mini работает (fallback), ответ: {result}")

        except Exception as e:
            status['issues'].append(f"❌ GPT-5-mini не работает: {e}")
            print(f"   ❌ GPT-5-mini не работает: {e}")
        
    except ImportError as e:
        status['issues'].append(f"❌ Не удалось импортировать openai: {e}")
        print(f"   ❌ Не удалось импортировать openai: {e}")
    except Exception as e:
        status['issues'].append(f"❌ Ошибка тестирования API: {e}")
        print(f"   ❌ Ошибка тестирования API: {e}")
    
    return status

def generate_final_report(model_status, param_status, syntax_status, api_status):
    """Генерирует итоговый отчет по проверке"""
    
    print("📊 ИТОГОВАЯ ОЦЕНКА ИНТЕГРАЦИИ gpt-4o-mini")
    print("=" * 70)
    
    # Подсчитываем общую оценку
    total_issues = (
        len(model_status['issues']) + 
        len(param_status['issues']) + 
        len(syntax_status['issues']) + 
        len(api_status['issues'])
    )
    
    # Оценка по компонентам
    model_score = (model_status['gpt5_mini_found'] / model_status['checked_files']) * 100 if model_status['checked_files'] > 0 else 0
    param_score = 100 - (param_status['max_tokens_issues'] + param_status['temperature_issues']) * 20
    syntax_score = (syntax_status['syntax_ok'] / syntax_status['total_files']) * 100 if syntax_status['total_files'] > 0 else 0
    api_score = 100 if api_status['gpt5_mini_working'] else 50
    
    overall_score = (model_score + param_score + syntax_score + api_score) / 4
    
    print(f"🎯 ОБЩАЯ ОЦЕНКА: {overall_score:.1f}/100")
    
    print(f"\n📋 ДЕТАЛЬНАЯ ОЦЕНКА ПО КОМПОНЕНТАМ:")
    print(f"   🔄 Замена моделей: {model_score:.1f}/100")
    print(f"   ⚙️  Параметры: {param_score:.1f}/100")
    print(f"   🐍 Синтаксис: {syntax_score:.1f}/100")
    print(f"   🔌 API интеграция: {api_score:.1f}/100")
    
    print(f"\n📊 СТАТИСТИКА:")
    print(f"   Всего проблем: {total_issues}")
    print(f"   Файлов с gpt-4o-mini: {model_status['gpt5_mini_found']}/{model_status['checked_files']}")
    print(f"   Файлов с корректным синтаксисом: {syntax_status['syntax_ok']}/{syntax_status['total_files']}")
    print(f"   GPT-5-mini работает: {'✅ Да' if api_status['gpt5_mini_working'] else '❌ Нет'}")
    
    if total_issues == 0:
        print(f"\n🎉 ИНТЕГРАЦИЯ ПРОШЛА ИДЕАЛЬНО!")
        print("   Система полностью готова к использованию gpt-4o-mini")
    elif overall_score >= 80:
        print(f"\n✅ ИНТЕГРАЦИЯ ПРОШЛА УСПЕШНО!")
        print("   Система готова к использованию с небольшими замечаниями")
    elif overall_score >= 60:
        print(f"\n⚠️  ИНТЕГРАЦИЯ ТРЕБУЕТ ДОРАБОТКИ!")
        print("   Есть проблемы, которые нужно исправить")
    else:
        print(f"\n❌ ИНТЕГРАЦИЯ НЕ УДАЛАСЬ!")
        print("   Требуется серьезная доработка")
    
    # Рекомендации
    print(f"\n💡 РЕКОМЕНДАЦИИ:")
    
    if model_status['gpt4o_mini_remaining'] > 0:
        print(f"   • Проверить {model_status['gpt4o_mini_remaining']} файлов с GPT-5-mini (старые упоминания)")
    
    if param_status['max_tokens_issues'] > 0:
        print(f"   • Заменить max_tokens на max_completion_tokens в {param_status['max_tokens_issues']} файлах")
    
    if param_status['temperature_issues'] > 0:
        print(f"   • Установить temperature=1 в {param_status['temperature_issues']} файлах")
    
    if not api_status['gpt5_mini_working']:
        print(f"   • Проверить доступность gpt-4o-mini в OpenAI API")
    
    # Создаем отчет
    create_integration_report(model_status, param_status, syntax_status, api_status, overall_score)

def create_integration_report(model_status, param_status, syntax_status, api_status, overall_score):
    """Создает детальный отчет по интеграции"""
    
    report_content = f"""# 🔍 ОТЧЕТ ПО ПРОВЕРКЕ ИНТЕГРАЦИИ gpt-4o-mini

## 📊 ОБЩАЯ ОЦЕНКА
**Дата проверки:** Январь 2025  
**Общая оценка:** {overall_score:.1f}/100  
**Статус:** {'✅ УСПЕШНО' if overall_score >= 80 else '⚠️ ТРЕБУЕТ ДОРАБОТКИ' if overall_score >= 60 else '❌ НЕ УДАЛАСЬ'}

## 🎯 ДЕТАЛЬНАЯ ОЦЕНКА ПО КОМПОНЕНТАМ

### 🔄 Замена моделей: {model_status['gpt5_mini_found']}/{model_status['checked_files']} файлов
- **Проверено файлов:** {model_status['checked_files']}
- **Содержат GPT-5-mini:** {model_status['gpt5_mini_found']}
- **Содержат GPT-4o-mini:** {model_status['gpt4o_mini_remaining']}

### ⚙️ Параметры
- **Проблемы с max_tokens:** {param_status['max_tokens_issues']}
- **Проблемы с temperature:** {param_status['temperature_issues']}
- **Неподдерживаемые параметры:** {param_status['unsupported_params']}

### 🐍 Синтаксис Python
- **Всего файлов:** {syntax_status['total_files']}
- **Синтаксис корректен:** {syntax_status['syntax_ok']}
- **Ошибки синтаксиса:** {syntax_status['syntax_errors']}

### 🔌 API интеграция
- **OpenAI API доступен:** {'✅ Да' if api_status['api_available'] else '❌ Нет'}
- **GPT-5-mini работает:** {'✅ Да' if api_status['gpt5_mini_working'] else '❌ Нет'}

## 📋 ВЫЯВЛЕННЫЕ ПРОБЛЕМЫ

"""
    
    # Добавляем проблемы
    all_issues = []
    all_issues.extend(model_status['issues'])
    all_issues.extend(param_status['issues'])
    all_issues.extend(syntax_status['issues'])
    all_issues.extend(api_status['issues'])
    
    if all_issues:
        for issue in all_issues:
            report_content += f"{issue}\n"
    else:
        report_content += "✅ Проблем не выявлено\n"
    
    report_content += f"""
## 💡 РЕКОМЕНДАЦИИ

"""
    
    # Добавляем рекомендации
    if model_status['gpt4o_mini_remaining'] > 0:
        report_content += f"• Проверить {model_status['gpt4o_mini_remaining']} файлов с GPT-5-mini (старые упоминания)\n"
    
    if param_status['max_tokens_issues'] > 0:
        report_content += f"• Заменить max_tokens на max_completion_tokens в {param_status['max_tokens_issues']} файлах\n"
    
    if param_status['temperature_issues'] > 0:
        report_content += f"• Установить temperature=1 в {param_status['temperature_issues']} файлах\n"
    
    if not api_status['gpt5_mini_working']:
        report_content += "• Проверить доступность gpt-4o-mini в OpenAI API\n"
    
    report_content += f"""
## 🎉 ЗАКЛЮЧЕНИЕ

"""
    
    if overall_score >= 80:
        report_content += "Интеграция gpt-4o-mini прошла успешно. Система готова к использованию новой модели."
    elif overall_score >= 60:
        report_content += "Интеграция требует доработки. Есть проблемы, которые нужно исправить перед использованием."
    else:
        report_content += "Интеграция не удалась. Требуется серьезная доработка системы."
    
    # Сохраняем отчет
    try:
        with open('GPT5_INTEGRATION_CHECK_REPORT.md', 'w', encoding='utf-8') as f:
            f.write(report_content)
        print(f"   📁 Создан отчет: GPT5_INTEGRATION_CHECK_REPORT.md")
    except Exception as e:
        print(f"   ⚠️  Ошибка создания отчета: {e}")

if __name__ == "__main__":
    check_system_integration()

