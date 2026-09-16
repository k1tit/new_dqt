"""Безопасное удаление таблиц из SQLite DQ.

Не трогает sqlite_* . Имена резолвятся только к таблицам из sqlite_master.
По умолчанию — dry-run. Реальное удаление: интерактивное подтверждение или --yes.

Примеры:
  python edit_table/drop_table.py --list
  python edit_table/drop_table.py --tables AUSP AUSP_143
  python edit_table/drop_table.py --tables AUSP --with-derived --yes
  python edit_table/drop_table.py --like DFKKBPTAXNUM% --dry-run
  python edit_table/drop_table.py --db db_august.db
"""
from __future__ import annotations

import argparse
import fnmatch
import os
import re
import sys

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass


def _bootstrap_dq_project() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    parent = os.path.dirname(here)
    for candidate in (parent, here):
        if os.path.isfile(os.path.join(candidate, 'utils', 'sqlite_safe.py')):
            if candidate not in sys.path:
                sys.path.insert(0, candidate)
            return candidate
    if parent not in sys.path:
        sys.path.insert(0, parent)
    return parent


_PROJECT_ROOT = _bootstrap_dq_project()
from utils.sqlite_safe import connect_sqlite, probe_db_writable, resolve_database_path

SQLITE_PREFIX = 'sqlite_'
AUSP_DERIVED = ('AUSP_143', 'AUSP_604', 'AUSP_148', 'AUSP_151')
DFKK_DERIVED = (
    'DFKKBPTAXNUM1',
    'DFKKBPTAXNUM2',
    'DFKKBPTAXNUM3',
    'DFKKBPTAXNUM4',
    'DFKKBPTAXNUM5',
    'DFKKBPTAXNUM6',
)
AUSP_EQUIPMENT_ALIASES = frozenset({
    'AUSP_EQUIPMENT',
    'AUSP_EQUIPMEN',
    'AUSP_EQUIPME',
    'AUSP_EQUIPM',
    'AUSP_EQUIP',
    'AUSP_EQPMNT',
    'AUSP_EQ',
})


def quote_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def is_sqlite_internal(name: str) -> bool:
    return str(name or '').strip().lower().startswith(SQLITE_PREFIX)


def list_user_tables(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def table_row_count(conn, table_name: str) -> int:
    cur = conn.execute(f'SELECT COUNT(*) FROM {quote_ident(table_name)}')
    return int(cur.fetchone()[0])


def _norm_key(name: str) -> str:
    return str(name or '').strip().upper().replace('/', '').replace('_', '').replace(' ', '').replace('-', '')


def resolve_table_name(existing: list[str], requested: str) -> str | None:
    want = str(requested or '').strip()
    if not want or is_sqlite_internal(want):
        return None
    want_u = want.upper()
    for name in existing:
        if str(name).strip().upper() == want_u:
            return name
    if want_u in AUSP_EQUIPMENT_ALIASES:
        for name in existing:
            if str(name).strip().upper() in AUSP_EQUIPMENT_ALIASES:
                return name
    want_n = _norm_key(want)
    hits = [name for name in existing if _norm_key(name) == want_n]
    if len(hits) == 1:
        return hits[0]
    return None


def match_like(existing: list[str], pattern: str) -> list[str]:
    pat = str(pattern or '').strip().replace('%', '*')
    if not pat:
        return []
    out = []
    for name in existing:
        if is_sqlite_internal(name):
            continue
        if fnmatch.fnmatch(name.upper(), pat.upper()):
            out.append(name)
    return out


def derived_for(table_name: str, existing: list[str]) -> list[str]:
    have = {str(n).strip().upper(): n for n in existing}
    key = str(table_name or '').strip().upper()
    extra: list[str] = []
    if key == 'AUSP':
        extra = [have[n] for n in AUSP_DERIVED if n in have]
    elif key == 'DFKKBPTAXNUM':
        extra = [have[n] for n in DFKK_DERIVED if n in have]
    elif key in AUSP_EQUIPMENT_ALIASES:
        extra = [have[n] for n in AUSP_EQUIPMENT_ALIASES if n in have and have[n] != table_name]
    return extra


def parquet_cache_path(project_root: str, db_path: str, table_name: str) -> str:
    stem = os.path.splitext(os.path.basename(db_path or 'db'))[0] or 'db'
    stem = re.sub(r'[^\w.\-]+', '_', stem)
    safe = re.sub(r'[^\w.\-]+', '_', str(table_name or 'table'))
    return os.path.join(project_root, 'cache', 'parquet', stem, f'{safe}.parquet')


def collect_targets(
    existing: list[str],
    names: list[str],
    like_patterns: list[str],
    with_derived: bool,
) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()

    def add(name: str) -> None:
        if name not in seen:
            seen.add(name)
            resolved.append(name)

    for raw in names:
        hit = resolve_table_name(existing, raw)
        if hit:
            add(hit)
        else:
            missing.append(raw)
    for pat in like_patterns:
        found = match_like(existing, pat)
        if not found:
            missing.append(pat)
            continue
        for hit in found:
            add(hit)
    if with_derived:
        base = list(resolved)
        for name in base:
            for extra in derived_for(name, existing):
                add(extra)
    return resolved, missing


def drop_tables(conn, tables: list[str]) -> list[str]:
    dropped: list[str] = []
    conn.execute('BEGIN IMMEDIATE')
    try:
        for name in tables:
            if is_sqlite_internal(name):
                raise ValueError(f'запрещено удалять системную таблицу: {name}')
            conn.execute(f'DROP TABLE IF EXISTS {quote_ident(name)}')
            dropped.append(name)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return dropped


def remove_parquet(project_root: str, db_path: str, tables: list[str]) -> list[str]:
    removed: list[str] = []
    for name in tables:
        path = parquet_cache_path(project_root, db_path, name)
        if os.path.isfile(path):
            os.remove(path)
            removed.append(path)
    return removed


def print_plan(conn, db_path: str, db_source: str, tables: list[str], dry_run: bool) -> None:
    print(f'БД: {os.path.abspath(db_path)}')
    print(f'Источник пути: {db_source}')
    mode = 'DRY-RUN (ничего не удалится)' if dry_run else 'УДАЛЕНИЕ'
    print(f'Режим: {mode}')
    print(f'Таблиц к удалению: {len(tables)}')
    for name in tables:
        try:
            n = table_row_count(conn, name)
            print(f'  - {name}  ({n:,} строк)')
        except Exception as e:
            print(f'  - {name}  (COUNT не удался: {e})')


def confirm_drop(tables: list[str], assume_yes: bool) -> bool:
    if assume_yes:
        return True
    expected = f'DROP {len(tables)} TABLES'
    print(f'\nДля подтверждения введите: {expected}')
    typed = input('> ').strip().upper()
    return typed == expected.upper()


def interactive_pick(existing: list[str], conn) -> list[str]:
    if not existing:
        print('В базе нет пользовательских таблиц.')
        return []
    print('\nТаблицы в БД:')
    for i, name in enumerate(existing, 1):
        try:
            n = table_row_count(conn, name)
            print(f'  {i:3d}. {name} ({n:,} строк)')
        except Exception:
            print(f'  {i:3d}. {name}')
    raw = input('\nНомера или имена через запятую (пусто = отмена): ').strip()
    if not raw:
        return []
    picked: list[str] = []
    seen: set[str] = set()
    for token in re.split(r'[,\s]+', raw):
        token = token.strip()
        if not token:
            continue
        if token.isdigit():
            idx = int(token)
            if 1 <= idx <= len(existing):
                name = existing[idx - 1]
            else:
                print(f'Пропуск номера {token}')
                continue
        else:
            name = resolve_table_name(existing, token)
            if not name:
                print(f'Не найдена таблица {token}')
                continue
        if name not in seen:
            seen.add(name)
            picked.append(name)
    if picked and any(t.upper() == 'AUSP' for t in picked):
        extra = derived_for('AUSP', existing)
        extra = [e for e in extra if e not in seen]
        if extra:
            ans = input(f'Добавить производные {", ".join(extra)}? [y/N]: ').strip().lower()
            if ans in ('y', 'yes', 'д', 'да'):
                picked.extend(extra)
    return picked


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description='Безопасное удаление таблиц SQLite (config/database.json).',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'CLI с --tables/--like без --yes = dry-run.\n'
            'Реальное удаление: --yes или интерактив + строка DROP N TABLES.\n'
            'sqlite_* не удаляются.'
        ),
    )
    p.add_argument('--db', default=None, help='Путь к .db (иначе config/database.json / DQ_DATABASE)')
    p.add_argument('--list', action='store_true', help='Показать таблицы и выйти')
    p.add_argument('--tables', nargs='+', default=[], metavar='NAME', help='Имена таблиц')
    p.add_argument('--like', nargs='+', default=[], metavar='PATTERN', help='Маска, например AUSP%% или DFKKBPTAXNUM*')
    p.add_argument('--with-derived', action='store_true', help='К AUSP добавить AUSP_143/604/148/151; к DFKKBPTAXNUM — 1..6')
    p.add_argument('--dry-run', action='store_true', help='Только план, без DROP')
    p.add_argument('--yes', action='store_true', help='Удалить без интерактивного подтверждения')
    p.add_argument('--vacuum', action='store_true', help='После DROP выполнить VACUUM (долго, переписывает файл БД)')
    p.add_argument('--keep-parquet', action='store_true', help='Не удалять parquet-кэш таблиц')
    return p.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    print(f'БД: {os.path.abspath(db_path)}  [{db_source}]')

    conn = connect_sqlite(db_path)
    try:
        existing = list_user_tables(conn)
        if args.list and not args.tables and not args.like:
            if not existing:
                print('Пользовательских таблиц нет.')
                return 0
            print(f'Таблиц: {len(existing)}')
            for name in existing:
                try:
                    n = table_row_count(conn, name)
                    print(f'  {name}  {n:,}')
                except Exception as e:
                    print(f'  {name}  ({e})')
            return 0

        if args.tables or args.like:
            targets, missing = collect_targets(existing, args.tables, args.like, args.with_derived)
            if missing:
                print('Не найдены / не совпали:')
                for item in missing:
                    print(f'  - {item}')
                if not targets:
                    return 2
        else:
            targets = interactive_pick(existing, conn)

        if not targets:
            print('Нечего удалять.')
            return 0

        cli_targets = bool(args.tables or args.like)
        if args.dry_run:
            dry_run = True
        elif args.yes:
            dry_run = False
        elif cli_targets:
            dry_run = True
        else:
            dry_run = False

        print_plan(conn, db_path, db_source, targets, dry_run)
        if dry_run:
            print('\nDry-run: таблицы не удалены. Для удаления добавьте --yes (CLI) или запустите без --tables и подтвердите DROP N TABLES.')
            return 0

        ok, err = probe_db_writable(db_path)
        if not ok:
            print(f'БД недоступна на запись: {err}')
            return 3
        if not confirm_drop(targets, args.yes):
            print('Отменено: подтверждение не совпало.')
            return 1

        dropped = drop_tables(conn, targets)
        print(f'Удалено таблиц: {len(dropped)}')
        for name in dropped:
            print(f'  DROP {name}')
        if not args.keep_parquet:
            removed = remove_parquet(_PROJECT_ROOT, db_path, dropped)
            for path in removed:
                print(f'  parquet cache: {path}')
        if args.vacuum:
            print('VACUUM...')
            conn.execute('VACUUM')
            print('VACUUM done')
        left = list_user_tables(conn)
        print(f'Осталось пользовательских таблиц: {len(left)}')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(run())
