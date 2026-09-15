"""Evaluators for Product Conformity rules based on dm_product_general."""
from __future__ import annotations

import re
from typing import Any, Callable, Optional, Sequence

import pandas as pd

MARA_RULE_CODES = frozenset({
    'RPCONF_166.1',
    'RPCONF_196.10',
    'RPCONF_196.11',
    'RPCONF_196.12',
    'RPCONF_253.4',
    'RPCONF_265.1',
    'RPCONF_371.1',
})
MAKT_RULE_CODES = frozenset({'RPCONF_225.4', 'RPCONF_225.5'})
AUSP_RULE_CODES = frozenset({'RPCONF_53.1'})
MATERIAL_RULE_CODES = MARA_RULE_CODES | MAKT_RULE_CODES | AUSP_RULE_CODES

FINISHED_GOODS_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZFGM', 'ZFGA', 'ZNVM'})
BPP_ATINN_CODES = frozenset({'829', '868'})

MTPOS_ALLOWED = {
    'RPCONF_196.10': {
        'ZNVL': frozenset({'NORM', 'ZWST'}),
        'ZKIT': frozenset({'NORM'}),
    },
    'RPCONF_196.11': {'ZSV': frozenset({'LEIS', 'ZLIS'})},
    'RPCONF_196.12': {'ZSTL': frozenset({'LEIS'})},
}

ERROR_DESCRIPTIONS = {
    'RPCONF_166.1': 'MEINS must be CS/PC/ST for MTART ZFG/ZFGS when MTPOS_MARA is not ZFGD/ZCVI/ZCVP/ZSNK.',
    'RPCONF_196.10': 'MTPOS_MARA must be NORM/ZWST for ZNVL and NORM for ZKIT.',
    'RPCONF_196.11': 'MTPOS_MARA must be LEIS/ZLIS for MTART ZSV.',
    'RPCONF_196.12': 'MTPOS_MARA must be LEIS for MTART ZSTL.',
    'RPCONF_225.4': 'MAKTX must be uppercase for English material descriptions.',
    'RPCONF_225.5': 'MAKTX must not start/end with whitespace or contain multiple consecutive whitespace characters.',
    'RPCONF_253.4': 'MATKL for MTART ZFGC must be one of 1111005/1111006/1111007/1111009/1113002.',
    'RPCONF_265.1': 'MHDRZ must be less than or equal to MHDHB for Finished Goods.',
    'RPCONF_371.1': 'GEWEI must be KG for MTART ZFG/ZFGS/ZFGC/ZFGM/ZFGA/ZNVM.',
    'RPCONF_53.1': 'BPP code assigned to a ZFG* material does not exist in the BPP reference.',
}


def find_col(df: pd.DataFrame, names: Sequence[str]) -> Optional[str]:
    if df is None or df.empty:
        return None
    normalized = {
        str(c).strip().upper().replace(' ', '').replace('_', '').replace('.', ''): c
        for c in df.columns
    }
    for name in names:
        key = str(name).strip().upper().replace(' ', '').replace('_', '').replace('.', '')
        if key in normalized:
            return normalized[key]
    return None


def _filled(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    return series.notna() & text.ne('') & ~text.str.lower().isin({'none', 'null', 'nan', 'na', '<na>', 'nat'})


def _codes(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip().str.upper()
    text = text.str.replace(r'\.0+$', '', regex=True)
    return text.where(_filled(series), '')


def _matnr(series: pd.Series) -> pd.Series:
    return _codes(series).str.lstrip('0').replace('', '0')


def _empty_result(reason: str, stats: Optional[dict] = None) -> dict:
    return {
        'df': pd.DataFrame(),
        'ok_mask': pd.Series(dtype=bool),
        'error_description': '',
        'skip_reason': reason,
        'stats': stats or {},
    }


def _result(df: pd.DataFrame, ok_mask: pd.Series, rule_code: str, stats: dict) -> dict:
    return {
        'df': df,
        'ok_mask': ok_mask.astype(bool),
        'error_description': ERROR_DESCRIPTIONS[rule_code],
        'skip_reason': None,
        'stats': stats,
    }


def _english_makt(makt: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    if makt is None or makt.empty:
        return pd.DataFrame(), None
    spras_col = find_col(makt, ('SPRAS', 'LANGU', 'LANGUAGE', 'LANG'))
    if not spras_col:
        return pd.DataFrame(), None
    language = _codes(makt[spras_col])
    return makt.loc[language.eq('E')].copy(), spras_col


def _attach_material_description(mara: pd.DataFrame, makt: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    existing = find_col(mara, ('material_description', 'MAKTX'))
    if existing:
        out = mara.copy()
        out['LOOKUP_MATERIAL_DESCRIPTION'] = out[existing]
        return out, 'LOOKUP_MATERIAL_DESCRIPTION'

    english, _ = _english_makt(makt)
    mara_matnr = find_col(mara, ('MATNR', 'material_code', 'MATERIAL', 'MATERIAL_NUMBER'))
    makt_matnr = find_col(english, ('MATNR', 'material_code', 'MATERIAL', 'MATERIAL_NUMBER'))
    maktx_col = find_col(english, ('MAKTX', 'material_description'))
    if not mara_matnr or not makt_matnr or not maktx_col:
        return mara.copy(), None

    lookup = makt.attrs.get('_dq_material_description_lookup')
    if not isinstance(lookup, dict):
        keys = _matnr(english[makt_matnr])
        values = english[maktx_col]
        valid = keys.ne('0') & _filled(values)
        pairs = pd.DataFrame({'key': keys.loc[valid], 'value': values.loc[valid]})
        lookup = pairs.drop_duplicates('key', keep='first').set_index('key')['value'].to_dict()
        makt.attrs['_dq_material_description_lookup'] = lookup
    out = mara.copy()
    out['LOOKUP_MATERIAL_DESCRIPTION'] = _matnr(out[mara_matnr]).map(lookup)
    return out, 'LOOKUP_MATERIAL_DESCRIPTION'


def _scope_mara_not_abp(mara: pd.DataFrame, makt: pd.DataFrame, rule_code: str) -> tuple[pd.DataFrame, dict, Optional[str]]:
    stats = {'input': len(mara), 'description_matched': 0, 'after_abp': 0, 'evaluated': 0}
    work, desc_col = _attach_material_description(mara, makt)
    if not desc_col:
        return work.iloc[0:0].copy(), stats, f'{rule_code}: MAKT.MAKTX (SPRAS=E) не найден — нельзя применить NOT LIKE %ABP%'
    stats['description_matched'] = int(_filled(work[desc_col]).sum())
    if stats['description_matched'] == 0:
        return work.iloc[0:0].copy(), stats, (
            f'{rule_code}: MARA не сджойнилась с MAKT по MATNR — '
            'проверьте колонки MATNR/MATERIAL_NUMBER и формат ключа'
        )
    non_abp = _filled(work[desc_col]) & ~work[desc_col].astype(str).str.contains('ABP', case=False, na=False)
    work = work.loc[non_abp].copy()
    stats['after_abp'] = len(work)
    return work, stats, None


def evaluate_mara_rule(
    mara: pd.DataFrame,
    rule_code: str,
    value_col: str,
    makt: pd.DataFrame,
) -> dict:
    rc = str(rule_code).strip().upper()
    work, stats, skip_reason = _scope_mara_not_abp(mara, makt, rc)
    if skip_reason:
        return _empty_result(skip_reason, stats)

    mtart_col = find_col(work, ('MTART', 'material_type_code'))
    if not mtart_col:
        return _empty_result(f'{rc}: MARA.MTART не найден', stats)
    if not value_col or value_col not in work.columns:
        return _empty_result(f'{rc}: проверяемая колонка не найдена', stats)

    mtart = _codes(work[mtart_col])
    value = _codes(work[value_col])

    if rc == 'RPCONF_166.1':
        mtpos_col = find_col(work, ('MTPOS_MARA', 'general_item_category_group_code', 'MTPOS'))
        if not mtpos_col:
            return _empty_result(f'{rc}: MARA.MTPOS_MARA не найден', stats)
        mtpos = _codes(work[mtpos_col])
        scope = (
            mtart.isin({'ZFG', 'ZFGS'})
            & _filled(work[value_col])
            & _filled(work[mtpos_col])
            & ~mtpos.isin({'ZFGD', 'ZCVI', 'ZCVP', 'ZSNK'})
        )
        scoped = work.loc[scope].copy()
        ok = _codes(scoped[value_col]).isin({'CS', 'PC', 'ST'})
    elif rc in MTPOS_ALLOWED:
        allowed_by_type = MTPOS_ALLOWED[rc]
        scope = mtart.isin(set(allowed_by_type)) & _filled(work[value_col])
        scoped = work.loc[scope].copy()
        scoped_mtart = _codes(scoped[mtart_col])
        scoped_value = _codes(scoped[value_col])
        ok = pd.Series(False, index=scoped.index)
        for material_type, allowed in allowed_by_type.items():
            ok |= scoped_mtart.eq(material_type) & scoped_value.isin(allowed)
    elif rc == 'RPCONF_253.4':
        scope = mtart.eq('ZFGC') & _filled(work[value_col])
        scoped = work.loc[scope].copy()
        ok = _codes(scoped[value_col]).isin({'1111005', '1111006', '1111007', '1111009', '1113002'})
    elif rc == 'RPCONF_265.1':
        total_col = find_col(work, ('MHDHB', 'total_shelf_life'))
        if not total_col:
            return _empty_result(f'{rc}: MARA.MHDHB не найден', stats)
        remaining = pd.to_numeric(work[value_col], errors='coerce')
        total = pd.to_numeric(work[total_col], errors='coerce')
        scope = mtart.isin(FINISHED_GOODS_TYPES) & remaining.notna() & total.notna()
        scoped = work.loc[scope].copy()
        ok = pd.to_numeric(scoped[value_col], errors='coerce').le(
            pd.to_numeric(scoped[total_col], errors='coerce')
        )
    elif rc == 'RPCONF_371.1':
        scope = mtart.isin(FINISHED_GOODS_TYPES) & _filled(work[value_col])
        scoped = work.loc[scope].copy()
        ok = _codes(scoped[value_col]).eq('KG')
    else:
        return _empty_result(f'{rc}: MARA evaluator отсутствует', stats)

    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк после условий technical_definition', stats)
    return _result(scoped, ok, rc, stats)


def evaluate_makt_rule(makt: pd.DataFrame, rule_code: str, value_col: str) -> dict:
    rc = str(rule_code).strip().upper()
    english, spras_col = _english_makt(makt)
    stats = {'input': len(makt), 'english': len(english), 'evaluated': 0}
    if not spras_col:
        return _empty_result(f'{rc}: MAKT.SPRAS не найден — нельзя применить SPRAS=E', stats)
    if not value_col or value_col not in english.columns:
        return _empty_result(f'{rc}: MAKT.MAKTX не найден', stats)

    scoped = english.loc[_filled(english[value_col])].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненных MAKT.MAKTX при SPRAS=E', stats)
    text = scoped[value_col].astype(str)
    if rc == 'RPCONF_225.4':
        ok = text.eq(text.str.upper())
    elif rc == 'RPCONF_225.5':
        ok = ~text.str.contains(r'^\s|\s$|\s{2,}', regex=True, na=False)
    else:
        return _empty_result(f'{rc}: MAKT evaluator отсутствует', stats)
    return _result(scoped, ok, rc, stats)


def _load(loader: Callable[[str], pd.DataFrame], table_name: str) -> pd.DataFrame:
    try:
        value = loader(table_name)
        return value if value is not None else pd.DataFrame()
    except Exception:
        return pd.DataFrame()


def _dedupe_bpp_ausp(ausp: pd.DataFrame, atinn_col: str, objek_col: str) -> pd.DataFrame:
    work = ausp.copy()
    atzhl_col = find_col(work, ('ATZHL',))
    cluster_col = find_col(work, ('SAP_CLUSTER', 'CLUSTER'))
    klart_col = find_col(work, ('KLART', 'CLASS_TYPE'))
    keys = [atinn_col, objek_col]
    if cluster_col:
        keys.append(cluster_col)
    if klart_col:
        keys.append(klart_col)
    if atzhl_col:
        work['_DQ_ATZHL'] = pd.to_numeric(work[atzhl_col], errors='coerce').fillna(-1)
        work = work.sort_values('_DQ_ATZHL').drop_duplicates(keys, keep='last')
        return work.drop(columns=['_DQ_ATZHL'])
    return work.drop_duplicates(keys, keep='last')


def _material_type_lookup(mara: pd.DataFrame) -> tuple[dict, dict, bool]:
    matnr_col = find_col(mara, ('MATNR', 'material_code', 'MATERIAL'))
    mtart_col = find_col(mara, ('MTART', 'material_type_code'))
    cluster_col = find_col(mara, ('SAP_CLUSTER', 'CLUSTER'))
    if not matnr_col or not mtart_col:
        return {}, {}, False
    exact = {}
    simple = {}
    for idx in mara.index:
        matnr = _matnr(pd.Series([mara.at[idx, matnr_col]])).iloc[0]
        mtart = _codes(pd.Series([mara.at[idx, mtart_col]])).iloc[0]
        cluster = _codes(pd.Series([mara.at[idx, cluster_col]])).iloc[0] if cluster_col else ''
        if matnr and mtart:
            simple.setdefault(matnr, mtart)
            if cluster:
                exact.setdefault((cluster, matnr), mtart)
    return exact, simple, bool(cluster_col)


def _bpp_reference_codes(reference: pd.DataFrame) -> set[str]:
    if reference is None or reference.empty:
        return set()
    code_col = find_col(reference, ('ATWRT', 'BPP_CODE', 'CODE', 'VALUE'))
    if not code_col:
        return set()
    return set(_codes(reference[code_col])) - {''}


def evaluate_ausp_bpp_rule(
    ausp: pd.DataFrame,
    rule_code: str,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = str(rule_code).strip().upper()
    stats = {'input': len(ausp), 'bpp_rows': 0, 'evaluated': 0, 'reference': ''}
    atinn_col = find_col(ausp, ('ATINN',))
    objek_col = find_col(ausp, ('OBJEK', 'MATNR', 'MATERIAL'))
    if not atinn_col or not objek_col or not value_col or value_col not in ausp.columns:
        return _empty_result(f'{rc}: AUSP.ATINN/OBJEK/ATWRT не найдены', stats)

    atinn = _codes(ausp[atinn_col])
    work = ausp.loc[atinn.isin(BPP_ATINN_CODES)].copy()
    klart_col = find_col(work, ('KLART', 'CLASS_TYPE'))
    if klart_col:
        work = work.loc[_codes(work[klart_col]).eq('001')].copy()
    work = _dedupe_bpp_ausp(work, atinn_col, objek_col)
    stats['bpp_rows'] = len(work)
    if work.empty:
        return _empty_result(f'{rc}: нет AUSP для BPP (ATINN 829/868, KLART=001)', stats)

    mara = _load(loader, 'MARA')
    if mara.empty:
        return _empty_result(f'{rc}: MARA не найдена для определения MTART', stats)
    exact_type, simple_type, mara_has_cluster = _material_type_lookup(mara)
    if not simple_type:
        return _empty_result(f'{rc}: MARA.MATNR/MTART не найдены', stats)

    work = work.copy()
    work['_DQ_MATNR'] = _matnr(work[objek_col])
    ausp_cluster_col = find_col(work, ('SAP_CLUSTER', 'CLUSTER'))
    if mara_has_cluster and ausp_cluster_col and exact_type:
        clusters = _codes(work[ausp_cluster_col])
        work['LOOKUP_MATERIAL_TYPE'] = [
            exact_type.get((cluster, matnr), '')
            for cluster, matnr in zip(clusters, work['_DQ_MATNR'])
        ]
    else:
        work['LOOKUP_MATERIAL_TYPE'] = work['_DQ_MATNR'].map(simple_type).fillna('')

    bpp = _codes(work[value_col])
    scope = (
        _filled(work[value_col])
        & bpp.ne('ZZZZZZZZZZ')
        & work['LOOKUP_MATERIAL_TYPE'].astype(str).str.upper().str.startswith('ZFG')
    )
    scoped = work.loc[scope].copy()
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненных BPP-кодов для материалов MTART LIKE ZFG%', stats)

    primary = _load(loader, 'ZMDM_BPP_CODET')
    valid_codes = _bpp_reference_codes(primary)
    if valid_codes:
        stats['reference'] = 'ZMDM_BPP_CODET'
    else:
        fallback = _load(loader, 'ZMDM_BPP_CODE')
        valid_codes = _bpp_reference_codes(fallback)
        if valid_codes:
            stats['reference'] = 'ZMDM_BPP_CODE'
    if not valid_codes:
        return _empty_result(
            f'{rc}: ZMDM_BPP_CODET и fallback ZMDM_BPP_CODE отсутствуют или не содержат колонку кода',
            stats,
        )

    scoped['LOOKUP_BPP_REFERENCE'] = stats['reference']
    ok = _codes(scoped[value_col]).isin(valid_codes)
    stats['evaluated'] = len(scoped)
    return _result(scoped, ok, rc, stats)


def evaluate_material_rule(
    df: pd.DataFrame,
    table_name: str,
    rule_code: str,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = str(rule_code).strip().upper()
    table = str(table_name).strip().upper()
    if rc in MARA_RULE_CODES and table == 'MARA':
        return evaluate_mara_rule(df, rc, value_col, _load(loader, 'MAKT'))
    if rc in MAKT_RULE_CODES and table == 'MAKT':
        return evaluate_makt_rule(df, rc, value_col)
    if rc in AUSP_RULE_CODES and table == 'AUSP':
        return evaluate_ausp_bpp_rule(df, rc, value_col, loader)
    return _empty_result(f'{rc}: неверная таблица {table} для material evaluator')
