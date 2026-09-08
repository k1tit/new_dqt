"""Helpers for logical dm_product_general (MARA-centric)."""
from __future__ import annotations

from typing import Optional, Sequence

import pandas as pd

BASIC_SCOPE_EXCLUDED_MTART = frozenset({'ZCDN', 'ZSPN'})


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
    return s.astype(str).str.strip().str.upper().replace({'NAN': '', 'NONE': '', 'NULL': '', 'NA': ''})


def is_basic_scope_mask(df: pd.DataFrame) -> pd.Series:
    """
    IF (LVORM <> 'X' AND MSTAE <> '99') AND MTART NOT IN (ZCDN, ZSPN) THEN '1' ELSE '0'
    Missing LVORM/MSTAE columns: treat as non-blocking (empty != X / != 99).
    """
    if df is None or df.empty:
        return pd.Series(dtype=bool)

    mtart_col = find_col(df, ('MTART', 'MATERIAL_TYPE_CODE', 'MATERIAL_TYPE'))
    lvorm_col = find_col(df, ('LVORM', 'DELETION_FLAG', 'LOEVM'))
    mstae_col = find_col(df, ('MSTAE', 'MATERIAL_STATUS_CODE', 'MMSTA'))

    ok = pd.Series(True, index=df.index)
    if mtart_col:
        mtart = _norm(df[mtart_col])
        ok = ok & ~mtart.isin(BASIC_SCOPE_EXCLUDED_MTART)
    if lvorm_col:
        lvorm = _norm(df[lvorm_col])
        ok = ok & (lvorm != 'X')
    if mstae_col:
        mstae = _norm(df[mstae_col])
        ok = ok & (mstae != '99')
    return ok


def apply_is_basic_scope(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df if df is not None else pd.DataFrame()
    return df.loc[is_basic_scope_mask(df)].copy()
