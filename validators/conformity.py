import pandas as pd
import re
import os
import json
from .base_validator import BaseValidator
_FULLWIDTH_DIGITS = str.maketrans('０１２３４５６７８９', '0123456789')

def _strict_digits_only_tel(val) -> bool:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return True
    try:
        if isinstance(val, (int, float)) and (not pd.isna(val)) and (float(val) == int(float(val))):
            s = str(int(float(val)))
            return bool(s) and s.isdigit()
    except (ValueError, TypeError, OverflowError):
        pass
    s = str(val).strip().replace('\ufeff', '').strip().translate(_FULLWIDTH_DIGITS)
    if not s or s.lower() in ('none', 'null', 'nan', 'na'):
        return True
    if re.match('^\\d+\\.0+$', s):
        s = str(int(float(s)))
    return re.search('[^0-9]', s) is None

def _value_filled_mask(series: pd.Series) -> pd.Series:
    s = series.astype(str).str.strip()
    s_for_zero = s.str.replace(',', '.', regex=False)
    zeroish = s_for_zero.str.match(r'^-?0+(?:[.][0]+)?$', na=False)
    return series.notna() & (s != '') & ~s.str.lower().isin(['none', 'null', 'nan', 'na']) & ~zeroish

def _load_postal_standards(project_root: str) -> list:
    paths = [
        os.path.join(project_root, 'json files', 'conf_postal_code_standard.json'),
        os.path.join(project_root, 'data', 'conf_postal_code_standard.json'),
        os.path.join('json files', 'conf_postal_code_standard.json'),
    ]
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                return data
            if isinstance(data, dict):
                rows = data.get('conf_postal_code_standard') or data.get('standards') or data.get('postal_code_standard')
                if isinstance(rows, list):
                    return rows
        except Exception as e:
            print(f'      [WARN] conf_postal_code_standard: {e}')
    return []

def _normalize_postal_raw(val) -> str:
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ''
    try:
        if isinstance(val, (int, float)) and (not pd.isna(val)) and float(val) == int(float(val)):
            return str(int(float(val)))
    except (ValueError, TypeError, OverflowError):
        pass
    s = str(val).strip().replace('\ufeff', '').strip()
    if re.match(r'^\d+\.0+$', s):
        s = str(int(float(s)))
    return s

def _t005_primary_postal_length(t005_row: dict | None) -> int | None:
    """T005 Length — длина основного почтового индекса (POST_CODE1). Length_1..9 — другие поля (PO box и т.д.)."""
    if not t005_row:
        return None
    ln = t005_row.get('Length')
    if ln is None or str(ln).strip() == '':
        ln = t005_row.get('LENGTH')
    if ln is None or str(ln).strip() == '':
        return None
    try:
        n = int(float(str(ln).strip()))
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None

def _postal_is_valid(val, country: str, standards: list, t005_row: dict | None) -> bool:
    raw = _normalize_postal_raw(val)
    if not raw or raw.lower() in ('none', 'null', 'nan', 'na'):
        return True
    cc = str(country or '').strip().upper()
    digits = re.sub(r'\D', '', raw)
    expected_len = _t005_primary_postal_length(t005_row)
    if expected_len is not None and len(digits) != expected_len:
        return False
    matched_standard = False
    for row in standards:
        row_cc = str(row.get('country_code') or row.get('COUNTRY') or row.get('land1') or '').strip().upper()
        if row_cc and row_cc not in ('*', cc):
            continue
        matched_standard = True
        pattern = row.get('regex') or row.get('pattern')
        if pattern:
            if not re.match(str(pattern), raw, flags=re.IGNORECASE):
                return False
            continue
        allowed = row.get('postal_code') or row.get('POST_CODE1') or row.get('code')
        if allowed is not None:
            allowed_set = row.get('allowed_codes') or row.get('valid_codes')
            if isinstance(allowed_set, (list, set, tuple)):
                if raw.upper() not in {str(x).strip().upper() for x in allowed_set}:
                    return False
            elif str(allowed).strip().upper() != raw.upper():
                return False
    if matched_standard:
        return True
    if cc == 'RU' or not cc:
        return bool(re.fullmatch(r'\d{6}', digits))
    return bool(re.fullmatch(r'[A-Z0-9][A-Z0-9 \-]{0,9}', raw, flags=re.IGNORECASE))

class ConformityValidator(BaseValidator):

    def validate(self, df, column_name, allowed_values=None, technical_definition=None, rule_code=None, **kwargs):
        if column_name not in df.columns:
            return (0, 0, None)
        effective_rule_code = str(rule_code or self.rule_info.get('rule_code', '')).strip().upper()
        if effective_rule_code == 'RCCONF_63.1':
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            conf_path = os.path.join(project_root, 'json files', 'conf_tax_number_format.json')
            allowed_lengths = {8, 9, 10, 12}
            try:
                with open(conf_path, 'r', encoding='utf-8') as f:
                    conf_list = json.load(f)
                for item in conf_list if isinstance(conf_list, list) else []:
                    if str(item.get('country_code', '')).upper() == 'RU':
                        ln = item.get('length')
                        if ln is not None:
                            allowed_lengths.add(int(ln))
            except Exception as e:
                print(f'      [WARN] RCCONF_63.1: conf_tax_number_format: {e}')

            def _norm_tax(v):
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    return ''
                if isinstance(v, (int, float)) and v == int(v):
                    return str(int(v))
                s = str(v).strip()
                if s.endswith('.0') and s[:-2].isdigit():
                    s = s[:-2]
                return s
            short_c = next((c for c in ('Tax_Number', 'TAXNUM', column_name) if c in df.columns), None)
            long_c = next((c for c in ('Tax_Number_Long', 'TAXNUM_LONG') if c in df.columns), None)
            if not short_c and (not long_c):
                return (0, 0, None)
            short_s = df[short_c].map(_norm_tax) if short_c else pd.Series('', index=df.index)
            long_s = df[long_c].map(_norm_tax) if long_c else pd.Series('', index=df.index)
            ser = short_s.where(short_s != '', long_s)
            non_empty = ser != ''
            total_rows = int(non_empty.sum())
            if total_rows == 0:
                return (0, 0, None)
            ok = non_empty & ser.str.match('^\\d+$', na=False) & ser.str.len().isin(allowed_lengths)
            error_mask = non_empty & ~ok
            error_count = int(error_mask.sum())
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Invalid TAXNUM5 format (Tax_Number|Tax_Number_Long). RU lengths: {sorted(allowed_lengths)}')
            return (total_rows, error_count, error_df)
        if effective_rule_code == 'RCCONF_113.1':
            print('      [DEBUG] RCCONF_113.1 fail-safe in ConformityValidator is ACTIVE')
            from utils.sap_account_keys import norm_sap_account_group, norm_sap_recon_account
            account_group_col = None
            for c in df.columns:
                cu = str(c).strip().lower()
                if cu in ('account_group_code', 'b.account_group_code', 'ktokd'):
                    account_group_col = c
                    break
            if not account_group_col:
                print('      [WARN] RCCONF_113.1 in ConformityValidator: account_group_code отсутствует, пропускаем правило')
                return (0, 0, None)
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            conf_path = os.path.join(project_root, 'json files', 'conf_recon_accounts.json')
            allowed_pairs = set()
            try:
                with open(conf_path, 'r', encoding='utf-8') as f:
                    conf = json.load(f)
                rows = conf.get('conf_recon_accounts', []) if isinstance(conf, dict) else []
                for row in rows:
                    g = norm_sap_account_group(row.get('account_group_code'))
                    a = norm_sap_recon_account(row.get('reconciliation_account'))
                    if g and a:
                        allowed_pairs.add((g, a))
            except Exception as e:
                print(f'      [WARN] RCCONF_113.1 in ConformityValidator: не удалось загрузить conf_recon_accounts.json: {e}')
                return (0, 0, None)
            if not allowed_pairs:
                return (0, 0, None)
            recon_norm = df[column_name].apply(norm_sap_recon_account)
            group_norm = df[account_group_col].apply(norm_sap_account_group)
            evaluated_mask = (recon_norm != '') & (group_norm != '')
            total_rows = int(evaluated_mask.sum())
            if total_rows == 0:
                return (0, 0, None)
            eval_idx = df.index[evaluated_mask]
            pair_keys = pd.Series(list(zip(group_norm.loc[eval_idx], recon_norm.loc[eval_idx])), index=eval_idx)
            exists_mask = pd.Series(False, index=df.index)
            exists_mask.loc[eval_idx] = pair_keys.isin(allowed_pairs)
            error_mask = evaluated_mask & ~exists_mask
            error_count = int(error_mask.sum())
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = df[error_mask].copy()
            error_df['DQ_ERROR_TYPE'] = 'INVALID_COMBINATION'
            error_df['DQ_RULE_CODE'] = 'RCCONF_113.1'
            error_df['DQ_RULE_DESCRIPTION'] = self.rule_info.get('rule_description', '')
            error_df['DQ_COLUMN_CHECKED'] = column_name
            error_df['DQ_ERROR_DESCRIPTION'] = 'Invalid combination of account_group_code and reconciliation_account'
            error_df['DQ_TIMESTAMP'] = pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')
            return (total_rows, error_count, error_df)
        if effective_rule_code in {'RCCONF_383.1', 'RCCONF_384.1'}:
            print(f'      [DEBUG] {effective_rule_code}: strict geo-format validator active (dot + 6 decimals)')
            account_group_col = None
            for c in df.columns:
                cu = str(c).strip().lower()
                if cu in ('account_group_code', 'b.account_group_code', 'ktokd', 'b.ktokd', 'kna.ktokd', 'kna.KTOKD'.lower()):
                    account_group_col = c
                    break
            s = df[column_name].astype(str).str.strip()
            is_null_like = df[column_name].isna() | (s == '') | s.str.lower().isin(['none', 'null', 'nan', 'na'])
            integer_part = s.str.replace(',', '.', regex=False).str.extract('^\\s*([+-]?\\d+)', expand=False).fillna('')
            integer_zero = integer_part.str.lstrip('+-').str.lstrip('0').eq('')
            zero_skip = integer_zero & ~is_null_like
            account_group_skip = pd.Series(False, index=df.index)
            if account_group_col is not None:
                ag = df[account_group_col].astype(str).str.strip()
                account_group_skip = ag.str.startswith('7')
            skip_mask = is_null_like | zero_skip | account_group_skip
            evaluated_mask = ~skip_mask
            total_rows = int(evaluated_mask.sum())
            if total_rows == 0:
                return (0, 0, None)
            fmt_ok = s.str.match('^-?\\d{1,3}\\.\\d{6}$', na=False)
            error_mask = evaluated_mask & ~fmt_ok
            error_count = int(error_mask.sum())
            print(f'      [DEBUG] {effective_rule_code}: evaluated={total_rows:,}, errors={error_count:,}')
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Invalid coordinate format in {column_name}. Expected (-)x.xxxxxx / (-)xx.xxxxxx / (-)xxx.xxxxxx with dot as decimal separator.')
            return (total_rows, error_count, error_df)
        if effective_rule_code == 'RCCONF_22.4':
            filled = _value_filled_mask(df[column_name])
            total_rows = int(filled.sum())
            if total_rows == 0:
                return (0, 0, None)

            def _city_has_invalid_number(val) -> bool:
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return False
                text = str(val).strip()
                if not text:
                    return False
                upper = text.upper()
                if 'PRAHA' in upper or 'BRATISLAVA' in upper:
                    return False
                return bool(re.search(r'\d', text))

            error_mask = filled & df[column_name].apply(_city_has_invalid_number)
            error_count = int(error_mask.sum())
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'City name in {column_name} must not contain numeric characters (except PRAHA/BRATISLAVA).')
            return (total_rows, error_count, error_df)
        if effective_rule_code == 'RCCONF_21.1':
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.dirname(current_dir)
            standards = _load_postal_standards(project_root)
            country_col = kwargs.get('country_column')
            if not country_col or country_col not in df.columns:
                for cand in ('COUNTRY', 'country_code', 'C/R', 'LAND1'):
                    resolved = cand if cand in df.columns else None
                    if not resolved:
                        for c in df.columns:
                            if str(c).strip().upper() == cand.upper():
                                resolved = c
                                break
                    if resolved:
                        country_col = resolved
                        break
            t005_by_country = kwargs.get('t005_by_country') or {}
            filled = _value_filled_mask(df[column_name])
            total_rows = int(filled.sum())
            if total_rows == 0:
                return (0, 0, None)
            if country_col and country_col in df.columns:
                countries = df[country_col].astype(str).str.strip().str.upper()
            else:
                countries = pd.Series('', index=df.index)
                print('      [WARN] RCCONF_21.1: колонка страны не найдена — для пустой страны применяется RU-формат (6 цифр)')

            def _row_postal_error(row) -> bool:
                postal = row[column_name]
                if not _value_filled_mask(pd.Series([postal])).iloc[0]:
                    return False
                cc = countries.loc[row.name] if row.name in countries.index else ''
                t005_row = t005_by_country.get(cc) if cc else None
                return not _postal_is_valid(postal, cc, standards, t005_row)

            eval_df = df.loc[filled]
            error_mask = pd.Series(False, index=df.index)
            error_mask.loc[filled] = eval_df.apply(_row_postal_error, axis=1)
            error_count = int(error_mask.sum())
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Postal code in {column_name} is not consistent with conf_postal_code_standard / T005.')
            return (total_rows, error_count, error_df)
        if effective_rule_code == 'RCCONF_24.1':
            from utils.sap_account_keys import norm_sap_account_group
            account_group_col = None
            best_filled = -1
            for c in df.columns:
                cu = str(c).strip().lower()
                if cu in ('account_group_code', 'b.account_group_code', 'ktokd', 'b.ktokd', 'kna.ktokd', 'group_1'):
                    filled = int((df[c].apply(norm_sap_account_group) != '').sum())
                    if filled > best_filled:
                        best_filled = filled
                        account_group_col = c
            if not account_group_col:
                print(f'      [WARN] RCCONF_24.1: account_group_code (KTOKD) not found after KNA1 join; columns: {list(df.columns)[:20]}')
                return (0, 0, None)
            region_col = column_name if column_name in df.columns else None
            if not region_col:
                for cand in ('REGION', 'Rg', 'PO_Region', 'RegStGrp_', 'region', 'region_code'):
                    if cand in df.columns:
                        region_col = cand
                        break
            if not region_col:
                print(f'      [WARN] RCCONF_24.1: REGION column not found; columns: {[c for c in df.columns if "reg" in str(c).lower()][:8]}')
                return (0, 0, None)
            region_filled = _value_filled_mask(df[region_col])
            ktokd_norm = df[account_group_col].apply(norm_sap_account_group)
            mandatory_groups = {'7038', '9038'}
            # Только группы 7038/9038 в scope; NULL KTOKD и прочие группы — пропуск (ELSE '' в правиле).
            eval_mask = ktokd_norm.isin(mandatory_groups)
            total_rows = int(eval_mask.sum())
            if total_rows == 0:
                filled_any = int((ktokd_norm != '').sum())
                print(f'      [WARN] RCCONF_24.1: нет строк с KTOKD in (7038,9038) после JOIN ADRC->BUT020->KNA1 (колонка {account_group_col}, всего с KTOKD: {filled_any:,})')
                return (0, 0, None)
            error_mask = eval_mask & ~region_filled
            error_count = int(error_mask.sum())
            if error_count == 0:
                return (total_rows, 0, None)
            error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', f'Region in {region_col} is mandatory for account groups 7038 and 9038')
            if error_df is not None and 'KTOKD' not in error_df.columns:
                error_df = error_df.copy()
                error_df['KTOKD'] = df.loc[error_mask, account_group_col].values
            return (total_rows, error_count, error_df)
        total_rows = len(df)
        if technical_definition and rule_code in ['RCCONF_38.3', 'RCCONF_39.3', 'RCCONF_39.3.2']:
            if rule_code == 'RCCONF_38.3':
                r3_user_col = None
                for col in df.columns:
                    col_lower = col.lower()
                    if col_lower == 'r3_user' or col_lower == 'r3user' or 'r3_user' in col_lower or ('r3user' in col_lower):
                        r3_user_col = col
                        break
                if r3_user_col:
                    base_mask = df[r3_user_col].astype(str).str.strip() == '1'
                    if not base_mask.any():
                        return (0, 0, None)
                    df_filtered = df[base_mask].copy()
                else:
                    print(f'      [WARN] R3_USER не найден в валидаторе для правила {rule_code}')
                    df_filtered = df.copy()
            else:
                df_filtered = df.copy()
            error_mask = pd.Series([False] * len(df_filtered), index=df_filtered.index)
            null_mask = df_filtered[column_name].isna() | (df_filtered[column_name].astype(str).str.strip() == '')
            non_null_mask = ~null_mask
            if non_null_mask.any():
                for idx in df_filtered[non_null_mask].index:
                    tel_value = df_filtered.loc[idx, column_name]
                    if not _strict_digits_only_tel(tel_value):
                        error_mask.loc[idx] = True
            error_count = error_mask.sum()
            if rule_code == 'RCCONF_39.3.2':
                error_description = f'Invalid telephone number format in {column_name}. Must contain only digits 0-9 (no +, spaces, or other characters). Empty values are allowed. (Only rows with filled PERSNUMBER.)'
            elif rule_code == 'RCCONF_39.3':
                error_description = f'Invalid telephone number format in {column_name}. Must contain only digits 0-9 (no +, spaces, or other characters). Empty values are allowed. (Only rows with empty PERSNUMBER.)'
            else:
                error_description = f'Invalid telephone number format in {column_name}. Must contain only digits 0-9 (no +, spaces, or other characters). Empty values are allowed. Only fixed phones (R3_USER=1) are checked.'
            if error_count > 0:
                error_df = self._prepare_error_dataframe(df_filtered, error_mask, 'CONFORMITY', error_description)
            else:
                error_df = None
            total_rows = non_null_mask.sum() if non_null_mask.any() else 0
            return (total_rows, error_count, error_df)
        elif technical_definition and rule_code == 'RCCONF_38.5':
            error_mask = pd.Series([False] * len(df), index=df.index)
            null_mask = df[column_name].isna()
            non_null_mask = ~null_mask
            if non_null_mask.any():
                for idx in df[non_null_mask].index:
                    phone_value = str(df.loc[idx, column_name]).strip()
                    if not phone_value or phone_value.lower() in ['none', 'null', 'nan', '']:
                        continue
                    if re.search('[^0-9]', phone_value):
                        error_mask.loc[idx] = True
                        continue
                    is_valid_format = False
                    if phone_value.startswith('9') and len(phone_value) == 9:
                        is_valid_format = True
                    elif phone_value.startswith('9') and len(phone_value) == 10:
                        is_valid_format = True
                    elif phone_value.startswith('8') and len(phone_value) == 11 and (len(phone_value) > 1) and (phone_value[1] == '9'):
                        is_valid_format = True
                    if not is_valid_format:
                        error_mask.loc[idx] = True
            error_count = error_mask.sum()
            error_description = f'Invalid telephone format in {column_name}. Must contain only digits and match format (9 or 10 digits starting with 9, or 11 digits starting with 89)'
            if error_count > 0:
                error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', error_description)
            else:
                error_df = None
            if error_df is not None and self.error_saver:
                self._save_errors_if_needed(error_df)
            total_rows = non_null_mask.sum() if non_null_mask.any() else 0
            return (total_rows, error_count, error_df)
        elif technical_definition and rule_code in ['RCCONF_39.5', 'RCCONF_39.5.2']:
            null_mask = df[column_name].isna() | (df[column_name].astype(str).str.strip() == '')
            empty_vals = df[column_name].astype(str).str.strip().str.lower().isin(['none', 'null', 'nan', 'na'])
            null_mask = null_mask | empty_vals
            non_null_mask = ~null_mask
            _fullwidth = str.maketrans('０１２３４５６７８９', '0123456789')

            def _normalize_raw(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return ''
                s = str(val).strip().replace('\ufeff', '').strip()
                s = re.sub('\\s+', '', s)
                return s.translate(_fullwidth)

            def _to_digits(val):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return ''
                s = str(val).strip().replace('\ufeff', '').strip()
                s = re.sub('\\s+', '', s)
                s = s.translate(_fullwidth)
                if not s or s.lower() in ('none', 'null', 'nan'):
                    return ''
                try:
                    if isinstance(val, (int, float)) and val == int(val):
                        return str(int(val))
                except (ValueError, TypeError):
                    pass
                if re.match('^\\d+\\.0+$', s):
                    return str(int(float(s)))
                try:
                    n = float(s)
                    if n == int(n):
                        return str(int(n))
                except (ValueError, TypeError):
                    pass
                return re.sub('\\D', '', s)

            def _raw_has_only_digits_or_plus_separators(raw, d):
                if not raw or not d:
                    return raw == d or not raw
                r = str(raw).translate(_fullwidth)
                r = re.sub('[\\s\\-\\(\\)\\.]', '', r)
                r = r.lstrip('+').strip()
                return r == d

            def _is_valid_format_39_5(d):
                if len(d) == 10 and d[0] == '9':
                    return True
                if len(d) == 11 and d.startswith('89'):
                    return True
                if len(d) == 11 and d.startswith('79'):
                    return True
                return False

            def _is_valid_format_39_5_2(d):
                if len(d) == 10 and d[0] == '9':
                    return True
                if len(d) == 11 and d.startswith('89'):
                    return True
                if len(d) == 11 and d.startswith('79'):
                    return True
                if len(d) == 11 and d[0] == '8' and (d[1] != '9'):
                    return True
                return False

            def _is_error(val, rc):
                if val is None or (isinstance(val, float) and pd.isna(val)):
                    return False
                raw = _normalize_raw(val)
                if not raw or raw.lower() in ('none', 'null', 'nan'):
                    return False
                d = _to_digits(val)
                if not d:
                    return False
                if not _raw_has_only_digits_or_plus_separators(raw, d):
                    return True
                is_valid = _is_valid_format_39_5(d) if rc == 'RCCONF_39.5' else _is_valid_format_39_5_2(d)
                return not is_valid
            error_mask = df[column_name].apply(lambda v: _is_error(v, rule_code))
            error_count = int(error_mask.sum())
            if rule_code == 'RCCONF_39.5.2':
                error_description = f'Invalid telephone number format in {column_name}. RCCONF_39.5.2: 10 digits starting with 9, or 11 digits 89…/79…, or 11 digits 8x (second digit not 9). All digits only (spaces, dashes, brackets, leading + allowed).'
            else:
                error_description = f'Invalid telephone number format in {column_name}. RCCONF_39.5: 10 digits starting with 9, or 11 digits 89…/79…. All digits only (spaces, dashes, brackets, leading + allowed).'
            if error_count > 0:
                error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', error_description)
            else:
                error_df = None
            if error_df is not None and self.error_saver:
                self._save_errors_if_needed(error_df)
            total_rows = non_null_mask.sum() if non_null_mask.any() else 0
            return (total_rows, error_count, error_df)
        elif effective_rule_code == 'RCCONF_24.1':
            print('      [WARN] RCCONF_24.1: попали в generic ConformityValidator — специальная ветка не сработала')
            return (0, 0, None)
        else:
            mask = df[column_name].notna() & ~df[column_name].astype(str).isin(['', 'None', 'null'])
            if allowed_values:
                mask = mask & df[column_name].astype(str).isin(allowed_values)
            error_mask = ~mask
            error_count = error_mask.sum()
            if allowed_values:
                sample_values = list(set(allowed_values))[:5]
                error_description = f'Invalid value in column {column_name}. Allowed: {sample_values}'
            else:
                error_description = f'Invalid value in column {column_name}'
        error_df = self._prepare_error_dataframe(df, error_mask, 'CONFORMITY', error_description)
        if error_df is not None and self.error_saver:
            self._save_errors_if_needed(error_df)
        total_rows = mask.sum() if 'mask' in locals() else len(df)
        return (total_rows, error_count, error_df)