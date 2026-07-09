"""Format SAP date values (YYYYMMDD, Excel floats) for human-readable export."""
from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

_SAP_DATE_COL_KEYS = frozenset({
    'DATE_FROM', 'DATE_TO', 'VALID_FROM', 'VALID_TO',
    'DATEFROM', 'DATETO', 'VALIDFROM', 'VALIDTO',
})
_EMPTY = {'', 'none', 'null', 'nan', 'nat', '-', '0', '0.0', '0.00', 'n/a', 'na'}


def _normalize_col_key(name: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', str(name or '').upper())


def is_sap_date_column(col_name: str) -> bool:
    return _normalize_col_key(col_name) in _SAP_DATE_COL_KEYS


def format_sap_date_value(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    if isinstance(value, (datetime, date)):
        return value.strftime('%d.%m.%Y')
    s = str(value).strip().strip("'").strip('"')
    if not s or s.lower() in _EMPTY:
        return ''
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        y, m, d = s.split('-')
        return f'{d}.{m}.{y}'
    if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', s):
        return s
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', s):
        d, m, y = s.split('/')
        return f'{d}.{m}.{y}'
    digits = ''
    if re.fullmatch(r'\d+\.0+', s):
        digits = s.split('.')[0]
    elif re.fullmatch(r'\d+', s):
        digits = s
    else:
        only = re.sub(r'\D', '', s)
        if len(only) == 8:
            digits = only
    if len(digits) == 8 and digits != '00000000':
        try:
            y = int(digits[:4])
            m = int(digits[4:6])
            d = int(digits[6:8])
            if 1000 <= y <= 9999 and 1 <= m <= 12 and 1 <= d <= 31:
                return f'{d:02d}.{m:02d}.{y}'
        except (ValueError, TypeError):
            pass
    try:
        if isinstance(value, (int, float)) and not pd.isna(value):
            n = float(value)
            if 30000 <= n <= 60000:
                dt = datetime.utcfromtimestamp((n - 25569) * 86400)
                return dt.strftime('%d.%m.%Y')
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return s


def format_dataframe_sap_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if is_sap_date_column(col):
            out[col] = out[col].apply(format_sap_date_value)
    return out
