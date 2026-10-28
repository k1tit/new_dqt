"""Evaluators for Product Conformity rules based on dm_product_general."""
from __future__ import annotations

import json
import os
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
MARC_RULE_CODES = frozenset({'RPCONF_160.4', 'RPCONF_284.1', 'RPCONF_284.2', 'RPCOMP_148.1'})
MVKE_RULE_CODES = frozenset({'RPCOMP_149.1', 'RPCOMP_153.1', 'RPCOMP_199.1', 'RPCOMP_252.1', 'RPCOMP_262.1'})
MATERIAL_RULE_CODES = MARA_RULE_CODES | MAKT_RULE_CODES | AUSP_RULE_CODES | MARC_RULE_CODES | MVKE_RULE_CODES
MATERIAL_BPP_AUSP_TABLE = 'AUSP 829.861'
MATERIAL_AUSP_TABLES = frozenset({
    'AUSP',
    'AUSP_EQUIPMENT',
    'AUSP_MATERIAL',
    'AUSP_CLASS',
    'AUSP_CLASSIFICATION',
    MATERIAL_BPP_AUSP_TABLE,
})
AUSP_TABLE_NAMES_SENTINEL = '__AUSP_TABLE_NAMES__'
CUSTOMER_AUSP_SLICES = frozenset({'AUSP_143', 'AUSP_148', 'AUSP_151', 'AUSP_604'})

FINISHED_GOODS_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZFGM', 'ZFGA', 'ZNVM'})
BPP_ATNAM = 'CCHBC_BPP_CODE'
BPP_ATINN_CODES = frozenset({'829', '868'})
EQUIPMENT_ATINN_CODES = frozenset({'24', '27', '30', '52'})
CUSTOMER_ATINN_CODES = frozenset({'143', '148', '151', '604'})
MATERIAL_AUSP_ATINN_BY_RULE = {
    'RPCONF_53.1': BPP_ATINN_CODES,
}


def material_ausp_atinn_values(rule_code: str) -> frozenset[str]:
    rc = str(rule_code or '').strip().upper()
    return MATERIAL_AUSP_ATINN_BY_RULE.get(rc, frozenset())


def _format_atinn_list(values) -> str:
    vals = [str(v) for v in values if v]
    return ','.join(sorted(vals, key=lambda x: (0, int(x)) if x.isdigit() else (1, x)))


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
    'RPCONF_225.4': 'MAKTX must be uppercase.',
    'RPCONF_225.5': 'MAKTX must not start/end with whitespace or contain multiple consecutive whitespace characters.',
    'RPCONF_253.4': 'MATKL for MTART ZFGC must be one of 1111005/1111006/1111007/1111009/1113002.',
    'RPCONF_265.1': 'MHDRZ must be less than or equal to MHDHB for Finished Goods.',
    'RPCONF_371.1': 'GEWEI must be KG for MTART ZFG/ZFGS/ZFGC/ZFGM/ZFGA/ZNVM.',
    'RPCONF_53.1': 'AUSP 829.861 ATWRT of a ZFG* material (ATINN CCHBC_BPP_CODE, KLART=001) is not in CAWN_M/CAWNT_M ATWRT. Empty ATWRT and ZZZZZZZZZZ are out of scope.',
    'RPCONF_160.4': 'MTVFP must be 02 or Z2 for MTART ZNVM. Empty MTVFP is out of scope.',
    'RPCONF_284.1': 'DISMM must be ND when MARA.MSTAE=99, otherwise X0 or ND, for finished and semi-finished materials. Empty DISMM is out of scope.',
    'RPCONF_284.2': 'DISMM must be ZB, PD or ND for MTART ZSPS. Empty DISMM is out of scope.',
    'RPCOMP_148.1': 'MAABC must be filled for MTART ZFG/ZFGS/ZFGC/ZNVM when MMSTA is not 99, 98 or 97 and the MARA description is not ABP.',
    'RPCOMP_149.1': 'KTGRM must be filled for the listed material types when VKORG is not 0001 and MATKL is not 1110000.',
    'RPCOMP_153.1': 'ZZ_KONDM must be filled for ZFG* on sales org 0001 and distribution channel 01 when the product hierarchy is in scope.',
    'RPCOMP_199.1': 'MTPOS must be filled when MTART is not ZCDS.',
    'RPCOMP_252.1': 'KONDM must be filled for ZFG* on sales org 0001 and distribution channel 01 when the product hierarchy is in scope.',
    'RPCOMP_262.1': 'MVGR3 must be filled for finished-goods types, and for ZSF/ZNVL when MATKL is 1001009 or 1003012.',
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


def _atinn_codes(series: pd.Series) -> pd.Series:
    text = _codes(series)

    def _norm(value: str) -> str:
        if not value:
            return ''
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            stripped = value.lstrip('0')
            return stripped or '0'

    return text.map(_norm)


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
        'error_description': ERROR_DESCRIPTIONS.get(rule_code, rule_code),
        'skip_reason': None,
        'stats': stats,
    }


_RU_REGION = re.compile(r'(?<![A-Za-z0-9])RU(?![A-Za-z0-9])')


def description_has_ru_region(series: pd.Series) -> pd.Series:
    text = series.astype(str)
    return series.notna() & text.str.contains(_RU_REGION, na=False)


def _english_makt(makt: pd.DataFrame) -> tuple[pd.DataFrame, Optional[str]]:
    if makt is None or makt.empty:
        return pd.DataFrame(), None
    spras_col = find_col(makt, ('SPRAS', 'LANGU', 'LANGUAGE', 'LANG'))
    if not spras_col:
        return makt.copy(), None
    language = _codes(makt[spras_col])
    english = makt.loc[language.eq('E') | language.eq('EN')].copy()
    return english, spras_col


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
    ru = description_has_ru_region(work[desc_col])
    work = work.loc[ru].copy()
    stats['after_ru'] = len(work)
    if work.empty:
        return work, stats, f'{rule_code}: нет материалов с регионом RU отдельным словом в MAKTX'
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
    stats = {'input': len(makt) if makt is not None else 0, 'evaluated': 0}
    if makt is None or makt.empty:
        return _empty_result(f'{rc}: MAKT пуст', stats)
    if not value_col or value_col not in makt.columns:
        value_col = find_col(makt, ('MAKTX', 'material_description')) or value_col
    if not value_col or value_col not in makt.columns:
        return _empty_result(f'{rc}: MAKT.MAKTX не найден', stats)

    scoped = makt.loc[_filled(makt[value_col])].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненных MAKT.MAKTX', stats)
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


def _bpp_key_forms(code: str) -> set[str]:
    if not code:
        return set()
    forms = {code}
    if code.isdigit():
        forms.add(code.lstrip('0') or '0')
    return forms


def _expand_bpp_codes(codes: set[str]) -> set[str]:
    out = set()
    for code in codes:
        out |= _bpp_key_forms(code)
    return out


def _bpp_code_matches(code: str, valid_codes: set[str]) -> bool:
    return bool(_bpp_key_forms(code) & valid_codes)


def _atwrt_codes(frame: pd.DataFrame, code_col: str) -> set[str]:
    if frame is None or frame.empty or not code_col:
        return set()
    return set(_codes(frame[code_col])) - {''}


def _bpp_reference_codes(reference: pd.DataFrame) -> set[str]:
    if reference is None or reference.empty:
        return set()
    code_col = find_col(reference, ('ATWRT', 'BPP_CODE'))
    if not code_col:
        return set()
    all_codes = _atwrt_codes(reference, code_col)
    name_col = find_col(reference, ('ATWTB', 'BPP_NAME'))
    if not name_col:
        return all_codes
    named = _atwrt_codes(reference.loc[_filled(reference[name_col])], code_col)
    return named or all_codes


def _bpp_codes_from_cawn(cawn: pd.DataFrame, atinn_needed) -> set[str]:
    if cawn is None or cawn.empty:
        return set()
    code_col = find_col(cawn, ('ATWRT', 'BPP_CODE'))
    if not code_col:
        return set()
    all_codes = _atwrt_codes(cawn, code_col)
    atinn_col = find_col(cawn, ('ATINN',))
    if not atinn_col or not atinn_needed:
        return all_codes
    scoped = cawn.loc[_atinn_codes(cawn[atinn_col]).isin(atinn_needed)]
    return _atwrt_codes(scoped, code_col) or all_codes


def _bpp_codes_from_cawn_pair(cawn: pd.DataFrame, cawnt: pd.DataFrame, atinn_needed) -> tuple[set[str], str]:
    cawn_codes = _bpp_codes_from_cawn(cawn, atinn_needed)
    if cawnt is None or cawnt.empty:
        if cawn_codes:
            return cawn_codes, 'CAWN_M'
        return set(), ''
    atwrt_col = find_col(cawn, ('ATWRT', 'BPP_CODE', 'CODE', 'VALUE')) if cawn is not None and not cawn.empty else None
    atinn_c = find_col(cawn, ('ATINN',)) if cawn is not None and not cawn.empty else None
    atzhl_c = find_col(cawn, ('ATZHL',)) if cawn is not None and not cawn.empty else None
    atinn_t = find_col(cawnt, ('ATINN',))
    atzhl_t = find_col(cawnt, ('ATZHL',))
    atwtb = find_col(cawnt, ('ATWTB', 'ATWRT', 'BPP_CODE'))
    if atwrt_col and atinn_c and atzhl_c and atinn_t and atzhl_t and atwtb:
        work = cawn
        if atinn_needed:
            work = work.loc[_atinn_codes(work[atinn_c]).isin(atinn_needed)]
        texts = cawnt.loc[_filled(cawnt[atwtb])]
        named = set(zip(_atinn_codes(texts[atinn_t]).tolist(), _atinn_codes(texts[atzhl_t]).tolist()))
        if named and not work.empty:
            keys = list(zip(_atinn_codes(work[atinn_c]).tolist(), _atinn_codes(work[atzhl_c]).tolist()))
            mask = pd.Series([(k in named) for k in keys], index=work.index)
            joined = set(_codes(work.loc[mask, atwrt_col])) - {''}
            if joined:
                return joined, 'CAWN_M+CAWNT_M'
    t_codes = _bpp_codes_from_cawn(cawnt, atinn_needed)
    if cawn_codes and t_codes:
        both = cawn_codes & t_codes
        if both:
            return both, 'CAWN_M+CAWNT_M'
    if cawn_codes:
        return cawn_codes, 'CAWN_M'
    if t_codes:
        return t_codes, 'CAWNT_M'
    return set(), ''


def _frame_atwrt(frame: pd.DataFrame) -> set[str]:
    if frame is None or getattr(frame, 'empty', True):
        return set()
    code_col = find_col(frame, ('ATWRT', 'BPP_CODE'))
    if not code_col:
        return set()
    return _atwrt_codes(frame, code_col)


def _resolve_bpp_reference(
    loader: Callable[[str], pd.DataFrame],
    atinn_needed,
) -> tuple[set[str], str]:
    del atinn_needed
    found: list[tuple[str, set[str]]] = []
    for name in ('CAWN_M', 'CAWNT_M'):
        codes = _frame_atwrt(_load(loader, name))
        if codes:
            found.append((name, codes))
    if not found:
        return set(), ''
    codes = set()
    for _source, part in found:
        codes |= part
    return _expand_bpp_codes(codes), '+'.join(source for source, _part in found)


def _cabn_filter_json_path() -> str:
    return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'json files', 'ausp_cabn_filter.json'))


def _atinn_from_cabn(cabn: pd.DataFrame, atnam: str) -> set[str]:
    if cabn is None or cabn.empty:
        return set()
    atnam_col = find_col(cabn, ('ATNAM', 'CHARACT', 'CHARACTERISTIC', 'ATNAME'))
    atinn_col = find_col(cabn, ('ATINN',))
    if not atnam_col or not atinn_col:
        return set()
    names = _codes(cabn[atnam_col])
    matched = cabn.loc[names.eq(str(atnam).strip().upper()), atinn_col]
    return set(_atinn_codes(matched)) - {''}


def _atinn_from_cabn_filter_json(atnam: str) -> set[str]:
    path = _cabn_filter_json_path()
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError, TypeError):
        return set()
    rows = data.get('rows', data if isinstance(data, list) else [])
    target = str(atnam).strip().upper()
    out = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get('ATNAM') or '').strip().upper() != target:
            continue
        for key in ('ATINN_CL1', 'ATINN_CL2', 'ATINN'):
            raw = row.get(key)
            if raw is None or str(raw).strip() == '':
                continue
            try:
                out.add(str(int(float(str(raw).strip()))))
            except (TypeError, ValueError):
                text = str(raw).strip().lstrip('0')
                if text:
                    out.add(text)
    return out


def resolve_bpp_atinn_codes(loader: Callable[[str], pd.DataFrame]) -> tuple[frozenset[str], str]:
    from_cabn = _atinn_from_cabn(_load(loader, 'CABN'), BPP_ATNAM)
    if from_cabn:
        return frozenset(from_cabn), 'CABN.ATNAM=CCHBC_BPP_CODE'
    from_json = _atinn_from_cabn_filter_json(BPP_ATNAM)
    if from_json:
        return frozenset(from_json), 'ausp_cabn_filter.json CCHBC_BPP_CODE'
    return frozenset(BPP_ATINN_CODES), 'fallback ATINN 829/868'


def is_material_bpp_ausp_table(name: str) -> bool:
    return str(name or '').strip().upper() == MATERIAL_BPP_AUSP_TABLE.upper()


def _is_material_ausp_table_name(name: str) -> bool:
    u = str(name or '').strip().upper()
    return u == 'AUSP' or u.startswith('AUSP_') or is_material_bpp_ausp_table(u)


MATERIAL_MARC_MATNR_TABLES = frozenset({'MARA', 'MAKT', 'MARC', 'MVKE'})


def material_table_uses_marc_matnr_scope(table_name: str) -> bool:
    u = str(table_name or '').strip().upper()
    return u in MATERIAL_MARC_MATNR_TABLES


def marc_matnr_key_set(marc: pd.DataFrame) -> set[str]:
    if marc is None or marc.empty:
        return set()
    col = find_col(marc, ('MATNR', 'material_code', 'MATERIAL', 'MATERIAL_NUMBER'))
    if not col:
        return set()
    return {key for key in _matnr(marc[col]).tolist() if key and key != '0'}


def filter_frame_to_marc_matnrs(df: pd.DataFrame, table_name: str, allowed: set[str]):
    """Keep rows whose material number is in MARC.MATNR."""
    empty = df.iloc[0:0].copy() if df is not None else pd.DataFrame()
    if not material_table_uses_marc_matnr_scope(table_name):
        return df, None, None
    if df is None or df.empty:
        return empty, None, None
    names = ('MATNR', 'material_code', 'MATERIAL', 'MATERIAL_NUMBER')
    col = None
    for name in names:
        col = find_col(df, (name,))
        if col:
            break
    if not col:
        return empty, None, 'колонка MATNR не найдена'
    if not allowed:
        return empty, col, 'MARC.MATNR пуст'
    keys = _matnr(df[col])
    return df.loc[keys.isin(allowed)].copy(), col, None


def _sample_atinn_text(df: pd.DataFrame) -> str:
    atinn_col = find_col(df, ('ATINN',))
    if not atinn_col:
        return 'нет ATINN'
    present = {v for v in set(_atinn_codes(df[atinn_col])) if v}
    return _format_atinn_list(present) or 'пусто'


def _klart_is_material_class(series: pd.Series) -> pd.Series:
    codes = _codes(series)
    return codes.eq('001') | codes.eq('01') | codes.eq('1')


def _pick_material_ausp_frame(
    ausp: pd.DataFrame,
    table_name: str,
    loader: Callable[[str], pd.DataFrame],
    atinn_needed,
) -> tuple[pd.DataFrame, str, list[tuple[str, str]]]:
    requested = str(table_name or '').strip().upper() or MATERIAL_BPP_AUSP_TABLE
    if is_material_bpp_ausp_table(requested) and ausp is not None and not getattr(ausp, 'empty', True):
        return ausp, MATERIAL_BPP_AUSP_TABLE, [(MATERIAL_BPP_AUSP_TABLE, _sample_atinn_text(ausp))]
    pinned = _load(loader, MATERIAL_BPP_AUSP_TABLE)
    if pinned is not None and not getattr(pinned, 'empty', True):
        return pinned, MATERIAL_BPP_AUSP_TABLE, [(MATERIAL_BPP_AUSP_TABLE, _sample_atinn_text(pinned))]
    return pd.DataFrame(), MATERIAL_BPP_AUSP_TABLE, [(MATERIAL_BPP_AUSP_TABLE, 'нет строк')]


def evaluate_ausp_bpp_rule(
    ausp: pd.DataFrame,
    rule_code: str,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
    table_name: str = MATERIAL_BPP_AUSP_TABLE,
) -> dict:
    rc = str(rule_code).strip().upper()
    atinn_needed, atinn_source = resolve_bpp_atinn_codes(loader)
    ausp, ausp_table, table_samples = _pick_material_ausp_frame(ausp, table_name, loader, atinn_needed)
    stats = {
        'input': len(ausp) if ausp is not None else 0,
        'bpp_rows': 0,
        'evaluated': 0,
        'reference': '',
        'bpp_atinn': _format_atinn_list(atinn_needed),
        'bpp_atinn_source': atinn_source,
        'ausp_table': ausp_table,
    }
    atinn_col = find_col(ausp, ('ATINN',))
    objek_col = find_col(ausp, ('OBJEK', 'MATNR', 'MATERIAL'))
    if value_col not in (ausp.columns if ausp is not None else []):
        value_col = find_col(ausp, ('ATWRT', value_col or 'ATWRT')) or value_col
    if ausp is None or ausp.empty:
        return _empty_result(f'{rc}: таблица {ausp_table} пуста (нужен CCHBC_BPP_CODE в {ausp_table}, KLART=001)', stats)
    if not atinn_col or not objek_col or not value_col or value_col not in ausp.columns:
        return _empty_result(f'{rc}: {ausp_table}.ATINN/OBJEK/ATWRT не найдены', stats)

    atinn = _atinn_codes(ausp[atinn_col])
    present = [v for v in set(atinn) if v]
    present_ordered = _format_atinn_list(present).split(',') if present else []
    stats['ausp_atinn_sample'] = ','.join([p for p in present_ordered if p][:20])
    work = ausp.loc[atinn.isin(atinn_needed)].copy()
    klart_col = find_col(work, ('KLART', 'CLASS_TYPE'))
    if klart_col:
        work = work.loc[_klart_is_material_class(work[klart_col])].copy()
    work = _dedupe_bpp_ausp(work, atinn_col, objek_col)
    stats['bpp_rows'] = len(work)
    if work.empty:
        present_s = stats['ausp_atinn_sample'] or 'пусто'
        extra = ''
        present_set = set(present)
        if present_set and present_set <= EQUIPMENT_ATINN_CODES:
            extra = (
                ' Это cooler AUSP_EQUIPMENT (ATINN 24/27/30/52), не BPP материала. '
                'CCHBC_BPP_CODE — CABN.ATNAM → ATINN (обычно 829/868), ATWRT, KLART=001. '
                'Нужен дамп классификации материалов в AUSP (не customer 143/148/151/604 и не cooler).'
            )
        elif present_set and present_set <= CUSTOMER_ATINN_CODES:
            extra = (
                ' Это customer AUSP (143/148/151/604), не BPP. '
                'RPCONF_53.1 читает AUSP классификации: ATWRT по ATINN из CABN.ATNAM=CCHBC_BPP_CODE.'
            )
        other = [f'{name} ATINN={sample}' for name, sample in table_samples if name != ausp_table]
        if other:
            extra += ' Проверены также: ' + '; '.join(other) + '.'
        return _empty_result(
            f'{rc}: нет {BPP_ATNAM} в {ausp_table} (ATINN {{{stats["bpp_atinn"]}}} из {atinn_source}, KLART=001). '
            f'В таблице ATINN: {present_s}.{extra}',
            stats,
        )

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

    valid_codes, reference_name = _resolve_bpp_reference(loader, atinn_needed)
    if not valid_codes:
        return _empty_result(
            f'{rc}: нет справочника BPP. В CAWN_M/CAWNT_M нет значений ATWRT.',
            stats,
        )
    stats['reference'] = reference_name

    scoped['LOOKUP_BPP_REFERENCE'] = stats['reference']
    ok = _codes(scoped[value_col]).map(lambda code: _bpp_code_matches(code, valid_codes))
    stats['evaluated'] = len(scoped)
    return _result(scoped, ok, rc, stats)


def _marc_with_material_context(marc: pd.DataFrame, loader: Callable[[str], pd.DataFrame], rule_code: str):
    stats = {'input': len(marc) if marc is not None else 0}
    if marc is None or marc.empty:
        return None, stats, f'{rule_code}: MARC пуст'
    matnr_col = find_col(marc, ('MATNR', 'material_code', 'MATERIAL'))
    if not matnr_col:
        return None, stats, f'{rule_code}: MARC.MATNR не найден'
    mara = _load(loader, 'MARA')
    exact_type, simple_type, mara_has_cluster = _material_type_lookup(mara)
    if not simple_type:
        return None, stats, f'{rule_code}: MARA.MATNR/MTART не найдены'
    from utils.dm_product_plant import apply_is_basic_scope, apply_ru_marc_plant_scope
    work, plant_col, plant_skip = apply_ru_marc_plant_scope(marc)
    if plant_skip:
        return None, stats, f'{rule_code}: {plant_skip}'
    stats['after_plant_scope'] = len(work)
    if work.empty:
        return None, stats, f'{rule_code}: нет строк MARC с Plnt/WERKS 36*/38*/39* ({plant_col})'
    work = apply_is_basic_scope(work).copy()
    stats['after_basic_scope'] = len(work)
    work['_DQ_MATNR'] = _matnr(work[matnr_col])
    cluster_col = find_col(work, ('SAP_CLUSTER', 'CLUSTER'))
    if mara_has_cluster and cluster_col and exact_type:
        clusters = _codes(work[cluster_col])
        work['LOOKUP_MATERIAL_TYPE'] = [
            exact_type.get((cluster, matnr), '')
            for cluster, matnr in zip(clusters, work['_DQ_MATNR'])
        ]
    else:
        work['LOOKUP_MATERIAL_TYPE'] = work['_DQ_MATNR'].map(simple_type).fillna('')
    english, _spras = _english_makt(_load(loader, 'MAKT'))
    makt_matnr = find_col(english, ('MATNR', 'material_code', 'MATERIAL'))
    maktx_col = find_col(english, ('MAKTX', 'material_description'))
    if english.empty or not makt_matnr or not maktx_col:
        return None, stats, f'{rule_code}: MAKT.MAKTX (SPRAS=E) не найден — нельзя применить NOT LIKE %ABP%'
    keys = _matnr(english[makt_matnr])
    values = english[maktx_col]
    valid = keys.ne('0') & _filled(values)
    lookup = (
        pd.DataFrame({'key': keys.loc[valid], 'value': values.loc[valid]})
        .drop_duplicates('key', keep='first')
        .set_index('key')['value']
        .to_dict()
    )
    work['LOOKUP_MATERIAL_DESCRIPTION'] = work['_DQ_MATNR'].map(lookup)
    desc = work['LOOKUP_MATERIAL_DESCRIPTION']
    if int(_filled(desc).sum()) == 0:
        return None, stats, f'{rule_code}: MARC не сджойнился с MAKT по MATNR'
    ru = description_has_ru_region(desc)
    work = work.loc[ru].copy()
    stats['after_ru'] = len(work)
    if work.empty:
        return None, stats, f'{rule_code}: нет строк с регионом RU отдельным словом в LOOKUP_MATERIAL_DESCRIPTION'
    desc = work['LOOKUP_MATERIAL_DESCRIPTION']
    work = work.loc[_filled(desc) & ~desc.astype(str).str.contains('ABP', case=False, na=False)].copy()
    return work, stats, None


def _mara_status_lookup(mara: pd.DataFrame) -> tuple[dict, dict, bool]:
    matnr_col = find_col(mara, ('MATNR', 'material_code', 'MATERIAL'))
    status_col = find_col(mara, ('MSTAE', 'material_status_code', 'CROSS_PLANT_MATERIAL_STATUS'))
    cluster_col = find_col(mara, ('SAP_CLUSTER', 'CLUSTER'))
    if not matnr_col or not status_col:
        return {}, {}, False
    exact = {}
    simple = {}
    for idx in mara.index:
        matnr = _matnr(pd.Series([mara.at[idx, matnr_col]])).iloc[0]
        status = _codes(pd.Series([mara.at[idx, status_col]])).iloc[0]
        cluster = _codes(pd.Series([mara.at[idx, cluster_col]])).iloc[0] if cluster_col else ''
        if matnr:
            simple.setdefault(matnr, status)
            if cluster:
                exact.setdefault((cluster, matnr), status)
    return exact, simple, bool(cluster_col)


def _finished_or_semi(material_type: pd.Series) -> pd.Series:
    types = material_type.astype(str).str.strip().str.upper()
    listed = frozenset({'ZFG', 'ZFGS', 'ZFGM', 'ZFGA', 'ZFGC', 'ZNVM', 'ZSF', 'ZNVL', 'ZSFT', 'ZRWT'})
    return types.isin(listed) | types.str.startswith('ZRW') | types.str.startswith('ZSF')


def evaluate_rpconf_160_4(
    marc: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCONF_160.4'
    work, stats, skip = _marc_with_material_context(marc, loader, rc)
    stats['evaluated'] = 0
    stats['skipped_empty_mtvfp'] = 0
    if skip:
        return _empty_result(skip, stats)
    mtvfp_col = value_col if value_col in work.columns else find_col(work, ('MTVFP', 'availability_checking_group'))
    if not mtvfp_col:
        return _empty_result(f'{rc}: MARC.MTVFP не найден', stats)
    znvm = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.upper().eq('ZNVM')
    filled = _filled(work[mtvfp_col])
    stats['skipped_empty_mtvfp'] = int((znvm & ~filled).sum())
    scoped = work.loc[znvm & filled].copy()
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненного MTVFP для MTART=ZNVM', stats)
    ok = _codes(scoped[mtvfp_col]).isin({'02', 'Z2'})
    stats['evaluated'] = len(scoped)
    return _result(scoped, ok, rc, stats)


def evaluate_rpconf_284_1(
    marc: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCONF_284.1'
    work, stats, skip = _marc_with_material_context(marc, loader, rc)
    stats['evaluated'] = 0
    stats['skipped_empty_dismm'] = 0
    if skip:
        return _empty_result(skip, stats)
    dismm_col = value_col if value_col in work.columns else find_col(work, ('DISMM', 'mrp_type'))
    mmsta_col = find_col(work, ('MMSTA', 'material_status_code'))
    if not dismm_col or not mmsta_col:
        return _empty_result(f'{rc}: MARC.DISMM/MMSTA не найдены', stats)
    exact_status, simple_status, mara_has_cluster = _mara_status_lookup(_load(loader, 'MARA'))
    if not simple_status and not exact_status:
        return _empty_result(f'{rc}: MARA.MSTAE не найден', stats)
    cluster_col = find_col(work, ('SAP_CLUSTER', 'CLUSTER'))
    if mara_has_cluster and cluster_col and exact_status:
        clusters = _codes(work[cluster_col])
        work['LOOKUP_CROSS_PLANT_STATUS'] = [
            exact_status.get((cluster, matnr), '')
            for cluster, matnr in zip(clusters, work['_DQ_MATNR'])
        ]
    else:
        work['LOOKUP_CROSS_PLANT_STATUS'] = work['_DQ_MATNR'].map(simple_status).fillna('')

    filled = _filled(work[dismm_col])
    plant_blocked = _codes(work[mmsta_col]).eq('99')
    in_type = _finished_or_semi(work['LOOKUP_MATERIAL_TYPE'])
    stats['skipped_empty_dismm'] = int((~filled).sum())
    scoped = work.loc[filled & plant_blocked & in_type].copy()
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненного DISMM при MMSTA=99 для готовой и полуготовой продукции', stats)
    dismm = _codes(scoped[dismm_col])
    cross_blocked = _codes(scoped['LOOKUP_CROSS_PLANT_STATUS']).eq('99')
    ok = (cross_blocked & dismm.eq('ND')) | (~cross_blocked & dismm.isin({'X0', 'ND'}))
    stats['evaluated'] = len(scoped)
    return _result(scoped, ok, rc, stats)


def evaluate_rpconf_284_2(
    marc: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCONF_284.2'
    work, stats, skip = _marc_with_material_context(marc, loader, rc)
    stats['evaluated'] = 0
    stats['skipped_empty_dismm'] = 0
    if skip:
        return _empty_result(skip, stats)
    dismm_col = value_col if value_col in work.columns else find_col(work, ('DISMM', 'mrp_type'))
    mmsta_col = find_col(work, ('MMSTA', 'material_status_code'))
    if not dismm_col or not mmsta_col:
        return _empty_result(f'{rc}: MARC.DISMM/MMSTA не найдены', stats)
    filled = _filled(work[dismm_col])
    plant_blocked = _codes(work[mmsta_col]).eq('99')
    zsps = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.strip().str.upper().eq('ZSPS')
    stats['skipped_empty_dismm'] = int((zsps & ~filled).sum())
    scoped = work.loc[filled & plant_blocked & zsps].copy()
    if scoped.empty:
        return _empty_result(f'{rc}: нет заполненного DISMM при MMSTA=99 для MTART=ZSPS', stats)
    ok = _codes(scoped[dismm_col]).isin({'ZB', 'PD', 'ND'})
    stats['evaluated'] = len(scoped)
    return _result(scoped, ok, rc, stats)


KTGRM_MATERIAL_TYPES = frozenset({
    'ZFG', 'ZFGS', 'ZFGC', 'ZFGA', 'ZFGM', 'ZNVM', 'ZRE', 'ZSF', 'ZSV', 'ZSTL', 'ZRW',
})
SS_SM_HIERARCHY_L4 = frozenset({
    '01010012001', '01010012015', '01010012117', '01010012123', '01010012031',
    '01010012041', '01010012055', '01010022155', '01010012060', '01010032163',
    '01010012069', '01010012083', '01010012093', '01010012097', '01010012107',
    '01030042179', '01010032169', '01030052301', '01030052315', '01049882988',
    '01049992999', '01010022133', '01010022145', '01010012137',
})
SS_SM_HIERARCHY_L5 = '010100120832085'
SS_SM_HIERARCHY_L3 = '0206008'


def _zfill_code(series: pd.Series, width: int) -> pd.Series:
    codes = _codes(series)

    def _one(value: str) -> str:
        if not value:
            return ''
        if value.isdigit():
            return value.zfill(width)
        return value

    return codes.map(_one)


def _mara_code_lookup(mara: pd.DataFrame, column_names: Sequence[str]) -> dict:
    matnr_col = find_col(mara, ('MATNR', 'material_code', 'MATERIAL'))
    value_col = find_col(mara, column_names)
    if mara is None or mara.empty or not matnr_col or not value_col:
        return {}
    keys = _matnr(mara[matnr_col])
    values = _codes(mara[value_col])
    out = {}
    for key, value in zip(keys, values):
        if key and key != '0' and value and key not in out:
            out[key] = value
    return out


def _description_lookup(makt: pd.DataFrame) -> dict:
    english, _spras = _english_makt(makt)
    makt_matnr = find_col(english, ('MATNR', 'material_code', 'MATERIAL'))
    maktx_col = find_col(english, ('MAKTX', 'material_description'))
    if english.empty or not makt_matnr or not maktx_col:
        return {}
    keys = _matnr(english[makt_matnr])
    values = english[maktx_col]
    valid = keys.ne('0') & _filled(values)
    frame = pd.DataFrame({'key': keys.loc[valid], 'value': values.loc[valid]})
    return frame.drop_duplicates('key', keep='first').set_index('key')['value'].to_dict()


def _mvke_with_material_context(
    mvke: pd.DataFrame,
    loader: Callable[[str], pd.DataFrame],
    rule_code: str,
    exclude_abp: bool = True,
):
    stats = {'input': len(mvke) if mvke is not None else 0}
    if mvke is None or mvke.empty:
        return None, stats, f'{rule_code}: MVKE пуст'
    matnr_col = find_col(mvke, ('MATNR', 'material_code', 'MATERIAL'))
    if not matnr_col:
        return None, stats, f'{rule_code}: MVKE.MATNR не найден'
    mara = _load(loader, 'MARA')
    types = _mara_code_lookup(mara, ('MTART', 'material_type_code'))
    groups = _mara_code_lookup(mara, ('MATKL', 'material_group_code'))
    if not types:
        return None, stats, f'{rule_code}: MARA.MATNR/MTART не найдены'
    if not groups:
        return None, stats, f'{rule_code}: MARA.MATKL не найден'
    work = mvke.copy()
    work['_DQ_MATNR'] = _matnr(work[matnr_col])
    work['LOOKUP_MATERIAL_TYPE'] = work['_DQ_MATNR'].map(types).fillna('')
    work['LOOKUP_MATERIAL_GROUP'] = work['_DQ_MATNR'].map(groups).fillna('')
    if not exclude_abp:
        stats['after_abp'] = len(work)
        return work, stats, None
    descriptions = _description_lookup(_load(loader, 'MAKT'))
    if not descriptions:
        return None, stats, f'{rule_code}: MAKT.MAKTX (SPRAS=E) не найден — нельзя применить NOT LIKE %ABP%'
    work['LOOKUP_MATERIAL_DESCRIPTION'] = work['_DQ_MATNR'].map(descriptions)
    desc = work['LOOKUP_MATERIAL_DESCRIPTION']
    if int(_filled(desc).sum()) == 0:
        return None, stats, f'{rule_code}: MVKE не сджойнился с MAKT по MATNR'
    work = work.loc[_filled(desc) & ~desc.astype(str).str.contains('ABP', case=False, na=False)].copy()
    stats['after_abp'] = len(work)
    return work, stats, None


def _product_hierarchy_scope(work: pd.DataFrame) -> tuple[Optional[pd.Series], Optional[str]]:
    l4_col = find_col(work, ('product_hierarchy_l4_code', 'PRODH_L4'))
    l5_col = find_col(work, ('product_hierarchy_l5_code', 'PRODH_L5'))
    l3_col = find_col(work, ('product_hierarchy_l3_code', 'PRODH_L3'))
    if l4_col or l5_col or l3_col:
        hit = pd.Series(False, index=work.index)
        if l4_col:
            hit = hit | _codes(work[l4_col]).isin(SS_SM_HIERARCHY_L4)
        if l5_col:
            hit = hit | _codes(work[l5_col]).eq(SS_SM_HIERARCHY_L5)
        if l3_col:
            hit = hit | _codes(work[l3_col]).eq(SS_SM_HIERARCHY_L3)
        return hit, None
    prodh_col = find_col(work, ('PRODH', 'PRDHA', 'product_hierarchy', 'product_hierarchy_code'))
    if not prodh_col:
        return None, 'MVKE.PRODH не найден'
    text = _codes(work[prodh_col])
    hit = (
        text.str[:11].isin(SS_SM_HIERARCHY_L4)
        | text.str[:15].eq(SS_SM_HIERARCHY_L5)
        | text.eq(SS_SM_HIERARCHY_L5)
        | text.str[:7].eq(SS_SM_HIERARCHY_L3)
        | text.eq(SS_SM_HIERARCHY_L3)
    )
    return hit, None


def evaluate_rpcomp_149_1(
    mvke: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_149.1'
    work, stats, skip = _mvke_with_material_context(mvke, loader, rc)
    stats['evaluated'] = 0
    if skip:
        return _empty_result(skip, stats)
    ktgrm_col = value_col if value_col in work.columns else find_col(work, ('KTGRM', 'account_assignmnet_group_code', 'account_assignment_group_code'))
    vkorg_col = find_col(work, ('VKORG', 'sales_org_code', 'SALES_ORG'))
    if not ktgrm_col or not vkorg_col:
        return _empty_result(f'{rc}: MVKE.KTGRM/VKORG не найдены', stats)
    material_type = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.strip().str.upper()
    material_group = work['LOOKUP_MATERIAL_GROUP'].astype(str).str.strip().str.upper()
    sales_org = _zfill_code(work[vkorg_col], 4)
    scope = (
        material_type.isin(KTGRM_MATERIAL_TYPES)
        & sales_org.ne('')
        & sales_org.ne('0001')
        & material_group.ne('')
        & material_group.ne('1110000')
    )
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MVKE в scope KTGRM', stats)
    ok = _filled(scoped[ktgrm_col])
    return _result(scoped, ok, rc, stats)


def _technical_so_scope(work: pd.DataFrame):
    vkorg_col = find_col(work, ('VKORG', 'sales_org_code', 'SALES_ORG'))
    vtweg_col = find_col(work, ('VTWEG', 'distribution_channel_code', 'DCHL'))
    if not vkorg_col or not vtweg_col:
        return None, 'MVKE.VKORG/VTWEG не найдены'
    hierarchy, hierarchy_skip = _product_hierarchy_scope(work)
    if hierarchy_skip:
        return None, hierarchy_skip
    material_type = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.strip().str.upper()
    material_group = work['LOOKUP_MATERIAL_GROUP'].astype(str).str.strip().str.upper()
    sales_org = _zfill_code(work[vkorg_col], 4)
    channel = _zfill_code(work[vtweg_col], 2)
    scope = (
        material_group.ne('1110000')
        & material_type.str.startswith('ZFG')
        & sales_org.eq('0001')
        & channel.eq('01')
        & hierarchy.eq(True)
    )
    return scope, None


def evaluate_rpcomp_153_1(
    mvke: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_153.1'
    work, stats, skip = _mvke_with_material_context(mvke, loader, rc)
    stats['evaluated'] = 0
    if skip:
        return _empty_result(skip, stats)
    flag_col = value_col if value_col in work.columns else find_col(work, ('ZZ_KONDM', 'ss_sm_flag'))
    if not flag_col:
        return _empty_result(f'{rc}: MVKE.ZZ_KONDM не найден', stats)
    scope, scope_skip = _technical_so_scope(work)
    if scope_skip:
        return _empty_result(f'{rc}: {scope_skip}', stats)
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MVKE в scope ZZ_KONDM', stats)
    ok = _filled(scoped[flag_col])
    return _result(scoped, ok, rc, stats)


def evaluate_rpcomp_199_1(
    mvke: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_199.1'
    work, stats, skip = _mvke_with_material_context(mvke, loader, rc)
    stats['evaluated'] = 0
    if skip:
        return _empty_result(skip, stats)
    mtpos_col = value_col if value_col in work.columns else find_col(work, ('MTPOS', 'item_category_group_code'))
    if not mtpos_col:
        return _empty_result(f'{rc}: MVKE.MTPOS не найден', stats)
    material_type = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.strip().str.upper()
    scope = material_type.ne('') & material_type.ne('ZCDS')
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MVKE в scope MTPOS', stats)
    ok = _filled(scoped[mtpos_col])
    return _result(scoped, ok, rc, stats)


def evaluate_rpcomp_252_1(
    mvke: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_252.1'
    work, stats, skip = _mvke_with_material_context(mvke, loader, rc)
    stats['evaluated'] = 0
    if skip:
        return _empty_result(skip, stats)
    kondm_col = value_col if value_col in work.columns else find_col(work, ('KONDM', 'material_price_group_code'))
    if not kondm_col:
        return _empty_result(f'{rc}: MVKE.KONDM не найден', stats)
    scope, scope_skip = _technical_so_scope(work)
    if scope_skip:
        return _empty_result(f'{rc}: {scope_skip}', stats)
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MVKE в scope KONDM', stats)
    ok = _filled(scoped[kondm_col])
    return _result(scoped, ok, rc, stats)


MVGR3_FINISHED_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZFGA', 'ZFGM', 'ZNVM'})
MVGR3_SEMI_TYPES = frozenset({'ZSF', 'ZNVL'})
MVGR3_SEMI_GROUPS = frozenset({'1001009', '1003012'})


def evaluate_rpcomp_262_1(
    mvke: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_262.1'
    work, stats, skip = _mvke_with_material_context(mvke, loader, rc, exclude_abp=False)
    stats['evaluated'] = 0
    if skip:
        return _empty_result(skip, stats)
    mvgr3_col = value_col if value_col in work.columns else find_col(work, ('MVGR3', 'pack_type_code'))
    if not mvgr3_col:
        return _empty_result(f'{rc}: MVKE.MVGR3 не найден', stats)
    material_type = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.strip().str.upper()
    material_group = work['LOOKUP_MATERIAL_GROUP'].astype(str).str.strip().str.upper()
    scope = material_type.isin(MVGR3_FINISHED_TYPES) | (
        material_type.isin(MVGR3_SEMI_TYPES) & material_group.isin(MVGR3_SEMI_GROUPS)
    )
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MVKE в scope MVGR3', stats)
    ok = _filled(scoped[mvgr3_col])
    return _result(scoped, ok, rc, stats)


MAABC_MATERIAL_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZNVM'})
MMSTA_EXCLUDED_FROM_MAABC = frozenset({'99', '98', '97'})


def _mara_type_name_lookup(mara: pd.DataFrame) -> dict:
    if mara is None or mara.empty:
        return {}
    matnr_col = find_col(mara, ('MATNR', 'material_code', 'MATERIAL'))
    mtart_col = find_col(mara, ('MTART', 'material_type_code'))
    name_col = find_col(mara, ('MAKTX', 'material_description', 'MAKTG'))
    if not matnr_col or not mtart_col or not name_col:
        return {}
    frame = pd.DataFrame({
        'key': _matnr(mara[matnr_col]),
        'mtart': _codes(mara[mtart_col]),
        'name': mara[name_col].where(_filled(mara[name_col]), ''),
    })
    frame = frame.loc[frame['key'].ne('') & frame['key'].ne('0')]
    frame = frame.drop_duplicates('key', keep='first')
    return {
        row.key: {'mtart': row.mtart, 'name': row.name}
        for row in frame.itertuples(index=False)
    }


def evaluate_rpcomp_148_1(
    marc: pd.DataFrame,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
) -> dict:
    rc = 'RPCOMP_148.1'
    stats = {'input': len(marc) if marc is not None else 0, 'evaluated': 0}
    if marc is None or marc.empty:
        return _empty_result(f'{rc}: MARC пуст', stats)
    from utils.dm_product_plant import apply_ru_marc_plant_scope
    work, _plant_col, plant_skip = apply_ru_marc_plant_scope(marc)
    if plant_skip:
        return _empty_result(f'{rc}: {plant_skip}', stats)
    if work.empty:
        return _empty_result(f'{rc}: нет строк MARC с Plnt/WERKS 36*/38*/39*', stats)
    matnr_col = find_col(work, ('MATNR', 'material_code', 'MATERIAL'))
    mmsta_col = find_col(work, ('MMSTA', 'material_status_code'))
    maabc_col = value_col if value_col in work.columns else find_col(work, ('MAABC', 'abc_indicator'))
    if not matnr_col:
        return _empty_result(f'{rc}: MARC.MATNR не найден', stats)
    if not mmsta_col:
        return _empty_result(f'{rc}: MARC.MMSTA не найден', stats)
    if not maabc_col:
        return _empty_result(f'{rc}: MARC.MAABC не найден', stats)
    lookup = _mara_type_name_lookup(_load(loader, 'MARA'))
    if not lookup:
        return _empty_result(f'{rc}: MARA.MATNR/MTART/MAKTX не найдены', stats)
    work = work.copy()
    work['_DQ_MATNR'] = _matnr(work[matnr_col])
    work['LOOKUP_MATERIAL_TYPE'] = work['_DQ_MATNR'].map(lambda key: (lookup.get(key) or {}).get('mtart', ''))
    work['LOOKUP_MATERIAL_DESCRIPTION'] = work['_DQ_MATNR'].map(lambda key: (lookup.get(key) or {}).get('name', ''))
    mmsta = _codes(work[mmsta_col])
    material_type = work['LOOKUP_MATERIAL_TYPE'].astype(str).str.upper()
    description = work['LOOKUP_MATERIAL_DESCRIPTION'].astype(str)
    scope = (
        material_type.isin(MAABC_MATERIAL_TYPES)
        & ~mmsta.isin(MMSTA_EXCLUDED_FROM_MAABC)
        & description_has_ru_region(work['LOOKUP_MATERIAL_DESCRIPTION'])
        & ~description.str.contains('ABP', case=False, na=False)
    )
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _empty_result(f'{rc}: нет строк MARC для MAABC после MMSTA/MTART/RU/ABP', stats)
    ok = _filled(scoped[maabc_col])
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
    if rc in AUSP_RULE_CODES and _is_material_ausp_table_name(table):
        return evaluate_ausp_bpp_rule(df, rc, value_col, loader, table_name=table)
    if rc in MARC_RULE_CODES and table == 'MARC':
        if rc == 'RPCOMP_148.1':
            return evaluate_rpcomp_148_1(df, value_col, loader)
        if rc == 'RPCONF_284.1':
            return evaluate_rpconf_284_1(df, value_col, loader)
        if rc == 'RPCONF_284.2':
            return evaluate_rpconf_284_2(df, value_col, loader)
        return evaluate_rpconf_160_4(df, value_col, loader)
    if rc in MVKE_RULE_CODES and table == 'MVKE':
        if rc == 'RPCOMP_153.1':
            return evaluate_rpcomp_153_1(df, value_col, loader)
        if rc == 'RPCOMP_199.1':
            return evaluate_rpcomp_199_1(df, value_col, loader)
        if rc == 'RPCOMP_252.1':
            return evaluate_rpcomp_252_1(df, value_col, loader)
        if rc == 'RPCOMP_262.1':
            return evaluate_rpcomp_262_1(df, value_col, loader)
        return evaluate_rpcomp_149_1(df, value_col, loader)
    return _empty_result(f'{rc}: неверная таблица {table} для material evaluator')
