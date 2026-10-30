"""MVKE conformity checks that compare channels, BAN, hierarchy and pack size."""
from __future__ import annotations

import math
import re
from typing import Callable, Optional, Sequence

import pandas as pd

from utils.material_rule_evaluator import (
    BPP_ATNAM,
    ERROR_DESCRIPTIONS,
    MVGR3_FINISHED_TYPES,
    SS_SM_HIERARCHY_L3,
    SS_SM_HIERARCHY_L4,
    SS_SM_HIERARCHY_L5,
    _atinn_codes,
    _atinn_from_cabn,
    _atinn_from_cabn_filter_json,
    _codes,
    _dedupe_bpp_ausp,
    _description_lookup,
    _empty_result,
    _filled,
    _klart_is_material_class,
    _load,
    _matnr,
    _mara_code_lookup,
    _mvke_with_material_context,
    _no_rows_after_filters,
    _product_hierarchy_scope,
    _result,
    _zfill_code,
    find_col,
)

HIERARCHY_EXCLUSION_L4 = frozenset({
    '01030052315', '01030052301', '01030052329', '01049992999', '01010012123', '01010012117',
})
TECHNICAL_SO_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZFGA', 'ZFGM'})
BRAND_SO_TYPES = frozenset({'ZFG', 'ZFGS', 'ZFGC', 'ZFGA', 'ZFGM'})
SYRUP_GROUPS = frozenset({'1001004', '1001022', '1001024'})
BULK_PACK_TYPES = frozenset({'TNK', 'BIB', 'BRL', 'KEG'})
SIZE_RE = re.compile(r'(?<!\d)(\d+(?:[.,]\d+)?)\s*(ML|KG|GR|G|L)\b', re.IGNORECASE)
VOLEH_TO_UOM = {
    'ML': ('ML', 1.0),
    'CCM': ('ML', 1.0),
    'CM3': ('ML', 1.0),
    'L': ('L', 1.0),
    'LTR': ('L', 1.0),
    'CDM': ('L', 1.0),
    'DM3': ('L', 1.0),
    'HL': ('L', 100.0),
    'G': ('G', 1.0),
    'GR': ('G', 1.0),
    'KG': ('KG', 1.0),
    'KGM': ('KG', 1.0),
}
CASE_153_2_VOLUME = (
    '01010012001', '01010012015', '01010012031', '01010012069',
    '01010012083', '01010012093', '01010012097', '01010012107',
)
CASE_153_3_VOLUME = ('01010012041', '01010012055', '01010012060')
CASE_153_4_VOLUME = (
    '01010012117', '01010012123', '01010022155', '01010032163', '01010032169',
    '01030042179', '01030052301', '01030052315', '01030052329', '01049882988',
    '01049992999', '0206008',
)
COFFEE_CHANNEL = 'CCHBC_COFFEE_CHANNEL'
COFFEE_FORMAT = 'CCHBC_COFFEE_FORMAT'

ERROR_DESCRIPTIONS.update({
    'RPCONF_149.9': 'KTGRM on distribution channel 01 must equal channel 04 for MTART ZRW and ZST when VKORG is not 0001.',
    'RPCONF_153.2': 'ZZ_KONDM must be SS or MS for the 749 ml/g pack-size cases on sales org 0001 channel 01.',
    'RPCONF_153.3': 'ZZ_KONDM must be SS or MS for the 750 ml pack-size cases on sales org 0001 channel 01.',
    'RPCONF_153.4': 'ZZ_KONDM must be SS or MS for the 999 ml/g, coffee and brand cases on sales org 0001 channel 01.',
    'RPCONF_252.1': 'KONDM must match the coffee, pack type or pack size case on sales org 0001 channel 01. Rows outside every case stay out of scope.',
    'RPCONF_262.3': 'MVGR3 and PRODH must be the same on every sales org and channel for the ZRW/ZSF syrup scope.',
    'RPCONF_262.5': 'Finished-goods MAKTX must contain the MVGR3 pack type code.',
    'RPCONF_262.6': 'MVGR3 on sales org 0001 channel 01 must equal MVGR3 of the BAN material.',
    'RPCONF_263.2': 'MVGR4 and PRODH must be the same on every sales org and channel for the ZRW/ZSF syrup scope.',
    'RPCONF_263.5': 'Finished-goods MAKTX on sales org 0001 channel 01 must contain the pack size from GROES or VOLUM.',
    'RPCONF_263.6': 'MVGR4 on sales org 0001 channel 01 must equal MVGR4 of the BAN material.',
    'RPCONF_264.6': 'MVGR5 on sales org 0001 channel 01 must equal MVGR5 of the BAN material.',
    'RPCONF_290.3': 'PRODH must be the same across distribution channels of one sales org. More than one PRODH is an error.',
    'RPCONF_290.4': 'PRODH must equal PRODH of the BAN material on the same sales org and distribution channel.',
    'RPCONF_30.3': 'MVGR1 and PRODH outside sales org 0001 must equal the sales org 0001 value for the ZRW/ZSF syrup scope.',
    'RPCONF_30.4': 'MVGR1 on sales org 0001 channel 01 must equal MVGR1 of the BAN material.',
    'RPCONF_30.5': 'MVGR1 and product hierarchy level 4 outside sales org 0001 must equal sales org 0001 for finished goods.',
    'RPCONF_30.6': 'MVGR1 outside sales org 0001 must equal sales org 0001 for finished goods that have a BPP BP code.',
    'RPCONF_65.2': 'MVGR2 and PRODH must be the same on every sales org and channel for the ZRW/ZSF syrup scope.',
    'RPCONF_65.3': 'MVGR2 on sales org 0001 channel 01 must equal MVGR2 of the BAN material.',
})


def _column(work: pd.DataFrame, value_col: str, names: Sequence[str]) -> Optional[str]:
    if value_col and value_col in work.columns and value_col in names:
        return value_col
    found = find_col(work, names)
    if found:
        return found
    if value_col and value_col in work.columns:
        return value_col
    return None


def _starts_with_any(text: pd.Series, prefixes: Sequence[str]) -> pd.Series:
    if not len(prefixes):
        return pd.Series(False, index=text.index)
    pattern = '^(?:' + '|'.join(re.escape(p) for p in prefixes) + ')'
    return text.astype(str).str.match(pattern, na=False)


def _near(series: pd.Series, target: float) -> pd.Series:
    number = pd.to_numeric(series, errors='coerce')
    return number.sub(target).abs().le(0.01)


def _parse_size_text(text: str):
    if text is None or (isinstance(text, float) and math.isnan(text)):
        return None
    match = SIZE_RE.search(str(text).upper())
    if not match:
        return None
    number = float(match.group(1).replace(',', '.'))
    unit = match.group(2).upper()
    if unit == 'GR':
        unit = 'G'
    gram = number * 1000.0 if unit in {'L', 'KG'} else number
    return number, unit, gram


def _parse_volum(volum: str, voleh: str):
    if not volum or not voleh:
        return None
    mapped = VOLEH_TO_UOM.get(str(voleh).strip().upper())
    if not mapped:
        return None
    try:
        number = float(str(volum).replace(',', '.'))
    except ValueError:
        return None
    unit, factor = mapped
    volume = number * factor
    gram = volume * 1000.0 if unit in {'L', 'KG'} else volume
    return volume, unit, gram


def _volume_token(volume: float) -> str:
    if volume is None or (isinstance(volume, float) and math.isnan(volume)):
        return ''
    if abs(volume - round(volume)) < 1e-6:
        return str(int(round(volume)))
    return f'{volume:.3f}'.rstrip('0').rstrip('.')


def _attach_description(work: pd.DataFrame, loader) -> pd.DataFrame:
    if 'LOOKUP_MATERIAL_DESCRIPTION' in work.columns:
        return work
    descriptions = _description_lookup(_load(loader, 'MAKT'))
    out = work.copy()
    out['LOOKUP_MATERIAL_DESCRIPTION'] = out['_DQ_MATNR'].map(descriptions)
    return out


def _attach_mara_attributes(work: pd.DataFrame, loader) -> pd.DataFrame:
    mara = _load(loader, 'MARA')
    out = work.copy()
    # ban_code в dm_product_general — это MARA.WRKST, ключ другого материала.
    out['LOOKUP_BAN'] = out['_DQ_MATNR'].map(_mara_code_lookup(mara, ('WRKST', 'ban_code'))).fillna('')
    out['LOOKUP_BAN'] = _matnr(out['LOOKUP_BAN']).where(out['LOOKUP_BAN'].astype(str).str.strip().ne(''), '')
    out.loc[out['LOOKUP_BAN'].isin({'', '0'}), 'LOOKUP_BAN'] = ''
    out['LOOKUP_MTPOS_MARA'] = out['_DQ_MATNR'].map(
        _mara_code_lookup(mara, ('MTPOS_MARA', 'general_item_category_group_code'))
    ).fillna('')
    groes = _mara_text_lookup(mara, ('GROES', 'size'))
    volum = _mara_text_lookup(mara, ('VOLUM', 'volume'))
    voleh = _mara_code_lookup(mara, ('VOLEH', 'volume_unit'))
    out['LOOKUP_GROES'] = out['_DQ_MATNR'].map(groes).fillna('')
    out['LOOKUP_VOLUM'] = out['_DQ_MATNR'].map(volum).fillna('')
    out['LOOKUP_VOLEH'] = out['_DQ_MATNR'].map(voleh).fillna('')
    return out


def _mara_text_lookup(mara: pd.DataFrame, column_names: Sequence[str]) -> dict:
    matnr_col = find_col(mara, ('MATNR', 'material_code', 'MATERIAL'))
    value_col = find_col(mara, column_names)
    if mara is None or mara.empty or not matnr_col or not value_col:
        return {}
    keys = _matnr(mara[matnr_col])
    values = mara[value_col]
    out = {}
    for key, value in zip(keys, values):
        if key and key != '0' and _filled(pd.Series([value])).iloc[0] and key not in out:
            out[key] = value
    return out


def _characteristic_lookup(loader, atnam: str, left4: bool = False, material_class_only: bool = False) -> dict:
    # ATINN признака: сначала CABN.ATNAM, иначе ausp_cabn_filter.json.
    # left4 — bpp_bp_code = LEFT(ATWRT, 4). material_class_only — только KLART 001, это ветка BPP.
    atinn = _atinn_from_cabn(_load(loader, 'CABN'), atnam) or _atinn_from_cabn_filter_json(atnam)
    if not atinn:
        return {}
    frames = []
    for name in ('AUSP', 'AUSP 829.861', 'AUSP_MATERIAL'):
        frame = _load(loader, name)
        if frame is not None and not frame.empty:
            frames.append(frame)
    if not frames:
        return {}
    ausp = pd.concat(frames, ignore_index=True)
    atinn_col = find_col(ausp, ('ATINN',))
    objek_col = find_col(ausp, ('OBJEK', 'MATNR', 'MATERIAL'))
    value_col = find_col(ausp, ('ATWRT',))
    if not atinn_col or not objek_col or not value_col:
        return {}
    work = ausp.loc[_atinn_codes(ausp[atinn_col]).isin(atinn)].copy()
    if work.empty:
        return {}
    klart_col = find_col(work, ('KLART', 'CLASS_TYPE'))
    if material_class_only and klart_col:
        work = work.loc[_klart_is_material_class(work[klart_col])].copy()
    if work.empty:
        return {}
    work = _dedupe_bpp_ausp(work, atinn_col, objek_col)
    keys = _matnr(work[objek_col])
    values = _codes(work[value_col])
    if left4:
        values = values.str[:4]
    out = {}
    for key, value in zip(keys, values):
        if key and key != '0' and value and key not in out:
            out[key] = value
    return out


def _prepare(mvke, loader, rule_code, exclude_abp: bool):
    work, stats, skip = _mvke_with_material_context(mvke, loader, rule_code, exclude_abp=exclude_abp)
    stats['evaluated'] = 0
    if skip:
        return None, stats, skip
    if work.empty:
        stats['no_rows_after_filters'] = True
        return None, stats, f'{rule_code}: нет строк MVKE после ABP'
    work = _attach_mara_attributes(work, loader)
    return work, stats, None


def _finish_empty(stats, reason):
    return _no_rows_after_filters(reason, stats)


def _sales_channels(work: pd.DataFrame):
    vkorg_col = find_col(work, ('VKORG', 'sales_org_code', 'SALES_ORG'))
    vtweg_col = find_col(work, ('VTWEG', 'distribution_channel_code', 'DCHL'))
    if not vkorg_col or not vtweg_col:
        return None, None, None, None, 'MVKE.VKORG/VTWEG не найдены'
    vkorg = _zfill_code(work[vkorg_col], 4)
    vtweg = _zfill_code(work[vtweg_col], 2)
    return vkorg_col, vtweg_col, vkorg, vtweg, None


def _hierarchy_text(work: pd.DataFrame):
    prodh_col = find_col(work, ('PRODH', 'PRDHA', 'product_hierarchy', 'product_hierarchy_code'))
    if not prodh_col:
        return None, None, None, 'MVKE.PRODH не найден'
    text = _codes(work[prodh_col])
    # product_hierarchy_l4_code — первые 11 символов PRODH, l3 — первые 7.
    return prodh_col, text, text.str[:11], None


def _hierarchy_excluded(text: pd.Series) -> pd.Series:
    return text.str[:11].isin(HIERARCHY_EXCLUSION_L4) | text.str[:7].eq(SS_SM_HIERARCHY_L3) | text.eq(SS_SM_HIERARCHY_L3)


def _technical_sales(vkorg: pd.Series, vtweg: pd.Series) -> pd.Series:
    return vkorg.eq('0001') & vtweg.eq('01')


def _syrup_scope(work: pd.DataFrame, pack_col: str) -> pd.Series:
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    material_group = _codes(work['LOOKUP_MATERIAL_GROUP'])
    pack = _codes(work[pack_col]) if pack_col else pd.Series('', index=work.index)
    raw = material_type.eq('ZRW') & material_group.isin(SYRUP_GROUPS)
    syrup = material_type.eq('ZSF') & pack.eq('ZSY') & material_group.eq('1001009')
    return raw | syrup


def _measures_for(work: pd.DataFrame) -> pd.DataFrame:
    description = work['LOOKUP_MATERIAL_DESCRIPTION'] if 'LOOKUP_MATERIAL_DESCRIPTION' in work.columns else pd.Series('', index=work.index)
    rows = []
    for key, groes, volum, voleh, desc in zip(
        work['_DQ_MATNR'], work['LOOKUP_GROES'], work['LOOKUP_VOLUM'], work['LOOKUP_VOLEH'], description.fillna('')
    ):
        # Отдельной колонки pack_size_volume_unified в выгрузке нет.
        # Порядок: GROES (330ML), затем MARA.VOLUM+VOLEH, затем токен размера в MAKTX.
        # Для L/KG gram_ml = число * 1000, чтобы 1.5L сравнивалось как 1500.
        parsed = _parse_size_text(groes) or _parse_volum(volum, voleh) or _parse_size_text(desc)
        if parsed:
            rows.append((key, parsed[0], parsed[1], parsed[2]))
    frame = pd.DataFrame(rows, columns=['key', 'volume', 'uom', 'gram'])
    if frame.empty:
        return pd.DataFrame(columns=['key', 'volume', 'uom', 'gram']).set_index('key')
    return frame.drop_duplicates('key', keep='first').set_index('key')


def _map_measures(work: pd.DataFrame) -> pd.DataFrame:
    measures = _measures_for(work)
    out = work.copy()
    out['_DQ_VOLUME'] = out['_DQ_MATNR'].map(measures['volume']) if len(measures) else pd.NA
    out['_DQ_UOM'] = out['_DQ_MATNR'].map(measures['uom']).fillna('') if len(measures) else ''
    out['_DQ_GRAM'] = out['_DQ_MATNR'].map(measures['gram']) if len(measures) else pd.NA
    return out


def _apply_flag_cases(work, base, flag, cases):
    # Кейсы идут по порядку. Первый подошедший решает исход: неверный SS/MS — ошибка, а не переход к следующему кейсу.
    decision = pd.Series(pd.NA, index=work.index, dtype='boolean')
    remaining = base.fillna(False).copy()
    for predicate, expected in cases:
        hit = remaining & predicate.fillna(False)
        decision.loc[hit] = flag.loc[hit].eq(expected).to_numpy()
        remaining = remaining & ~hit
    return decision


def _ss_base(work, flag_col, prodh_col, pack_col, pack_type_col, vkorg, vtweg, extra_prefixes=()):
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    material_group = _codes(work['LOOKUP_MATERIAL_GROUP'])
    hierarchy, hierarchy_skip = _product_hierarchy_scope(work)
    if hierarchy_skip:
        return None, hierarchy_skip
    text = _codes(work[prodh_col])
    if extra_prefixes:
        # 01030052329 есть в кейсе 153.4/252.1, но нет в общем списке UC03. Без этого ветка не выполняется.
        hierarchy = hierarchy | _starts_with_any(text, extra_prefixes)
    scope = (
        _filled(work[flag_col])
        & _filled(work[prodh_col])
        & _filled(work[pack_col])
        & _filled(work[pack_type_col])
        & material_group.ne('1110000')
        & material_type.str.startswith('ZFG')
        & _technical_sales(vkorg, vtweg)
        & hierarchy.fillna(False)
    )
    return scope, None


def _bulk_cases(pack, pack_type, flag_name_unused=None):
    del flag_name_unused
    return [
        (pack.eq('ZZ') & pack_type.ne('OTH'), 'SS'),
        (pack.eq('ZZ') & pack_type.eq('OTH'), 'MS'),
        (pack.ne('ZZ') & pack_type.isin(BULK_PACK_TYPES), 'SS'),
    ]


def evaluate_rpconf_149_9(mvke, value_col, loader):
    rc = 'RPCONF_149.9'
    work, stats, skip = _prepare(mvke, loader, rc, True)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    checked = _column(work, value_col, ('KTGRM', 'account_assignmnet_group_code', 'account_assignment_group_code'))
    _vkorg_col, _vtweg_col, vkorg, vtweg, sales_skip = _sales_channels(work)
    if not checked or sales_skip:
        return _empty_result(f'{rc}: {sales_skip or "MVKE.KTGRM не найден"}', stats)
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    material_group = _codes(work['LOOKUP_MATERIAL_GROUP'])
    value = _codes(work[checked])
    scope = (
        material_type.isin({'ZRW', 'ZST'})
        & material_group.ne('1110000')
        & vkorg.ne('')
        & vkorg.ne('0001')
        & value.ne('')
        & vtweg.isin({'01', '04'})
    )
    side = work.loc[scope, ['_DQ_MATNR']].copy()
    side['vkorg'] = vkorg.loc[scope]
    side['vtweg'] = vtweg.loc[scope]
    side['value'] = value.loc[scope]
    if side.empty:
        return _finish_empty(stats, f'{rc}: нет строк ZRW/ZST с KTGRM на каналах 01 и 04')
    # Пара — один материал и одна сбытовая организация, канал 01 против 04. В итог попадает строка канала 01.
    counts = side.groupby(['_DQ_MATNR', 'vkorg', 'vtweg'])['value'].nunique()
    single = side.join(counts.rename('nunique'), on=['_DQ_MATNR', 'vkorg', 'vtweg'])
    single = single.loc[single['nunique'].eq(1)].drop_duplicates(['_DQ_MATNR', 'vkorg', 'vtweg'])
    wide = single.pivot(index=['_DQ_MATNR', 'vkorg'], columns='vtweg', values='value')
    if '01' not in wide.columns or '04' not in wide.columns:
        return _finish_empty(stats, f'{rc}: нет пар каналов 01 и 04')
    both = wide['01'].notna() & wide['04'].notna()
    good_index = wide.index[both & wide['01'].eq(wide['04'])]
    bad_index = wide.index[both & wide['01'].ne(wide['04'])]
    pair_ok = {idx: True for idx in good_index}
    pair_ok.update({idx: False for idx in bad_index})
    channel_01 = scope & vtweg.eq('01')
    keys = list(zip(work['_DQ_MATNR'], vkorg))
    keep = pd.Series(
        [bool(channel_01.iloc[i]) and keys[i] in pair_ok for i in range(len(work))],
        index=work.index,
    )
    scoped = work.loc[keep].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rc}: нет пар каналов 01 и 04')
    ok = pd.Series([pair_ok[key] for key in zip(scoped['_DQ_MATNR'], _zfill_code(scoped[_vkorg_col], 4))], index=scoped.index)
    return _result(scoped, ok, rc, stats)


def _evaluate_ss_rule(mvke, value_col, loader, rule_code, cases_builder, extra_prefixes=(), enrich=None):
    work, stats, skip = _prepare(mvke, loader, rule_code, True)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    if enrich is not None:
        work = enrich(work)
    work = _attach_description(work, loader)
    work = _map_measures(work)
    flag_col = _column(work, value_col, ('ZZ_KONDM', 'ss_sm_flag'))
    prodh_col = find_col(work, ('PRODH', 'PRDHA', 'product_hierarchy', 'product_hierarchy_code'))
    pack_col = find_col(work, ('MVGR4', 'pack_size_code'))
    pack_type_col = find_col(work, ('MVGR3', 'pack_type_code'))
    _vk, _vt, vkorg, vtweg, sales_skip = _sales_channels(work)
    if not flag_col or not prodh_col or not pack_col or not pack_type_col or sales_skip:
        return _empty_result(f'{rule_code}: MVKE.ZZ_KONDM/PRODH/MVGR3/MVGR4/VKORG/VTWEG не найдены', stats)
    base, base_skip = _ss_base(work, flag_col, prodh_col, pack_col, pack_type_col, vkorg, vtweg, extra_prefixes)
    if base_skip:
        return _empty_result(f'{rule_code}: {base_skip}', stats)
    flag = _codes(work[flag_col])
    pack = _codes(work[pack_col])
    pack_type = _codes(work[pack_type_col])
    text = _codes(work[prodh_col])
    decision = _apply_flag_cases(work, base, flag, cases_builder(work, pack, pack_type, text))
    scoped = work.loc[decision.notna()].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rule_code}: нет строк MVKE в scope ZZ_KONDM')
    return _result(scoped, decision.loc[scoped.index].astype(bool), rule_code, stats)


def _cases_153_2(work, pack, pack_type, text):
    volume = pd.to_numeric(work['_DQ_VOLUME'], errors='coerce')
    uom = work['_DQ_UOM'].astype(str)
    volume_hierarchy = _starts_with_any(text, CASE_153_2_VOLUME)
    return _bulk_cases(pack, pack_type) + [
        (text.eq(SS_SM_HIERARCHY_L5) | text.str.startswith(SS_SM_HIERARCHY_L5), 'MS'),
        (volume_hierarchy & uom.isin({'ML', 'G'}) & volume.le(749), 'SS'),
        (
            volume_hierarchy
            & ((uom.isin({'ML', 'G'}) & volume.gt(749)) | (uom.isin({'L', 'KG'}) & volume.ge(1))),
            'MS',
        ),
    ]


def _cases_153_3(work, pack, pack_type, text):
    volume = pd.to_numeric(work['_DQ_VOLUME'], errors='coerce')
    uom = work['_DQ_UOM'].astype(str)
    volume_hierarchy = _starts_with_any(text, CASE_153_3_VOLUME)
    return _bulk_cases(pack, pack_type) + [
        (volume_hierarchy & uom.eq('ML') & volume.le(750), 'SS'),
        (
            volume_hierarchy
            & ((uom.eq('ML') & volume.gt(750)) | (uom.eq('L') & volume.ge(1))),
            'MS',
        ),
    ]


def _cases_153_4(work, pack, pack_type, text):
    gram = pd.to_numeric(work['_DQ_GRAM'], errors='coerce')
    volume = pd.to_numeric(work['_DQ_VOLUME'], errors='coerce')
    uom = work['_DQ_UOM'].astype(str)
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    brand = _codes(work[find_col(work, ('MVGR1', 'brand_code'))]) if find_col(work, ('MVGR1', 'brand_code')) else pd.Series('', index=work.index)
    channel = work.get('LOOKUP_COFFEE_CHANNEL', pd.Series('', index=work.index)).astype(str)
    coffee_format = work.get('LOOKUP_COFFEE_FORMAT', pd.Series('', index=work.index)).astype(str)
    # В тексте формулы AND стоит без скобок. Смысл кейса: (бренд CN или иерархия) и объём, не «любой CN».
    cn_or_hierarchy = brand.eq('CN') | text.str.startswith('01010012137')
    listed = _starts_with_any(text, CASE_153_4_VOLUME)
    return [
        (pack.eq('ZZ') & pack_type.eq('OTH'), 'MS'),
        (pack.ne('ZZ') & pack_type.isin(BULK_PACK_TYPES), 'SS'),
        (material_type.eq('ZFGC') & channel.isin({'CH3', 'CH4', 'CH5', 'CH6'}) & coffee_format.eq('CF1'), 'SS'),
        (material_type.eq('ZFGC') & channel.eq('CH3') & coffee_format.isin({'CF2', 'CF3'}), 'MS'),
        (material_type.eq('ZFGC') & channel.eq('CH5') & coffee_format.isin({'CF2', 'CF3'}), 'MS'),
        (material_type.eq('ZFGC') & channel.eq('CH4') & coffee_format.isin({'CF2', 'CF4'}), 'MS'),
        (material_type.eq('ZFGC') & channel.eq('CH6') & coffee_format.eq('CF4'), 'MS'),
        (material_type.eq('ZFGC') & channel.isin({'CH3', 'CH5'}) & coffee_format.eq('CF4'), 'SS'),
        (cn_or_hierarchy & _near(gram, 800), 'MS'),
        (cn_or_hierarchy & _near(gram, 250), 'SS'),
        (text.str.startswith('010100221332133') & gram.le(500), 'SS'),
        (text.str.startswith('010100221332133') & gram.gt(500), 'MS'),
        (text.str.startswith('010100221452145') & gram.le(99), 'SS'),
        (text.str.startswith('010100221452145') & gram.gt(99), 'MS'),
        (listed & uom.isin({'ML', 'G'}) & gram.le(999), 'SS'),
        (listed & uom.isin({'L', 'KG'}) & volume.ge(1), 'MS'),
    ]


def evaluate_rpconf_153_2(mvke, value_col, loader):
    return _evaluate_ss_rule(mvke, value_col, loader, 'RPCONF_153.2', _cases_153_2)


def evaluate_rpconf_153_3(mvke, value_col, loader):
    return _evaluate_ss_rule(mvke, value_col, loader, 'RPCONF_153.3', _cases_153_3)


def evaluate_rpconf_153_4(mvke, value_col, loader):
    def enrich(frame):
        out = frame.copy()
        out['LOOKUP_COFFEE_CHANNEL'] = out['_DQ_MATNR'].map(_characteristic_lookup(loader, COFFEE_CHANNEL)).fillna('')
        out['LOOKUP_COFFEE_FORMAT'] = out['_DQ_MATNR'].map(_characteristic_lookup(loader, COFFEE_FORMAT)).fillna('')
        return out

    return _evaluate_ss_rule(
        mvke, value_col, loader, 'RPCONF_153.4', _cases_153_4, CASE_153_4_VOLUME, enrich,
    )


def _first_case_decision(base, value, cases):
    # Как в 153.2: первый подошедший кейс решает. Строка без кейса остаётся вне проверки.
    decision = pd.Series(pd.NA, index=base.index, dtype='boolean')
    remaining = base.fillna(False).copy()
    for predicate, expected in cases:
        hit = remaining & predicate.fillna(False)
        decision.loc[hit] = value.loc[hit].eq(expected).to_numpy()
        remaining = remaining & ~hit
    return decision, remaining


def evaluate_rpconf_252_1(mvke, value_col, loader):
    rc = 'RPCONF_252.1'
    # Те же входные фильтры, что у RPCOMP_252.1 и 153.2: ABP, техническая SO, иерархия, тип и группа.
    work, stats, skip = _prepare(mvke, loader, rc, True)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    work = _attach_description(work, loader)
    work = _map_measures(work)
    work['LOOKUP_COFFEE_CHANNEL'] = work['_DQ_MATNR'].map(_characteristic_lookup(loader, COFFEE_CHANNEL)).fillna('')
    work['LOOKUP_COFFEE_FORMAT'] = work['_DQ_MATNR'].map(_characteristic_lookup(loader, COFFEE_FORMAT)).fillna('')
    kondm_col = _column(work, value_col, ('KONDM', 'material_price_group_code', 'material_pricing_group'))
    flag_col = find_col(work, ('ZZ_KONDM', 'ss_sm_flag'))
    pack_col = find_col(work, ('MVGR4', 'pack_size_code'))
    pack_type_col = find_col(work, ('MVGR3', 'pack_type_code'))
    brand_col = find_col(work, ('MVGR1', 'brand_code'))
    prodh_col, text, l4, hier_skip = _hierarchy_text(work)
    _vk, _vt, vkorg, vtweg, sales_skip = _sales_channels(work)
    if not kondm_col or not flag_col or not pack_col or not pack_type_col or hier_skip or sales_skip:
        return _empty_result(f'{rc}: {hier_skip or sales_skip or "MVKE.KONDM/ZZ_KONDM/MVGR3/MVGR4 не найдены"}', stats)
    hierarchy, hierarchy_skip = _product_hierarchy_scope(work)
    if hierarchy_skip:
        return _empty_result(f'{rc}: {hierarchy_skip}', stats)
    hierarchy = hierarchy | text.str[:11].eq('01030052329')
    # Пустой кофе выводит из проверки только ZFGC: кофейные кейсы без канала и формата не с чем сравнить.
    # Остальные готовые продукты идут по типу упаковки и иерархии.
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    material_group = _codes(work['LOOKUP_MATERIAL_GROUP'])
    kondm = _codes(work[kondm_col])
    channel = work['LOOKUP_COFFEE_CHANNEL'].astype(str)
    coffee_format = work['LOOKUP_COFFEE_FORMAT'].astype(str)
    pack = _codes(work[pack_col])
    pack_type = _codes(work[pack_type_col])
    brand = _codes(work[brand_col]) if brand_col else pd.Series('', index=work.index)
    gram = pd.to_numeric(work['_DQ_GRAM'], errors='coerce')
    zfgc = material_type.eq('ZFGC')
    has_coffee = channel.ne('') & coffee_format.ne('')
    base = (
        kondm.ne('')
        & _filled(work[flag_col])
        & _filled(work[pack_col])
        & _filled(work[pack_type_col])
        & material_group.ne('1110000')
        & material_type.isin(TECHNICAL_SO_TYPES)
        & _technical_sales(vkorg, vtweg)
        & hierarchy.fillna(False)
        & ~(zfgc & ~has_coffee)
    )
    cn = l4.eq('01010012137') | brand.eq('CN3')
    zfgc_cases = [
        (channel.isin({'CH3', 'CH4', 'CH5', 'CH6'}) & coffee_format.eq('CF1'), '03'),
        (channel.eq('CH3') & coffee_format.isin({'CF2', 'CF3'}), '04'),
        (channel.eq('CH5') & coffee_format.isin({'CF2', 'CF3'}), '03'),
        (channel.eq('CH4') & coffee_format.isin({'CF2', 'CF4'}), '03'),
        (channel.eq('CH6') & coffee_format.eq('CF4'), '03'),
    ]
    other_cases = [
        (pack_type.isin(BULK_PACK_TYPES), '03'),
        (pack.eq('ZZ') & pack_type.eq('OTH'), '04'),
        (cn & _near(gram, 250), '03'),
        (cn & _near(gram, 800), '04'),
        (l4.eq('01010022145') & gram.le(99), '03'),
        (l4.eq('01010022145') & gram.gt(99), '04'),
        (l4.eq('01010022133') & gram.le(500), '03'),
        (l4.eq('01010022133') & gram.gt(500), '04'),
        (l4.eq('01010012083'), '04'),
        (l4.eq('01030052329') & gram.le(100), '03'),
        (l4.eq('01030052329') & gram.gt(100), '04'),
    ]
    decision, zfgc_left = _first_case_decision(base & zfgc, kondm, zfgc_cases)
    # Формула для ZFGC: не прошёл кофейные кейсы — ошибка, к упаковке не переходим.
    decision.loc[zfgc_left] = False
    other_decision, _other_left = _first_case_decision(base & ~zfgc, kondm, other_cases)
    decision = decision.fillna(other_decision)
    scoped = work.loc[decision.notna()].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rc}: нет строк MVKE в scope KONDM')
    return _result(scoped, decision.loc[scoped.index].astype(bool), rc, stats)


def _distinct_pair(mvke, value_col, loader, rule_code, left_names):
    work, stats, skip = _prepare(mvke, loader, rule_code, False)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    left_col = _column(work, value_col, left_names)
    prodh_col, text, _l4, hier_skip = _hierarchy_text(work)
    pack_col = find_col(work, ('MVGR3', 'pack_type_code'))
    if not left_col or hier_skip:
        return _empty_result(f'{rule_code}: {hier_skip or "колонка " + "/".join(left_names) + " не найдена"}', stats)
    scope = _syrup_scope(work, pack_col) & _filled(work[left_col]) & text.ne('')
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rule_code}: нет строк MVKE в syrup/raw scope')
    # Одно значение поля и один PRODH на материал по всем сбытовым организациям и каналам. Пустые строки в счёт не входят.
    pair = _codes(scoped[left_col]) + '\t' + _codes(scoped[prodh_col])
    ok = pair.groupby(scoped['_DQ_MATNR']).transform('nunique').eq(1)
    return _result(scoped, ok, rule_code, stats)


def evaluate_rpconf_262_3(mvke, value_col, loader):
    return _distinct_pair(mvke, value_col, loader, 'RPCONF_262.3', ('MVGR3', 'pack_type_code'))


def evaluate_rpconf_263_2(mvke, value_col, loader):
    return _distinct_pair(mvke, value_col, loader, 'RPCONF_263.2', ('MVGR4', 'pack_size_code'))


def evaluate_rpconf_65_2(mvke, value_col, loader):
    return _distinct_pair(mvke, value_col, loader, 'RPCONF_65.2', ('MVGR2', 'flavour_code'))


def evaluate_rpconf_262_5(mvke, value_col, loader):
    rc = 'RPCONF_262.5'
    work, stats, skip = _prepare(mvke, loader, rc, False)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    work = _attach_description(work, loader)
    pack_col = _column(work, value_col, ('MVGR3', 'pack_type_code'))
    prodh_col, text, _l4, hier_skip = _hierarchy_text(work)
    if not pack_col or hier_skip:
        return _empty_result(f'{rc}: {hier_skip or "MVKE.MVGR3 не найден"}', stats)
    if int(_filled(work['LOOKUP_MATERIAL_DESCRIPTION']).sum()) == 0:
        return _empty_result(f'{rc}: MAKT.MAKTX не найден', stats)
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    pack = _codes(work[pack_col])
    description = work['LOOKUP_MATERIAL_DESCRIPTION'].astype(str)
    scope = (
        pack.ne('')
        & work['LOOKUP_MTPOS_MARA'].astype(str).ne('ZCVI')
        & ~_hierarchy_excluded(text)
        & text.ne('01049992999')
        & material_type.str.startswith('ZFG')
    )
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rc}: нет строк Finished Goods для сверки MVGR3 с наименованием')
    desc = description.loc[scoped.index]
    token = pack.loc[scoped.index]
    ok = pd.Series(
        [bool(token_value) and token_value.casefold() in str(desc_value).casefold() for token_value, desc_value in zip(token, desc)],
        index=scoped.index,
    )
    return _result(scoped, ok, rc, stats)


def _size_search_tokens(groes, volum, voleh) -> list[str]:
    # Объём для сверки с наименованием — GROES или MARA.VOLUM+VOLEH, не код MVGR4 и не сам MAKTX.
    # Ищем и исходное число, и gram_ml: 0.33 L в наименовании часто записано как 330.
    parsed = _parse_size_text(groes) or _parse_volum(volum, voleh)
    if not parsed:
        return []
    tokens = []
    for number in (parsed[0], parsed[2]):
        token = _volume_token(number)
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _description_has_size(description: str, tokens: list[str]) -> bool:
    text = str(description or '')
    for token in tokens:
        forms = [token]
        if '.' in token:
            forms.append(token.replace('.', ','))
        for form in forms:
            if re.search(r'(?<!\d)' + re.escape(form) + r'(?!\d)', text):
                return True
    return False


def evaluate_rpconf_263_5(mvke, value_col, loader):
    rc = 'RPCONF_263.5'
    # ABP, техническая SO 0001/01, группа не 1110000 и тип ZFG% — как у 153.2 и RPCOMP_252.1.
    # MTPOS_MARA ZCVI и исключённая иерархия — как у соседней сверки наименования RPCONF_262.5.
    work, stats, skip = _prepare(mvke, loader, rc, True)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    work = _attach_description(work, loader)
    pack_col = _column(work, value_col, ('MVGR4', 'pack_size_code'))
    _prodh_col, text, _l4, hier_skip = _hierarchy_text(work)
    _vk, _vt, vkorg, vtweg, sales_skip = _sales_channels(work)
    if not pack_col or hier_skip or sales_skip:
        return _empty_result(f'{rc}: {hier_skip or sales_skip or "MVKE.MVGR4 не найден"}', stats)
    if int(_filled(work['LOOKUP_MATERIAL_DESCRIPTION']).sum()) == 0:
        return _empty_result(f'{rc}: MAKT.MAKTX не найден', stats)
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    material_group = _codes(work['LOOKUP_MATERIAL_GROUP'])
    scope = (
        _filled(work[pack_col])
        & ~_hierarchy_excluded(text)
        & material_type.str.startswith('ZFG')
        & material_group.ne('1110000')
        & work['LOOKUP_MTPOS_MARA'].astype(str).ne('ZCVI')
        & _technical_sales(vkorg, vtweg)
    )
    scoped = work.loc[scope].copy()
    token_rows = [
        _size_search_tokens(groes, volum, voleh)
        for groes, volum, voleh in zip(scoped['LOOKUP_GROES'], scoped['LOOKUP_VOLUM'], scoped['LOOKUP_VOLEH'])
    ]
    keep = [bool(tokens) for tokens in token_rows]
    scoped = scoped.loc[keep].copy()
    token_rows = [tokens for tokens, enabled in zip(token_rows, keep) if enabled]
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rc}: нет объёма упаковки в GROES или VOLUM на технической SO')
    description = scoped['LOOKUP_MATERIAL_DESCRIPTION'].astype(str)
    ok = pd.Series(
        [_description_has_size(text_value, tokens) for tokens, text_value in zip(token_rows, description)],
        index=scoped.index,
    )
    return _result(scoped, ok, rc, stats)


def _ban_compare(mvke, value_col, loader, rule_code, value_names, finished: bool, restrict_sales: bool, exclude_hierarchy: bool):
    work, stats, skip = _prepare(mvke, loader, rule_code, False)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    value_col_name = _column(work, value_col, value_names)
    prodh_col, text, _l4, hier_skip = _hierarchy_text(work)
    _vk, _vt, vkorg, vtweg, sales_skip = _sales_channels(work)
    if not value_col_name or hier_skip or sales_skip:
        return _empty_result(f'{rule_code}: {hier_skip or sales_skip or "колонка значения не найдена"}', stats)
    value = _codes(work[value_col_name])
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    # SKU сверяется с MVKE материала BAN (WRKST) на той же паре VKORG+VTWEG.
    # 290.4 без ограничения 0001/01 и без фильтра Finished Goods. Остальные BAN-правила — только 0001/01 и готовая продукция.
    sales_key = vkorg + '|' + vtweg
    ref = {}
    hier_by_key = {}
    for matnr, sale, val, prodh in zip(work['_DQ_MATNR'], sales_key, value, text):
        if not matnr or not val:
            continue
        ref.setdefault((matnr, sale), set()).add(val)
        hier_by_key.setdefault((matnr, sale), set()).add(prodh)
    ban_key = list(zip(work['LOOKUP_BAN'], sales_key))
    scope = value.ne('') & work['LOOKUP_BAN'].astype(str).ne('')
    if finished:
        scope = scope & material_type.isin(MVGR3_FINISHED_TYPES)
    if restrict_sales:
        scope = scope & _technical_sales(vkorg, vtweg)
    if exclude_hierarchy:
        scope = scope & ~_hierarchy_excluded(text)
    ok_flags = []
    keep_index = []
    for idx, enabled, key, own_value, own_prodh in zip(work.index, scope, ban_key, value, text):
        if not enabled:
            continue
        ban_values = ref.get(key)
        if not ban_values:
            continue
        ban_hierarchy = list(hier_by_key.get(key, set()))
        if exclude_hierarchy and bool(_hierarchy_excluded(pd.Series(ban_hierarchy)).any()):
            continue
        keep_index.append(idx)
        ok_flags.append(len(ban_values) == 1 and own_value in ban_values)
    scoped = work.loc[keep_index].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rule_code}: нет строк с BAN на той же сбытовой организации и канале')
    return _result(scoped, pd.Series(ok_flags, index=scoped.index), rule_code, stats)


def evaluate_rpconf_262_6(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_262.6', ('MVGR3', 'pack_type_code'), True, True, True)


def evaluate_rpconf_263_6(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_263.6', ('MVGR4', 'pack_size_code'), True, True, True)


def evaluate_rpconf_264_6(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_264.6', ('MVGR5', 'sales_unit_code'), True, True, True)


def evaluate_rpconf_30_4(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_30.4', ('MVGR1', 'brand_code'), True, True, True)


def evaluate_rpconf_65_3(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_65.3', ('MVGR2', 'flavour_code'), True, True, True)


def evaluate_rpconf_290_4(mvke, value_col, loader):
    return _ban_compare(mvke, value_col, loader, 'RPCONF_290.4', ('PRODH', 'product_hierarchy_code'), False, False, False)


def evaluate_rpconf_290_3(mvke, value_col, loader):
    rc = 'RPCONF_290.3'
    work, stats, skip = _prepare(mvke, loader, rc, False)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    prodh_col, text, _l4, hier_skip = _hierarchy_text(work)
    _vk, _vt, vkorg, _vtweg, sales_skip = _sales_channels(work)
    if hier_skip or sales_skip:
        return _empty_result(f'{rc}: {hier_skip or sales_skip}', stats)
    scope = text.ne('') & ~_hierarchy_excluded(text) & vkorg.ne('')
    scoped = work.loc[scope].copy()
    stats['evaluated'] = len(scoped)
    if scoped.empty:
        return _finish_empty(stats, f'{rc}: нет строк MVKE с PRODH вне исключённых иерархий')
    # Группа — материал, тип и сбытовая организация: каналы внутри одной VKORG должны нести один PRODH.
    # В исходной формуле и count=1, и count>1 возвращали успех. Несколько разных PRODH — ошибка.
    group_key = scoped['_DQ_MATNR'] + '|' + _codes(scoped['LOOKUP_MATERIAL_TYPE']) + '|' + vkorg.loc[scoped.index]
    ok = text.loc[scoped.index].groupby(group_key).transform('nunique').eq(1)
    return _result(scoped, ok, rc, stats)


def _compare_with_technical_so(mvke, value_col, loader, rule_code, left_names, right_kind: str, syrup: bool, finished_types: bool, require_bpp: bool):
    work, stats, skip = _prepare(mvke, loader, rule_code, False)
    if work is None:
        if stats.get('no_rows_after_filters'):
            return _no_rows_after_filters(skip, stats)
        return _empty_result(skip, stats)
    left_col = _column(work, value_col, left_names)
    prodh_col, text, l4, hier_skip = _hierarchy_text(work)
    _vk, _vt, vkorg, _vtweg, sales_skip = _sales_channels(work)
    pack_col = find_col(work, ('MVGR3', 'pack_type_code'))
    if not left_col or hier_skip or sales_skip:
        return _empty_result(f'{rule_code}: {hier_skip or sales_skip or "колонка значения не найдена"}', stats)
    left = _codes(work[left_col])
    if right_kind == 'prodh':
        right = text
    elif right_kind == 'l4':
        right = l4
    else:
        right = left
    material_type = _codes(work['LOOKUP_MATERIAL_TYPE'])
    # Строки вне 0001 сравниваются с единственной парой на 0001. Несколько разных пар на 0001 — ошибка.
    # 30.6 сверяет бренд. bpp_bp_code один на материал, поэтому это допуск в проверку, а не второе сравнение.
    # Страны dm_product_universe в выгрузке нет. Если BPP в AUSP нет совсем, допуск по BP не режет все строки.
    bpp_lookup = _characteristic_lookup(loader, BPP_ATNAM, left4=True, material_class_only=True) if require_bpp else {}
    if require_bpp and bpp_lookup:
        work = work.copy()
        work['LOOKUP_BPP_BP'] = work['_DQ_MATNR'].map(bpp_lookup).fillna('')
    else:
        require_bpp = False
    ref_mask = vkorg.eq('0001') & left.ne('') & right.ne('')
    ref = pd.DataFrame({'matnr': work.loc[ref_mask, '_DQ_MATNR'], 'pair': (left + '\t' + right).loc[ref_mask]})
    if ref.empty:
        return _finish_empty(stats, f'{rule_code}: нет эталона sales org 0001')
    counts = ref.groupby('matnr')['pair'].nunique()
    first = ref.drop_duplicates('matnr').set_index('matnr')['pair']
    sku_mask = vkorg.ne('0001') & vkorg.ne('') & left.ne('') & right.ne('')
    if syrup:
        sku_mask = sku_mask & _syrup_scope(work, pack_col)
    if finished_types:
        sku_mask = sku_mask & material_type.isin(BRAND_SO_TYPES)
    if require_bpp:
        sku_mask = sku_mask & work['LOOKUP_BPP_BP'].astype(str).ne('')
        ref_with_bpp = work['_DQ_MATNR'].isin(set(work.loc[vkorg.eq('0001') & work['LOOKUP_BPP_BP'].astype(str).ne(''), '_DQ_MATNR']))
        sku_mask = sku_mask & ref_with_bpp
    sku = work.loc[sku_mask].copy()
    if sku.empty:
        return _finish_empty(stats, f'{rule_code}: нет строк вне sales org 0001')
    sku_pair = (left + '\t' + right).loc[sku.index]
    known = sku['_DQ_MATNR'].isin(counts.index)
    sku = sku.loc[known].copy()
    sku_pair = sku_pair.loc[sku.index]
    stats['evaluated'] = len(sku)
    if sku.empty:
        return _finish_empty(stats, f'{rule_code}: нет пары со sales org 0001')
    unique = sku['_DQ_MATNR'].map(counts).eq(1)
    same = sku_pair.eq(sku['_DQ_MATNR'].map(first))
    return _result(sku, unique & same, rule_code, stats)


def evaluate_rpconf_30_3(mvke, value_col, loader):
    return _compare_with_technical_so(
        mvke, value_col, loader, 'RPCONF_30.3', ('MVGR1', 'brand_code'), 'prodh', True, False, False,
    )


def evaluate_rpconf_30_5(mvke, value_col, loader):
    return _compare_with_technical_so(
        mvke, value_col, loader, 'RPCONF_30.5', ('MVGR1', 'brand_code'), 'l4', False, True, False,
    )


def evaluate_rpconf_30_6(mvke, value_col, loader):
    return _compare_with_technical_so(
        mvke, value_col, loader, 'RPCONF_30.6', ('MVGR1', 'brand_code'), 'brand', False, True, True,
    )


_DISPATCH = {
    'RPCONF_149.9': evaluate_rpconf_149_9,
    'RPCONF_153.2': evaluate_rpconf_153_2,
    'RPCONF_153.3': evaluate_rpconf_153_3,
    'RPCONF_153.4': evaluate_rpconf_153_4,
    'RPCONF_252.1': evaluate_rpconf_252_1,
    'RPCONF_262.3': evaluate_rpconf_262_3,
    'RPCONF_262.5': evaluate_rpconf_262_5,
    'RPCONF_262.6': evaluate_rpconf_262_6,
    'RPCONF_263.2': evaluate_rpconf_263_2,
    'RPCONF_263.5': evaluate_rpconf_263_5,
    'RPCONF_263.6': evaluate_rpconf_263_6,
    'RPCONF_264.6': evaluate_rpconf_264_6,
    'RPCONF_290.3': evaluate_rpconf_290_3,
    'RPCONF_290.4': evaluate_rpconf_290_4,
    'RPCONF_30.3': evaluate_rpconf_30_3,
    'RPCONF_30.4': evaluate_rpconf_30_4,
    'RPCONF_30.5': evaluate_rpconf_30_5,
    'RPCONF_30.6': evaluate_rpconf_30_6,
    'RPCONF_65.2': evaluate_rpconf_65_2,
    'RPCONF_65.3': evaluate_rpconf_65_3,
}


def evaluate_mvke_conformity(mvke, rule_code, value_col, loader: Callable):
    rc = str(rule_code).strip().upper()
    function = _DISPATCH.get(rc)
    if function is None:
        return _empty_result(f'{rc}: проверка MVKE не подключена')
    return function(mvke, value_col, loader)
