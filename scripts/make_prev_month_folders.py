"""Папка прошлого месяца и пустые каталоги под выгрузки, которые должны быть в БД.

Имя папки — месяц латиницей: в ноябре это october.
Каталоги внутри — таблицы из rules.json и material_rules.json плюс join-зависимости.
Сюда не входят таблицы, которые прогон пишет сам (*_partners, adr2_rule_partners).

Папка не кладётся в db/: загрузчик считает каждую подпапку db/ отдельной таблицей.

  python scripts/make_prev_month_folders.py
  python scripts/make_prev_month_folders.py --parent D:\\dumps
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import date

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from scripts.report_required_tables import (  # noqa: E402
    DEFAULT_MATERIAL_RULES,
    DEFAULT_RULES,
    expand_dependencies,
    load_rules,
    primary_tables_from_rules,
)

_MONTHS = (
    'january', 'february', 'march', 'april', 'may', 'june',
    'july', 'august', 'september', 'october', 'november', 'december',
)
_INVALID_FOLDER = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_GENERATED_EXACT = frozenset({'ADR2_RULE_PARTNERS'})
_REFERENCE_EXTRACTS = ('T005', 'ZGLOBAL_CUSTOMER', 'ZTRADE_NAME')


def previous_month_name(today: date | None = None) -> str:
    current = today or date.today()
    return _MONTHS[current.month - 2]


def folder_name(table: str) -> str:
    raw = str(table or '').strip()
    compact = raw.upper().replace('/', '').replace('_', '')
    if compact == 'LOTGCADR':
        raw = 'LOTGC_ADR'
    cleaned = _INVALID_FOLDER.sub('_', raw).strip(' .')
    return cleaned


def is_generated(table: str) -> bool:
    name = str(table or '').strip().upper()
    return name in _GENERATED_EXACT or name.endswith('_PARTNERS')


def required_tables() -> list[str]:
    names: set[str] = set()
    for path in (DEFAULT_RULES, DEFAULT_MATERIAL_RULES):
        rules = load_rules(path)
        primary = primary_tables_from_rules(rules)
        codes: set[str] = set()
        for rule_codes in primary.values():
            codes.update(rule_codes)
        expanded = expand_dependencies(set(primary), codes)
        names.update(expanded)
    names.update(_REFERENCE_EXTRACTS)
    folders = {folder_name(name) for name in names if name and not is_generated(name)}
    folders.discard('')
    return sorted(folders, key=str.upper)


def create_month_tree(parent: str, today: date | None = None) -> tuple[str, list[str]]:
    month = previous_month_name(today)
    root = os.path.join(os.path.abspath(parent), month)
    os.makedirs(root, exist_ok=True)
    created = []
    for name in required_tables():
        path = os.path.join(root, name)
        os.makedirs(path, exist_ok=True)
        created.append(name)
    return root, created


def main() -> int:
    parser = argparse.ArgumentParser(description='Папка прошлого месяца с пустыми каталогами таблиц для БД')
    parser.add_argument(
        '--parent',
        default=os.path.join(_PROJECT_ROOT, 'incoming'),
        help='Куда положить папку месяца (по умолчанию incoming/ в корне проекта)',
    )
    args = parser.parse_args()
    parent = args.parent
    if not os.path.isabs(parent):
        parent = os.path.join(_PROJECT_ROOT, parent)
    root, created = create_month_tree(parent)
    print(f'Папка: {root}')
    print(f'Каталогов: {len(created)}')
    for name in created:
        print(f'  {name}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
