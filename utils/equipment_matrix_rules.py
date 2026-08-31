"""Equipment conf matrices: cooler order-block status + CDE door equivalent."""
from __future__ import annotations

import json
import os
import re
from typing import Any

NO_COOLER_LITERAL = 'No cooler must be linked to this customer'
COOLER_STATUS_CODES = frozenset({'PLCD', 'UINV', 'FOND', 'NACT', 'LOST'})


def _project_roots() -> list[str]:
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(here)
    return [root, os.getcwd()]


def _conf_paths(filename: str) -> list[str]:
    out = []
    for root in _project_roots():
        out.append(os.path.join(root, 'json files', filename))
        out.append(os.path.join(root, 'config', filename))
    return out


def load_conf_mappings(filename: str) -> tuple[list[dict], str | None]:
    """Load mappings[] (or bare list) from json files/<filename>."""
    for path in _conf_paths(filename):
        path = os.path.abspath(path)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, list):
            return ([r for r in data if isinstance(r, dict)], path)
        if isinstance(data, dict):
            for key in ('mappings', 'rules', 'data'):
                rows = data.get(key)
                if isinstance(rows, list) and rows:
                    return ([r for r in rows if isinstance(r, dict)], path)
    return ([], None)


def norm_block_code(v: Any) -> str:
    if v is None:
        return ''
    try:
        import pandas as pd
        if isinstance(v, float) and pd.isna(v):
            return ''
    except Exception:
        pass
    s = str(v).replace('\ufeff', '').replace('\xa0', ' ').strip().strip("'").strip('"')
    if s.lower() in ('', 'none', 'null', 'nan', '<na>', 'nat', 'n/a', 'na'):
        return ''
    if re.fullmatch(r'\d+\.0+', s):
        s = s.split('.')[0]
    return s.upper()


def norm_status_code(v: Any) -> str:
    return norm_block_code(v)


def norm_category_code(v: Any) -> str:
    return norm_block_code(v)


def to_decimal_doors(v: Any) -> float | None:
    """to_decimal(number_of_doors, 1, 1) — one fractional digit."""
    if v is None:
        return None
    try:
        import pandas as pd
        if isinstance(v, float) and pd.isna(v):
            return None
    except Exception:
        pass
    s = str(v).replace('\ufeff', '').replace('\xa0', ' ').strip().replace(',', '.')
    if s.lower() in ('', 'none', 'null', 'nan', '<na>', 'n/a', 'na'):
        return None
    try:
        return round(float(s), 1)
    except (TypeError, ValueError):
        return None


def _is_no_cooler_status(status: str) -> bool:
    s = str(status or '').strip()
    if not s:
        return False
    if s == NO_COOLER_LITERAL:
        return True
    return s.lower().startswith('no cooler must be linked')


def load_cooler_status_matrix() -> tuple[dict[str, set[str]], set[str], str | None]:
    """
    Returns:
      allowed: block -> set(allowed_cooler_status)  [excludes no-cooler literal]
      no_cooler_blocks: set of block codes with no-cooler literal
      path
    """
    rows, path = load_conf_mappings('conf_order_block_cooler_status.json')
    allowed: dict[str, set[str]] = {}
    no_cooler: set[str] = set()
    for r in rows:
        block = norm_block_code(r.get('central_order_block_code'))
        status = str(r.get('allowed_cooler_status') or '').strip()
        if _is_no_cooler_status(status):
            no_cooler.add(block)
            continue
        st = norm_status_code(status)
        if not st:
            continue
        allowed.setdefault(block, set()).add(st)
    return (allowed, no_cooler, path)


def load_door_equivalent_matrix() -> tuple[dict[str, set[float]], str | None]:
    """category -> set of door_equivalent floats."""
    rows, path = load_conf_mappings('conf_cde_category_door_equivalent.json')
    out: dict[str, set[float]] = {}
    for r in rows:
        cat = norm_category_code(r.get('cde_category_code'))
        eq = to_decimal_doors(r.get('door_equivalent'))
        if not cat or eq is None:
            continue
        out.setdefault(cat, set()).add(eq)
    return (out, path)


def account_group_like_7pct(v: Any) -> bool:
    s = norm_block_code(v)
    return bool(s) and s.startswith('7')


def _blank_text(v: Any) -> bool:
    if v is None:
        return True
    try:
        import pandas as pd
        if isinstance(v, float) and pd.isna(v):
            return True
    except Exception:
        pass
    s = str(v).replace('\ufeff', '').replace('\xa0', ' ').strip()
    return s.lower() in ('', 'none', 'null', 'nan', '<na>', 'nat', 'n/a', 'na')


def norm_equipment_status(v: Any) -> str:
    s = norm_status_code(v)
    if not s:
        return ''
    if s in COOLER_STATUS_CODES:
        return s
    for code in COOLER_STATUS_CODES:
        if code in s:
            return code
    return s


def norm_cde_type(v: Any) -> str:
    return norm_block_code(v)


def cooler_scope_skip(
    *,
    model: Any,
    cde_type: Any,
    status: Any,
    account_group: Any,
    require_model: bool = True,
    doors: Any = None,
    category: Any = None,
    require_doors: bool = False,
    require_category: bool = False,
) -> bool:
    """True → rule returns '' (out of scope)."""
    if require_model and _blank_text(model):
        return True
    if norm_cde_type(cde_type) != 'COOLER':
        return True
    st = norm_equipment_status(status)
    if not st or st not in COOLER_STATUS_CODES:
        return True
    if account_group_like_7pct(account_group):
        return True
    if require_doors and to_decimal_doors(doors) is None:
        return True
    if require_category and not norm_category_code(category):
        return True
    return False


def eval_rcconf_342_1(
    block: Any,
    status: Any,
    allowed: dict[str, set[str]],
    no_cooler_blocks: set[str],
) -> str | None:
    """Return '1' pass, '0' fail, None skip (block unknown)."""
    st = norm_equipment_status(status)
    blk = norm_block_code(block)
    allowed_set = allowed.get(blk)
    if allowed_set is not None:
        return '1' if st in allowed_set else '0'
    if blk in no_cooler_blocks:
        return '0'
    return None


def eval_rcconf_342_2(block: Any, no_cooler_blocks: set[str]) -> str:
    """Return '0' if block forbids cooler, else '1'."""
    blk = norm_block_code(block)
    return '0' if blk in no_cooler_blocks else '1'


def eval_rcconf_278_1(
    category: Any,
    doors: Any,
    matrix: dict[str, set[float]],
) -> str:
    """Return '1' if doors match any door_equivalent for category, else '0'."""
    cat = norm_category_code(category)
    eq = to_decimal_doors(doors)
    allowed = matrix.get(cat) or set()
    if eq is not None and eq in allowed:
        return '1'
    return '0'
