"""Выгрузка таблицы KNVP из SQLite в файл (по умолчанию до 20 000 строк).

Примеры:
  python scripts/export_knvp_sample.py
  python scripts/export_knvp_sample.py --limit 20000 --headers structure
  python scripts/export_knvp_sample.py --db db_june.db --format csv --out exports/knvp.csv
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.sqlite_safe import connect_sqlite, resolve_database_path
from utils.column_map_resolver import (
    apply_column_headers_for_rules,
    load_column_map,
    resolve_column_in_df,
    _table_mapping,
)

DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
TABLE_NAME = 'KNVP'
DEFAULT_LIMIT = 20000
KNVP_STRUCTURE_PATH = os.path.join(_PROJECT_ROOT, 'json files', 'knvp_sap_structure.json')


def _resolve_table_name(conn, table_name: str) -> str:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    want = str(table_name).strip().upper()
    for (name,) in rows:
        if str(name).strip().upper() == want:
            return name
    raise ValueError(f'Таблица {table_name} не найдена в БД')


def _format_structure(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    with open(KNVP_STRUCTURE_PATH, encoding='utf-8') as f:
        cfg = json.load(f)
    order = cfg.get('column_order') or []
    export_to_sap = cfg.get('export_to_sap') or {}
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
        src = resolve_column_in_df(df, sap_field, TABLE_NAME, column_map, _PROJECT_ROOT)
        if src and sap_field not in sap_to_src:
            sap_to_src[sap_field] = src
            used_src.add(src)
    series_map = {sap: df[src] for sap, src in ((s, sap_to_src.get(s)) for s in order) if src}
    out = pd.DataFrame(series_map)
    ordered = [c for c in order if c in out.columns]
    out = out[ordered]
    tail = [c for c in df.columns if c not in used_src]
    if tail:
        out = pd.concat([out, df[tail]], axis=1)
    return out


def _apply_headers(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if df.empty or mode == 'raw':
        return df
    if mode == 'structure':
        return _format_structure(df)
    column_map = load_column_map(_PROJECT_ROOT)
    out = apply_column_headers_for_rules(df, TABLE_NAME, column_map, _PROJECT_ROOT, log_renames=False)
    if mode == 'both':
        return out
    tm = _table_mapping(column_map, TABLE_NAME) or {}
    alias = tm.get('_aliases') or {}
    drop = set()
    for sap, names in alias.items():
        if sap not in out.columns:
            continue
        for name in names:
            n = str(name).strip()
            if n and n in out.columns and n != sap:
                drop.add(n)
    for logical, physical in tm.items():
        if str(logical).startswith('_'):
            continue
        phys = str(physical).strip()
        log = str(logical).strip()
        if phys in out.columns and log in out.columns and log != phys:
            drop.add(log)
    out = out.drop(columns=sorted(drop), errors='ignore')
    order = [c for c in (tm.get('_header_order') or []) if c in out.columns]
    rest = [c for c in out.columns if c not in order]
    return out[order + rest]


def export_knvp(
    db_path: str,
    *,
    limit: int = DEFAULT_LIMIT,
    headers: str = 'structure',
    fmt: str = 'csv',
    output: str | None = None,
) -> str:
    conn = connect_sqlite(db_path)
    try:
        actual = _resolve_table_name(conn, TABLE_NAME)
        total = int(conn.execute(f'SELECT COUNT(*) FROM "{actual}"').fetchone()[0])
        lim = max(0, int(limit))
        print(f'БД: {db_path}')
        print(f'Таблица: {actual} | всего строк: {total:,} | выгружаем: {min(lim, total):,}')
        df = pd.read_sql_query(f'SELECT * FROM "{actual}" LIMIT {lim}', conn)
    finally:
        conn.close()

    before_cols = list(df.columns)
    df = _apply_headers(df, headers)
    print(f'Шапка ({headers}): {len(before_cols)} → {len(df.columns)} колонок')
    print('Колонки: ' + ', '.join(map(str, df.columns[:20])) + (' ...' if len(df.columns) > 20 else ''))

    os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    if output:
        out_path = output if os.path.isabs(output) else os.path.join(_PROJECT_ROOT, output)
    else:
        ext = 'xlsx' if fmt == 'xlsx' else 'csv'
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, f'KNVP_sample_{lim}_{ts}.{ext}')

    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if fmt == 'xlsx':
        df.to_excel(out_path, index=False)
    else:
        df.to_csv(out_path, index=False, encoding='utf-8-sig')

    print(f'Сохранено: {out_path} ({len(df):,} строк)')
    return out_path


def main() -> None:
    p = argparse.ArgumentParser(description='Выгрузка sample KNVP из БД в файл')
    p.add_argument('--db', default=None, help='Путь к .db (по умолчанию из config/database.json / DQ_DATABASE)')
    p.add_argument('--limit', type=int, default=DEFAULT_LIMIT, help=f'Сколько строк выгрузить (default {DEFAULT_LIMIT})')
    p.add_argument(
        '--headers',
        choices=('raw', 'sap', 'both', 'structure'),
        default='structure',
        help='Шапка: raw / sap / both / structure (SAP DDIC)',
    )
    p.add_argument('--format', dest='fmt', choices=('csv', 'xlsx'), default='csv')
    p.add_argument('--out', default=None, help='Путь выходного файла')
    args = p.parse_args()

    db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=False)
    if not db_path or not os.path.isfile(db_path):
        raise SystemExit(f'БД не найдена: {db_path!r} (источник: {db_source}). Укажите --db или DQ_DATABASE / config/database.json')
    print(f'Источник БД: {db_source}')

    export_knvp(db_path, limit=args.limit, headers=args.headers, fmt=args.fmt, output=args.out)


if __name__ == '__main__':
    main()
