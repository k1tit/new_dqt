import os
import sys
import argparse
import logging
from datetime import datetime, time
_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
try:
    from utils.sqlite_safe import resolve_database_path, load_database_config, DB_CONFIG_REL
except ImportError as _imp_err:
    print(f'[FATAL] Не удалось импортировать utils.sqlite_safe: {_imp_err}\n  Каталог проекта: {_PROJECT_ROOT}\n  Запускайте из папки data_quality_checker:\n    cd {_PROJECT_ROOT}\n    python main.py --help', flush=True)
    raise SystemExit(1) from _imp_err
DB_PATH, DB_SOURCE = resolve_database_path(_PROJECT_ROOT)
RULES_FILE = os.path.join(_PROJECT_ROOT, 'json files', 'rules.json')
MATERIAL_RULES_FILE = os.path.join(_PROJECT_ROOT, 'json files', 'material_rules.json')
OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'quality_reports')
MATERIAL_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'Material report')

try:
    from utils.report_profiles import REPORT_CHOICES, list_profiles_help, resolve_profile
except ImportError:
    REPORT_CHOICES = ('customer', 'material', 'all')

    def resolve_profile(project_root, profile_id):
        pid = str(profile_id or '').strip().lower()
        if pid == 'material':
            return {
                'id': 'material',
                'title': 'Material',
                'rules_file': os.path.join(project_root, 'json files', 'material_rules.json'),
                'output_dir': os.path.join(project_root, 'Material report'),
                'report_prefix': 'material_check_report',
            }
        if pid == 'customer':
            return {
                'id': 'customer',
                'title': 'Customer / Equipment',
                'rules_file': os.path.join(project_root, 'json files', 'rules.json'),
                'output_dir': os.path.join(project_root, 'quality_reports'),
                'report_prefix': 'quality_check_report',
            }
        raise ValueError(pid)

    def list_profiles_help():
        return 'customer | material | all'

def print_project_info():
    print('=' * 80)
    print('СИСТЕМА ПРОВЕРКИ КАЧЕСТВА ДАННЫХ')
    print('=' * 80)
    print(f'Версия: 2.0')
    try:
        from core.checker import FastDataQualityChecker
        print(f'Сборка checker: {FastDataQualityChecker.CHECKER_BUILD_ID}')
    except Exception:
        pass
    print(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print('-' * 80)

def setup_environment():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    print(f'Рабочая директория: {current_dir}')
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    required_dirs = ['core', 'utils', 'validators', 'table_scripts']
    for dir_name in required_dirs:
        dir_path = os.path.join(current_dir, dir_name)
        if os.path.exists(dir_path):
            files = [f for f in os.listdir(dir_path) if f.endswith('.py')]
            print(f'{dir_name}/: {len(files)} файлов')
        else:
            print(f'{dir_name}/: НЕ НАЙДЕН!')
    if os.path.isdir(os.path.join(current_dir, 'config')):
        print(f'config/: найден')
    print('-' * 80)
    required_files = [
        (DB_PATH, 'База данных SQLite'),
        (RULES_FILE, 'Правила Customer (rules.json)'),
        (MATERIAL_RULES_FILE, 'Правила Material (material_rules.json)'),
    ]
    for file_path, description in required_files:
        full_path = os.path.join(current_dir, file_path) if not os.path.isabs(file_path) else file_path
        if os.path.exists(full_path):
            size_kb = os.path.getsize(full_path) / 1024
            mtime = datetime.fromtimestamp(os.path.getmtime(full_path)).strftime('%Y-%m-%d %H:%M')
            extra = f', изменён {mtime}' if description.startswith('База данных') else ''
            print(f'{description}: {file_path} ({size_kb:.1f} KB{extra})')
            if description.startswith('База данных'):
                print(f'  Источник пути: {DB_SOURCE}')
                cfg = load_database_config(current_dir)
                if cfg.get('period'):
                    print(f"  Период в {DB_CONFIG_REL}: {cfg.get('period')}")
        else:
            print(f'{description}: {file_path} - НЕ НАЙДЕН!')
            if description.startswith('База данных'):
                print(f'  Укажите файл в config/database.json (поле database) или запуск: python main.py --db имя_файла.db')
    column_map_candidates = [os.path.join(current_dir, 'config', 'column_map.json'), os.path.join(current_dir, 'json files', 'column_map.json')]
    column_map_found = None
    for p in column_map_candidates:
        if os.path.exists(p):
            column_map_found = p
            break
    if column_map_found:
        size_kb = os.path.getsize(column_map_found) / 1024
        rel = os.path.relpath(column_map_found, current_dir)
        print(f'Файл маппинга колонок: {rel} ({size_kb:.1f} KB)')
    else:
        print(f'Файл маппинга колонок: не найден (искали config/column_map.json и json files/column_map.json), будет использоваться стандартный маппинг')
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    os.makedirs(MATERIAL_OUTPUT_DIR, exist_ok=True)
    print(f'Выходная директория (customer): {OUTPUT_DIR}')
    print(f'Выходная директория (material): {MATERIAL_OUTPUT_DIR}')
    return current_dir

def load_checker_module():
    print('\n' + '=' * 80)
    print('ИМПОРТ МОДУЛЕЙ')
    print('=' * 80)
    current_dir = os.path.dirname(os.path.abspath(__file__))
    checker_path = os.path.join(current_dir, 'core', 'checker.py')
    if not os.path.exists(checker_path):
        print(f'ФАТАЛЬНАЯ ОШИБКА: Файл {checker_path} не найден!')
        sys.exit(1)
    cache_dir = os.path.join(current_dir, 'core', '__pycache__')
    if os.path.isdir(cache_dir):
        for name in os.listdir(cache_dir):
            if name.startswith('checker.') and name.endswith('.pyc'):
                try:
                    os.remove(os.path.join(cache_dir, name))
                except OSError:
                    pass
    for mod in ('core.checker', 'core'):
        sys.modules.pop(mod, None)
    try:
        print('Загружаем core.checker...')
        if current_dir not in sys.path:
            sys.path.insert(0, current_dir)
        from core.checker import FastDataQualityChecker
        print('FastDataQualityChecker загружен успешно')
        return FastDataQualityChecker
    except Exception as e:
        print(f'ОШИБКА ЗАГРУЗКИ МОДУЛЯ: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        sys.exit(1)

def list_tables(checker):
    print('\n' + '=' * 80)
    print('ДОСТУПНЫЕ ТАБЛИЦЫ ДЛЯ ПРОВЕРКИ')
    print('=' * 80)
    tables = checker.list_available_tables()
    if tables:
        print(f'Всего таблиц: {len(tables)}')
        print('-' * 80)
        for i, table in enumerate(tables, 1):
            rules = checker.get_table_rules(table)
            print(f'{i:3d}. {table:25} - {len(rules):3d} правил')
        print('=' * 80)
    else:
        print('[!] Нет доступных таблиц для проверки')
    return tables

def _recreate_checker_from(checker):
    """Перезагрузить core/checker.py с диска и создать новый экземпляр (актуальный код)."""
    FastDataQualityChecker = load_checker_module()
    return FastDataQualityChecker(
        checker.db_path,
        checker.rules_file,
        checker.output_dir,
        parallel_tables=getattr(checker, 'parallel_tables', 0),
        use_async_load=getattr(checker, 'use_async_load', False),
        debug=getattr(checker, 'debug', False),
        reference_datetime=getattr(checker, 'reference_datetime', None),
        save_all_errors=getattr(checker, 'save_all_errors', False),
        use_parquet_cache=getattr(checker, 'use_parquet_cache', True),
        rebuild_parquet_cache=getattr(checker, 'rebuild_parquet_cache', False),
        report_prefix=getattr(checker, 'report_prefix', 'quality_check_report'),
    )


def build_checker(FastDataQualityChecker, profile: dict, *, parallel_tables=2, async_load=True, debug=False, reference_datetime=None, save_all_errors=False, parquet_cache=True, rebuild_parquet_cache=False):
    os.makedirs(profile['output_dir'], exist_ok=True)
    print(f"[REPORT] {profile.get('title', profile['id'])}")
    print(f"  rules:  {profile['rules_file']}")
    print(f"  output: {profile['output_dir']}")
    print(f"  db:     {DB_PATH}")
    return FastDataQualityChecker(
        DB_PATH,
        profile['rules_file'],
        profile['output_dir'],
        parallel_tables=parallel_tables,
        use_async_load=async_load,
        debug=debug,
        reference_datetime=reference_datetime,
        save_all_errors=save_all_errors,
        use_parquet_cache=parquet_cache,
        rebuild_parquet_cache=rebuild_parquet_cache,
        report_prefix=profile.get('report_prefix', 'quality_check_report'),
    )


def prompt_report_profile() -> str:
    """Интерактивный выбор: customer / material / all."""
    print('\n' + '=' * 80)
    print('ВЫБОР ОТЧЁТА')
    print('=' * 80)
    print(list_profiles_help())
    print('-' * 80)
    print('  [C] Customer / Equipment  (rules.json -> quality_reports)')
    print('  [M] Material              (material_rules.json -> Material report)')
    print('  [A] Все отчёты подряд     (одна БД)')
    print('-' * 80)
    while True:
        choice = input('Какой отчёт запустить? [C/M/A] (по умолчанию C): ').strip().upper()
        if choice in ('', 'C'):
            return 'customer'
        if choice == 'M':
            return 'material'
        if choice == 'A':
            return 'all'
        print('Введите C, M или A')

def _refresh_handlers_before_run(checker):
    if hasattr(checker, 'reload_table_handlers'):
        checker.reload_table_handlers()
    return _recreate_checker_from(checker)

def run_full_check(checker):
    print('\n' + '=' * 80)
    print('ЗАПУСК ПОЛНОЙ ПРОВЕРКИ ВСЕХ ТАБЛИЦ')
    print('=' * 80)
    start_time = datetime.now()
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    try:
        checker = _refresh_handlers_before_run(checker)
        checker.run()
    except Exception as e:
        print(f'ОШИБКА ВЫПОЛНЕНИЯ: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        return checker, False
    end_time = datetime.now()
    elapsed = end_time - start_time
    print('\n' + '=' * 80)
    print('ПРОВЕРКА ЗАВЕРШЕНА')
    print('=' * 80)
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    print(f"Конец:  {end_time.strftime('%H:%M:%S')}")
    print(f'Длительность: {elapsed}')
    return checker, True

def _parse_only_rule_codes(only_rules_arg) -> set | None:
    if not only_rules_arg:
        return None
    codes = {s.strip() for s in only_rules_arg.split(',') if s.strip()}
    return codes if codes else None

def parse_reference_date_string(s):
    if s is None or not str(s).strip():
        return None
    s = str(s).strip()
    for fmt in ('%Y-%m-%d', '%d.%m.%Y'):
        try:
            d = datetime.strptime(s, fmt).date()
            return datetime.combine(d, time(23, 59, 59))
        except ValueError:
            continue
    raise ValueError(f'Неверный формат даты: {s!r} (ожидается YYYY-MM-DD)')

def prompt_reference_datetime(checker):
    print('\nОпорная дата для расчётов «на дату» (например RCCONF_173.1 — срок с даты назначения блока):')
    print('  [Enter] — текущие дата и время компьютера')
    print('  или введите дату снимка данных: YYYY-MM-DD (учёт до конца этого дня)')
    try:
        s = input('> ').strip()
    except EOFError:
        s = ''
    if not s:
        checker.reference_datetime = None
        print('[INFO] Опорная дата: текущее время системы')
        return
    try:
        checker.reference_datetime = parse_reference_date_string(s)
        print(f'[INFO] Опорная дата (конец дня): {checker.reference_datetime}')
    except ValueError as e:
        print(f'[WARN] {e}. Используется текущее время системы.')
        checker.reference_datetime = None

def run_table_check(checker, table_name, only_rule_codes: set | None=None):
    print('\n' + '=' * 80)
    print(f'ЗАПУСК ПРОВЕРКИ ТАБЛИЦЫ: {table_name}')
    print('=' * 80)
    start_time = datetime.now()
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    try:
        rules = checker.get_table_rules(table_name)
        if not rules:
            print(f"ОШИБКА: Для таблицы '{table_name}' нет правил!")
            return checker, False
        print(f'Найдено правил: {len(rules)}')
        print('-' * 80)
        for i, rule in enumerate(rules, 1):
            rule_desc = rule.get('rule_description', 'Без описания')
            if len(rule_desc) > 50:
                rule_desc = rule_desc[:47] + '...'
            print(f"{i:3d}. {rule.get('rule_code', 'N/A'):15} - {rule_desc}")
        print('-' * 80)
        if only_rule_codes:
            print(f'Только правила: {sorted(only_rule_codes)}')
        print('Запускаем проверку...')
        checker = _refresh_handlers_before_run(checker)
        checker.run(specific_table=table_name, only_rule_codes=only_rule_codes)
    except Exception as e:
        print(f'[!] ОШИБКА ВЫПОЛНЕНИЯ: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        return checker, False
    end_time = datetime.now()
    elapsed = end_time - start_time
    print('\n' + '=' * 80)
    print(f'ПРОВЕРКА ТАБЛИЦЫ {table_name} ЗАВЕРШЕНА')
    print('=' * 80)
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    print(f"Конец:  {end_time.strftime('%H:%M:%S')}")
    print(f'Длительность: {elapsed}')
    return checker, True

def run_selected_tables_check(checker, table_names, only_rule_codes: set | None=None):
    print('\n' + '=' * 80)
    print(f'ЗАПУСК ПРОВЕРКИ ДЛЯ ВЫБРАННЫХ ТАБЛИЦ')
    print('=' * 80)
    print(f"Таблицы для проверки: {', '.join(table_names)}")
    print(f'Количество таблиц: {len(table_names)}')
    print('-' * 80)
    start_time = datetime.now()
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    try:
        checker = _refresh_handlers_before_run(checker)
        import inspect
        sig = inspect.signature(checker.run)
        if 'table_list' in sig.parameters:
            checker.run(table_list=table_names, only_rule_codes=only_rule_codes)
        else:
            for name in table_names:
                checker.run(specific_table=name, only_rule_codes=only_rule_codes)
    except Exception as e:
        print(f'ОШИБКА ВЫПОЛНЕНИЯ: {type(e).__name__}: {e}')
        import traceback
        traceback.print_exc()
        return checker, False
    end_time = datetime.now()
    elapsed = end_time - start_time
    print('\n' + '=' * 80)
    print(f'ПРОВЕРКА ВЫБРАННЫХ ТАБЛИЦ ЗАВЕРШЕНА')
    print('=' * 80)
    print(f"Начало: {start_time.strftime('%H:%M:%S')}")
    print(f"Конец:  {end_time.strftime('%H:%M:%S')}")
    print(f'Длительность: {elapsed}')
    return checker, True

def interactive_mode(checker, FastDataQualityChecker=None, checker_kwargs=None):
    print('\n' + '=' * 80)
    print('ИНТЕРАКТИВНЫЙ РЕЖИМ')
    print('=' * 80)
    checker_kwargs = checker_kwargs or {}
    while True:
        print('\nДоступные команды:')
        print('  [R] - Сменить тип отчёта (Customer / Material / All)')
        print('  [L] - Список таблиц (по текущим правилам)')
        print('  [F] - Полная проверка всех таблиц текущего отчёта')
        print('  [1] - Проверить таблицу по номеру')
        print('  [N] - Проверить таблицу по имени')
        print('  [M] - Проверить несколько таблиц')
        print('  [Q] - Выход')
        print(f"  Текущий отчёт: rules={os.path.basename(checker.rules_file)} -> {checker.output_dir}")
        print('  Перед проверкой F/1/N/M можно задать опорную дату для правил на дату (например RCCONF_173.1)')
        print('  (перед каждой проверкой core/checker.py и обработчики таблиц перезагружаются с диска)')
        print('-' * 80)
        choice = input('Выберите действие: ').strip().upper()
        if choice == 'Q':
            print('Выход из программы...')
            break
        elif choice == 'R':
            report_id = prompt_report_profile()
            if report_id == 'all':
                print('[INFO] Режим All: при [F] будут прогнаны оба отчёта подряд.')
                checker._run_all_reports = True
            else:
                checker._run_all_reports = False
                profile = resolve_profile(_PROJECT_ROOT, report_id)
                if FastDataQualityChecker is None:
                    FastDataQualityChecker = load_checker_module()
                checker = build_checker(FastDataQualityChecker, profile, **checker_kwargs)
        elif choice == 'L':
            list_tables(checker)
        elif choice == 'F':
            confirm = input('Запустить полную проверку? (y/N): ').strip().upper()
            if confirm == 'Y':
                prompt_reference_datetime(checker)
                if getattr(checker, '_run_all_reports', False) and FastDataQualityChecker is not None:
                    for pid in ('customer', 'material'):
                        profile = resolve_profile(_PROJECT_ROOT, pid)
                        c = build_checker(FastDataQualityChecker, profile, **{
                            **checker_kwargs,
                            'reference_datetime': getattr(checker, 'reference_datetime', None),
                        })
                        run_full_check(c)
                else:
                    checker, _ = run_full_check(checker)
        elif choice == '1':
            tables = list_tables(checker)
            if tables:
                try:
                    table_num = int(input('Введите номер таблицы: ').strip())
                    if 1 <= table_num <= len(tables):
                        table_name = tables[table_num - 1]
                        prompt_reference_datetime(checker)
                        checker, _ = run_table_check(checker, table_name)
                    else:
                        print(f'Неверный номер. Допустимый диапазон: 1-{len(tables)}')
                except ValueError:
                    print('Введите число!')
        elif choice == 'N':
            table_name = input('Введите имя таблицы: ').strip()
            if table_name:
                prompt_reference_datetime(checker)
                checker, _ = run_table_check(checker, table_name)
            else:
                print('Имя таблицы не может быть пустым!')
        elif choice == 'M':
            tables = list_tables(checker)
            if tables:
                print(f'\nВведите номера таблиц через пробел (например: 1 3 5):')
                try:
                    input_str = input('Номера таблиц: ').strip()
                    if input_str:
                        numbers = [int(n) for n in input_str.split()]
                        selected_tables = []
                        for num in numbers:
                            if 1 <= num <= len(tables):
                                selected_tables.append(tables[num - 1])
                            else:
                                print(f'Неверный номер {num}. Допустимый диапазон: 1-{len(tables)}')
                        if selected_tables:
                            prompt_reference_datetime(checker)
                            checker, _ = run_selected_tables_check(checker, selected_tables)
                        else:
                            print('Не выбрано ни одной таблицы!')
                except ValueError:
                    print('Введите числа через пробел!')
        else:
            print('Неизвестная команда. Попробуйте еще раз.')
    return checker

def parse_arguments():
    parser = argparse.ArgumentParser(description='Система проверки качества данных', formatter_class=argparse.RawDescriptionHelpFormatter, epilog='\nПримеры использования:\n  python main.py                    # Запуск в интерактивном режиме\n  python main.py --all              # Проверка всех таблиц\n  python main.py --all --async-load # Загрузка таблиц асинхронно (быстрее при многих таблицах)\n  python main.py --all --parallel-tables 4   # Параллельная обработка 4 таблиц\n  python main.py --table KNA1       # Проверка только таблицы KNA1\n  python main.py --table BUT000 --only-rules RCCONF_15.1  # Одна таблица + только эти правила\n  python main.py --table KNA1 --log-file kna1.log   # Логи KNA1 в файл\n  python main.py --table KNA1 --debug               # Подробные логи (DEBUG)\n  python main.py --tables KNA1 BUT000  # Проверка нескольких таблиц\n  python main.py --only-rules RCCOMP_375.1,RCCONF_39.5  # Только указанные правила (по всем таблицам)\n  python main.py --reference-date 2026-04-01  # Опорная дата для правил «на дату» (RCCONF_173.1 и др.)\n  python main.py --list             # Показать список таблиц\n  python main.py --help             # Показать эту справку\n\nСмена БД каждый месяц (одно место):\n  1) Положите новый файл, например db_may.db, в корень проекта\n  2) Отредактируйте config/database.json: "database": "db_may.db", "period": "2026-05"\n  Либо: set DQ_DATABASE=db_may.db  или  python main.py --all --db db_may.db\n        ')
    parser.add_argument(
        '--report',
        type=str,
        metavar='TYPE',
        default=None,
        choices=['customer', 'material', 'all'],
        help='Тип отчёта: customer (rules.json -> quality_reports), material (material_rules.json -> Material report), all (оба). Без флага — вопрос в консоли.',
    )
    parser.add_argument('--all', action='store_true', help='Запустить проверку всех таблиц')
    parser.add_argument('--table', type=str, metavar='TABLE_NAME', help='Проверить конкретную таблицу')
    parser.add_argument('--tables', type=str, nargs='+', metavar='TABLE', help='Проверить указанные таблицы (через пробел)')
    parser.add_argument('--list', action='store_true', help='Показать список доступных таблиц')
    parser.add_argument('--output', type=str, metavar='DIR', default=None, help='Переопределить директорию отчётов (иначе из профиля --report)')
    parser.add_argument('--db', type=str, metavar='PATH', default=None, help='Путь к SQLite (переопределяет config/database.json и DQ_DATABASE). По умолчанию — поле database в config/database.json')
    parser.add_argument('--rules', type=str, metavar='PATH', default=None, help='Переопределить файл правил (иначе из профиля --report)')
    parser.add_argument('--only-rules', type=str, metavar='RULE1,RULE2,...', default=None, help='Выполнить только указанные правила (изолированный запуск). Пример: --only-rules RCCOMP_375.1,RCCONF_39.5')
    parser.add_argument('--debug', action='store_true', help='Подробное логирование (DEBUG): checker, KNA1Handler и др.')
    parser.add_argument('--log-file', type=str, metavar='PATH', default=None, help='Дополнительно писать логи в файл (например, kna1.log при проверке KNA1)')
    parser.add_argument('--reference-date', type=str, metavar='YYYY-MM-DD', default=None, help='Опорная дата снимка данных для правил «на дату» (например RCCONF_173.1). Формат: YYYY-MM-DD или DD.MM.YYYY; конец этого календарного дня. Для архивных выгрузок обязательно укажите дату актуальности данных, иначе расчёт от «сегодня» исказит результат. Без параметра — текущее время компьютера.')
    parser.add_argument('--parallel-tables', type=int, default=2, metavar='N', help='Параллельная обработка таблиц (потоков). По умолчанию: 2. 0 = выкл.')
    parser.add_argument('--async-load', dest='async_load', action='store_true', default=True, help='Асинхронная загрузка таблиц в RAM (по умолчанию: вкл.)')
    parser.add_argument('--no-async-load', dest='async_load', action='store_false', help='Отключить async-load')
    parser.add_argument('--save-all-errors', action='store_true', default=False, help='Писать все строки ошибок без лимита 100k (старое поведение для ADR2/KNVP/…). По умолчанию: лимит.')
    parser.add_argument('--parquet-cache', dest='parquet_cache', action='store_true', default=True, help='Кэш таблиц в cache/parquet/ (по умолчанию: вкл., нужен pyarrow)')
    parser.add_argument('--no-parquet-cache', dest='parquet_cache', action='store_false', help='Отключить parquet-кэш, всегда читать SQLite')
    parser.add_argument('--rebuild-parquet-cache', action='store_true', default=False, help='Пересобрать parquet из SQLite (игнорировать старый кэш)')
    return parser.parse_args()

def main():
    args = parse_arguments()
    log_level = logging.DEBUG if args.debug else logging.INFO
    log_fmt = '%(levelname)s:%(name)s: %(message)s'
    logging.basicConfig(level=log_level, format=log_fmt, force=True)
    if getattr(args, 'log_file', None):
        log_path = args.log_file
        if not os.path.isabs(log_path):
            log_path = os.path.join(_PROJECT_ROOT, log_path)
        fh = logging.FileHandler(log_path, encoding='utf-8')
        fh.setFormatter(logging.Formatter(log_fmt))
        logging.getLogger().addHandler(fh)
        print(f'[LOG] Логи пишутся в файл: {os.path.abspath(log_path)}')
    global DB_PATH, DB_SOURCE, RULES_FILE, OUTPUT_DIR
    try:
        DB_PATH, DB_SOURCE = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    except FileNotFoundError as e:
        print(f'ОШИБКА: {e}')
        sys.exit(2)

    reference_dt = None
    if getattr(args, 'reference_date', None):
        try:
            reference_dt = parse_reference_date_string(args.reference_date)
        except ValueError as e:
            print(f'ОШИБКА: {e}')
            sys.exit(2)

    print_project_info()
    current_dir = setup_environment()
    FastDataQualityChecker = load_checker_module()

    # Выбор отчёта: CLI --report или вопрос в консоли
    report_id = getattr(args, 'report', None)
    if not report_id:
        if sys.stdin.isatty():
            report_id = prompt_report_profile()
        else:
            report_id = 'customer'
            print('[INFO] --report не задан, неинтерактивно -> customer')

    checker_kwargs = {
        'parallel_tables': getattr(args, 'parallel_tables', 2),
        'async_load': getattr(args, 'async_load', True),
        'debug': getattr(args, 'debug', False),
        'reference_datetime': reference_dt,
        'save_all_errors': getattr(args, 'save_all_errors', False),
        'parquet_cache': getattr(args, 'parquet_cache', True),
        'rebuild_parquet_cache': getattr(args, 'rebuild_parquet_cache', False),
    }

    def _make_profile_checker(pid: str):
        profile = resolve_profile(_PROJECT_ROOT, pid)
        if args.rules:
            profile['rules_file'] = args.rules if os.path.isabs(args.rules) else os.path.join(_PROJECT_ROOT, args.rules)
        if args.output:
            profile['output_dir'] = args.output if os.path.isabs(args.output) else os.path.join(_PROJECT_ROOT, args.output)
        return build_checker(FastDataQualityChecker, profile, **checker_kwargs)

    run_all_reports = report_id == 'all'
    try:
        if run_all_reports:
            # для list / table / interactive стартуем с customer; full --all прогонит оба
            checker = _make_profile_checker('customer')
            checker._run_all_reports = True
        else:
            checker = _make_profile_checker(report_id)
            checker._run_all_reports = False
    except Exception as e:
        print(f'ОШИБКА СОЗДАНИЯ CHECKER: {type(e).__name__}: {e}')
        sys.exit(1)

    RULES_FILE = checker.rules_file
    OUTPUT_DIR = checker.output_dir

    build_id = getattr(checker, 'CHECKER_BUILD_ID', '')
    print(f'[INFO] Активная сборка checker: {build_id}')
    if reference_dt:
        print(f'[INFO] Опорная дата для правил «на дату»: {reference_dt} (конец календарного дня)')
    else:
        print('[INFO] Опорная дата: не задана — для правил «на дату» используется текущее время системы')
        print('[WARN] Проверка старых выгрузок: без опорной даты возраст считается от «сегодня», а не от даты снимка. Итоги по RCCONF_173.1 и аналогам будут искажены. Задайте дату актуальности данных (--reference-date или ввод при запуске), совпадающую с датой/регламентом выгрузки.')
        cli_runs_check = bool(args.all or args.table or args.tables or getattr(args, 'only_rules', None))
        if cli_runs_check and sys.stdin.isatty():
            print('[INFO] Задать опорную дату сейчас (RCCONF_173.1 и др.)? Enter — оставить время системы; или введите дату ниже.')
            prompt_reference_datetime(checker)

    def _run_full_for_profiles():
        profiles = ('customer', 'material') if run_all_reports else (report_id,)
        last = checker
        for pid in profiles:
            c = _make_profile_checker(pid)
            c.reference_datetime = getattr(checker, 'reference_datetime', None)
            last, _ = run_full_check(c)
        return last

    if args.list:
        if run_all_reports:
            for pid in ('customer', 'material'):
                c = _make_profile_checker(pid)
                print(f"\n--- {pid} ---")
                list_tables(c)
        else:
            list_tables(checker)
    elif args.all:
        _run_full_for_profiles()
    elif args.table:
        if run_all_reports:
            print('[WARN] --table с --report all: правило/таблица только в текущем (customer) наборе; для material задайте --report material')
        run_table_check(checker, args.table, only_rule_codes=_parse_only_rule_codes(args.only_rules))
    elif args.tables:
        if run_all_reports:
            print('[WARN] --tables с --report all: только customer-профиль; для material: --report material')
        run_selected_tables_check(checker, args.tables, only_rule_codes=_parse_only_rule_codes(args.only_rules))
    elif getattr(args, 'only_rules', None):
        only_rules = [s.strip() for s in args.only_rules.split(',') if s.strip()]
        if only_rules:
            if run_all_reports:
                for pid in ('customer', 'material'):
                    c = _make_profile_checker(pid)
                    c.run(only_rule_codes=set(only_rules))
            else:
                checker.run(only_rule_codes=set(only_rules))
        else:
            print('Укажите хотя бы одно правило для --only-rules (через запятую).')
    elif not sys.stdin.isatty():
        print('\n[INFO] Запуск без аргументов в неинтерактивной среде. Укажите режим:\n'
              '  python main.py --report customer --all\n'
              '  python main.py --report material --all\n'
              '  python main.py --report all --all\n'
              '  python main.py --list --report customer\n'
              '  python main.py --help')
    else:
        interactive_mode(checker, FastDataQualityChecker=FastDataQualityChecker, checker_kwargs=checker_kwargs)
    print('\n' + '=' * 80)
    print('РАБОТА ПРОГРАММЫ ЗАВЕРШЕНА')
    print('=' * 80)
if __name__ == '__main__':
    print(f'[DQ] Запуск main.py ({_PROJECT_ROOT})', flush=True)
    try:
        main()
    except KeyboardInterrupt:
        print('\n\nПрограмма прервана пользователем.', flush=True)
        sys.exit(0)
    except Exception as e:
        print(f'\n[FATAL] НЕОБРАБОТАННАЯ ОШИБКА: {type(e).__name__}: {e}', flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)