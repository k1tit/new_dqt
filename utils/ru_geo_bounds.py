"""RCCONF_383.3 / RCCONF_384.3: coordinate inside the Russia bounding box."""
from __future__ import annotations

import re

import pandas as pd

RU_LAT_MIN = round(41 + 11 / 60, 6)
RU_LAT_MAX = round(77 + 43 / 60, 6)
RU_LON_WEST = round(19 + 38 / 60, 6)
RU_LON_EAST = round(-(169 + 40 / 60), 6)

RU_ORDER_BLOCK_SKIP = frozenset({
    'S', 'SP', 'E', 'G', 'S2', 'S3', 'S4', 'S5', 'S9', 'R', 'U', 'M', 'NR',
})


def parse_coord(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip().str.replace('\ufeff', '', regex=False)
    s = s.str.replace(',', '.', regex=False).str.replace(r'\s+', '', regex=True)
    return pd.to_numeric(s, errors='coerce').round(6)


def latitude_inside_russia(num: pd.Series) -> pd.Series:
    return num.notna() & num.ge(RU_LAT_MIN) & num.le(RU_LAT_MAX)


def longitude_inside_russia(num: pd.Series) -> pd.Series:
    in_main = num.ge(RU_LON_WEST) & num.le(180)
    in_wrap = num.ge(-180) & num.le(RU_LON_EAST)
    return num.notna() & (in_main | in_wrap)


def coord_axis(name: str) -> str | None:
    """lat / lon / alt. Altitude is neither rule."""
    n = re.sub(r'[^A-Z0-9]', '', str(name or '').upper())
    if not n or n.startswith('DQ'):
        return None
    if 'LONGITUD' in n or n in {'LON', 'LONG', 'LONGITUDE'}:
        return 'lon'
    if 'LATITUDE' in n or n in {'LAT', 'LATITUDE'}:
        return 'lat'
    if 'ALTITUDE' in n or 'ALTITUD' in n:
        return 'alt'
    return None


def pick_coord_column(columns, axis: str) -> str | None:
    hits = [c for c in columns if coord_axis(c) == axis]
    if not hits:
        return None

    def rank(col: str) -> tuple:
        n = re.sub(r'[^A-Z0-9]', '', str(col).upper())
        preferred = {
            'lon': {'LOTGCLONGITUD', 'LONGITUDE', 'LON'},
            'lat': {'LOTGCLATITUDE', 'LATITUDE', 'LAT'},
        }.get(axis, set())
        return (0 if n in preferred else 1, str(col))

    hits.sort(key=rank)
    return hits[0]


def drop_other_coord_columns(df: pd.DataFrame, keep_axis: str) -> pd.DataFrame:
    drop = [
        c for c in df.columns
        if not str(c).startswith('DQ_') and coord_axis(c) not in (None, keep_axis)
    ]
    if not drop:
        return df
    return df.drop(columns=drop)
