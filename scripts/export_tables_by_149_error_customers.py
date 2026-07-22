"""Выгрузка таблиц из БД только по клиентам из ошибок RCCOMP_149.1 / 149.2.

По умолчанию — раздельно: подпапки RCCOMP_149_1 и RCCOMP_149_2.
Опция --rule combined — один общий список клиентов.

Примеры:
  python scripts/export_tables_by_149_error_customers.py
  python scripts/export_tables_by_149_error_customers.py --rule 149.1
  python scripts/export_tables_by_149_error_customers.py --rule combined
  python scripts/export_tables_by_149_error_customers.py --errors-dir quality_reports/errors_...
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
from datetime import datetime

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.sqlite_safe import connect_sqlite, resolve_database_path

DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
DEFAULT_REPORTS_DIR = os.path.join(_PROJECT_ROOT, 'quality_reports')
DEFAULT_TABLES = ('KNVP', 'KNA1', 'KNVV')
RULE_CODES = ('RCCOMP_149.1', 'RCCOMP_149.2')
CUSTOMER_COL_CANDIDATES = (
    'KUNNR', 'Customer', 'CUSTOMER', 'customer_code', 'Customer_1',
    '_cust_key', 'HgLvCust_', 'PARTNER',
)
BATCH_SIZE = 400


def normalize_customer_id(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    s = str(value).strip()
    if not s or s.lower() in ('nan', 'none', 'null', '<na>', 'nat'):
        return ''
    if re.match(r'^\d+\.0+$', s):
        s = str(int(float(s)))
    digits = re.sub(r'\D+', '', s)
    if not digits:
        return ''
    if len(digits) >= 10:
        return digits[-10:].zfill(10)
    return digits.zfill(10)


def customer_id_variants(cid: str) -> list[str]:
    n = normalize_customer_id(cid)
    if not n:
        return []
    out = [n]
    stripped = n.lstrip('0') or '0'
    if stripped not in out:
        out.append(stripped)
    return out


def _safe_read_table(path: str) -> pd.DataFrame:
    ext = os.path.splitext(path)[1].lower()
    if ext == '.csv':
        for sep in (';', ',', '\t'):
            try:
                df = pd.read_csv(path, sep=sep, dtype=str, encoding='utf-8-sig')
                if len(df.columns) > 1 or sep == ',':
                    return df
            except Exception:
                continue
        return pd.read_csv(path, dtype=str, encoding='utf-8-sig')
    if ext in ('.xlsx', '.xls'):
        return pd.read_excel(path, dtype=str)
    raise ValueError(f'Неподдерживаемый формат: {path}')


def find_customer_column(columns) -> str | None:
    upper = {str(c).strip().upper(): c for c in columns}
    for cand in CUSTOMER_COL_CANDIDATES:
        if cand.upper() in upper:
            return upper[cand.upper()]
    for c in columns:
        cu = str(c).strip().upper().replace(' ', '_')
        if cu in ('KUNNR', 'CUSTOMER', 'CUSTOMER_CODE', '_CUST_KEY') or cu.endswith('_KUNNR'):
            return c
    return None


def collect_customers_from_error_file(path: str) -> set[str]:
    df = _safe_read_table(path)
    if df is None or df.empty:
        return set()
    col = find_customer_column(df.columns)
    if not col:
        print(f'  [WARN] Нет колонки клиента в {os.path.basename(path)}: {list(df.columns)[:12]}...')
        return set()
    keys = {normalize_customer_id(v) for v in df[col].tolist()}
    keys.discard('')
    print(f'  {os.path.basename(path)}: колонка [{col}] → {len(keys):,} уникальных клиентов')
    return keys


def detect_rule_from_path(path: str) -> str | None:
    name = os.path.basename(path).upper()
    for rule in RULE_CODES:
        if rule.upper() in name:
            return rule
    return None


def find_149_error_files(
    errors_dir: str | None,
    reports_dir: str,
    explicit_files: list[str],
) -> dict[str, str]:
    """rule_code -> path to newest error file."""
    by_rule: dict[str, str] = {}

    for f in explicit_files or []:
        p = f if os.path.isabs(f) else os.path.join(_PROJECT_ROOT, f)
        if not os.path.isfile(p):
            print(f'  [WARN] Файл не найден: {p}')
            continue
        rule = detect_rule_from_path(p)
        if not rule:
            print(f'  [WARN] Не удалось определить правило (149.1/149.2) для: {p}')
            continue
        by_rule[rule] = p
        print(f'  {rule}: {p}')
    if by_rule and explicit_files:
        return by_rule

    search_roots: list[str] = []
    if errors_dir:
        d = errors_dir if os.path.isabs(errors_dir) else os.path.join(_PROJECT_ROOT, errors_dir)
        search_roots.append(d)
    else:
        pattern = os.path.join(reports_dir, 'errors_*')
        dirs = sorted(glob.glob(pattern), key=os.path.getmtime, reverse=True)
        if dirs:
            search_roots.append(dirs[0])
            print(f'Автовыбор папки ошибок: {dirs[0]}')
        else:
            search_roots.append(reports_dir)

    for root in search_roots:
        if not os.path.isdir(root):
            print(f'  [WARN] Папка не найдена: {root}')
            continue
        for rule in RULE_CODES:
            if rule in by_rule:
                continue
            matches = []
            for ext in ('*.csv', '*.xlsx', '*.xls'):
                matches.extend(glob.glob(os.path.join(root, f'{rule}_*{ext}')))
                matches.extend(glob.glob(os.path.join(root, '**', f'{rule}_*{ext}'), recursive=True))
            matches = sorted(set(matches), key=os.path.getmtime, reverse=True)
            if matches:
                by_rule[rule] = matches[0]
                print(f'  Найден {rule}: {matches[0]}')
            else:
                print(f'  [WARN] Нет файла ошибок для {rule} в {root}')
    return by_rule


def normalize_rule_arg(value: str) -> str:
    v = str(value or '').strip().upper().replace(' ', '')
    if v in ('BOTH', 'ALL', '149', 'SEPARATE'):
        return 'BOTH'
    if v in ('COMBINED', 'UNION', 'MERGE'):
        return 'COMBINED'
    if v in ('149.1', 'RCCOMP_149.1', '1'):
        return 'RCCOMP_149.1'
    if v in ('149.2', 'RCCOMP_149.2', '2'):
        return 'RCCOMP_149.2'
    raise ValueError(f'Неизвестный --rule: {value!r}. Ожидается 149.1 / 149.2 / both / combined')


def resolve_table_name(conn, table_name: str) -> str:
    want = str(table_name).strip().upper()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (name,) in rows:
        if str(name).strip().upper() == want:
            return name
    raise ValueError(f'Таблица {table_name} не найдена в БД')


def resolve_customer_column(conn, table_name: str) -> str:
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
    col = find_customer_column(cols)
    if col:
        return col
    raise RuntimeError(f'В {table_name} не найдена колонка клиента. Колонки: {cols[:25]}...')


def fetch_by_customers(conn, table_name: str, customer_col: str, customer_ids: list[str]) -> pd.DataFrame:
    if not customer_ids:
        return pd.DataFrame()
    variants: list[str] = []
    seen: set[str] = set()
    for cid in customer_ids:
        for v in customer_id_variants(cid):
            if v not in seen:
                seen.add(v)
                variants.append(v)

    frames: list[pd.DataFrame] = []
    quoted_col = f'"{customer_col}"'
    quoted_table = f'"{table_name}"'
    for i in range(0, len(variants), BATCH_SIZE):
        batch = variants[i:i + BATCH_SIZE]
        placeholders = ','.join(['?'] * len(batch))
        query = (
            f'SELECT * FROM {quoted_table} '
            f"WHERE TRIM(REPLACE(CAST({quoted_col} AS TEXT), char(160), '')) IN ({placeholders})"
        )
        part = pd.read_sql_query(query, conn, params=batch)
        if not part.empty:
            frames.append(part)

    if not frames:
        print(f'  [INFO] {table_name}: SQL IN не нашёл строк — fallback filter по нормализованному ключу')
        keys = set(customer_ids)
        df_all = pd.read_sql_query(f'SELECT * FROM {quoted_table}', conn)
        if df_all.empty:
            return df_all
        mask = df_all[customer_col].map(normalize_customer_id).isin(keys)
        return df_all.loc[mask].copy()

    out = pd.concat(frames, ignore_index=True)
    keys = set(customer_ids)
    mask = out[customer_col].map(normalize_customer_id).isin(keys)
    return out.loc[mask].drop_duplicates().copy()


def save_df(df: pd.DataFrame, output_base: str, fmt: str) -> list[str]:
    os.makedirs(os.path.dirname(output_base) or '.', exist_ok=True)
    saved: list[str] = []
    if fmt in ('csv', 'both'):
        path = f'{output_base}.csv'
        df.to_csv(path, index=False, encoding='utf-8-sig', sep=';')
        saved.append(path)
    if fmt in ('xlsx', 'both'):
        path = f'{output_base}.xlsx'
        if len(df) > 1_000_000:
            print(f'  [WARN] {len(df):,} строк > Excel limit — xlsx пропущен, используйте csv')
        else:
            df.to_excel(path, index=False, engine='openpyxl')
            saved.append(path)
    return saved


def export_for_customers(
    conn,
    tables: list[str],
    customer_ids: list[str],
    out_dir: str,
    fmt: str,
    label: str,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    list_path = os.path.join(out_dir, f'customers_{label}.txt')
    with open(list_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(customer_ids) + '\n')
    print(f'  Список клиентов ({len(customer_ids):,}): {list_path}')

    for table in tables:
        try:
            actual = resolve_table_name(conn, table)
            cust_col = resolve_customer_column(conn, actual)
            print(f'\n  [{label} / {table}] колонка клиента: {cust_col}')
            df = fetch_by_customers(conn, actual, cust_col, customer_ids)
            print(f'    строк выгружено: {len(df):,}')
            base = os.path.join(out_dir, f'{table}_by_{label}_error_customers')
            saved = save_df(df, base, fmt)
            for p in saved:
                print(f'    → {p}')
            if not df.empty:
                found = {normalize_customer_id(v) for v in df[cust_col].tolist()}
                found.discard('')
                missing = [c for c in customer_ids if c not in found]
                print(f'    клиентов в выгрузке: {len(found):,} / {len(customer_ids):,}')
                if missing:
                    miss_path = os.path.join(out_dir, f'{table}_missing_customers.txt')
                    with open(miss_path, 'w', encoding='utf-8') as mf:
                        mf.write('\n'.join(missing) + '\n')
                    print(f'    не найдено в {table}: {len(missing):,} → {miss_path}')
        except Exception as e:
            print(f'    [ERROR] {table}: {e}')


def parse_args():
    p = argparse.ArgumentParser(
        description='Выгрузка KNVP/KNA1/KNVV из БД по клиентам из ошибок RCCOMP_149.1 / 149.2'
    )
    p.add_argument('--db', default=None, help='Путь к .db (иначе config/database.json)')
    p.add_argument('--errors-dir', default=None, help='Папка errors_YYYY-... (иначе последняя в quality_reports)')
    p.add_argument('--error-file', action='append', default=[], help='Явный файл ошибок (можно несколько)')
    p.add_argument('--reports-dir', default=DEFAULT_REPORTS_DIR, help='Корень quality_reports')
    p.add_argument(
        '--rule',
        default='both',
        help='149.1 | 149.2 | both (раздельно, default) | combined (общий список)',
    )
    p.add_argument(
        '--tables',
        default=','.join(DEFAULT_TABLES),
        help=f'Таблицы через запятую (default: {",".join(DEFAULT_TABLES)})',
    )
    p.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Куда писать выгрузки')
    p.add_argument('--format', choices=('csv', 'xlsx', 'both'), default='csv', help='Формат файлов')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    print('=' * 72)
    print('Выгрузка таблиц по клиентам из ошибок RCCOMP_149.1 / 149.2')
    print('=' * 72)

    try:
        rule_mode = normalize_rule_arg(args.rule)
    except ValueError as e:
        print(f'ОШИБКА: {e}')
        return 1

    by_rule = find_149_error_files(args.errors_dir, args.reports_dir, args.error_file)
    if not by_rule:
        print('ОШИБКА: не найдены файлы ошибок 149.1/149.2. Укажите --errors-dir или --error-file')
        return 1

    if rule_mode in ('RCCOMP_149.1', 'RCCOMP_149.2'):
        if rule_mode not in by_rule:
            print(f'ОШИБКА: нет файла ошибок для {rule_mode}')
            return 1
        by_rule = {rule_mode: by_rule[rule_mode]}

    customers_by_rule: dict[str, list[str]] = {}
    for rule, path in by_rule.items():
        keys = collect_customers_from_error_file(path)
        customers_by_rule[rule] = sorted(keys)
        print(f'{rule}: {len(keys):,} клиентов')

    if not any(customers_by_rule.values()):
        print('ОШИБКА: в файлах ошибок нет клиентов')
        return 1

    db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    print(f'БД ({db_source}): {db_path}')

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    root_out = os.path.join(args.output_dir, f'rccomp_149_customers_{ts}')
    os.makedirs(root_out, exist_ok=True)
    tables = [t.strip().upper() for t in str(args.tables).split(',') if t.strip()]

    conn = connect_sqlite(db_path)
    try:
        if rule_mode == 'COMBINED':
            merged: set[str] = set()
            for ids in customers_by_rule.values():
                merged.update(ids)
            label = 'RCCOMP_149_combined'
            print(f'\n--- {label}: {len(merged):,} клиентов (объединение) ---')
            export_for_customers(conn, tables, sorted(merged), os.path.join(root_out, label), args.format, label)
        else:
            for rule, ids in customers_by_rule.items():
                if not ids:
                    print(f'\n--- {rule}: пусто, пропуск ---')
                    continue
                label = rule.replace('.', '_')
                print(f'\n=== {rule}: {len(ids):,} клиентов ===')
                export_for_customers(conn, tables, ids, os.path.join(root_out, label), args.format, label)
    finally:
        conn.close()

    print(f'\nГотово. Папка: {root_out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
