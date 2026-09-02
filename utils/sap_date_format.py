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


def _calendar_ok_ymd(y: int, m: int, d: int) -> bool:
    try:
        date(y, m, d)
        return True
    except (ValueError, TypeError):
        return False


def is_valid_sap_date_value(value) -> bool:
    """
    True if value is a parseable calendar date (SAP YYYYMMDD / ISO / DD.MM.YYYY / Excel serial).
    Empty / zero-date / null → False (caller should exclude empties before format check).
    """
    if value is None:
        return False
    try:
        if isinstance(value, float) and pd.isna(value):
            return False
    except Exception:
        pass
    if isinstance(value, datetime):
        return True
    if isinstance(value, date):
        return True
    if isinstance(value, pd.Timestamp):
        return not pd.isna(value)

    s = str(value).strip().strip("'").strip('"').replace('\ufeff', '').replace('\xa0', ' ')
    if not s or s.lower() in _EMPTY:
        return False

    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        y, m, d = (int(x) for x in s.split('-'))
        return _calendar_ok_ymd(y, m, d)
    if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', s):
        d, m, y = (int(x) for x in s.split('.'))
        return _calendar_ok_ymd(y, m, d)
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', s):
        d, m, y = (int(x) for x in s.split('/'))
        return _calendar_ok_ymd(y, m, d)

    digits = ''
    if re.fullmatch(r'\d+\.0+', s):
        digits = s.split('.')[0]
    elif re.fullmatch(r'\d+', s):
        digits = s
    else:
        only = re.sub(r'\D', '', s)
        if len(only) == 8:
            digits = only

    if len(digits) == 8:
        if set(digits) <= {'0'}:
            return False
        y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        return _calendar_ok_ymd(y, m, d)

    try:
        if isinstance(value, (int, float)) and not pd.isna(value):
            n = float(value)
            if 30000 <= n <= 60000:
                datetime.utcfromtimestamp((n - 25569) * 86400)
                return True
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return False


def parse_sap_date_to_date(value):
    """
    Parse SAP/Excel/ISO date to datetime.date, or None if empty/invalid.
    """
    if value is None:
        return None
    try:
        if isinstance(value, float) and pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        if pd.isna(value):
            return None
        return value.date()

    s = str(value).strip().strip("'").strip('"').replace('\ufeff', '').replace('\xa0', ' ')
    if not s or s.lower() in _EMPTY:
        return None

    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        y, m, d = (int(x) for x in s.split('-'))
        return date(y, m, d) if _calendar_ok_ymd(y, m, d) else None
    if re.fullmatch(r'\d{2}\.\d{2}\.\d{4}', s):
        d, m, y = (int(x) for x in s.split('.'))
        return date(y, m, d) if _calendar_ok_ymd(y, m, d) else None
    if re.fullmatch(r'\d{2}/\d{2}/\d{4}', s):
        d, m, y = (int(x) for x in s.split('/'))
        return date(y, m, d) if _calendar_ok_ymd(y, m, d) else None

    digits = ''
    if re.fullmatch(r'\d+\.0+', s):
        digits = s.split('.')[0]
    elif re.fullmatch(r'\d+', s):
        digits = s
    else:
        only = re.sub(r'\D', '', s)
        if len(only) == 8:
            digits = only

    if len(digits) == 8:
        if set(digits) <= {'0'}:
            return None
        y, m, d = int(digits[:4]), int(digits[4:6]), int(digits[6:8])
        return date(y, m, d) if _calendar_ok_ymd(y, m, d) else None

    try:
        if isinstance(value, (int, float)) and not pd.isna(value):
            n = float(value)
            if 30000 <= n <= 60000:
                return datetime.utcfromtimestamp((n - 25569) * 86400).date()
    except (ValueError, TypeError, OverflowError, OSError):
        pass
    return None


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
