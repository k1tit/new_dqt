"""Shared helpers for RCCONF_39.5 / RCCONF_39.5.2 telephone format checks."""
from __future__ import annotations

import re

_FULLWIDTH = str.maketrans('０１２３４５６７８９', '0123456789')
_ALLOWED_SEPARATORS_RE = re.compile(r'[\s\-\(\)\.]')
_TRAILING_DECIMAL_ZERO_RE = re.compile(r'^\d+\.0+$')


def normalize_tel_raw(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return ''
    s = str(val).strip().replace('\ufeff', '').strip()
    return re.sub(r'\s+', '', s).translate(_FULLWIDTH)


def tel_to_digits(val) -> str:
    if val is None or (isinstance(val, float) and val != val):
        return ''
    s = normalize_tel_raw(val)
    if not s or s.lower() in ('none', 'null', 'nan'):
        return ''
    try:
        if isinstance(val, (int, float)) and val == int(val):
            return str(int(val))
    except (ValueError, TypeError, OverflowError):
        pass
    if _TRAILING_DECIMAL_ZERO_RE.match(s):
        return str(int(float(s)))
    try:
        n = float(s.replace(',', '.'))
        if n == int(n):
            return str(int(n))
    except (ValueError, TypeError, OverflowError):
        pass
    return re.sub(r'\D', '', s)


def tel_raw_has_only_allowed_chars(raw, digits: str) -> bool:
    if not digits:
        return not raw
    raw_s = normalize_tel_raw(raw)
    if not raw_s:
        return False
    if tel_to_digits(raw_s) != digits:
        return False
    try:
        if re.search(r'[eE]', raw_s):
            n = float(raw_s.replace(',', '.'))
            if n == int(n) and str(int(n)) == digits:
                return True
    except (ValueError, TypeError, OverflowError):
        pass
    if re.search(r'[a-zA-Z]', raw_s):
        return False
    cleaned = _ALLOWED_SEPARATORS_RE.sub('', raw_s)
    cleaned = cleaned.lstrip('+').strip()
    if cleaned == digits:
        return True
    if _TRAILING_DECIMAL_ZERO_RE.match(raw_s) and str(int(float(raw_s))) == digits:
        return True
    try:
        n = float(raw_s.replace(',', '.'))
        if n == int(n) and str(int(n)) == digits:
            return True
    except (ValueError, TypeError, OverflowError):
        pass
    return re.sub(r'\D', '', raw_s) == digits


def is_valid_rccconf_39_5_digits(digits: str) -> bool:
    if not digits or not digits.isdigit():
        return False
    if len(digits) == 10 and digits[0] == '9':
        return True
    if len(digits) == 11 and digits.startswith('89'):
        return True
    return False


def is_valid_rccconf_39_5_2_digits(digits: str) -> bool:
    if not digits or not digits.isdigit():
        return False
    if len(digits) == 10 and digits[0] == '9':
        return True
    if len(digits) == 11 and (digits.startswith('89') or digits.startswith('79')):
        return True
    if len(digits) == 11 and digits[0] == '8' and digits[1] != '9':
        return True
    return False


def is_valid_rccconf_39_5_value(val, rule_code: str = 'RCCONF_39.5') -> bool:
    digits = tel_to_digits(val)
    if not digits:
        return False
    raw = normalize_tel_raw(val)
    if raw and not tel_raw_has_only_allowed_chars(val, digits):
        return False
    rc = str(rule_code or '').strip().upper()
    if rc == 'RCCONF_39.5.2':
        return is_valid_rccconf_39_5_2_digits(digits)
    return is_valid_rccconf_39_5_digits(digits)
