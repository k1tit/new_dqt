"""Подсчёт полностью пустых строк в таблице SQLite.

Строка считается пустой, если во всех ячейках пусто / NULL / none / nan / null
(та же логика, что utils.empty_rows.fully_empty_rows_mask).

Примеры:
  python scripts/count_empty_rows.py --table KNVP
  python scripts/count_empty_rows.py --table LOTGC_ADR --db db_june.db
  python scripts/count_empty_rows.py --all
"""
from __future__ import annotations

import argparse
import os
import sys

import pandas as pd

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.empty_rows import fully_empty_rows_mask
from utils.sqlite_safe import connect_sqlite, resolve_database_path


def list_tables(conn) -> list[str]:
    df = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        conn,
    )
    return df['name'].astype(str).tolist() if not df.empty else []


def resolve_table_name(conn, table_name: str) -> str | None:
    want = str(table_name or '').strip()
    if not want:
        return None
    tables = list_tables(conn)
    want_u = want.upper()
    for name in tables:
        if str(name).strip().upper() == want_u:
            return name
    # /LOT/GC_ADR ↔ LOTGC_ADR
    want_norm = want_u.replace('/', '').replace('_', '').replace(' ', '')
    for name in tables:
        n = str(name).strip().upper().replace('/', '').replace('_', '').replace(' ', '')
        if n == want_norm:
            return name
    return None


def count_empty_rows(conn, table_name: str, chunksize: int = 100_000) -> tuple[int, int]:
    """Возвращает (total_rows, empty_rows). Читает таблицу чанками."""
    safe = table_name.replace('"', '')
    total = 0
    empty = 0
    for chunk in pd.read_sql_query(f'SELECT * FROM "{safe}"', conn, chunksize=max(1000, int(chunksize))):
        total += len(chunk)
        if chunk.empty:
            continue
        empty += int(fully_empty_rows_mask(chunk).sum())
    return total, empty


def print_result(table_name: str, total: int, empty: int) -> None:
    if total == 0:
        print(f'{table_name}: таблица пуста (0 строк)')
        return
    if empty == 0:
        print(f'{table_name}: пустых строк нет (всего строк: {total:,})')
    else:
        print(f'{table_name}: полностью пустых строк: {empty:,} из {total:,}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Count fully empty rows in SQLite table(s)')
    parser.add_argument('--db', default=None, help='Path to .db (default: config/database.json)')
    parser.add_argument('--table', '-t', default=None, help='Table name (e.g. KNVP, LOTGC_ADR)')
    parser.add_argument('--all', action='store_true', help='Scan all tables in the database')
    parser.add_argument('--chunksize', type=int, default=100_000, help='Rows per chunk (default 100000)')
    args = parser.parse_args()

    if not args.table and not args.all:
        parser.error('Укажите --table NAME или --all')

    db_path = resolve_database_path(args.db, _PROJECT_ROOT)
    if not db_path or not os.path.isfile(db_path):
        print(f'[ERROR] БД не найдена: {db_path}')
        return 1

    print(f'[INFO] DB: {db_path}')
    conn = connect_sqlite(db_path)
    try:
        if args.all:
            tables = list_tables(conn)
            if not tables:
                print('[INFO] В БД нет таблиц')
                return 0
            print(f'[INFO] Таблиц: {len(tables)}')
            grand_empty = 0
            for name in tables:
                total, empty = count_empty_rows(conn, name, chunksize=args.chunksize)
                print_result(name, total, empty)
                grand_empty += empty
            if grand_empty == 0:
                print('[SUMMARY] Во всех таблицах пустых строк нет')
            else:
                print(f'[SUMMARY] Всего полностью пустых строк по БД: {grand_empty:,}')
            return 0

        resolved = resolve_table_name(conn, args.table)
        if not resolved:
            print(f'[ERROR] Таблица не найдена: {args.table}')
            print('[HINT] Доступные:', ', '.join(list_tables(conn)[:40]))
            return 1
        total, empty = count_empty_rows(conn, resolved, chunksize=args.chunksize)
        print_result(resolved, total, empty)
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
