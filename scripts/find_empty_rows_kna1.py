"""
Найти пустые строки / пустые ключи / пустоты по колонкам в KNA1 (SQLite).

Примеры:
  python scripts/find_empty_rows_kna1.py
  python scripts/find_empty_rows_kna1.py --mode full
  python scripts/find_empty_rows_kna1.py --mode key
  python scripts/find_empty_rows_kna1.py --mode columns --top 30
  python scripts/find_empty_rows_kna1.py --columns KUNNR,NAME1,ORT01 --export
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime

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

TABLE_NAME = 'KNA1'
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')
CUSTOMER_CANDIDATES = ('Customer', 'KUNNR', 'CUSTOMER', 'customer_code', 'KUNNR_KNA1')
EMPTY_TOKENS = frozenset({'', 'nan', 'none', 'null', 'nat', '<na>'})
CHUNK_SIZE = 50_000


def is_empty_series(s: pd.Series) -> pd.Series:
    """True где значение считается пустым (NaN / пробелы / nan|none|null)."""
    as_str = s.astype('string')
    stripped = as_str.str.strip()
    return as_str.isna() | stripped.isna() | stripped.eq('') | stripped.str.lower().isin(EMPTY_TOKENS)


def resolve_customer_column(columns: list[str]) -> str | None:
    upper = {str(c).strip().upper(): c for c in columns}
    for cand in CUSTOMER_CANDIDATES:
        if cand.upper() in upper:
            return upper[cand.upper()]
    for c in columns:
        cu = str(c).strip().upper()
        if cu == 'KUNNR' or 'CUSTOMER' in cu:
            return c
    return None


def iter_kna1_chunks(conn, chunksize: int = CHUNK_SIZE):
    return pd.read_sql_query(f'SELECT * FROM "{TABLE_NAME}"', conn, chunksize=chunksize)


def analyze_kna1(conn, columns_filter: list[str] | None, collect_full: bool, collect_key: bool, collect_cols: bool):
    total_rows = 0
    col_empty_counts: dict[str, int] = {}
    full_empty_frames: list[pd.DataFrame] = []
    key_empty_frames: list[pd.DataFrame] = []
    cols_empty_frames: list[pd.DataFrame] = []
    customer_col: str | None = None
    all_columns: list[str] = []

    for chunk in iter_kna1_chunks(conn):
        if chunk.empty:
            continue
        if not all_columns:
            all_columns = list(chunk.columns)
            customer_col = resolve_customer_column(all_columns)
            for c in all_columns:
                col_empty_counts[c] = 0

        n = len(chunk)
        total_rows += n
        empty_mask = pd.DataFrame({c: is_empty_series(chunk[c]) for c in chunk.columns})

        if collect_cols or collect_full:
            for c in chunk.columns:
                col_empty_counts[c] += int(empty_mask[c].sum())

        row_base = total_rows - n
        if collect_full:
            fully_empty = empty_mask.all(axis=1)
            if fully_empty.any():
                part = chunk.loc[fully_empty].copy()
                part.insert(0, '_row_in_table_approx', row_base + fully_empty.to_numpy().nonzero()[0])
                full_empty_frames.append(part)

        if collect_key and customer_col:
            key_empty = empty_mask[customer_col]
            if key_empty.any():
                part = chunk.loc[key_empty].copy()
                part.insert(0, '_row_in_table_approx', row_base + key_empty.to_numpy().nonzero()[0])
                key_empty_frames.append(part)

        if columns_filter:
            present = [c for c in columns_filter if c in chunk.columns]
            if present:
                any_empty = empty_mask[present].any(axis=1)
                if any_empty.any():
                    part = chunk.loc[any_empty].copy()
                    for c in present:
                        part[f'_empty__{c}'] = empty_mask.loc[any_empty, c].astype(bool).values
                    cols_empty_frames.append(part)

    def _concat(frames: list[pd.DataFrame]) -> pd.DataFrame:
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    return {
        'total_rows': total_rows,
        'columns': all_columns,
        'customer_col': customer_col,
        'col_empty_counts': col_empty_counts,
        'full_empty': _concat(full_empty_frames),
        'key_empty': _concat(key_empty_frames),
        'cols_empty': _concat(cols_empty_frames),
    }


def save_df(df: pd.DataFrame, path_base: str, fmt: str) -> list[str]:
    if df is None or df.empty:
        return []
    os.makedirs(os.path.dirname(path_base) or '.', exist_ok=True)
    saved: list[str] = []
    if fmt in ('csv', 'both'):
        p = f'{path_base}.csv'
        df.to_csv(p, index=False, encoding='utf-8-sig', sep=';')
        saved.append(p)
    if fmt in ('xlsx', 'both'):
        p = f'{path_base}.xlsx'
        # Excel лимит строк — режем с предупреждением в имени
        export = df.head(1_048_575) if len(df) > 1_048_575 else df
        export.to_excel(p, index=False, engine='openpyxl')
        saved.append(p)
    return saved


def parse_args():
    p = argparse.ArgumentParser(description='Поиск пустых строк / ключей / колонок в KNA1.')
    p.add_argument('--db', help='Путь к SQLite (по умолчанию config/database.json)')
    p.add_argument(
        '--mode',
        choices=('all', 'full', 'key', 'columns'),
        default='all',
        help='full=полностью пустые строки; key=пустой Customer/KUNNR; columns=сводка по колонкам; all=всё',
    )
    p.add_argument(
        '--columns',
        default='',
        help='Через запятую: выгрузить строки, где хотя бы одна из этих колонок пустая',
    )
    p.add_argument('--top', type=int, default=40, help='Сколько колонок показать в топе пустот')
    p.add_argument('--export', action='store_true', help='Сохранить найденные строки в exports/')
    p.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Папка для выгрузки')
    p.add_argument('--format', choices=('csv', 'xlsx', 'both'), default='csv')
    p.add_argument('--chunksize', type=int, default=CHUNK_SIZE, help='Размер чанка чтения SQLite')
    return p.parse_args()


def main() -> int:
    global CHUNK_SIZE
    args = parse_args()
    CHUNK_SIZE = max(1000, int(args.chunksize))

    db_path, db_source = resolve_database_path(_PROJECT_ROOT, args.db, must_exist=True)
    cols_filter = [c.strip() for c in args.columns.split(',') if c.strip()] if args.columns else None

    mode = args.mode
    collect_full = mode in ('all', 'full')
    collect_key = mode in ('all', 'key')
    collect_cols = mode in ('all', 'columns') or bool(cols_filter)

    print(f'База: {db_path}')
    print(f'Источник БД: {db_source}')
    print(f'Таблица: {TABLE_NAME}')
    print(f'Reжим: {mode}')

    conn = connect_sqlite(db_path)
    try:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (TABLE_NAME,),
        ).fetchone()
        if not exists:
            print(f'ERROR: таблица {TABLE_NAME} не найдена в БД')
            return 1
        result = analyze_kna1(conn, cols_filter, collect_full, collect_key, collect_cols)
    finally:
        conn.close()

    total = result['total_rows']
    print(f'Всего строк в KNA1: {total:,}')
    print(f'Колонок: {len(result["columns"]):,}')
    if result['customer_col']:
        print(f'Колонка клиента: {result["customer_col"]}')
    else:
        print('Колонка клиента: не найдена')

    ts = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    out_dir = args.output_dir if os.path.isabs(args.output_dir) else os.path.join(_PROJECT_ROOT, args.output_dir)
    saved_all: list[str] = []
    found_any = False

    if collect_full:
        full_df = result['full_empty']
        n = len(full_df)
        print(f'\nПолностью пустые строки (все колонки пустые): {n:,}')
        if n:
            found_any = True
            if args.export or mode == 'full':
                saved_all.extend(save_df(full_df, os.path.join(out_dir, f'kna1_full_empty_{ts}'), args.format))

    if collect_key:
        key_df = result['key_empty']
        n = len(key_df)
        col = result['customer_col'] or 'KUNNR/Customer'
        print(f'\nСтроки с пустым ключом клиента ({col}): {n:,}')
        if n:
            found_any = True
            preview_cols = [c for c in key_df.columns if not str(c).startswith('_')][:8]
            print(key_df[preview_cols].head(10).to_string(index=False))
            if args.export or mode == 'key':
                saved_all.extend(save_df(key_df, os.path.join(out_dir, f'kna1_empty_key_{ts}'), args.format))

    if collect_cols and result['col_empty_counts']:
        ranked = sorted(result['col_empty_counts'].items(), key=lambda x: (-x[1], x[0]))
        top_n = max(1, int(args.top))
        print(f'\nТоп-{top_n} колонок по числу пустых значений (из {total:,} строк):')
        print(f'{"column":40} {"empty":>12} {"pct":>8}')
        for col, cnt in ranked[:top_n]:
            pct = (100.0 * cnt / total) if total else 0.0
            print(f'{col:40} {cnt:12,} {pct:7.2f}%')
            if cnt:
                found_any = True
        if args.export and mode in ('all', 'columns'):
            summary = pd.DataFrame(
                [
                    {
                        'column': col,
                        'empty_count': cnt,
                        'total_rows': total,
                        'empty_pct': round((100.0 * cnt / total) if total else 0.0, 4),
                    }
                    for col, cnt in ranked
                    if cnt > 0
                ]
            )
            saved_all.extend(save_df(summary, os.path.join(out_dir, f'kna1_empty_columns_summary_{ts}'), args.format))

    if cols_filter:
        missing = [c for c in cols_filter if c not in result['columns']]
        if missing:
            print(f'\nWARN: колонки не найдены в KNA1: {missing}')
        cols_df = result['cols_empty']
        print(f'\nСтроки, где пуста хотя бы одна из [{", ".join(cols_filter)}]: {len(cols_df):,}')
        if not cols_df.empty:
            found_any = True
            saved_all.extend(save_df(cols_df, os.path.join(out_dir, f'kna1_empty_in_columns_{ts}'), args.format))

    if saved_all:
        print('\nСохранено:')
        for p in saved_all:
            print(f'  {p}')
    elif not found_any:
        print('\nПустых строк/ключей по выбранному режиму не найдено.')
    else:
        print('\n(для выгрузки файлов добавьте --export)')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
