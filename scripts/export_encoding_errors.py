"""Выгрузка строк с испорченной кодировкой (mojibake) из таблицы SQLite.

Скрипт только читает данные. Значения в БД не изменяются: в выгрузку попадает
значение как есть, наиболее вероятный оригинал и цепочка кодировок, которая
привела к порче — этого достаточно для перезапроса выгрузки у владельца источника.

Детектор: utils.encoding_diagnostics (round-trip репар с проверкой на улучшение
метрик). Валидный не-ASCII текст (армянский, греческий, кириллица, `№`, `45µM`)
в выгрузку не попадает.

Примеры:
  python scripts/export_encoding_errors.py
  python scripts/export_encoding_errors.py --table MAKT --columns MAKTX --format xlsx
  python scripts/export_encoding_errors.py --table MARA --keys MATNR
  python scripts/export_encoding_errors.py --all-tables --out exports/encoding_all.csv
  python scripts/export_encoding_errors.py --fail-on-findings
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from typing import List, Optional, Sequence

import pandas as pd

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.encoding_diagnostics import inspect_frame
from utils.sqlite_safe import connect_sqlite, resolve_database_path

DEFAULT_TABLE = 'MAKT'
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
TEXT_AFFINITY = ('CHAR', 'CLOB', 'TEXT', '')
KEY_CANDIDATES = (
    'MANDT', 'MATNR', 'SPRAS', 'KUNNR', 'PARTNER', 'LIFNR',
    'ATINN', 'OBJEK', 'KLART', 'ADRNR', 'WERKS', 'BUKRS', 'VKORG',
)
MAX_KEY_COLUMNS = 6
FINDING_COLUMNS = (
    'value_as_delivered', 'suggested_original', 'codec_chain',
    'damaged_fragment', 'fragment_suggested', 'fragment_codepoints',
    'marker_score', 'script_transitions',
)


def list_tables(conn) -> List[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ).fetchall()
    return [str(r[0]) for r in rows]


def resolve_table_name(conn, table_name: str) -> Optional[str]:
    want = str(table_name or '').strip()
    if not want:
        return None
    tables = list_tables(conn)
    want_upper = want.upper()
    for name in tables:
        if name.strip().upper() == want_upper:
            return name
    want_norm = want_upper.replace('/', '').replace('_', '').replace(' ', '')
    for name in tables:
        if name.strip().upper().replace('/', '').replace('_', '').replace(' ', '') == want_norm:
            return name
    return None


def table_columns(conn, table: str) -> List[dict]:
    safe = table.replace('"', '')
    return [
        {'name': str(row[1]), 'type': str(row[2] or '').upper(), 'pk': int(row[5] or 0)}
        for row in conn.execute(f'PRAGMA table_info("{safe}")').fetchall()
    ]


def pick_text_columns(columns: Sequence[dict], requested: Optional[str]) -> List[str]:
    available = {c['name'].upper(): c['name'] for c in columns}
    if requested:
        chosen: List[str] = []
        missing: List[str] = []
        for raw in str(requested).split(','):
            name = raw.strip()
            if not name:
                continue
            actual = available.get(name.upper())
            if actual:
                chosen.append(actual)
            else:
                missing.append(name)
        if missing:
            print(f'[WARN] Колонки не найдены и пропущены: {", ".join(missing)}')
        return chosen
    return [
        c['name'] for c in columns
        if any(token in c['type'] for token in TEXT_AFFINITY if token) or not c['type']
    ]


def pick_key_columns(columns: Sequence[dict], requested: Optional[str]) -> List[str]:
    """Колонки-идентификаторы для выгрузки. Могут пересекаться с проверяемыми."""
    available = {c['name'].upper(): c['name'] for c in columns}
    if requested:
        return [available[raw.strip().upper()] for raw in str(requested).split(',')
                if raw.strip() and raw.strip().upper() in available]
    primary = [c['name'] for c in columns if c['pk'] > 0]
    if primary:
        return primary[:MAX_KEY_COLUMNS]
    return [available[name] for name in KEY_CANDIDATES if name in available][:MAX_KEY_COLUMNS]


def scan_table(
    conn,
    table: str,
    columns_requested: Optional[str],
    keys_requested: Optional[str],
    chunksize: int,
    max_rows: Optional[int],
    max_findings: int,
) -> tuple[List[dict], int]:
    columns = table_columns(conn, table)
    if not columns:
        print(f'[WARN] {table}: не удалось прочитать структуру, пропуск')
        return [], 0

    scanned = pick_text_columns(columns, columns_requested)
    if not scanned:
        print(f'[WARN] {table}: нет текстовых колонок для проверки, пропуск')
        return [], 0
    keys = pick_key_columns(columns, keys_requested)

    safe = table.replace('"', '')
    select_columns = ', '.join(f'"{c}"' for c in dict.fromkeys(list(keys) + list(scanned)))
    query = f'SELECT rowid AS _rowid, {select_columns} FROM "{safe}"'
    if max_rows:
        query += f' LIMIT {int(max_rows)}'

    print(f'[INFO] {table}: проверяем колонки {", ".join(scanned)}'
          + (f' | ключи: {", ".join(keys)}' if keys else ' | ключей не найдено'))

    findings: List[dict] = []
    total = 0
    try:
        reader = pd.read_sql_query(query, conn, chunksize=max(1000, int(chunksize)), dtype=str)
    except Exception as exc:
        print(f'[WARN] {table}: чтение не удалось ({exc}), пропуск')
        return [], 0

    for chunk in reader:
        total += len(chunk)
        found = inspect_frame(chunk, scanned, key_columns=['_rowid'] + keys, table=table)
        if found:
            findings.extend(found)
            if len(findings) >= max_findings:
                print(f'[WARN] {table}: достигнут лимит --max-findings ({max_findings}), сканирование прервано')
                findings = findings[:max_findings]
                break
        if total % (max(1000, int(chunksize)) * 10) == 0:
            print(f'[INFO] {table}: просмотрено {total:,} строк, находок {len(findings):,}')
    return findings, total


def build_frame(findings: Sequence[dict]) -> pd.DataFrame:
    df = pd.DataFrame(list(findings))
    if df.empty:
        return df
    lead = [c for c in ('table', '_rowid') if c in df.columns]
    keys = [c for c in df.columns if c not in lead and c != 'column' and c not in FINDING_COLUMNS]
    ordered = lead + keys + ['column'] + [c for c in FINDING_COLUMNS if c in df.columns]
    return df[[c for c in ordered if c in df.columns]]


def print_summary(df: pd.DataFrame, scanned_rows: int) -> None:
    print('-' * 78)
    print(f'[SUMMARY] просмотрено строк: {scanned_rows:,} | найдено испорченных значений: {len(df):,}')
    if df.empty:
        print('[SUMMARY] порчи кодировки не обнаружено')
        return
    print('[SUMMARY] по цепочкам кодировок:')
    for chain, count in df['codec_chain'].value_counts().items():
        print(f'    {chain}: {count:,}')
    if 'table' in df.columns and df['table'].nunique() > 1:
        print('[SUMMARY] по таблицам:')
        for table, count in df['table'].value_counts().items():
            print(f'    {table}: {count:,}')
    print('[SUMMARY] примеры:')
    for _, row in df.head(10).iterrows():
        print(f'    {row["value_as_delivered"]}')
        print(f'      -> {row["suggested_original"]}   [{row["codec_chain"]}]')


def save(df: pd.DataFrame, fmt: str, out: Optional[str], sep: str, table_label: str) -> str:
    if out:
        out_path = out if os.path.isabs(out) else os.path.join(_PROJECT_ROOT, out)
    else:
        stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        ext = 'xlsx' if fmt == 'xlsx' else 'csv'
        out_path = os.path.join(DEFAULT_OUTPUT_DIR, f'encoding_errors_{table_label}_{stamp}.{ext}')
    parent = os.path.dirname(out_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    if fmt == 'xlsx':
        df.to_excel(out_path, index=False, engine='openpyxl')
    else:
        df.to_csv(out_path, index=False, encoding='utf-8-sig', sep=sep)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Выгрузка строк с испорченной кодировкой (только чтение БД)',
    )
    parser.add_argument('--db', default=None, help='Путь к .db (по умолчанию config/database.json / DQ_DATABASE)')
    parser.add_argument('--table', '-t', default=DEFAULT_TABLE, help=f'Таблица (по умолчанию {DEFAULT_TABLE})')
    parser.add_argument('--all-tables', action='store_true', help='Проверить все таблицы БД (долго)')
    parser.add_argument('--columns', default=None, help='Колонки через запятую (по умолчанию все текстовые)')
    parser.add_argument('--keys', default=None, help='Колонки-ключи для выгрузки (по умолчанию PK / MATNR, SPRAS и др.)')
    parser.add_argument('--format', dest='fmt', choices=('csv', 'xlsx'), default='csv')
    parser.add_argument('--out', default=None, help='Путь выходного файла')
    parser.add_argument('--sep', default=';', help='Разделитель CSV (по умолчанию ;)')
    parser.add_argument('--chunksize', type=int, default=100_000, help='Строк в чанке (по умолчанию 100000)')
    parser.add_argument('--limit-rows', type=int, default=None, help='Проверить только первые N строк таблицы')
    parser.add_argument('--max-findings', type=int, default=200_000, help='Предохранитель на число находок')
    parser.add_argument('--fail-on-findings', action='store_true', help='Код возврата 2, если находки есть')
    args = parser.parse_args()

    try:
        db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    except FileNotFoundError as exc:
        print(f'[ERROR] {exc}')
        return 1

    print(f'[INFO] БД: {db_path} ({db_source})')
    conn = connect_sqlite(db_path, for_bulk_read=True)
    try:
        if args.all_tables:
            targets = list_tables(conn)
            label = 'all'
        else:
            resolved = resolve_table_name(conn, args.table)
            if not resolved:
                print(f'[ERROR] Таблица не найдена: {args.table}')
                print('[HINT] Доступные: ' + ', '.join(list_tables(conn)[:40]))
                return 1
            targets = [resolved]
            label = resolved.replace('/', '')
        if not targets:
            print('[INFO] В БД нет таблиц')
            return 0

        findings: List[dict] = []
        scanned_rows = 0
        budget = max(1, int(args.max_findings))
        for table in targets:
            found, total = scan_table(
                conn,
                table,
                args.columns,
                args.keys,
                args.chunksize,
                args.limit_rows,
                budget - len(findings),
            )
            findings.extend(found)
            scanned_rows += total
            if len(findings) >= budget:
                break
    finally:
        conn.close()

    df = build_frame(findings)
    print_summary(df, scanned_rows)
    if not df.empty:
        out_path = save(df, args.fmt, args.out, args.sep, label)
        print(f'[OK] Сохранено: {out_path} ({len(df):,} строк)')
        return 2 if args.fail_on_findings else 0
    print('[OK] Файл не создан: находок нет')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
