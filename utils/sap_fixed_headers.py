from __future__ import annotations

import pandas as pd

AUSP_HEADER = (
    'MANDT', 'OBJEK', 'ATINN', 'ATZHL', 'MAFID', 'KLART', 'ADZHL', 'ATWRT', 'ATFLV',
    'ATAWE', 'ATFLB', 'ATAW1', 'ATCOD', 'ATTLV', 'ATTLB', 'ATPRZ', 'ATINC', 'ATAUT',
    'AENNR', 'DATUV', 'LKENZ', 'ATIMB', 'ATZIS', 'ATSRT', 'ATVGLART', 'DATUB',
    'DEC_VALUE_FROM', 'DEC_VALUE_TO', 'CURR_VALUE_FROM', 'CURR_VALUE_TO', 'CURRENCY',
    'DATE_FROM', 'DATE_TO', 'TIME_FROM', 'TIME_TO', 'PARTNER_GUID', 'CHANGED_AT',
    'CHANGED_BY', 'TYPE_BP_GUID',
)
MAKT_HEADER = ('MANDT', 'MATNR', 'SPRAS', 'MAKTX', 'MAKTG')
MARC_HEADER = (
    'MANDT', 'MATNR', 'WERKS', 'MMSTA', 'NCOST', 'KAUTB', 'MTVFP', 'RGEKZ', 'XCHAR',
    'XCHPF', 'STLAN', 'QZGTP', 'ABCIN', 'CCFIX', 'STAWN', 'KAUSF', 'LOSGR', 'LVORM',
    'KZDKZ', 'PERIV', 'BSTFE', 'FIXLS', 'SCM_FIXPEG_PROD_SET', 'SCM_GRPRT', 'QMATV',
    'LADGR', 'SCM_LSUOM', 'DISLS', 'PSTAT', 'SCM_SHLF_LFE_REQ_MAX', 'MAXLZ', 'MAXLS',
    'BSTMA', 'MABST', 'MINLS', 'BSTMI', 'DISPO', 'DISMM', 'LGPRO', 'PRCTR', 'UEETK',
    '/CWM/TRAME',
)
MARA_HEADER = (
    'MANDT', 'MATNR', 'ERSDA', 'CREATED_AT_TIME', 'ERNAM', 'LAEDA', 'AENAM', 'VPSTA',
    'PSTAT', 'LVORM', 'MTART', 'MBRSH', 'MATKL', 'BISMT', 'MEINS', 'BSTME',
    'ZEINR', 'ZEIAR', 'ZEIVR', 'ZEIFO', 'AESZN', 'BLATT', 'BLANZ', 'FERTH',
    'FORMT', 'GROES', 'WRKST', 'NORMT', 'LABOR', 'EKWSL', 'BRGEW', 'NTGEW',
    'GEWEI', 'VOLUM', 'VOLEH', 'BEHVO', 'RAUBE', 'TEMPB', 'DISST', 'TRAGR',
    'STOFF', 'SPART', 'KUNNR', 'EANNR', 'WESCH', 'BWVOR', 'BWSCL', 'SAISO',
    'ETIAR', 'ETIFO', 'ENTAR', 'EAN11', 'NUMTP', 'LAENG', 'BREIT', 'HOEHE',
    'MEABM', 'PRDHA', 'AEKLK', 'CADKZ', 'QMPUR', 'ERGEW', 'ERGEI', 'ERVOL',
    'ERVOE', 'GEWTO', 'VOLTO', 'VABME', 'KZREV', 'KZKFG', 'XCHPF', 'VHART',
    'FUELG', 'STFAK', 'MAGRV', 'BEGRU', 'DATAB', 'LIQDT', 'SAISJ', 'PLGTP',
    'MLGUT', 'EXTWG', 'SATNR', 'ATTYP', 'KZKUP', 'KZNFM', 'PMATA', 'MSTAE',
    'MSTAV', 'MSTDE', 'MSTDV', 'TAKLV', 'RBNRM', 'MHDRZ', 'MHDHB', 'MHDLP',
    'INHME', 'INHAL', 'VPREH', 'ETIAG', 'INHBR', 'CMETH', 'CUOBF', 'KZUMW',
    'KOSCH', 'SPROF', 'NRFHG', 'MFRPN', 'MFRNR', 'BMATN', 'MPROF', 'KZWSM',
    'SAITY', 'PROFL', 'IHIVI', 'ILOOS', 'SERLV', 'KZGVH', 'XGCHP', 'KZEFF',
    'COMPL', 'IPRKZ', 'RDMHD', 'PRZUS', 'MTPOS_MARA', 'BFLME', 'MATFI', 'CMREL',
    'BBTYP', 'SLED_BBD', 'GTIN_VARIANT', 'GENNR', 'RMATP', 'GDS_RELEVANT', 'WEORA', 'HUTYP_DFLT',
    'PILFERABLE', 'WHSTC', 'WHMATGR', 'HNDLCODE', 'HAZMAT', 'HUTYP', 'TARE_VAR', 'MAXC',
    'MAXC_TOL', 'MAXL', 'MAXB', 'MAXH', 'MAXDIM_UOM', 'HERKL', 'MFRGR', 'QQTIME',
    'QQTIMEUOM', 'QGRP', 'SERIAL', 'PS_SMARTFORM', 'LOGUNIT', 'CWQREL', 'CWQPROC', 'CWQTOLGR',
    'ADPROF', 'IPMIPPRODUCT', 'ALLOW_PMAT_IGNO', 'MEDIUM', 'COMMODITY', 'ANIMAL_ORIGIN', 'TEXTILE_COMP_IND', 'LAST_CHANGED_TIME',
    'MATNR_EXTERNAL', 'CHML_CMPLNC_RLVNCE_IND', 'LOGISTICAL_MAT_CATEGORY', 'SALES_MATERIAL', 'IDENTIFICATION_TAG_TYPE', 'PRODUCTOID', 'SGT_CSGR', 'SGT_COVSA',
    'SGT_STAT', 'SGT_SCOPE', 'SGT_REL', 'ANP', 'PSM_CODE', 'FSH_MG_AT1', 'FSH_MG_AT2', 'FSH_MG_AT3',
    'FSH_SEALV', 'FSH_SEAIM', 'FSH_SC_MID', 'DUMMY_PRD_INCL_EEW_PS', 'SCM_MATID_GUID16', 'SCM_MATID_GUID22', 'SCM_MATURITY_DUR', 'SCM_SHLF_LFE_REQ_MIN',
    'SCM_SHLF_LFE_REQ_MAX', 'SCM_PUOM', 'RMATP_PB', 'PROD_SHAPE', 'MO_PROFILE_ID', 'OVERHANG_TRESH', 'BRIDGE_TRESH', 'BRIDGE_MAX_SLOPE',
    'HEIGHT_NONFLAT', 'HEIGHT_NONFLAT_UOM', 'SCM_KITCOMP', 'SCM_PROD_PAOOPT', 'SCM_BOD_DEPLVL', 'SCM_RESTRICT_INVBAL', 'SCM_DRP_GL_STOCK', 'SCM_EXCL_EXPEDITE',
    'NEWPROD_INDI', 'PRD_STARTDT', 'PRD_ENDDT', 'INV_PLN_MODE', 'FLAGCLASS', '/CWM/XCWMAT', '/CWM/VALUM', '/CWM/TOLGR',
    '/CWM/TARA', '/CWM/TARUM', '/BEV1/LULEINH', '/BEV1/LULDEGRP', '/BEV1/NESTRUCCAT', '/DSD/SL_TOLTYP', '/DSD/SV_CNT_GRP', '/DSD/VC_GROUP',
    '/SAPMP/KADU', '/SAPMP/ABMEIN', '/SAPMP/KADP', '/SAPMP/BRAD', '/SAPMP/SPBI', '/SAPMP/TRAD', '/SAPMP/KEDU', '/SAPMP/SPTR',
    '/SAPMP/FBDK', '/SAPMP/FBHK', '/SAPMP/RILI', '/SAPMP/FBAK', '/SAPMP/AHO', '/SAPMP/MIFRR', '/STTPEC/SERTYPE', '/STTPEC/SYNCACT',
    '/STTPEC/SYNCTIME', '/STTPEC/SYNCCHG', '/STTPEC/COUNTRY_REF', '/STTPEC/PRDCAT', '/VSO/R_TILT_IND', '/VSO/R_STACK_IND', '/VSO/R_BOT_IND', '/VSO/R_TOP_IND',
    '/VSO/R_STACK_NO', '/VSO/R_PAL_IND', '/VSO/R_PAL_OVR_D', '/VSO/R_PAL_OVR_W', '/VSO/R_PAL_B_HT', '/VSO/R_PAL_MIN_H', '/VSO/R_TOL_B_HT', '/VSO/R_NO_P_GVH',
    '/VSO/R_QUAN_UNIT', '/VSO/R_KZGVH_IND', 'PACKCODE', 'DG_PACK_STATUS', 'SRV_DURA', 'SRV_DURA_UOM', 'SRV_SERWI', 'SRV_ESCAL',
    'SOM_CYCLE', 'SOM_CYCLE_RULE', 'SOM_TC_SCHEMA', 'SOM_CTR_AUTORENEWAL', 'MCOND', 'RETDELC', 'LOGLEV_RETO', 'NSNID',
    'ICFA', 'RIC_ID', 'DFS_SENSITIVITY_KEY', 'DFS_MFRP2', 'OVLPN', 'ADSPC_SPC', 'VARID', 'MSBOOKPARTNO',
    'TOLERANCE_TYPE', 'DPCBT', 'XGRDT', 'IMATN', 'PICNUM', 'BSTAT', 'COLOR_ATINN', 'SIZE1_ATINN',
    'SIZE2_ATINN', 'COLOR', 'SIZE1', 'SIZE2', 'FREE_CHAR', 'CARE_CODE', 'BRAND_ID', 'FIBER_CODE1',
    'FIBER_PART1', 'FIBER_CODE2', 'FIBER_PART2', 'FIBER_CODE3', 'FIBER_PART3', 'FIBER_CODE4', 'FIBER_PART4', 'FIBER_CODE5',
    'FIBER_PART5', 'FASHGRD', 'MAKTX', 'MAKTG',
)

_AUSP_TABLES = frozenset({
    'AUSP',
    'AUSP 829.861',
    'AUSP_MATERIAL',
    'AUSP_CLASS',
    'AUSP_CLASSIFICATION',
})


def _norm(value) -> str:
    return str(value or '').strip().upper().replace(' ', '').replace('_', '').replace('.', '')


def fixed_header_for(table_name: str):
    name = str(table_name or '').strip().upper()
    if name == 'MAKT':
        return MAKT_HEADER, ('SPRAS', 'MAKTX', 'MATNR')
    if name == 'MARC':
        return MARC_HEADER, ('MATNR', 'WERKS')
    if name == 'MARA':
        return MARA_HEADER, ('MATNR', 'MTART', 'MAKTX')
    if name in _AUSP_TABLES:
        return AUSP_HEADER, ('ATINN', 'OBJEK', 'ATWRT')
    return None, ()


def _names_present(columns, needed) -> bool:
    have = {_norm(col) for col in columns}
    return all(_norm(name) in have for name in needed)


def _row_is_header(row, header) -> bool:
    if len(row) != len(header):
        return False
    return all(_norm(value) == _norm(name) for value, name in zip(row, header))


def apply_fixed_sap_header(df: pd.DataFrame, table_name: str) -> pd.DataFrame:
    header, needed = fixed_header_for(table_name)
    if df is None or header is None or not needed:
        return df
    if df.empty or _names_present(df.columns, needed):
        return df
    if len(df.columns) != len(header):
        return df
    if _row_is_header(df.iloc[0].tolist(), header):
        out = df.iloc[1:].copy()
        out.columns = list(header)
        out.reset_index(drop=True, inplace=True)
        print(
            f'   [HEADER] {table_name}: первая строка была шапкой, '
            f'столбцы привязаны ({len(header)})'
        )
        return out
    known = {_norm(name) for name in header}
    if any(_norm(col) in known for col in df.columns):
        return df
    out = df.copy()
    out.columns = list(header)
    print(
        f'   [HEADER] {table_name}: имена столбцов не распознаны, '
        f'привязана шапка по позиции ({len(header)})'
    )
    return out
