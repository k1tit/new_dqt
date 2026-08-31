"""dm_customer_equipment filters/joins — logical DM, no physical table."""
from __future__ import annotations

import re
from typing import Any

import pandas as pd

TJ30T_STSMA = 'CSEQ01'
DATBI_OPEN_PREFIXES = ('99991231', '9999-12-31')


def _blank(v: Any) -> bool:
    if v is None:
        return True
    try:
        if isinstance(v, float) and pd.isna(v):
            return True
    except Exception:
        pass
    s = str(v).replace('\ufeff', '').replace('\xa0', ' ').strip()
    return s.lower() in ('', 'none', 'null', 'nan', '<na>', 'nat', 'n/a', 'na')


def ltrim_zeros(v: Any) -> str:
    """LTRIM('0', value) as in DM join INOB.CUOBJ = LTRIM('0', AUSP.OBJEK)."""
    if _blank(v):
        return ''
    s = str(v).replace('\ufeff', '').strip()
    if re.fullmatch(r'\d+\.0+', s):
        s = s.split('.')[0]
    s = s.lstrip('0')
    return s or '0'


def norm_objnr(v: Any) -> str:
    if _blank(v):
        return ''
    s = str(v).replace('\ufeff', '').strip().upper()
    if re.fullmatch(r'\d+\.0+', s):
        s = s.split('.')[0]
    return s


def is_open_datbi(v: Any) -> bool:
    if _blank(v):
        return False
    s = str(v).strip()
    if any(s.startswith(p) for p in DATBI_OPEN_PREFIXES):
        return True
    digits = re.sub(r'\D', '', s)[:8]
    return digits == '99991231'


def is_jest_active(inact: Any) -> bool:
    if _blank(inact):
        return True
    return str(inact).strip().upper() not in ('X', '1', 'TRUE', 'Y', 'YES')


def filter_vequi_dm(df: pd.DataFrame, *, equnr_col, datbi_col=None, spras_col=None, kunde_col=None) -> pd.DataFrame:
    """V_EQUI eq: DATBI open + KUNDE NOT NULL + prefer SPRAS=E per EQUNR."""
    if df is None or df.empty or not equnr_col:
        return pd.DataFrame() if df is None else df.iloc[0:0].copy()
    out = df
    if datbi_col and datbi_col in out.columns:
        out = out.loc[out[datbi_col].apply(is_open_datbi)].copy()
    if kunde_col and kunde_col in out.columns:
        out = out.loc[~out[kunde_col].apply(_blank)].copy()
    if out.empty:
        return out
    if spras_col and spras_col in out.columns and equnr_col in out.columns:
        keys = out[equnr_col].map(norm_objnr)
        spras = out[spras_col].astype(str).str.strip().str.upper()
        e_keys = set(keys[spras == 'E'].tolist())
        keep = (spras == 'E') | (~keys.isin(e_keys))
        out = out.loc[keep].copy()
    return out


def filter_jest_dm(df: pd.DataFrame, *, inact_col=None) -> pd.DataFrame:
    """JEST: INACT != X."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.iloc[0:0].copy()
    if not inact_col or inact_col not in df.columns:
        return df.copy()
    return df.loc[df[inact_col].apply(is_jest_active)].copy()


def filter_tj30t_dm(df: pd.DataFrame, *, spras_col=None, stsma_col=None) -> pd.DataFrame:
    """TJ30T: SPRAS=E AND STSMA=CSEQ01."""
    if df is None or df.empty:
        return pd.DataFrame() if df is None else df.iloc[0:0].copy()
    out = df
    if spras_col and spras_col in out.columns:
        out = out.loc[out[spras_col].astype(str).str.strip().str.upper() == 'E'].copy()
    if stsma_col and stsma_col in out.columns:
        out = out.loc[out[stsma_col].astype(str).str.strip().str.upper() == TJ30T_STSMA].copy()
    return out


def build_estat_to_txt04(tj30t: pd.DataFrame, *, estat_col, txt_col) -> dict[str, str]:
    """JEST.STAT (ESTAT) -> equipment_status_code (TXT04)."""
    out: dict[str, str] = {}
    if tj30t is None or tj30t.empty or not estat_col or not txt_col:
        return out
    for estat, txt in zip(tj30t[estat_col].tolist(), tj30t[txt_col].tolist()):
        k = norm_objnr(estat)
        if not k or k in out:
            continue
        t = str(txt or '').strip().upper()
        if t:
            out[k] = t
    return out


def build_cuobj_to_matnr(inob: pd.DataFrame, *, cuobj_col, objek_col) -> dict[str, str]:
    """INOB: LTRIM(CUOBJ) -> MATNR (OBJEK)."""
    out: dict[str, str] = {}
    if inob is None or inob.empty or not cuobj_col or not objek_col:
        return out
    for cu, mat in zip(inob[cuobj_col].tolist(), inob[objek_col].tolist()):
        k = ltrim_zeros(cu)
        if not k or k in out or _blank(mat):
            continue
        out[k] = str(mat).strip()
    return out
