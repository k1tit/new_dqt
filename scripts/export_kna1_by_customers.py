import argparse
import os
import re
import sys
from datetime import datetime

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.sqlite_safe import connect_sqlite, resolve_database_path
from utils.column_map_resolver import apply_column_headers_for_rules, load_column_map, _table_mapping, _canonical_sap_name_for_column, _norm

DEFAULT_CUSTOMERS_FILE = os.path.join(os.path.dirname(__file__), 'kna1_customers_list.txt')
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
TABLE_NAME = 'KNA1'
CUSTOMER_CANDIDATES = ('Customer', 'KUNNR', 'CUSTOMER', 'customer_code', 'KUNNR_KNA1')
BATCH_SIZE = 400


def normalize_customer_id(value) -> str:
    if value is None:
        return ''
    s = str(value).strip()
    if not s or s.lower() in ('nan', 'none', 'null'):
        return ''
    if re.match(r'^\d+\.0+$', s):
        s = str(int(float(s)))
    digits = re.sub(r'\D+', '', s)
    if not digits:
        return ''
    if len(digits) >= 10:
        return digits[-10:].zfill(10)
    return digits.zfill(10)


def load_customer_ids(customers_file: str | None, stdin: bool, inline: list[str]) -> list[str]:
    raw_lines: list[str] = []
    if inline:
        raw_lines.extend(inline)
    if stdin:
        raw_lines.extend(sys.stdin.read().splitlines())
    if customers_file:
        path = customers_file if os.path.isabs(customers_file) else os.path.join(_PROJECT_ROOT, customers_file)
        if not os.path.isfile(path):
            raise FileNotFoundError(f'Файл со списком клиентов не найден: {path}')
        with open(path, encoding='utf-8') as f:
            raw_lines.extend(f.readlines())
    if not raw_lines:
        raise ValueError('Список клиентов пуст. Укажите --customers-file, --customer или --stdin.')
    seen: set[str] = set()
    ordered: list[str] = []
    for line in raw_lines:
        token = line.strip()
        if not token or token.startswith('#'):
            continue
        if ';' in token and not token.isdigit():
            token = token.split(';', 1)[0].strip()
        if ',' in token and not token.replace(',', '').isdigit():
            for part in token.split(','):
                cid = normalize_customer_id(part)
                if cid and cid not in seen:
                    seen.add(cid)
                    ordered.append(cid)
            continue
        cid = normalize_customer_id(token)
        if cid and cid not in seen:
            seen.add(cid)
            ordered.append(cid)
    return ordered


def resolve_kna1_customer_column(conn) -> str:
    cols = [row[1] for row in conn.execute('PRAGMA table_info(KNA1)').fetchall()]
    upper = {str(c).strip().upper(): c for c in cols}
    for cand in CUSTOMER_CANDIDATES:
        if cand.upper() in upper:
            return upper[cand.upper()]
    for c in cols:
        cu = str(c).strip().upper()
        if 'CUSTOMER' in cu or cu == 'KUNNR':
            return c
    raise RuntimeError(f'В KNA1 не найдена колонка клиента. Колонки: {cols[:20]}...')


def format_kna1_headers(df: pd.DataFrame, mode: str) -> pd.DataFrame:
    if df is None or df.empty or mode == 'raw':
        return df
    column_map = load_column_map(_PROJECT_ROOT)
    out = apply_column_headers_for_rules(df, TABLE_NAME, column_map, _PROJECT_ROOT, log_renames=False)
    if mode == 'both':
        return out
    tm = _table_mapping(column_map, TABLE_NAME) or {}
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


def fetch_kna1(conn, customer_col: str, customer_ids: list[str]) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    quoted_col = f'"{customer_col}"'
    for i in range(0, len(customer_ids), BATCH_SIZE):
        batch = customer_ids[i:i + BATCH_SIZE]
        placeholders = ','.join(['?'] * len(batch))
        query = f'SELECT * FROM KNA1 WHERE TRIM(CAST({quoted_col} AS TEXT)) IN ({placeholders})'
        part = pd.read_sql_query(query, conn, params=batch)
        if not part.empty:
            frames.append(part)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True).drop_duplicates()


def find_missing(customer_ids: list[str], df: pd.DataFrame, customer_col: str) -> list[str]:
    if df.empty:
        return list(customer_ids)
    found = {normalize_customer_id(v) for v in df[customer_col].tolist()}
    return [cid for cid in customer_ids if cid not in found]


def save_outputs(df: pd.DataFrame, output_base: str, fmt: str) -> list[str]:
    os.makedirs(os.path.dirname(output_base) or '.', exist_ok=True)
    saved: list[str] = []
    if fmt in ('csv', 'both'):
        csv_path = f'{output_base}.csv'
        df.to_csv(csv_path, index=False, encoding='utf-8-sig', sep=';')
        saved.append(csv_path)
    if fmt in ('xlsx', 'both'):
        xlsx_path = f'{output_base}.xlsx'
        df.to_excel(xlsx_path, index=False, engine='openpyxl')
        saved.append(xlsx_path)
    return saved


def parse_args():
    p = argparse.ArgumentParser(description='Выгрузка KNA1 из SQLite по списку номеров клиентов (Customer/KUNNR).')
    p.add_argument('--db', help='Путь к SQLite (по умолчанию config/database.json)')
    p.add_argument('--customers-file', default=DEFAULT_CUSTOMERS_FILE, help='Файл: один клиент на строку')
    p.add_argument('--customer', action='append', default=[], help='Один или несколько клиентов (можно повторять флаг)')
    p.add_argument('--stdin', action='store_true', help='Читать список клиентов из stdin')
    p.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Папка для результата')
    p.add_argument('--output-name', default='', help='Имя файла без расширения (по умолчанию kna1_export_<timestamp>)')
    p.add_argument('--format', choices=('csv', 'xlsx', 'both'), default='both', help='Формат выгрузки')
    p.add_argument('--headers', choices=('sap', 'raw', 'both'), default='sap', help='Шапка: sap (KUNNR/KTOKD/...), raw (как в БД), both (SAP + исходные)')
    p.add_argument('--missing-file', default='', help='Куда сохранить клиентов, не найденных в KNA1')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    use_file = not args.stdin and not args.customer
    customers_file = args.customers_file if use_file else None
    customer_ids = load_customer_ids(customers_file, args.stdin, args.customer)
    print(f'База: {db_path}')
    print(f'Источник БД: {db_source}')
    print(f'Клиентов в списке: {len(customer_ids):,}')
    conn = connect_sqlite(db_path)
    try:
        customer_col = resolve_kna1_customer_column(conn)
        print(f'Колонка клиента в KNA1: {customer_col}')
        df = fetch_kna1(conn, customer_col, customer_ids)
    finally:
        conn.close()
    missing = find_missing(customer_ids, df, customer_col)
    df = format_kna1_headers(df, args.headers)
    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    out_name = args.output_name.strip() or f'kna1_export_{ts}'
    output_base = os.path.join(args.output_dir if os.path.isabs(args.output_dir) else os.path.join(_PROJECT_ROOT, args.output_dir), out_name)
    saved = save_outputs(df, output_base, args.format) if not df.empty else []
    missing_path = args.missing_file.strip()
    if not missing_path:
        missing_path = f'{output_base}_missing.txt'
    elif not os.path.isabs(missing_path):
        missing_path = os.path.join(_PROJECT_ROOT, missing_path)
    if missing:
        os.makedirs(os.path.dirname(missing_path) or '.', exist_ok=True)
        with open(missing_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(missing) + '\n')
    print(f'Найдено в KNA1: {len(df):,} строк')
    print(f'Не найдено клиентов: {len(missing):,}')
    if saved:
        for path in saved:
            print(f'Сохранено: {path}')
    else:
        print('Данные KNA1 не найдены — файлы выгрузки не созданы.')
    if missing:
        print(f'Список отсутствующих: {missing_path}')
    return 0 if not missing else 2


if __name__ == '__main__':
    raise SystemExit(main())
