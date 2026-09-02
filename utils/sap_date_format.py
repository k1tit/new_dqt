"""Format / parse SAP date values (YYYYMMDD, ISO+time, Excel floats) for DQ checks and export."""
from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd

_SAP_DATE_COL_KEYS = frozenset({
    'DATE_FROM', 'DATE_TO', 'VALID_FROM', 'VALID_TO',
    'DATEFROM', 'DATETO', 'VALIDFROM', 'VALIDTO',
    'INBDT', 'ANSDT', 'DATAB', 'DATBI', 'ERDAT', 'AEDAT',
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


def _ymd_to_date(y: int, m: int, d: int):
    if not _calendar_ok_ymd(y, m, d):
        return None
    return date(y, m, d)


def _excel_serial_to_date(n: float):
    # Excel serial day (Windows 1900 system); typical business dates ~20000..60000
    if not (15000 <= n <= 80000):
        return None
    try:
        return datetime.utcfromtimestamp((n - 25569) * 86400).date()
    except (ValueError, TypeError, OverflowError, OSError):
        return None


def parse_sap_date_to_date(value):
    """
    Parse SAP/Excel/ISO/datetime-with-time to datetime.date, or None if empty/invalid.
    Handles common dump forms: YYYYMMDD, YYYY-MM-DD[ HH:MM:SS], DD.MM.YYYY, Excel serial,
    pandas/numpy timestamps.
    """
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass

    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    # numpy.datetime64
    try:
        if hasattr(value, 'dtype') and str(getattr(value, 'dtype', '')).startswith('datetime64'):
            ts = pd.Timestamp(value)
            if pd.isna(ts):
                return None
            return ts.date()
    except Exception:
        pass

    # numeric Excel serial or YYYYMMDD as int/float
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            n = float(value)
        except (ValueError, TypeError, OverflowError):
            n = None
        if n is not None:
            if 15000 <= n <= 80000:
                return _excel_serial_to_date(n)
            # YYYYMMDD as number (e.g. 20240115.0)
            if 19000101 <= n <= 29991231 and float(n) == int(n):
                digits = f'{int(n):08d}'
                return _ymd_to_date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))

    s = str(value).strip().strip("'").strip('"').replace('\ufeff', '').replace('\xa0', ' ')
    if not s or s.lower() in _EMPTY:
        return None
    # strip fractional seconds / timezone noise for matching
    s_norm = s.replace('T', ' ')

    # ISO date or datetime: 2024-01-15 / 2024-01-15 00:00:00 / 2024-01-15 00:00:00.000
    m = re.match(r'^(\d{4})-(\d{2})-(\d{2})(?:[ \t].*)?$', s_norm)
    if m:
        return _ymd_to_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    # DD.MM.YYYY[ time]
    m = re.match(r'^(\d{2})\.(\d{2})\.(\d{4})(?:[ \t].*)?$', s_norm)
    if m:
        return _ymd_to_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    # DD/MM/YYYY[ time]
    m = re.match(r'^(\d{2})/(\d{2})/(\d{4})(?:[ \t].*)?$', s_norm)
    if m:
        return _ymd_to_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))

    # YYYYMMDD or YYYYMMDD.0 or YYYYMMDDHHMMSS → take first 8 if look like YYYYMMDD
    if re.fullmatch(r'\d+\.0+', s):
        digits = s.split('.')[0]
    elif re.fullmatch(r'\d+', s):
        digits = s
    else:
        digits = re.sub(r'\D', '', s)

    if len(digits) >= 8:
        head = digits[:8]
        if set(head) <= {'0'}:
            return None
        y, mo, d = int(head[:4]), int(head[4:6]), int(head[6:8])
        # prefer YYYYMMDD when year looks sane; avoid misreading Excel serial digits
        if 1900 <= y <= 2999:
            return _ymd_to_date(y, mo, d)

    # numeric string Excel serial
    try:
        n = float(s.replace(',', '.'))
        if 15000 <= n <= 80000:
            return _excel_serial_to_date(n)
    except (ValueError, TypeError):
        pass

    # last resort: pandas
    try:
        ts = pd.to_datetime(s, dayfirst=True, errors='coerce')
        if ts is not None and not pd.isna(ts):
            return ts.date()
    except Exception:
        pass
    return None


def is_valid_sap_date_value(value) -> bool:
    """True if value is a parseable calendar date. Empty/zero-date → False."""
    return parse_sap_date_to_date(value) is not None


def format_sap_date_value(value) -> str:
    parsed = parse_sap_date_to_date(value)
    if parsed is not None:
        return parsed.strftime('%d.%m.%Y')
    if value is None:
        return ''
    try:
        if pd.isna(value):
            return ''
    except Exception:
        pass
    s = str(value).strip().strip("'").strip('"')
    if not s or s.lower() in _EMPTY:
        return ''
    return s


def format_dataframe_sap_date_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        if is_sap_date_column(col):
            out[col] = out[col].apply(format_sap_date_value)
    return out
