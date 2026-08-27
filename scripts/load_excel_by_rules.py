"""Загрузка Excel/CSV из обычной папки db/: подпапки + плоские файлы.

Примеры в db/:
  KNA1.xlsx, KNA1_1.xlsx     → таблица KNA1
  db/BUT000/*.xlsx           → как раньше
  V_EQUI.xlsx, JEST.xlsx

Сначала можно только посмотреть:
  python scripts/load_excel_by_rules.py --dry-run

Загрузка (то же, что пункт 3 меню add_table):
  python scripts/load_excel_by_rules.py
"""
from __future__ import annotations

import argparse
import os
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from edit_table.add_table import (  # noqa: E402
    collect_db_load_groups,
    default_rules_path,
    load_all_tables_from_db_folders,
    load_excel_matched_to_rules,
    _resolve_data_path,
    _resolve_db_path,
)


def main() -> int:
    parser = argparse.ArgumentParser(description='Load db/ dumps (folders + flat Excel) matched to rules into SQLite')
    parser.add_argument(
        '--folder',
        default=_resolve_data_path(),
        help='Папка выгрузок (по умолчанию db/)',
    )
    parser.add_argument('--rules', default=default_rules_path(), help='Путь к rules.json')
    parser.add_argument('--db', default=None, help='Путь к SQLite (по умолчанию из config)')
    parser.add_argument('--dry-run', action='store_true', help='Только показать, что будет загружено')
    parser.add_argument('--method', choices=('fast', 'ultra_fast'), default='fast')
    parser.add_argument('--skip-final-dedup', action='store_true')
    parser.add_argument(
        '--only',
        nargs='*',
        default=None,
        help='Ограничить список таблиц, напр. --only KNA1 V_EQUI JEST',
    )
    args = parser.parse_args()
    folder = args.folder
    if not os.path.isabs(folder):
        folder = os.path.join(_PROJECT_ROOT, folder)
    print(f'Проект: {_PROJECT_ROOT}')
    print(f'БД: {args.db or _resolve_db_path()}')
    print(f'Папка: {folder}')
    groups = collect_db_load_groups(folder, rules_path=args.rules)
    print('\nБудет загружено:')
    for table, info in sorted(groups.items(), key=lambda x: str(x[0]).upper()):
        if args.only and table not in args.only:
            continue
        n = len(info.get('files') or [])
        print(f'  {table}: {n} файл(ов)')
    load_excel_matched_to_rules(folder, rules_path=args.rules, dry_run=True)
    if args.dry_run:
        return 0
    results = load_all_tables_from_db_folders(
        db_path=args.db,
        base_folder=folder,
        method=args.method,
        skip_final_dedup=args.skip_final_dedup,
        only_tables=args.only,
    )
    return 0 if results else 1


if __name__ == '__main__':
    raise SystemExit(main())
