"""Scope / pass-fail helpers for Product Conformity rules on MARA (dm_product_general)."""
from __future__ import annotations

from typing import Iterable, Optional, Sequence, Tuple

import pandas as pd

RPCONF_MATERIAL_RULES = frozenset({'RPCONF_166.1', 'RPCONF_196.10', 'RPCONF_196.11'})

RULE_MTART_SCOPE = {
    'RPCONF_166.1': frozenset({'ZFG', 'ZFGS'}),
    'RPCONF_196.10': frozenset({'ZNVL', 'ZKIT'}),
    'RPCONF_196.11': frozenset({'ZSV'}),
}

RULE_ALLOWED_BY_MTART = {
    'RPCONF_166.1': {
        'ZFG': frozenset({'CS', 'ST', 'PC'}),
        'ZFGS': frozenset({'CS', 'ST', 'PC'}),
    },
    'RPCONF_196.10': {
        'ZNVL': frozenset({'NORM', 'ZWST'}),
        'ZKIT': frozenset({'NORM'}),
    },
    'RPCONF_196.11': {
        'ZSV': frozenset({'LEIS', 'ZLIS'}),
    },
}


def find_col(df: pd.DataFrame, names: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    wanted = [str(n).strip().upper().replace(' ', '').replace('_', '') for n in names]
    for c in df.columns:
        cu = str(c).strip().upper().replace(' ', '').replace('_', '')
        if cu in wanted:
            return c
    for c in df.columns:
        cu = str(c).strip().upper().replace(' ', '').replace('_', '')
        for w in wanted:
            if w and (w == cu or w in cu or cu in w):
                return c
    return None


def _norm_series(s: pd.Series) -> pd.Series:
    return s.astype(str).str.strip().str.upper().replace({'NAN': '', 'NONE': '', 'NULL': '', 'NA': ''})


def value_filled_mask(series: pd.Series) -> pd.Series:
    if series is None:
        return pd.Series(dtype=bool)
    null_like = series.isna()
    text = series.astype(str).str.strip()
    empty = text.eq('') | text.str.lower().isin(['none', 'null', 'nan', 'na'])
    return ~(null_like | empty)


def build_matnr_to_maktx(makt_df: pd.DataFrame, spras: str = 'E') -> dict:
    """MATNR -> MAKTX; prefer SPRAS=E when language column exists."""
    out: dict = {}
    if makt_df is None or makt_df.empty:
        return out
    matnr_col = find_col(makt_df, ('MATNR', 'MATERIAL', 'MATERIAL_NUMBER'))
    maktx_col = find_col(makt_df, ('MAKTX', 'MATERIAL_DESCRIPTION', 'MATERIALDESCRIPTION', 'MAKTG'))
    if not matnr_col or not maktx_col:
        return out
    spras_col = find_col(makt_df, ('SPRAS', 'LANGU', 'LANGUAGE', 'LANG'))
    work = makt_df
    if spras_col:
        pref = _norm_series(work[spras_col]) == str(spras or 'E').strip().upper()
        if pref.any():
            work = work.loc[pref]
    keys = _norm_series(work[matnr_col]).str.lstrip('0')
    vals = work[maktx_col].astype(str)
    for k, v in zip(keys.tolist(), vals.tolist()):
        if not k or k in out:
            continue
        out[k] = v
    return out


def attach_material_description(mara_df: pd.DataFrame, makt_df: Optional[pd.DataFrame]) -> Tuple[pd.DataFrame, str]:
    """Add material_description from MAKT; return (df, column_name)."""
    df = mara_df.copy()
    existing = find_col(df, ('MATERIAL_DESCRIPTION', 'MAKTX', 'MATERIALDESCRIPTION'))
    if existing:
        if existing != 'material_description':
            df['material_description'] = df[existing]
        return df, 'material_description'
    matnr_col = find_col(df, ('MATNR', 'MATERIAL', 'MATERIAL_NUMBER'))
    lookup = build_matnr_to_maktx(makt_df) if makt_df is not None else {}
    if not matnr_col or not lookup:
        df['material_description'] = ''
        return df, 'material_description'
    keys = _norm_series(df[matnr_col]).str.lstrip('0')
    df['material_description'] = keys.map(lambda k: lookup.get(k, ''))
    return df, 'material_description'


def exclude_abp_description(df: pd.DataFrame, desc_col: str) -> pd.DataFrame:
    if not desc_col or desc_col not in df.columns:
        return df
    desc = df[desc_col].astype(str)
    abp = desc.str.contains('ABP', case=False, na=False)
    return df.loc[~abp].copy()


def scope_mara_for_rpconf(
    df: pd.DataFrame,
    rule_code: str,
    value_col: str,
    makt_df: Optional[pd.DataFrame] = None,
    apply_basic_scope: bool = True,
) -> Tuple[pd.DataFrame, dict]:
    """
    Apply dm_product_general Conformity scope:
    - is_basic_scope = 1 (LVORM<>X, MSTAE<>99, MTART not in ZCDN/ZSPN)
    - exclude material_description LIKE %ABP% (MAKT SPRAS=E)
    - MTART in rule scope
    - value column not null/empty (Conformity: empty -> skip)
    """
    from utils.dm_product_general import apply_is_basic_scope

    stats = {
        'before': len(df) if df is not None else 0,
        'after_basic_scope': None,
        'after_abp': None,
        'after_mtart': None,
        'after_value': None,
        'makt_joined': False,
        'mtart_col': None,
        'value_col': value_col,
    }
    if df is None or df.empty:
        stats['after_value'] = 0
        return df if df is not None else pd.DataFrame(), stats

    rc = str(rule_code or '').strip().upper()
    mtart_scope = RULE_MTART_SCOPE.get(rc)
    if not mtart_scope:
        return df, stats

    work = df.copy()
    if apply_basic_scope:
        work = apply_is_basic_scope(work)
    stats['after_basic_scope'] = len(work)

    work, desc_col = attach_material_description(work, makt_df)
    stats['makt_joined'] = bool(makt_df is not None and not getattr(makt_df, 'empty', True))
    work = exclude_abp_description(work, desc_col)
    stats['after_abp'] = len(work)

    mtart_col = find_col(work, ('MTART', 'MATERIAL_TYPE', 'MATERIAL_TYPE_CODE', 'MATERIALTYPE'))
    stats['mtart_col'] = mtart_col
    if not mtart_col or mtart_col not in work.columns:
        return work.iloc[0:0].copy(), stats
    if not value_col or value_col not in work.columns:
        return work.iloc[0:0].copy(), stats

    mtart = _norm_series(work[mtart_col])
    work = work.loc[mtart.isin(mtart_scope)].copy()
    stats['after_mtart'] = len(work)

    filled = value_filled_mask(work[value_col])
    work = work.loc[filled].copy()
    stats['after_value'] = len(work)
    return work, stats


def pass_mask_for_rpconf(df: pd.DataFrame, rule_code: str, value_col: str, mtart_col: Optional[str] = None) -> pd.Series:
    """True = pass ('1'), False = fail ('0') within already-scoped df."""
    rc = str(rule_code or '').strip().upper()
    allowed_map = RULE_ALLOWED_BY_MTART.get(rc) or {}
    if df is None or df.empty or not value_col or value_col not in df.columns:
        return pd.Series(dtype=bool)

    mtart_c = mtart_col or find_col(df, ('MTART', 'MATERIAL_TYPE', 'MATERIAL_TYPE_CODE', 'MATERIALTYPE'))
    if not mtart_c or mtart_c not in df.columns:
        return pd.Series(False, index=df.index)

    mtart = _norm_series(df[mtart_c])
    value = _norm_series(df[value_col])
    ok = pd.Series(False, index=df.index)
    for mt, allowed in allowed_map.items():
        ok = ok | (mtart.eq(mt) & value.isin(set(allowed)))
    return ok


def error_description_for_rule(rule_code: str) -> str:
    rc = str(rule_code or '').strip().upper()
    if rc == 'RPCONF_166.1':
        return 'MEINS must be CS/ST/PC when MTART in (ZFG, ZFGS); is_basic_scope=1; exclude %ABP%; empty MEINS skipped.'
    if rc == 'RPCONF_196.10':
        return 'MTPOS_MARA: ZNVL -> NORM/ZWST; ZKIT -> NORM; is_basic_scope=1; exclude %ABP%; empty MTPOS skipped.'
    if rc == 'RPCONF_196.11':
        return 'MTPOS_MARA must be LEIS/ZLIS when MTART=ZSV; is_basic_scope=1; exclude %ABP%; empty MTPOS skipped.'
    return f'Invalid value for {rc}'
