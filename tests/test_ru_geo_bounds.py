import pandas as pd

from utils.ru_geo_bounds import (
    RU_LAT_MAX,
    RU_LAT_MIN,
    RU_LON_EAST,
    RU_LON_WEST,
    latitude_inside_russia,
    longitude_inside_russia,
    parse_coord,
    pick_coord_column,
)
from validators.conformity import ConformityValidator


def test_bounds_constants():
    assert RU_LAT_MIN == 41.183333
    assert RU_LAT_MAX == 77.716667
    assert RU_LON_WEST == 19.633333
    assert RU_LON_EAST == -169.666667


def test_latitude_box():
    num = parse_coord(pd.Series(['41.183333', '55,7558', '77.716667', '41.183332', '0', '90', None, '']))
    inside = latitude_inside_russia(num)
    assert inside.tolist()[:5] == [True, True, True, False, False]
    assert bool(inside.iloc[5]) is False
    assert bool(inside.iloc[6]) is False


def test_longitude_wraps_antimeridian():
    num = parse_coord(pd.Series([
        '19.633333',
        '37.6173',
        '180',
        '-180',
        '-169.666667',
        '-170',
        '19.633332',
        '0',
        '-169',
        '190',
    ]))
    inside = longitude_inside_russia(num)
    assert inside.tolist() == [True, True, True, True, True, True, False, False, False, False]


def test_validator_skips_null_and_blocks_and_flags_outside():
    df = pd.DataFrame({
        '_LOT_GC_LATITUDE': ['55.75', '0', None, '10', '60'],
        'account_group_code': ['9038', '9038', '9038', '7038', '9038'],
        'central_order_block_code': ['', '', '', '', 'S'],
    })
    validator = ConformityValidator({'rule_code': 'RCCONF_384.3', 'rule_description': 'lat'})
    total, errors, error_df = validator.validate(df, '_LOT_GC_LATITUDE')
    assert total == 2
    assert errors == 1
    assert error_df['_LOT_GC_LATITUDE'].tolist() == ['0']


def test_validator_longitude_moscow_ok_zero_fail():
    df = pd.DataFrame({
        '_LOT_GC_LONGITUD': ['37.6173', '0', '-170.5'],
        'KTOKD': ['9038', '9038', '9038'],
    })
    validator = ConformityValidator({'rule_code': 'RCCONF_383.3', 'rule_description': 'lon'})
    total, errors, error_df = validator.validate(df, '_LOT_GC_LONGITUD')
    assert total == 3
    assert errors == 1
    assert error_df['_LOT_GC_LONGITUD'].tolist() == ['0']


def test_rules_keep_their_own_coordinate():
    df = pd.DataFrame({
        'Latitude': ['54.333752', '0.0', '13.747205', '51.109233'],
        'Longitude': ['0.0', '0.0', '37.6173', '30.5'],
        'Altitude': ['0.0', '0.0', '0.0', '0.0'],
        'KTOKD': ['9038', '9038', '9038', '9038'],
    })
    assert pick_coord_column(df.columns, 'lon') == 'Longitude'
    assert pick_coord_column(df.columns, 'lat') == 'Latitude'

    lon = ConformityValidator({'rule_code': 'RCCONF_383.3', 'rule_description': 'lon'})
    total, errors, error_df = lon.validate(df, 'Longitude')
    assert total == 4
    assert errors == 2
    assert 'Latitude' not in error_df.columns
    assert 'Altitude' not in error_df.columns
    assert error_df['Longitude'].tolist() == ['0.0', '0.0']

    lat = ConformityValidator({'rule_code': 'RCCONF_384.3', 'rule_description': 'lat'})
    total, errors, error_df = lat.validate(df, 'Latitude')
    assert total == 4
    assert errors == 2
    assert 'Longitude' not in error_df.columns
    assert 'Altitude' not in error_df.columns
    assert error_df['Latitude'].tolist() == ['0.0', '13.747205']
