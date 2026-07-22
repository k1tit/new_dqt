"""Выгрузка ПОЛНЫХ строк таблиц из БД по клиентам из ошибок RCCOMP_149.1 / 149.2.

Не «список клиентов», а срезы таблиц (SELECT *), где KUNNR/Customer ∈ ошибки 149.
По умолчанию раздельно: подпапки RCCOMP_149_1 и RCCOMP_149_2.

Примеры:
  python scripts/export_tables_by_149_error_customers.py
  python scripts/export_tables_by_149_error_customers.py --tables KNVP --workers 3
  python scripts/export_tables_by_149_error_customers.py --workers 3 --parallel-rules
  python scripts/export_tables_by_149_error_customers.py --rule 149.1
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

import pandas as pd

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.sqlite_safe import (
    connect_sqlite,
    resolve_database_path,
    load_database_config,
    DB_CONFIG_REL,
)

DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
DEFAULT_REPORTS_DIR = os.path.join(_PROJECT_ROOT, 'quality_reports')
DEFAULT_TABLES = ('KNVP', 'KNA1', 'KNVV')
RULE_CODES = ('RCCOMP_149.1', 'RCCOMP_149.2')
CUSTOMER_COL_CANDIDATES = (
    'KUNNR', 'Customer', 'CUSTOMER', 'customer_code', 'Customer_1',
    '_cust_key', 'HgLvCust_', 'PARTNER',
)
BATCH_SIZE = 900  # SQLite лимит переменных ~999
DEFAULT_WORKERS = 3

try:
    from tqdm import tqdm as _tqdm  # type: ignore
except ImportError:
    _tqdm = None


class ProgressBar:
    """tqdm если установлен, иначе простой ASCII-бар в stderr."""

    def __init__(self, total: int, desc: str = '', unit: str = 'it'):
        self.total = max(0, int(total))
        self.desc = desc
        self.unit = unit
        self.n = 0
        self._bar = None
        if _tqdm is not None:
            self._bar = _tqdm(total=self.total, desc=desc, unit=unit, file=sys.stderr, leave=True)
        else:
            self._render()

    def update(self, n: int = 1) -> None:
        self.n = min(self.total, self.n + int(n))
        if self._bar is not None:
            self._bar.update(n)
        else:
            self._render()

    def set_description(self, desc: str) -> None:
        self.desc = desc
        if self._bar is not None:
            self._bar.set_description(desc)
        else:
            self._render()

    def close(self) -> None:
        if self._bar is not None:
            self._bar.close()
        else:
            sys.stderr.write('\n')
            sys.stderr.flush()

    def _render(self) -> None:
        width = 28
        if self.total <= 0:
            pct = 100.0
            filled = width
        else:
            pct = 100.0 * self.n / self.total
            filled = int(width * self.n / self.total)
        bar = '#' * filled + '-' * (width - filled)
        line = f'\r{self.desc}: |{bar}| {self.n}/{self.total} {self.unit} ({pct:5.1f}%)'
        sys.stderr.write(line)
        sys.stderr.flush()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


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


def build_customer_variants(customer_ids: list[str]) -> list[str]:
    variants: list[str] = []
    seen: set[str] = set()
    for cid in customer_ids:
        for v in customer_id_variants(cid):
            if v not in seen:
                seen.add(v)
                variants.append(v)
    return variants


def _open_export_conn(db_path: str):
    """Отдельное read-friendly соединение (для параллельных воркеров)."""
    conn = connect_sqlite(db_path)
    try:
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('PRAGMA cache_size=-262144')  # ~256MB
        conn.execute('PRAGMA mmap_size=268435456')
    except Exception:
        pass
    return conn


def _fill_temp_customer_keys(conn, variants: list[str], *, progress_desc: str = '') -> str:
    """Создаёт TEMP TABLE с ключами клиентов — один JOIN вместо сотен IN-запросов."""
    tmp = '_dq_export_cust_keys'
    conn.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    conn.execute(f'CREATE TEMP TABLE "{tmp}" (k TEXT PRIMARY KEY NOT NULL)')
    batches = list(range(0, len(variants), BATCH_SIZE))
    with ProgressBar(len(batches) or 1, desc=progress_desc or 'load keys', unit='batch') as bar:
        if not batches:
            bar.update(1)
        for i in batches:
            batch = variants[i:i + BATCH_SIZE]
            conn.executemany(f'INSERT OR IGNORE INTO "{tmp}"(k) VALUES (?)', [(v,) for v in batch])
            bar.update(1)
    conn.commit()
    return tmp


def fetch_by_customers(
    conn,
    table_name: str,
    customer_col: str,
    customer_ids: list[str],
    *,
    variants: list[str] | None = None,
    progress_desc: str = '',
) -> pd.DataFrame:
    if not customer_ids:
        return pd.DataFrame()
    variants = variants if variants is not None else build_customer_variants(customer_ids)
    keys = set(customer_ids)
    quoted_col = f'"{customer_col}"'
    quoted_table = f'"{table_name}"'
    desc = progress_desc or f'SQL {table_name}'

    t0 = time.perf_counter()
    tmp = _fill_temp_customer_keys(conn, variants, progress_desc=f'{desc} keys')

    # 1) быстрый путь: точное равенство текста (без TRIM на каждой строке таблицы)
    query_fast = (
        f'SELECT t.* FROM {quoted_table} AS t '
        f'INNER JOIN "{tmp}" AS c ON CAST(t.{quoted_col} AS TEXT) = c.k'
    )
    print(f'    [..] {table_name}: JOIN по ключам ({len(variants):,} вариантов)...', flush=True)
    out = pd.read_sql_query(query_fast, conn)
    elapsed = time.perf_counter() - t0
    print(f'    [..] {table_name}: JOIN за {elapsed:.1f}с → {len(out):,} строк', flush=True)

    if out.empty:
        # 2) медленный fallback: TRIM (если в БД мусорные пробелы) — один проход, не сотни IN
        print(f'    [INFO] {table_name}: точный JOIN пуст — fallback TRIM JOIN', flush=True)
        t1 = time.perf_counter()
        query_trim = (
            f'SELECT t.* FROM {quoted_table} AS t '
            f'INNER JOIN "{tmp}" AS c ON '
            f"TRIM(REPLACE(CAST(t.{quoted_col} AS TEXT), char(160), '')) = c.k"
        )
        out = pd.read_sql_query(query_trim, conn)
        print(
            f'    [..] {table_name}: TRIM JOIN за {time.perf_counter() - t1:.1f}с → {len(out):,} строк',
            flush=True,
        )

    try:
        conn.execute(f'DROP TABLE IF EXISTS "{tmp}"')
    except Exception:
        pass

    if out.empty:
        return out

    # финальная нормализация к каноническим id из ошибок
    mask = out[customer_col].map(normalize_customer_id).isin(keys)
    return out.loc[mask].drop_duplicates().copy()


def save_df(df: pd.DataFrame, output_base: str, fmt: str) -> list[str]:
    os.makedirs(os.path.dirname(output_base) or '.', exist_ok=True)
    saved: list[str] = []
    steps = []
    if fmt in ('csv', 'both'):
        steps.append('csv')
    if fmt in ('xlsx', 'both'):
        steps.append('xlsx')
    with ProgressBar(len(steps) or 1, desc=f'write {os.path.basename(output_base)}', unit='file') as bar:
        if fmt in ('csv', 'both'):
            path = f'{output_base}.csv'
            df.to_csv(path, index=False, encoding='utf-8-sig', sep=';')
            saved.append(path)
            bar.update(1)
        if fmt in ('xlsx', 'both'):
            path = f'{output_base}.xlsx'
            if len(df) > 1_000_000:
                print(f'  [WARN] {len(df):,} строк > Excel limit — xlsx пропущен, используйте csv')
            else:
                df.to_excel(path, index=False, engine='openpyxl')
                saved.append(path)
            bar.update(1)
    return saved


def _export_one_table(
    db_path: str,
    table: str,
    customer_ids: list[str],
    variants: list[str],
    out_dir: str,
    fmt: str,
    label: str,
) -> dict:
    """Воркер: своё соединение → выгрузка одной таблицы."""
    t0 = time.perf_counter()
    conn = _open_export_conn(db_path)
    try:
        actual = resolve_table_name(conn, table)
        cust_col = resolve_customer_column(conn, actual)
        df = fetch_by_customers(
            conn, actual, cust_col, customer_ids,
            variants=variants,
            progress_desc=f'{label}/{table}',
        )
        base = os.path.join(out_dir, f'{table}_rows_for_{label}_error_customers')
        saved = save_df(df, base, fmt)
        found = set()
        missing: list[str] = []
        if not df.empty:
            found = {normalize_customer_id(v) for v in df[cust_col].tolist()}
            found.discard('')
            missing = [c for c in customer_ids if c not in found]
            if missing:
                miss_path = os.path.join(out_dir, f'{table}_missing_customers.txt')
                with open(miss_path, 'w', encoding='utf-8') as mf:
                    mf.write('\n'.join(missing) + '\n')
        return {
            'table': table,
            'cust_col': cust_col,
            'rows': len(df),
            'found': len(found),
            'missing': len(missing),
            'saved': saved,
            'sec': time.perf_counter() - t0,
            'error': None,
        }
    except Exception as e:
        return {
            'table': table,
            'cust_col': None,
            'rows': 0,
            'found': 0,
            'missing': 0,
            'saved': [],
            'sec': time.perf_counter() - t0,
            'error': str(e),
        }
    finally:
        conn.close()


def export_for_customers(
    db_path: str,
    tables: list[str],
    customer_ids: list[str],
    out_dir: str,
    fmt: str,
    label: str,
    *,
    workers: int = DEFAULT_WORKERS,
    write_customer_list: bool = False,
) -> None:
    os.makedirs(out_dir, exist_ok=True)
    print(
        f'  Выгружаем ПОЛНЫЕ строки таблиц {", ".join(tables)} '
        f'только по {len(customer_ids):,} клиентам из ошибок ({label})',
        flush=True,
    )
    if write_customer_list:
        list_path = os.path.join(out_dir, f'customers_{label}.txt')
        with open(list_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(customer_ids) + '\n')
        print(f'  (опц.) список клиентов: {list_path}')

    variants = build_customer_variants(customer_ids)
    print(f'  Ключей для JOIN (с вариантами): {len(variants):,}')
    n_workers = max(1, min(int(workers), len(tables)))
    print(f'  Параллельных воркеров: {n_workers} (таблицы: {", ".join(tables)})', flush=True)

    results: list[dict] = []
    with ProgressBar(len(tables), desc=f'{label} tables', unit='table') as tables_bar:
        with ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {
                pool.submit(
                    _export_one_table, db_path, table, customer_ids, variants, out_dir, fmt, label
                ): table
                for table in tables
            }
            for fut in as_completed(futs):
                table = futs[fut]
                tables_bar.set_description(f'{label} ✓ {table}')
                res = fut.result()
                results.append(res)
                if res.get('error'):
                    print(f'\n  [ERROR] {table}: {res["error"]}', flush=True)
                else:
                    print(
                        f'\n  [{label} / {table}] ПОЛНЫЕ СТРОКИ таблицы | col={res["cust_col"]} | '
                        f'rows={res["rows"]:,} | customers={res["found"]:,}/{len(customer_ids):,} | '
                        f'{res["sec"]:.1f}с',
                        flush=True,
                    )
                    for p in res.get('saved') or []:
                        print(f'    → TABLE FILE: {p}', flush=True)
                    if res.get('missing'):
                        print(f'    не найдено в {table}: {res["missing"]:,}', flush=True)
                tables_bar.update(1)

    ok_files = [p for r in results for p in (r.get('saved') or [])]
    print(f'\n  Итого файлов таблиц для {label}: {len(ok_files)}', flush=True)
    for p in ok_files:
        print(f'    • {p}', flush=True)

def parse_args():
    p = argparse.ArgumentParser(
        description='Выгрузка KNVP/KNA1/KNVV из БД по клиентам из ошибок RCCOMP_149.1 / 149.2'
    )
    p.add_argument(
        '--db',
        default=None,
        help='Переопределить путь/имя .db. По умолчанию берётся поле database из config/database.json',
    )
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
    p.add_argument(
        '--workers',
        type=int,
        default=DEFAULT_WORKERS,
        help=f'Параллельных таблиц одновременно (default {DEFAULT_WORKERS})',
    )
    p.add_argument(
        '--parallel-rules',
        action='store_true',
        help='Параллельно выгружать 149.1 и 149.2 (отдельные соединения)',
    )
    p.add_argument(
        '--write-customer-list',
        action='store_true',
        help='Дополнительно сохранить txt со списком клиентов (по умолчанию только таблицы)',
    )
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
    with ProgressBar(len(by_rule), desc='Читаем файлы ошибок', unit='file') as bar:
        for rule, path in by_rule.items():
            bar.set_description(f'Ошибки {rule}')
            keys = collect_customers_from_error_file(path)
            customers_by_rule[rule] = sorted(keys)
            print(f'{rule}: {len(keys):,} клиентов', flush=True)
            bar.update(1)

    if not any(customers_by_rule.values()):
        print('ОШИБКА: в файлах ошибок нет клиентов')
        return 1

    # Имя БД — из config/database.json (поле database), если не передан --db
    if args.db and str(args.db).strip():
        db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    else:
        cfg = load_database_config(_PROJECT_ROOT)
        db_name = str(cfg.get('database') or '').strip()
        cfg_path = os.path.join(_PROJECT_ROOT, DB_CONFIG_REL)
        if not db_name:
            print(f'ОШИБКА: в {cfg_path} нет поля "database"')
            return 1
        db_path = db_name if os.path.isabs(db_name) else os.path.normpath(os.path.join(_PROJECT_ROOT, db_name))
        period = str(cfg.get('period') or '').strip()
        db_source = DB_CONFIG_REL.replace('\\', '/')
        if period:
            db_source += f' (period={period})'
        if not os.path.isfile(db_path):
            print(f'ОШИБКА: файл БД не найден: {db_path}')
            print(f'  Источник: {db_source} → database="{db_name}"')
            print(f'  Положите .db в корень проекта или поправьте {DB_CONFIG_REL}')
            return 1
        print(f'config/database.json → database: {db_name}')

    print(f'БД ({db_source}): {db_path}')
    if _tqdm is None:
        print('[INFO] Для красивого прогресс-бара можно поставить: pip install tqdm')

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    root_out = os.path.join(args.output_dir, f'rccomp_149_customers_{ts}')
    os.makedirs(root_out, exist_ok=True)
    tables = [t.strip().upper() for t in str(args.tables).split(',') if t.strip()]
    workers = max(1, int(args.workers))

    jobs: list[tuple[str, list[str]]] = []
    if rule_mode == 'COMBINED':
        merged: set[str] = set()
        for ids in customers_by_rule.values():
            merged.update(ids)
        jobs.append(('RCCOMP_149_combined', sorted(merged)))
    else:
        for rule, ids in customers_by_rule.items():
            if ids:
                jobs.append((rule.replace('.', '_'), ids))

    def _run_job(label: str, ids: list[str]) -> None:
        print(f'\n=== {label}: {len(ids):,} клиентов из ошибок → полные строки таблиц ===', flush=True)
        export_for_customers(
            db_path, tables, ids, os.path.join(root_out, label), args.format, label,
            workers=workers,
            write_customer_list=bool(args.write_customer_list),
        )

    if args.parallel_rules and len(jobs) > 1:
        print(f'Параллельный экспорт правил: {len(jobs)} jobs', flush=True)
        with ProgressBar(len(jobs), desc='Правила', unit='rule') as jobs_bar:
            with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
                futs = {pool.submit(_run_job, label, ids): label for label, ids in jobs}
                for fut in as_completed(futs):
                    label = futs[fut]
                    try:
                        fut.result()
                    except Exception as e:
                        print(f'[ERROR] {label}: {e}', flush=True)
                    jobs_bar.set_description(f'Готово {label}')
                    jobs_bar.update(1)
    else:
        with ProgressBar(len(jobs), desc='Правила', unit='rule') as jobs_bar:
            for label, ids in jobs:
                jobs_bar.set_description(f'Экспорт {label}')
                _run_job(label, ids)
                jobs_bar.update(1)

    print(f'\nГотово. Папка: {root_out}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
