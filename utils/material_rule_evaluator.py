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
MATERIAL_RULE_CODES = MARA_RULE_CODES | MAKT_RULE_CODES | AUSP_RULE_CODES
MATERIAL_AUSP_TABLES = frozenset({
    'AUSP',
    'AUSP_EQUIPMENT',
    'AUSP_MATERIAL',
    'AUSP_CLASS',
    'AUSP_CLASSIFICATION',
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


def _bpp_codes_from_cawn(cawn: pd.DataFrame, atinn_needed) -> set[str]:
    if cawn is None or cawn.empty:
        return set()
    code_col = find_col(cawn, ('ATWRT', 'BPP_CODE', 'CODE', 'VALUE'))
    if not code_col:
        return set()
    work = cawn
    atinn_col = find_col(cawn, ('ATINN',))
    if atinn_col and atinn_needed:
        work = work.loc[_atinn_codes(work[atinn_col]).isin(atinn_needed)]
    spras_col = find_col(work, ('SPRAS', 'LANGU', 'LANGUAGE'))
    if spras_col:
        lang = _codes(work[spras_col])
        english = work.loc[lang.eq('E') | lang.eq('EN')]
        if not english.empty:
            work = english
    return set(_codes(work[code_col])) - {''}


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
        texts = cawnt
        spras = find_col(texts, ('SPRAS', 'LANGU', 'LANGUAGE'))
        if spras:
            lang = _codes(texts[spras])
            english = texts.loc[lang.eq('E') | lang.eq('EN')]
            if not english.empty:
                texts = english
        texts = texts.loc[_filled(texts[atwtb])]
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


def _resolve_bpp_reference(
    loader: Callable[[str], pd.DataFrame],
    atinn_needed,
) -> tuple[set[str], str]:
    codes, source = _bpp_codes_from_cawn_pair(_load(loader, 'CAWN_M'), _load(loader, 'CAWNT_M'), atinn_needed)
    if codes:
        return codes, source
    for name in ('ZMDM_BPP_CODET', 'ZMDM_BPP_CODE'):
        zmdm = _bpp_reference_codes(_load(loader, name))
        if zmdm:
            return zmdm, name
    for name in ('CAWN', 'CAWNT'):
        fallback = _bpp_codes_from_cawn(_load(loader, name), atinn_needed)
        if fallback:
            return fallback, f'{name} ATINN={_format_atinn_list(atinn_needed)}'
    return set(), ''


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


def _is_material_ausp_table_name(name: str) -> bool:
    u = str(name or '').strip().upper()
    return u == 'AUSP' or u.startswith('AUSP_')


def _sample_atinn_text(df: pd.DataFrame) -> str:
    atinn_col = find_col(df, ('ATINN',))
    if not atinn_col:
        return 'нет ATINN'
    present = {v for v in set(_atinn_codes(df[atinn_col])) if v}
    return _format_atinn_list(present) or 'пусто'


def _count_bpp_hits(df: pd.DataFrame, atinn_needed) -> int:
    if df is None or df.empty or not atinn_needed:
        return 0
    atinn_col = find_col(df, ('ATINN',))
    if not atinn_col:
        return 0
    atinn = _atinn_codes(df[atinn_col])
    work = df.loc[atinn.isin(atinn_needed)]
    if work.empty:
        return 0
    klart_col = find_col(work, ('KLART', 'CLASS_TYPE'))
    if klart_col:
        work = work.loc[_codes(work[klart_col]).eq('001')]
    return int(len(work))


def _ausp_pick_key(name: str, hits: int) -> tuple:
    u = str(name or '').strip().upper()
    if u == 'AUSP_EQUIPMENT':
        prio = 0
    elif u in ('AUSP_MATERIAL', 'AUSP_CLASS', 'AUSP_CLASSIFICATION'):
        prio = 1
    elif u == 'AUSP':
        prio = 5
    else:
        prio = 4
    return (-int(hits), prio, u)


def _discover_ausp_table_names(table_name: str, loader: Callable[[str], pd.DataFrame]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(name) -> None:
        u = str(name or '').strip().upper()
        if not u or u in seen or u in CUSTOMER_AUSP_SLICES:
            return
        if not _is_material_ausp_table_name(u):
            return
        seen.add(u)
        out.append(u)

    add(table_name)
    for name in ('AUSP_EQUIPMENT', 'AUSP_MATERIAL', 'AUSP_CLASS', 'AUSP_CLASSIFICATION', 'AUSP'):
        add(name)
    try:
        extra = loader(AUSP_TABLE_NAMES_SENTINEL)
    except Exception:
        extra = None
    if isinstance(extra, (list, tuple, set, frozenset)):
        for name in extra:
            add(name)
    elif isinstance(extra, pd.DataFrame) and not extra.empty:
        col = extra.columns[0]
        for name in extra[col].tolist():
            add(name)
    return out


def _pick_material_ausp_frame(
    ausp: pd.DataFrame,
    table_name: str,
    loader: Callable[[str], pd.DataFrame],
    atinn_needed,
) -> tuple[pd.DataFrame, str, list[tuple[str, str]]]:
    samples: list[tuple[str, str]] = []
    frames: dict[str, pd.DataFrame] = {}
    requested = str(table_name or '').strip().upper() or 'AUSP'
    if ausp is not None:
        frames[requested] = ausp
    for name in _discover_ausp_table_names(requested, loader):
        if name in frames:
            continue
        loaded = _load(loader, name)
        if loaded is not None and not loaded.empty:
            frames[name] = loaded
    scored = []
    for name, df in frames.items():
        samples.append((name, _sample_atinn_text(df)))
        hits = _count_bpp_hits(df, atinn_needed)
        if hits > 0:
            scored.append((name, df, hits))
    if scored:
        scored.sort(key=lambda item: _ausp_pick_key(item[0], item[2]))
        name, df, _hits = scored[0]
        return df, name, samples
    fallback = frames.get(requested)
    if fallback is None:
        fallback = frames.get('AUSP')
    if fallback is None and frames:
        name = next(iter(frames))
        return frames[name], name, samples
    if fallback is None:
        fallback = ausp if ausp is not None else pd.DataFrame()
    return fallback, requested, samples


def evaluate_ausp_bpp_rule(
    ausp: pd.DataFrame,
    rule_code: str,
    value_col: str,
    loader: Callable[[str], pd.DataFrame],
    table_name: str = 'AUSP_EQUIPMENT',
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
        work = work.loc[_codes(work[klart_col]).eq('001')].copy()
    work = _dedupe_bpp_ausp(work, atinn_col, objek_col)
    stats['bpp_rows'] = len(work)
    if work.empty:
        present_s = stats['ausp_atinn_sample'] or 'пусто'
        extra = ''
        present_set = set(present)
        if present_set and present_set <= EQUIPMENT_ATINN_CODES:
            extra = (
                ' В AUSP_EQUIPMENT сейчас только cooler ATINN 24/27/30/52. '
                'CCHBC_BPP_CODE — не колонка, это CABN.ATNAM → ATINN (обычно 829/868), значение в ATWRT, KLART=001. '
                'Догрузите в AUSP_EQUIPMENT строки BPP и таблицу CABN.'
            )
        elif present_set and present_set <= CUSTOMER_ATINN_CODES:
            extra = (
                ' Это customer AUSP (143/148/151/604), не BPP. '
                'RPCONF_53.1 читает AUSP_EQUIPMENT: ATWRT по ATINN из CABN.ATNAM=CCHBC_BPP_CODE.'
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
            f'{rc}: нет справочника BPP. Нет CAWN_M/CAWNT_M, ZMDM_BPP_CODET/ZMDM_BPP_CODE и CAWN/CAWNT '
            f'с ATWRT для ATINN {{{stats["bpp_atinn"]}}}.',
            stats,
        )
    stats['reference'] = reference_name

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
    if rc in AUSP_RULE_CODES and _is_material_ausp_table_name(table):
        return evaluate_ausp_bpp_rule(df, rc, value_col, loader, table_name=table)
    return _empty_result(f'{rc}: неверная таблица {table} для material evaluator')
