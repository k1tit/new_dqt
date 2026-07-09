from __future__ import annotations

import argparse
import json
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

from utils.sqlite_safe import connect_sqlite, resolve_database_path
from utils.column_map_resolver import (
    apply_column_headers_for_rules,
    load_column_map,
    resolve_column_in_df,
    _table_mapping,
    _canonical_sap_name_for_column,
    _norm,
)

_KNVV_STRUCTURE_CACHE: dict | None = None
HEADER_MODES_KNVV = ('raw', 'sap', 'both', 'structure')
HEADER_MODES_DEFAULT = ('raw', 'sap', 'both')


def list_tables(conn) -> list[str]:
    df = pd.read_sql_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
        conn,
    )
    return df['name'].tolist() if not df.empty else []


def table_row_count(conn, table_name: str) -> int:
    safe = table_name.replace('"', '')
    return int(pd.read_sql_query(f'SELECT COUNT(*) AS c FROM "{safe}"', conn)['c'].iloc[0])


def table_columns(conn, table_name: str) -> list[str]:
    df = pd.read_sql_query(f'PRAGMA table_info("{table_name}")', conn)
    return df['name'].astype(str).tolist() if not df.empty else []


def _load_knvv_structure() -> dict:
    global _KNVV_STRUCTURE_CACHE
    if _KNVV_STRUCTURE_CACHE is None:
        path = os.path.join(_PROJECT_ROOT, 'json files', 'knvv_sap_structure.json')
        with open(path, encoding='utf-8') as f:
            _KNVV_STRUCTURE_CACHE = json.load(f)
    return _KNVV_STRUCTURE_CACHE


def format_knvv_structure(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    cfg = _load_knvv_structure()
    order: list[str] = cfg.get('column_order') or []
    export_to_sap: dict[str, str] = cfg.get('export_to_sap') or {}
    column_map = load_column_map(_PROJECT_ROOT)
    sap_to_src: dict[str, str] = {}
    used_src: set[str] = set()
    for export_col, sap_field in export_to_sap.items():
        if export_col in df.columns and sap_field not in sap_to_src:
            sap_to_src[sap_field] = export_col
            used_src.add(export_col)
    for sap_field in order:
        if sap_field in sap_to_src:
            continue
        if sap_field in df.columns:
            sap_to_src[sap_field] = sap_field
            used_src.add(sap_field)
            continue
        src = resolve_column_in_df(df, sap_field, 'KNVV', column_map, _PROJECT_ROOT)
        if src and sap_field not in sap_to_src:
            sap_to_src[sap_field] = src
            used_src.add(src)
    series_map: dict[str, pd.Series] = {}
    for sap_field in order:
        src = sap_to_src.get(sap_field)
        if src:
            series_map[sap_field] = df[src]
    out = pd.DataFrame(series_map)
    ordered = [c for c in order if c in out.columns]
    out = out[ordered]
    tail = [c for c in df.columns if c not in used_src]
    if tail:
        out = pd.concat([out, df[tail]], axis=1)
    return out


def next_header_mode(current: str, table_name: str) -> str:
    table_u = str(table_name or '').strip().upper()
    if table_u == 'KNVV':
        cycle = {'raw': 'sap', 'sap': 'both', 'both': 'structure', 'structure': 'raw'}
    else:
        cycle = {'raw': 'sap', 'sap': 'both', 'both': 'raw', 'structure': 'raw'}
    return cycle.get(current, 'sap')


def header_modes_label(table_name: str) -> str:
    if str(table_name or '').strip().upper() == 'KNVV':
        return 'raw/sap/both/structure'
    return 'raw/sap/both'


def format_headers(df: pd.DataFrame, table_name: str, mode: str) -> pd.DataFrame:
    if df.empty or mode == 'raw':
        return df
    if mode == 'structure' and str(table_name or '').strip().upper() == 'KNVV':
        return format_knvv_structure(df)
    column_map = load_column_map(_PROJECT_ROOT)
    out = apply_column_headers_for_rules(df, table_name, column_map, _PROJECT_ROOT, log_renames=False)
    if mode == 'both':
        return out
    tm = _table_mapping(column_map, table_name) or {}
    cols = list(out.columns)
    drop: set[str] = set()
    alias = tm.get('_aliases') or {}
    for sap, names in alias.items():
        if sap not in cols:
            continue
        for name in names:
            n = str(name).strip()
            if n and n in cols and n != sap:
                drop.add(n)
    for logical, physical in tm.items():
        if str(logical).startswith('_'):
            continue
        phys = str(physical).strip()
        log = str(logical).strip()
        if phys in cols and log in cols and log != phys:
            drop.add(log)
    for col in cols:
        sap = _canonical_sap_name_for_column(col, tm)
        if sap and sap in cols and col != sap and _norm(col) != _norm(sap):
            drop.add(col)
    out = out.drop(columns=sorted(drop), errors='ignore')
    priority = [sap for sap in alias if sap in out.columns]
    for logical, physical in tm.items():
        if str(logical).startswith('_'):
            continue
        phys = str(physical).strip()
        if phys in out.columns and phys not in priority:
            priority.append(phys)
    tail = [c for c in out.columns if c not in priority]
    return out[priority + tail]


def configure_display(max_cols: int, width: int, colwidth: int) -> None:
    pd.set_option('display.max_columns', max_cols)
    pd.set_option('display.width', width)
    pd.set_option('display.max_colwidth', colwidth)
    pd.set_option('display.expand_frame_repr', False)


def print_table(df: pd.DataFrame, *, title: str, limit: int) -> None:
    print(f'\n{title}')
    if df.empty:
        print('(пусто)')
        return
    shown = len(df)
    total_cols = len(df.columns)
    print(f'Показано строк: {shown:,} | колонок: {total_cols}')
    print(df.to_string(index=False))


def show_table_info(conn, table_name: str) -> None:
    cols = table_columns(conn, table_name)
    print(f'\n{"=" * 72}')
    print(f'Таблица: {table_name}')
    try:
        print(f'Строк в БД: {table_row_count(conn, table_name):,}')
    except Exception as e:
        print(f'Строк в БД: не удалось посчитать ({e})')
    if cols:
        preview = ', '.join(cols[:18])
        extra = f' ... (+{len(cols) - 18})' if len(cols) > 18 else ''
        print(f'Колонки ({len(cols)}): {preview}{extra}')


def load_preview(conn, table_name: str, limit: int, offset: int = 0) -> pd.DataFrame:
    safe = table_name.replace('"', '')
    return pd.read_sql_query(
        f'SELECT * FROM "{safe}" LIMIT {int(limit)} OFFSET {int(offset)}',
        conn,
    )


def search_table(conn, table_name: str, column: str, value: str, limit: int) -> pd.DataFrame:
    cols = table_columns(conn, table_name)
    if column not in cols:
        raise ValueError(f"Колонка '{column}' не найдена")
    safe_val = value.replace("'", "''")
    safe_table = table_name.replace('"', '')
    q = f'''SELECT * FROM "{safe_table}" WHERE CAST("{column}" AS TEXT) LIKE '%{safe_val}%' LIMIT {int(limit)}'''
    return pd.read_sql_query(q, conn)


def resolve_table(tables: list[str], token: str) -> str | None:
    token = token.strip()
    if not token:
        return None
    if token.isdigit():
        idx = int(token)
        if 1 <= idx <= len(tables):
            return tables[idx - 1]
        return None
    upper = {t.upper(): t for t in tables}
    key = token.upper()
    if key in upper:
        return upper[key]
    matches = [t for t in tables if key in t.upper()]
    if len(matches) == 1:
        return matches[0]
    return None


def table_menu(conn, table_name: str, *, default_limit: int, headers: str, max_cols: int) -> None:
    offset = 0
    limit = default_limit
    while True:
        show_table_info(conn, table_name)
        df = load_preview(conn, table_name, limit, offset)
        df = format_headers(df, table_name, headers)
        configure_display(max_cols, 240, 40)
        print_table(df, title=f'Данные (offset={offset}, limit={limit})', limit=limit)
        print('\nКоманды:')
        print('  [Enter] — обновить')
        print('  [L]     — лимит строк')
        print('  [O]     — смещение (offset)')
        print('  [S]     — поиск по колонке')
        print(f'  [H]     — переключить шапку ({header_modes_label(table_name)})')
        print('  [B]     — назад к списку таблиц')
        cmd = input('Действие: ').strip().lower() or 'refresh'
        if cmd in ('b', 'back', '3'):
            return
        if cmd in ('', 'r', 'refresh'):
            continue
        if cmd in ('l', '1'):
            try:
                limit = max(1, int(input(f'Лимит строк [{limit}]: ').strip() or str(limit)))
            except ValueError:
                print('Введите число.')
            continue
        if cmd in ('o', 'offset', '2'):
            try:
                offset = max(0, int(input(f'Offset [{offset}]: ').strip() or str(offset)))
            except ValueError:
                print('Введите число.')
            continue
        if cmd in ('s', 'search'):
            col = input('Колонка: ').strip()
            val = input('Значение (подстрока): ').strip()
            if not col or not val:
                continue
            try:
                found = search_table(conn, table_name, col, val, limit)
                found = format_headers(found, table_name, headers)
                print_table(found, title=f"Поиск {col} LIKE '%{val}%'", limit=limit)
            except ValueError as e:
                print(f'Ошибка: {e}')
            continue
        if cmd in ('h', 'headers'):
            headers = next_header_mode(headers, table_name)
            print(f'Режим шапки: {headers}')
            continue
        print('Неизвестная команда.')


def interactive_loop(db_path: str, *, default_limit: int, headers: str, max_cols: int) -> None:
    print(f'Подключение: {db_path}')
    conn = connect_sqlite(db_path)
    headers_mode = headers
    try:
        while True:
            tables = list_tables(conn)
            if not tables:
                print('В базе нет пользовательских таблиц.')
                return
            print('\n' + '=' * 72)
            print('ТАБЛИЦЫ В БД')
            print('=' * 72)
            for i, name in enumerate(tables, 1):
                try:
                    n = table_row_count(conn, name)
                    print(f'  {i:3d}. {name:<32} {n:>12,} строк')
                except Exception:
                    print(f'  {i:3d}. {name}')
            print('\nВведите номер или имя таблицы (например KNA1).')
            print("Команды: [q] выход, [r] обновить список")
            token = input('\nВыбор: ').strip()
            if token.lower() in ('q', 'quit', 'exit'):
                break
            if token.lower() in ('r', 'refresh', ''):
                continue
            table_name = resolve_table(tables, token)
            if not table_name:
                print('Таблица не найдена. Укажите номер или точное имя.')
                continue
            table_menu(conn, table_name, default_limit=default_limit, headers=headers_mode, max_cols=max_cols)
    finally:
        conn.close()
    print('\nГотово.')


def parse_args():
    p = argparse.ArgumentParser(description='Просмотр таблиц SQLite в терминале (выбор из списка).')
    p.add_argument('--db', help='Путь к .db (по умолчанию config/database.json)')
    p.add_argument('--table', help='Сразу открыть таблицу без меню')
    p.add_argument('--limit', type=int, default=20, help='Строк на экран (по умолчанию 20)')
    p.add_argument('--offset', type=int, default=0, help='Смещение для --table')
    p.add_argument('--headers', choices=('raw', 'sap', 'both', 'structure'), default='sap', help='Шапка: sap, raw, both; для KNVV ещё structure (SAP DDIC)')
    p.add_argument('--max-cols', type=int, default=30, help='Макс. колонок в выводе')
    p.add_argument('-i', '--interactive', action='store_true', help='Интерактивный режим')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    try:
        db_path, source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    except FileNotFoundError as e:
        print(f'ОШИБКА: {e}')
        return 2
    print(f'Проект: {_PROJECT_ROOT}')
    print(f'БД ({source}): {db_path}')
    if args.table:
        conn = connect_sqlite(db_path)
        try:
            tables = list_tables(conn)
            table_name = resolve_table(tables, args.table) or args.table
            if table_name not in tables:
                print(f"Таблица '{args.table}' не найдена.")
                return 1
            show_table_info(conn, table_name)
            df = load_preview(conn, table_name, args.limit, args.offset)
            df = format_headers(df, table_name, args.headers)
            configure_display(args.max_cols, 240, 40)
            print_table(df, title='Данные', limit=args.limit)
        finally:
            conn.close()
        return 0
    if args.interactive or len(sys.argv) == 1:
        interactive_loop(db_path, default_limit=args.limit, headers=args.headers, max_cols=args.max_cols)
        return 0
    conn = connect_sqlite(db_path)
    try:
        tables = list_tables(conn)
        print('\nТаблицы:', ', '.join(tables[:30]) + (' ...' if len(tables) > 30 else ''))
        print('Интерактив: python scripts/view_table.py -i')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print('\nПрервано.')
        raise SystemExit(130)
