"""Сколько и какие таблицы нужны для прогона DQ-отчёта.

Читает rules.json и добавляет join/reference-зависимости так же,
как checker / memory_manager при загрузке.

Примеры:
  python scripts/report_required_tables.py
  python scripts/report_required_tables.py --out required_tables.txt
  python scripts/report_required_tables.py --tables V_EQUI JEST AUSP_EQUIPMENT
  python scripts/report_required_tables.py --only-rules RCCONF_342.1,RCCOMP_386.1
  python scripts/report_required_tables.py --db path/to.db --check-db
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import defaultdict

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

DEFAULT_RULES = os.path.join(_PROJECT_ROOT, 'json files', 'rules.json')

# Primary keys in rules.json that are equipment domain
EQUIPMENT_PRIMARY = frozenset({'V_EQUI', 'JEST', 'AUSP_EQUIPMENT'})

# Always pulled when any equipment primary is selected (dm_customer_equipment joins)
EQUIPMENT_DEPS = ('V_EQUI', 'JEST', 'AUSP_EQUIPMENT', 'TJ30T', 'INOB', 'KNA1')

# Soft deps by rule_code (needed for specific rules, not always auto-loaded)
RULE_EXTRA_TABLES: dict[str, tuple[str, ...]] = {
    'RCCONF_388.3': ('MAKT',),  # material_description vs EQKTX
    'RCCONF_143.7': ('TVBVK',),
    'RCCONF_119.2': ('KNVV',),
}

KNA1_DEPENDENT = frozenset({
    'BUT0BK', 'BUT051', 'KNB1', 'KNVV', 'KNVP', 'KNVH',
    'ADR2', 'ADR6', 'ADRC', 'BUT050',
    'AUSP', 'AUSP_143', 'AUSP_604', 'AUSP_148', 'AUSP_151',
    'LOTGC_ADR', '/LOT/GC_ADR', 'LOT_GC_ADR',
})

AUSP_CUSTOMER = frozenset({'AUSP', 'AUSP_143', 'AUSP_604', 'AUSP_148', 'AUSP_151'})
DFKK_ALIASES = frozenset({
    'DFKKBPTAXNUM', 'DFKKBPTAXNUM1', 'DFKKBPTAXNUM2', 'DFKKBPTAXNUM3',
    'DFKKBPTAXNUM4', 'DFKKBPTAXNUM5',
})
LOT_NAMES = frozenset({'/LOT/GC_ADR', 'LOTGC_ADR', 'LOT_GC_ADR'})


def _norm(t: str) -> str:
    return str(t or '').strip().upper()


def _is_active(rule: dict) -> bool:
    v = rule.get('is_active', 1)
    try:
        return int(v) == 1
    except (TypeError, ValueError):
        return str(v).strip().lower() in ('1', 'true', 'yes', 'y')


def _parse_only_rules(s: str | None) -> set[str] | None:
    if not s:
        return None
    out = set()
    for part in str(s).split(','):
        code = re.sub(r'[^A-Za-z0-9._-]', '', part.strip()).upper()
        if code:
            out.add(code)
    return out or None


def load_rules(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f'rules.json: ожидался object, got {type(data)}')
    return data


def primary_tables_from_rules(
    rules: dict,
    only_tables: set[str] | None = None,
    only_rules: set[str] | None = None,
) -> dict[str, list[str]]:
    """table -> [active rule_codes] after filters."""
    out: dict[str, list[str]] = {}
    for table, rows in rules.items():
        tu = _norm(table)
        if only_tables and tu not in only_tables:
            continue
        if not isinstance(rows, list):
            continue
        codes = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if not _is_active(r):
                continue
            code = re.sub(r'[^A-Za-z0-9._-]', '', str(r.get('rule_code') or '')).upper()
            if not code:
                continue
            if only_rules and code not in only_rules:
                continue
            codes.append(code)
        if codes:
            out[tu] = sorted(set(codes))
    return out


def expand_dependencies(primary: set[str], rule_codes: set[str]) -> dict[str, set[str]]:
    """
    Return {table: {reasons...}} — why each table is needed.
    Mirrors checker._expand_ausp_for_load + memory_manager._collect_tables_to_load (logical).
    """
    need: dict[str, set[str]] = defaultdict(set)

    for t in sorted(primary):
        need[t].add('primary (rules.json)')

    # Equipment cluster
    if primary & EQUIPMENT_PRIMARY:
        for t in EQUIPMENT_DEPS:
            need[t].add('equipment dm joins (V_EQUI/JEST/AUSP_EQUIPMENT → TJ30T, INOB, KNA1)')

    # Customer AUSP
    if primary & AUSP_CUSTOMER or 'AUSP' in primary:
        need['AUSP'].add('customer AUSP / derived')
        need['BUT000'].add('AUSP PARTNER_GUID → BUT000')
        need['KNA1'].add('AUSP → KNA1 scope')

    # DFKK
    if primary & DFKK_ALIASES or any(t.startswith('DFKKBPTAXNUM') for t in primary):
        need['DFKKBPTAXNUM'].add('taxnum base / aliases')

    # ADR* → BUT020 + KNA1
    if primary & {'ADRC', 'ADR2', 'ADR6'}:
        need['BUT020'].add('ADR* Addr.No. → PARTNER')
        need['KNA1'].add('ADR* customer scope')

    # LOT_GC_ADR
    if primary & LOT_NAMES or any(_norm(t).replace('/', '').replace('_', '') == 'LOTGCADR' for t in primary):
        need['BUT020'].add('LOT_GC_ADR ADRNR → BUT020')
        need['KNA1'].add('LOT_GC_ADR customer scope')

    # KNA1-dependent
    if primary & KNA1_DEPENDENT or 'KNA1' in primary or 'KNA1' in need:
        need['KNA1'].add('KNA1-dependent table / join')
        need['ZW2_CMDEMAND'].add('KNA1 reference (order block time / demand)')

    if 'KNA1' in primary:
        need['CDHDR'].add('KNA1 change docs (optional, RCCONF_173.1)')
        need['CDPOS'].add('KNA1 change docs (optional, RCCONF_173.1)')

    # Generic refs often added with add_reference_tables=True on full load
    # (document as soft when full report)
    # Per-rule extras
    for code in rule_codes:
        for t in RULE_EXTRA_TABLES.get(code, ()):
            need[_norm(t)].add(f'rule {code}')

    return dict(need)


def list_db_tables(db_path: str) -> set[str]:
    try:
        from utils.sqlite_safe import connect_sqlite
    except ImportError:
        import sqlite3
        connect_sqlite = None
    if connect_sqlite:
        conn = connect_sqlite(db_path)
    else:
        import sqlite3
        conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        return {_norm(r[0]) for r in rows}
    finally:
        conn.close()


def format_report(
    primary: dict[str, list[str]],
    expanded: dict[str, set[str]],
    *,
    db_tables: set[str] | None = None,
    rules_path: str,
    scope_note: str,
) -> str:
    lines: list[str] = []
    lines.append('=' * 72)
    lines.append('Таблицы для прогона DQ-отчёта')
    lines.append('=' * 72)
    lines.append(f'rules: {rules_path}')
    lines.append(f'scope: {scope_note}')
    lines.append('')

    n_primary = len(primary)
    n_rules = sum(len(v) for v in primary.values())
    lines.append(f'PRIMARY (есть активные правила): {n_primary} таблиц, {n_rules} правил')
    for t in sorted(primary):
        codes = primary[t]
        sample = ', '.join(codes[:5])
        more = f' …(+{len(codes) - 5})' if len(codes) > 5 else ''
        lines.append(f'  {t:24}  rules={len(codes):3d}  {sample}{more}')
    lines.append('')

    all_tables = sorted(expanded.keys())
    lines.append(f'ВСЕГО НУЖНО (primary + зависимости): {len(all_tables)} таблиц')
    for t in all_tables:
        reasons = sorted(expanded[t])
        mark = ''
        if db_tables is not None:
            mark = '  [OK in DB]' if t in db_tables else '  [MISSING in DB]'
        kind = 'PRIMARY' if t in primary else 'DEP'
        lines.append(f'  [{kind:7}] {t:24}{mark}')
        for r in reasons:
            lines.append(f'             ← {r}')
    lines.append('')

    if db_tables is not None:
        missing = [t for t in all_tables if t not in db_tables]
        present = [t for t in all_tables if t in db_tables]
        lines.append(f'В БД найдено: {len(present)} / {len(all_tables)}')
        if missing:
            lines.append('Отсутствуют в БД:')
            for t in missing:
                lines.append(f'  - {t}')
        else:
            lines.append('Все нужные таблицы есть в БД.')
        lines.append('')

    # compact copy-paste list
    lines.append('Список (для --tables / загрузки):')
    lines.append('  ' + ' '.join(all_tables))
    lines.append('')
    return '\n'.join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Список таблиц, нужных для прогона quality report',
    )
    parser.add_argument('--rules', default=DEFAULT_RULES, help='Путь к rules.json')
    parser.add_argument(
        '--tables',
        nargs='+',
        default=None,
        help='Ограничить primary-таблицами (как python main.py --tables …)',
    )
    parser.add_argument(
        '--only-rules',
        default=None,
        help='Только эти rule_code через запятую',
    )
    parser.add_argument(
        '--full-refs',
        action='store_true',
        help='Добавить soft refs полного прогона: T005, BUT020, KNVV (как add_reference_tables=True)',
    )
    parser.add_argument('--db', default=None, help='SQLite для --check-db')
    parser.add_argument(
        '--check-db',
        action='store_true',
        help='Сверить список с таблицами в SQLite',
    )
    parser.add_argument('--out', default=None, help='Записать отчёт в файл')
    args = parser.parse_args()

    rules_path = args.rules
    if not os.path.isabs(rules_path):
        rules_path = os.path.join(_PROJECT_ROOT, rules_path)
    if not os.path.isfile(rules_path):
        print(f'[ERROR] нет файла: {rules_path}', file=sys.stderr)
        return 1

    only_tables = {_norm(t) for t in args.tables} if args.tables else None
    only_rules = _parse_only_rules(args.only_rules)

    rules = load_rules(rules_path)
    primary = primary_tables_from_rules(rules, only_tables=only_tables, only_rules=only_rules)
    if not primary:
        print('[WARN] Нет primary-таблиц после фильтров (проверь --tables / --only-rules / is_active).')
        return 2

    rule_codes: set[str] = set()
    for codes in primary.values():
        rule_codes.update(codes)

    expanded = expand_dependencies(set(primary.keys()), rule_codes)

    if args.full_refs:
        for t in ('T005', 'BUT020', 'KNVV', 'ZW2_CMDEMAND'):
            expanded.setdefault(t, set()).add('full-load add_reference_tables')

    db_tables = None
    if args.check_db:
        db_path = args.db
        if not db_path:
            # try config / common names
            for cand in (
                os.path.join(_PROJECT_ROOT, 'db_june.db'),
                os.path.join(_PROJECT_ROOT, 'data', 'dq.db'),
                os.path.join(_PROJECT_ROOT, 'database.db'),
            ):
                if os.path.isfile(cand):
                    db_path = cand
                    break
        if not db_path or not os.path.isfile(db_path):
            print('[ERROR] --check-db: укажи существующий --db path', file=sys.stderr)
            return 1
        db_tables = list_db_tables(db_path)
        print(f'[INFO] DB: {db_path} ({len(db_tables)} tables)')

    if only_tables and only_rules:
        scope = f'tables={sorted(only_tables)}; rules={sorted(only_rules)}'
    elif only_tables:
        scope = f'tables={sorted(only_tables)}'
    elif only_rules:
        scope = f'rules={sorted(only_rules)}'
    else:
        scope = 'ALL active rules'

    text = format_report(
        primary,
        expanded,
        db_tables=db_tables,
        rules_path=rules_path,
        scope_note=scope,
    )
    print(text)
    if args.out:
        out_path = args.out
        if not os.path.isabs(out_path):
            out_path = os.path.join(_PROJECT_ROOT, out_path)
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(text)
        print(f'[INFO] записано: {out_path}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
