from __future__ import annotations
import re
from typing import Any
import pandas as pd
_EMPTY = {'', 'none', 'null', 'nan', '<na>', 'nat', '-', '.', 'n/a', 'na'}

def norm_sap_recon_account(value: Any, *, length: int=10) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    if isinstance(value, (int, float)):
        if value == 0:
            return ''
        if float(value) == int(value):
            digits = str(int(value))
            if not digits or set(digits) == {'0'}:
                return ''
            return digits.zfill(length) if len(digits) <= length else digits
    s = str(value).replace('\ufeff', '').replace('\xa0', ' ').strip()
    s = s.strip("'").strip('"').strip()
    if s.lower() in _EMPTY or s in {'0', '0.0', '0.00'}:
        return ''
    if re.fullmatch('0+(\\.0+)?', s):
        return ''
    if s.endswith('.0') and s[:-2].isdigit():
        s = s[:-2]
    if re.fullmatch('\\d+\\.0+', s):
        s = s.split('.')[0]
    digits = re.sub('\\D', '', s)
    if not digits or set(digits) == {'0'}:
        return ''
    if len(digits) <= length:
        return digits.zfill(length)
    return digits

def norm_sap_account_group(value: Any) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ''
    s = str(value).replace('\ufeff', '').replace('\xa0', ' ').strip().strip("'").strip('"')
    if s.lower() in _EMPTY:
        return ''
    if re.fullmatch('\\d+\\.0+', s):
        s = s.split('.')[0]
    if s.endswith('.0') and s[:-2].isdigit():
        s = s[:-2]
    return s