"""Helpers for logical dm_product_plant (MARC-centric)."""
from __future__ import annotations

import json
import os
from typing import Optional, Sequence

import pandas as pd

BASIC_SCOPE_EXCLUDED_PLANTS = frozenset({
    '4110', '4111', '4112', '4113', '4114', '4115', '4116',
    '4117', '4118', '4119', '4120', '4121', '4122',
})


def _json_path(name: str) -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'json files', name))


def find_col(df: pd.DataFrame, names: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    wanted = [str(n).strip().upper().replace(' ', '').replace('_', '') for n in names]
    for c in df.columns:
        cu = str(c).strip().upper().replace(' ', '').replace('_', '')
        if cu in wanted:
            return c
    return None


def _norm(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().replace({'NAN': '', 'NONE': '', 'NULL': '', 'NA': '', '<NA>': ''})


def inactive_plant_codes(path: Optional[str] = None) -> frozenset[str]:
    """plant_code_not_active rows with is_active = 0. Missing file -> empty set."""
    path = path or _json_path('plant_code_not_active.json')
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return frozenset()
    rows = payload.get('rows', []) if isinstance(payload, dict) else []
    out = set()
    for row in rows:
        flag = str(row.get('is_active', '0')).strip()
        if flag not in ('0', '0.0'):
            continue
        code = str(row.get('plant_code', '')).strip().upper()
        if code:
            out.add(code)
    return frozenset(out)


def is_active_plant_mask(werks: pd.Series, inactive: Optional[frozenset[str]] = None) -> pd.Series:
    """Keep plants with is_active = 1 or absent from plant_code_not_active. Drop flag 0."""
    inactive = inactive_plant_codes() if inactive is None else inactive
    codes = _norm(werks)
    return ~codes.isin(inactive)


def is_basic_scope_mask(df: pd.DataFrame) -> pd.Series:
    """
    Published formula (Jun 18, 2025):
    IF (LVORM <> 'X' AND MMSTA <> '99') OR plant_code NOT IN (4110..4122) THEN '1' ELSE '0'
    Missing LVORM/MMSTA: empty is treated as not X / not 99.
    """
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    lvorm_col = find_col(df, ('LVORM', 'DELETION_FLAG', 'LOEVM'))
    mmsta_col = find_col(df, ('MMSTA', 'MATERIAL_STATUS_CODE'))
    plant_col = find_col(df, ('WERKS', 'PLANT_CODE', 'PLANT'))

    material_ok = pd.Series(True, index=df.index)
    if lvorm_col:
        material_ok = material_ok & (_norm(df[lvorm_col]) != 'X')
    if mmsta_col:
        material_ok = material_ok & (_norm(df[mmsta_col]) != '99')
    if not plant_col:
        return material_ok
    outside = ~_norm(df[plant_col]).isin(BASIC_SCOPE_EXCLUDED_PLANTS)
    return material_ok | outside


def apply_is_basic_scope(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    return df.loc[is_basic_scope_mask(df)].copy()
