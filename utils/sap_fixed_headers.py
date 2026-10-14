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
