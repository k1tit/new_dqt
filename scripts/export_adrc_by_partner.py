"""Выгрузка ADRC по номеру клиента (PARTNER) через BUT020.

ADRC не хранит PARTNER напрямую: BUT020.PARTNER → BUT020.ADDRNUMBER → ADRC.ADDRNUMBER.

Примеры:
  python scripts/export_adrc_by_partner.py
  python scripts/export_adrc_by_partner.py --partner 3899988128
  python scripts/export_adrc_by_partner.py --db db_august.db --out exports/adrc_3899988128.xlsx
"""
from __future__ import annotations

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

DEFAULT_PARTNER = '3899988128'
DEFAULT_OUTPUT_DIR = os.path.join(_PROJECT_ROOT, 'exports')


def normalize_partner(value) -> str:
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


def resolve_table(conn, table_name: str) -> str:
    want = str(table_name).strip().upper()
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    ).fetchall()
    for (name,) in rows:
        if str(name).strip().upper() == want:
            return name
    raise ValueError(f'Таблица {table_name} не найдена в БД')


def resolve_column(conn, table_name: str, candidates: tuple[str, ...]) -> str:
    cols = [row[1] for row in conn.execute(f'PRAGMA table_info("{table_name}")').fetchall()]
    upper = {str(c).strip().upper(): c for c in cols}
    for cand in candidates:
        if cand.upper() in upper:
            return upper[cand.upper()]
    for col in cols:
        cu = str(col).strip().upper().replace(' ', '').replace('.', '').replace('_', '')
        for cand in candidates:
            key = cand.upper().replace(' ', '').replace('.', '').replace('_', '')
            if key and key in cu:
                return col
    raise RuntimeError(f'В {table_name} нет колонки из {candidates}. Есть: {cols[:30]}')


def partner_keys(partner: str) -> list[str]:
    keys = [partner]
    stripped = partner.lstrip('0') or '0'
    if stripped != partner:
        keys.append(stripped)
    return keys


def fetch_but020_links(conn, but020: str, partner_col: str, addr_col: str, partner: str) -> pd.DataFrame:
    keys = partner_keys(partner)
    placeholders = ','.join(['?'] * len(keys))
    sql = (
        f'SELECT DISTINCT '
        f'TRIM(CAST("{partner_col}" AS TEXT)) AS PARTNER, '
        f'TRIM(CAST("{addr_col}" AS TEXT)) AS ADDRNUMBER '
        f'FROM "{but020}" '
        f'WHERE TRIM(CAST("{partner_col}" AS TEXT)) IN ({placeholders}) '
        f'OR LTRIM(TRIM(CAST("{partner_col}" AS TEXT)), \'0\') IN ({placeholders})'
    )
    params = keys + [k.lstrip('0') or '0' for k in keys]
    df = pd.read_sql_query(sql, conn, params=params)
    if df.empty:
        return df
    df['PARTNER'] = df['PARTNER'].map(normalize_partner)
    df['ADDRNUMBER'] = df['ADDRNUMBER'].astype(str).str.strip()
    df = df[(df['PARTNER'] == partner) & (df['ADDRNUMBER'] != '') & (df['ADDRNUMBER'].str.lower() != 'nan')]
    return df.drop_duplicates().reset_index(drop=True)


def fetch_adrc(conn, adrc: str, addr_col: str, addr_numbers: list[str]) -> pd.DataFrame:
    if not addr_numbers:
        return pd.DataFrame()
    placeholders = ','.join(['?'] * len(addr_numbers))
    sql = (
        f'SELECT * FROM "{adrc}" '
        f'WHERE TRIM(CAST("{addr_col}" AS TEXT)) IN ({placeholders})'
    )
    return pd.read_sql_query(sql, conn, params=addr_numbers)


def build_export(adrc_df: pd.DataFrame, links: pd.DataFrame, adrc_addr_col: str) -> pd.DataFrame:
    if adrc_df.empty:
        return adrc_df
    out = adrc_df.copy()
    out['_ADDR_KEY'] = out[adrc_addr_col].astype(str).str.strip()
    mapped = links.rename(columns={'ADDRNUMBER': '_ADDR_KEY'})
    out = out.merge(mapped, on='_ADDR_KEY', how='left')
    out = out.drop(columns=['_ADDR_KEY'])
    cols = ['PARTNER'] + [c for c in out.columns if c != 'PARTNER']
    return out[cols]


def parse_args():
    p = argparse.ArgumentParser(description='Выгрузка ADRC по PARTNER через BUT020 в Excel')
    p.add_argument('--partner', default=DEFAULT_PARTNER, help=f'Номер клиента / PARTNER (по умолчанию {DEFAULT_PARTNER})')
    p.add_argument('--db', help='Путь к SQLite (по умолчанию config/database.json)')
    p.add_argument('--out', default='', help='Путь к xlsx (по умолчанию exports/adrc_<partner>_<timestamp>.xlsx)')
    p.add_argument('--output-dir', default=DEFAULT_OUTPUT_DIR, help='Папка для результата, если --out не задан')
    return p.parse_args()


def main() -> int:
    args = parse_args()
    partner = normalize_partner(args.partner)
    if not partner:
        print('[ERROR] Пустой номер клиента')
        return 1
    db_path = args.db
    if db_path:
        if not os.path.isabs(db_path):
            db_path = os.path.join(_PROJECT_ROOT, db_path)
    else:
        db_path, _ = resolve_database_path(_PROJECT_ROOT)
    if not os.path.isfile(db_path):
        print(f'[ERROR] БД не найдена: {db_path}')
        return 1
    conn = connect_sqlite(db_path)
    try:
        but020 = resolve_table(conn, 'BUT020')
        adrc = resolve_table(conn, 'ADRC')
        but_partner_col = resolve_column(conn, but020, ('PARTNER', 'Business Partner', 'Business_Partner', 'BPARTNER'))
        but_addr_col = resolve_column(conn, but020, ('ADDRNUMBER', 'Addr. No.', 'Addr__No_', 'ADRNR', 'ADDRNO'))
        adrc_addr_col = resolve_column(conn, adrc, ('ADDRNUMBER', 'Addr. No.', 'Addr__No_', 'ADRNR', 'ADDRNO'))
        print(f'[INFO] БД: {db_path}')
        print(f'[INFO] PARTNER={partner}')
        print(f'[INFO] JOIN: {adrc}.{adrc_addr_col} = {but020}.{but_addr_col}, клиент = {but020}.{but_partner_col}')
        links = fetch_but020_links(conn, but020, but_partner_col, but_addr_col, partner)
        if links.empty:
            print(f'[INFO] В {but020} нет адресов для PARTNER={partner}')
            return 2
        addr_numbers = sorted(set(links['ADDRNUMBER'].tolist()))
        print(f'[INFO] Адресных номеров в BUT020: {len(addr_numbers)}')
        adrc_df = fetch_adrc(conn, adrc, adrc_addr_col, addr_numbers)
        if adrc_df.empty:
            print(f'[INFO] В {adrc} нет строк по ADDRNUMBER из BUT020')
            return 3
        export_df = build_export(adrc_df, links, adrc_addr_col)
        out = args.out.strip()
        if out:
            if not os.path.isabs(out):
                out = os.path.join(_PROJECT_ROOT, out)
        else:
            os.makedirs(args.output_dir, exist_ok=True)
            stamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            out = os.path.join(args.output_dir, f'adrc_{partner}_{stamp}.xlsx')
        os.makedirs(os.path.dirname(out) or '.', exist_ok=True)
        export_df.to_excel(out, index=False, engine='openpyxl')
        print(f'[OK] Строк ADRC: {len(export_df):,}')
        print(f'[OK] Excel: {out}')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
