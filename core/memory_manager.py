import gc
import os
import json
import re
import sqlite3
import warnings
from datetime import datetime
import pandas as pd

warnings.filterwarnings('ignore', message='invalid value encountered in cast', category=RuntimeWarning)
from concurrent.futures import ThreadPoolExecutor
from utils.empty_rows import fully_empty_rows_mask
from utils.sqlite_safe import connect_sqlite, find_dq_project_root
try:
    import asyncio
    import aiosqlite
    _HAS_AIOSQLITE = True
except ImportError:
    _HAS_AIOSQLITE = False
TERMINAL_SYMBOLS_LOCAL = {'SUCCESS': '[OK]', 'ERROR': '[ERROR]', 'WARNING': '[WARN]', 'INFO': '[INFO]', 'SKIP': '[SKIP]', 'ROCKET': '[START]', 'GEAR': '[PROC]', 'MAGNIFYING_GLASS': '[CHECK]', 'CHECKMARK': '[DONE]', 'CHART_UP': '[STAT+]', 'CHART_DOWN': '[STAT-]', 'CLIPBOARD': '[CLIP]', 'FILE_FOLDER': '[DIR]', 'PAGE': '[FILE]', 'TABLE': '[TABLE]', 'COLUMN': '[COL]', 'BOOKS': '[DATA]', 'SAVE': '[SAVE]', 'TARGET': '[TARGET]', 'PALETTE': '[STYLE]', 'CELEBRATION': '[DONE]', 'BAR_CHART': '[CHART]', 'MEMO': '[NOTE]'}


def _term(symbol_name: str) -> str:
    return TERMINAL_SYMBOLS_LOCAL.get(symbol_name, '')

class MemoryManager:
    AUSP_DERIVED_NAMES = ('AUSP_143', 'AUSP_604', 'AUSP_148', 'AUSP_151')
    AUSP_ATINN_TO_COLUMN = {'143': 'CCAF', '604': 'RED_OUTLET', '148': 'ZGLOBAL_CUSTOMER', '151': 'ZTRADE_NAME'}
    DFKKBPTAXNUM_TABLES = ('DFKKBPTAXNUM1', 'DFKKBPTAXNUM2', 'DFKKBPTAXNUM3', 'DFKKBPTAXNUM4', 'DFKKBPTAXNUM5', 'DFKKBPTAXNUM6')
    TABLES_UNIQUE_PARTNER = ('ZBUT0000P3VVI9', 'ZBUT0000P', 'ZBUT0000P3VV19')
    TABLE_NAME_ALIASES = {'/LOT/GC_ADR': 'LOTGC_ADR', 'ZBUT0000P3VVI9': 'ZBUT0000P3VVI9_CRM'}
    AUSP_LOAD_NAME = 'AUSP'
    # drop_duplicates на load для таблиц больше порога — дорого и редко нужно (есть спец. дедуп)
    DROP_DUPES_MAX_ROWS = 500_000
    LOAD_THREAD_WORKERS = 4

    def __init__(self, db_path, *, use_parquet_cache: bool=True, rebuild_parquet_cache: bool=False):
        self.db_path = db_path
        self.data_cache = {}
        self.reference_cache = {}
        self._unique_partner_count = {}
        self.use_parquet_cache = bool(use_parquet_cache)
        self.rebuild_parquet_cache = bool(rebuild_parquet_cache)
        self._parquet_engine = self._detect_parquet_engine()
        if self.use_parquet_cache and not self._parquet_engine:
            print(f'   {_term("WARNING")} Parquet-кэш выключен: установите pyarrow (pip install pyarrow)')
            self.use_parquet_cache = False
        self._ensure_db_integrity()
        if self.use_parquet_cache:
            print(f'   {_term("INFO")} Parquet-кэш: {self._parquet_cache_dir()} (engine={self._parquet_engine}'
                  f'{", REBUILD" if self.rebuild_parquet_cache else ""})')

    @staticmethod
    def _detect_parquet_engine():
        try:
            import pyarrow  # noqa: F401
            return 'pyarrow'
        except ImportError:
            try:
                import fastparquet  # noqa: F401
                return 'fastparquet'
            except ImportError:
                return None

    def _parquet_cache_dir(self) -> str:
        root = find_dq_project_root(__file__)
        stem = os.path.splitext(os.path.basename(self.db_path or 'db'))[0] or 'db'
        # безопасное имя каталога
        stem = re.sub(r'[^\w.\-]+', '_', stem)
        return os.path.join(root, 'cache', 'parquet', stem)

    def _parquet_path_for_table(self, table_name: str) -> str:
        safe = re.sub(r'[^\w.\-]+', '_', str(table_name or 'table'))
        return os.path.join(self._parquet_cache_dir(), f'{safe}.parquet')

    def _db_fingerprint(self) -> tuple:
        try:
            st = os.stat(self.db_path)
            return (int(st.st_mtime_ns), int(st.st_size))
        except OSError:
            return (0, 0)

    def _parquet_is_fresh(self, parquet_path: str) -> bool:
        if self.rebuild_parquet_cache or not self.use_parquet_cache:
            return False
        if not parquet_path or not os.path.isfile(parquet_path):
            return False
        try:
            db_mtime = os.path.getmtime(self.db_path)
            pq_mtime = os.path.getmtime(parquet_path)
            # parquet не старше БД (допуск 2с на FS)
            return pq_mtime + 2.0 >= db_mtime
        except OSError:
            return False

    def _try_load_parquet(self, table_name: str):
        if not self.use_parquet_cache or not self._parquet_engine:
            return None
        path = self._parquet_path_for_table(table_name)
        if not self._parquet_is_fresh(path):
            return None
        t0 = datetime.now()
        try:
            df = pd.read_parquet(path, engine=self._parquet_engine)
            dt = (datetime.now() - t0).total_seconds()
            print(f'   {_term("INFO")} {table_name}: parquet cache hit ({len(df):,} строк, {dt:.1f}с) → {os.path.basename(path)}')
            return df
        except Exception as e:
            print(f'   {_term("WARNING")} {table_name}: parquet read failed ({e}), fallback SQLite')
            return None

    def _save_parquet(self, table_name: str, df: pd.DataFrame):
        if not self.use_parquet_cache or not self._parquet_engine or df is None:
            return
        try:
            os.makedirs(self._parquet_cache_dir(), exist_ok=True)
            path = self._parquet_path_for_table(table_name)
            t0 = datetime.now()
            # category → object for stable round-trip across engines
            out = df.copy()
            for c in out.columns:
                if str(out[c].dtype) == 'category':
                    out[c] = out[c].astype(object)
            out.to_parquet(path, engine=self._parquet_engine, index=False)
            dt = (datetime.now() - t0).total_seconds()
            size_mb = os.path.getsize(path) / (1024 * 1024)
            print(f'   {_term("SAVE")} {table_name}: parquet cache write {size_mb:.1f} MB in {dt:.1f}с')
        except Exception as e:
            print(f'   {_term("WARNING")} {table_name}: parquet write failed: {e}')

    def _postprocess_loaded_df(self, df, table_name, actual_name=None):
        if df is None:
            return None
        label = actual_name or table_name
        if len(df) > 0:
            df = self._optimize_dataframe(df)
        if len(df) > 0:
            if len(df) <= self.DROP_DUPES_MAX_ROWS:
                before = len(df)
                df = df.drop_duplicates()
                if len(df) < before:
                    print(f'   {_term("INFO")} {table_name}: удалено дубликатов {before - len(df):,} (осталось {len(df):,})', flush=True)
            else:
                print(f'   {_term("INFO")} {table_name}: drop_duplicates пропущен (>{self.DROP_DUPES_MAX_ROWS:,} строк)', flush=True)
        if df is not None and len(df) > 0 and (str(table_name).strip().upper() == 'ADRC'):
            df = self._apply_adrc_reserved_filter(df, table_name)
        if df is not None and len(df) > 0:
            df = self._drop_fully_empty_rows(df, log_label=label)
        return df

    def _ensure_db_integrity(self):
        try:
            if not self.db_path:
                return
            if not os.path.exists(self.db_path):
                return
            conn = connect_sqlite(self.db_path)
            try:
                row = conn.execute('PRAGMA quick_check(1);').fetchone()
                res = row[0] if row else None
            finally:
                conn.close()
            if res and str(res).strip().lower() != 'ok':
                stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                corrupted_path = f'{self.db_path}.corrupted_{stamp}'
                os.rename(self.db_path, corrupted_path)
                for suf in ('-wal', '-shm'):
                    p = self.db_path + suf
                    if os.path.exists(p):
                        try:
                            os.rename(p, corrupted_path + suf)
                        except OSError:
                            pass
                connect_sqlite(self.db_path).close()
                print(f'   [WARN] БД {self.db_path} битая ({res}); переименована в {os.path.basename(corrupted_path)} и создана пустая.')
        except Exception:
            return

    def _normalize_atinn_value(self, value):
        if value is None or (isinstance(value, float) and pd.isna(value)):
            return ''
        s = str(value).strip()
        try:
            return str(int(float(s)))
        except (ValueError, TypeError):
            return re.sub('\\.0+$', '', s) if s else ''

    def _find_ausp_columns(self, columns):
        cols = [c for c in columns if c is not None]
        atinn_col = atwrt_col = None
        for c in cols:
            raw = re.sub('[^A-Za-z0-9]', '', str(c).upper())
            if raw == 'ATINN':
                atinn_col = c
            if raw == 'ATWRT':
                atwrt_col = c
        if not atinn_col:
            for c in cols:
                if 'ATINN' in str(c).upper():
                    atinn_col = c
                    break
        if not atwrt_col:
            for c in cols:
                if 'ATWRT' in str(c).upper():
                    atwrt_col = c
                    break
        if not atinn_col and len(cols) >= 2:
            atinn_col = cols[1]
        if not atwrt_col and len(cols) >= 3:
            atwrt_col = cols[2]
        return (atinn_col, atwrt_col)

    def _get_ausp_cache_key(self):
        for k in self.data_cache:
            if str(k).strip().upper() == 'AUSP':
                return k
        return None

    def _find_table_in_db(self, logical_name, all_in_db=None):
        if all_in_db is None:
            all_in_db = self._get_all_table_names()
        logical_upper = str(logical_name or '').strip().upper()
        if not logical_upper:
            return None
        for t in all_in_db:
            if str(t).strip().upper() == logical_upper:
                return t
        alias_physical = self.TABLE_NAME_ALIASES.get(logical_name) or self.TABLE_NAME_ALIASES.get(logical_upper)
        if alias_physical:
            want = str(alias_physical).strip().upper()
            for t in all_in_db:
                if str(t).strip().upper() == want:
                    return t
        for logical, physical in self.TABLE_NAME_ALIASES.items():
            if str(logical).strip().upper() == logical_upper:
                want = str(physical).strip().upper()
                for t in all_in_db:
                    if str(t).strip().upper() == want:
                        return t
        if logical_upper == 'ZBUT0000P3VVI9':
            for t in all_in_db:
                tu = str(t).strip().upper()
                if tu.startswith('ZBUT0000P3VVI9'):
                    return t
        return None

    def _register_logical_table_aliases(self):
        for logical, physical in self.TABLE_NAME_ALIASES.items():
            if logical in self.data_cache:
                continue
            want = str(physical).strip().upper()
            for key, df in self.data_cache.items():
                if df is not None and str(key).strip().upper() == want:
                    self.data_cache[logical] = df
                    break
        if 'ZBUT0000P3VVI9' not in self.data_cache:
            for key, df in self.data_cache.items():
                ku = str(key).strip().upper()
                if ku.startswith('ZBUT0000P3VVI9') and df is not None:
                    self.data_cache['ZBUT0000P3VVI9'] = df
                    break

    def _store_loaded_table(self, table_name, df):
        if df is None:
            return
        if str(table_name).strip().upper() == 'ADRC' and len(df) > 0:
            df = self._apply_adrc_reserved_filter(df, table_name)
        self.data_cache[table_name] = df
        for logical, physical in self.TABLE_NAME_ALIASES.items():
            if str(physical).strip().upper() == str(table_name).strip().upper():
                self.data_cache[logical] = df

    def _collect_tables_to_load(self, table_names: list, add_reference_tables: bool=True):
        if not table_names:
            return []
        all_in_db = self._get_all_table_names()
        to_load = set()
        for t in table_names:
            found = self._find_table_in_db(t, all_in_db)
            if found:
                to_load.add(found)
        if self._needs_ausp_load(table_names):
            ausp = self._find_table_in_db(self.AUSP_LOAD_NAME, all_in_db)
            if ausp:
                to_load.add(ausp)
            for derived in self.AUSP_DERIVED_NAMES:
                found = self._find_table_in_db(derived, all_in_db)
                if found:
                    to_load.add(found)
        for logical in table_names:
            found = self._find_table_in_db(logical, all_in_db)
            if found:
                to_load.add(found)
        if set(table_names).intersection(set(self.DFKKBPTAXNUM_TABLES)) or any((str(t).strip().upper() == 'DFKKBPTAXNUM' for t in table_names)):
            dfkk_key = next((t for t in all_in_db if str(t).strip().upper() == 'DFKKBPTAXNUM'), None)
            if dfkk_key:
                to_load.add(dfkk_key)
        if add_reference_tables:
            for ref in ('T005', 'ZW2_CMDEMAND', 'BUT020', 'KNVV'):
                match = self._find_table_in_db(ref, all_in_db)
                if match:
                    to_load.add(match)
        kna1_dependent = {'BUT0BK', 'BUT051', 'KNB1', 'KNVV', 'KNVP', 'KNVH', 'ADR2', 'ADR6', 'ADRC', 'BUT050', 'KNA1'}
        kna1_requested = any((str(t).strip().upper() == 'KNA1' for t in table_names))
        if kna1_dependent.intersection({str(t).strip().upper() for t in table_names}) or kna1_requested:
            match = self._find_table_in_db('KNA1', all_in_db)
            if match:
                to_load.add(match)
            ref_cmd = self._find_table_in_db('ZW2_CMDEMAND', all_in_db)
            if ref_cmd:
                to_load.add(ref_cmd)
        if kna1_requested:
            for ref in ('CDHDR', 'CDPOS'):
                match = next((t for t in all_in_db if str(t).strip().upper() == ref), None)
                if match:
                    to_load.add(match)
        # ADRC / ADR2 / ADR6 → BUT020 (Addr.No. → PARTNER)
        if any((str(t).strip().upper() in ('ADRC', 'ADR2', 'ADR6') for t in table_names)):
            if any((str(t).strip().upper() == 'ADRC' for t in table_names)):
                if not any((str(x).strip().upper() == 'ADRC' for x in to_load)):
                    match = next((x for x in all_in_db if str(x).strip().upper() == 'ADRC'), None)
                    if match:
                        to_load.add(match)
            for ref in ('BUT020',):
                match = self._find_table_in_db(ref, all_in_db)
                if match:
                    to_load.add(match)
        # LOT_GC_ADR / LOTGC_ADR → нужен BUT020 + KNA1 (клиент по ADRNR)
        lot_names = {'/LOT/GC_ADR', 'LOTGC_ADR', 'LOT_GC_ADR'}
        if any((str(t).strip().upper().replace('/', '').replace('_', '') == 'LOTGCADR' or str(t).strip().upper() in lot_names for t in table_names)):
            for ref in ('BUT020', 'KNA1'):
                match = self._find_table_in_db(ref, all_in_db)
                if match:
                    to_load.add(match)
        return sorted(to_load)

    def _needs_ausp_load(self, table_names):
        if not table_names:
            return False
        ausp_derived = {str(x).strip().upper() for x in self.AUSP_DERIVED_NAMES}
        for t in table_names:
            tu = str(t or '').strip().upper()
            if tu == self.AUSP_LOAD_NAME or tu in ausp_derived:
                return True
        return False

    def _finalize_load_postprocess(self):
        if self._get_dfkkbptaxnum_cache_key():
            self._build_dfkkbptaxnum_alias_tables()
        self._build_ausp_derived_tables()
        self._register_logical_table_aliases()
        for t in self.TABLES_UNIQUE_PARTNER:
            if t in self.data_cache:
                self._apply_unique_partner_dedup(t)
        self._optimize_dataframes()

    def _build_ausp_derived_tables(self):
        ausp_key = self._get_ausp_cache_key()
        if not ausp_key:
            return
        if all((d in self.data_cache for d in self.AUSP_DERIVED_NAMES)):
            return
        df = self.data_cache[ausp_key]
        if df is None or df.empty:
            return
        atinn_col, atwrt_col = self._find_ausp_columns(df.columns)
        if not atinn_col or not atwrt_col:
            print(f'   {_term("WARNING")} AUSP: колонки ATINN/ATWRT не найдены, производные таблицы не созданы')
            return
        total_ausp = len(df)
        atinn_normalized = df[atinn_col].apply(self._normalize_atinn_value)
        unique_atinn = sorted(set(atinn_normalized) - {''}, key=lambda x: (len(str(x)), str(x)))
        if unique_atinn:
            sample = ', '.join((str(v) for v in list(unique_atinn)[:15]))
            if len(unique_atinn) > 15:
                sample += f', ... (всего {len(unique_atinn)} значений)'
            print(f'   {_term("INFO")} AUSP: всего {total_ausp:,} строк, в колонке ATINN найдены значения: {sample}')
        for atinn_val, col_name in self.AUSP_ATINN_TO_COLUMN.items():
            derived_name = f'AUSP_{atinn_val}'
            if derived_name in self.data_cache:
                continue
            mask = atinn_normalized == atinn_val
            slice_df = df.loc[mask].copy()
            slice_df = slice_df.rename(columns={atwrt_col: col_name})
            self.data_cache[derived_name] = slice_df
            n = len(slice_df)
            if n > 0:
                print(f'   {_term("INFO")} AUSP: создана таблица {derived_name} (ATINN={atinn_val}, колонка {col_name}): {n:,} строк')
            else:
                print(f'   {_term("WARNING")} AUSP: таблица {derived_name} пуста (нет строк с ATINN={atinn_val}); ожидаемые ATINN: 143, 604, 148, 151')

    def _get_dfkkbptaxnum_taxtype_column(self, df):
        if df is None or df.empty or (not hasattr(df, 'columns')):
            return None
        cols = list(df.columns)
        for root in [os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if __file__ else None, os.getcwd()]:
            if not root:
                continue
            for sub in ('json files', 'config'):
                path = os.path.join(root, sub, 'conf_dfkkbptaxnum.json')
                path = os.path.abspath(path)
                if os.path.isfile(path):
                    try:
                        with open(path, 'r', encoding='utf-8') as f:
                            cfg = json.load(f)
                        for key in ('taxtype_column', 'taxtype_column_name'):
                            col = cfg.get(key)
                            if col and isinstance(col, str) and col.strip():
                                col = col.strip()
                                if col in cols:
                                    return col
                                for c in cols:
                                    if str(c).strip().upper() == col.upper():
                                        return c
                        for c in cfg.get('taxtype_column_alternatives') or []:
                            if c and isinstance(c, str) and c.strip() and (c.strip() in cols):
                                return c.strip()
                    except Exception:
                        pass
        allowed = {1, 2, 3, 4, 5, 6}
        for col in cols:
            try:
                ser = df[col].dropna().astype(str).str.strip()
                nums = pd.to_numeric(ser, errors='coerce').dropna()
                if len(nums) == 0:
                    continue
                uniq = set((int(x) for x in nums.unique() if x == int(x)))
                if uniq and uniq <= allowed:
                    return col
            except Exception:
                continue
        for col in cols:
            cu = str(col).upper().replace(' ', '').replace('_', '')
            if cu in ('TAXTYPE', 'TAXTYP', 'TAXNUMTYPE', 'TYPE') or 'TAXTYPE' in cu or 'TAXTYP' in cu:
                return col
        return None

    def _get_dfkkbptaxnum_cache_key(self):
        for k in self.data_cache:
            if str(k).strip().upper() == 'DFKKBPTAXNUM':
                return k
        return None

    def _build_dfkkbptaxnum_alias_tables(self):
        cache_key = self._get_dfkkbptaxnum_cache_key()
        if not cache_key:
            return
        df = self.data_cache[cache_key]
        if df is None or df.empty:
            for name in self.DFKKBPTAXNUM_TABLES:
                self.data_cache[name] = df
            return
        type_col = self._get_dfkkbptaxnum_taxtype_column(df)
        if not type_col or type_col not in df.columns:
            print(f'   {_term("WARNING")} DFKKBPTAXNUM: колонка типа не найдена — постоянные таблицы не созданы. Укажите taxtype_column в conf_dfkkbptaxnum.json. Колонки: {list(df.columns)[:20]}')
            for name in self.DFKKBPTAXNUM_TABLES:
                self.data_cache[name] = df
            return
        total = len(df)
        try:
            conn = connect_sqlite(self.db_path)
            for table_name in self.DFKKBPTAXNUM_TABLES:
                m = re.match('DFKKBPTAXNUM(\\d)$', table_name, re.I)
                if not m:
                    self.data_cache[table_name] = df
                    continue
                typ = int(m.group(1))
                type_ser = df[type_col].astype(str).str.strip()
                numeric_type = pd.to_numeric(type_ser, errors='coerce')
                mask = (numeric_type == typ) | (type_ser == str(typ)) | (type_ser.str.upper() == f'RU{typ}')
                slice_df = df.loc[mask].copy()
                n = len(slice_df)
                slice_df.to_sql(table_name, conn, if_exists='replace', index=False)
                self.data_cache[table_name] = slice_df
                if n != total and n > 0:
                    print(f'   {_term("INFO")} DFKKBPTAXNUM: постоянная таблица {table_name} — {n:,} строк (taxtype={typ}), всего в исходной: {total:,}')
            conn.close()
            print(f'   {_term("INFO")} DFKKBPTAXNUM: созданы постоянные таблицы DFKKBPTAXNUM1..6 по полю taxtype, «Всего записей» — по каждой отдельно')
        except Exception as e:
            print(f'   {_term("WARNING")} DFKKBPTAXNUM: не удалось записать постоянные таблицы в БД: {e}')
            for table_name in self.DFKKBPTAXNUM_TABLES:
                m = re.match('DFKKBPTAXNUM(\\d)$', table_name, re.I)
                if m:
                    typ = int(m.group(1))
                    type_ser = df[type_col].astype(str).str.strip()
                    numeric_type = pd.to_numeric(type_ser, errors='coerce')
                    mask = (numeric_type == typ) | (type_ser == str(typ)) | (type_ser.str.upper() == f'RU{typ}')
                    self.data_cache[table_name] = df.loc[mask].copy()
                else:
                    self.data_cache[table_name] = df

    def _load_partner_column_config(self, table_name):
        if table_name not in self.TABLES_UNIQUE_PARTNER:
            return None
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) if __file__ else os.getcwd()
        for path in [os.path.join(root, 'json files', 'conf_zbut0000p_partner.json'), os.path.join(os.getcwd(), 'json files', 'conf_zbut0000p_partner.json'), os.path.join(root, 'config', 'conf_zbut0000p_partner.json')]:
            path = os.path.abspath(path)
            if os.path.isfile(path):
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        cfg = json.load(f)
                    col = cfg.get('partner_column') or cfg.get('partner_column_name')
                    if col and isinstance(col, str) and col.strip():
                        return col.strip()
                except Exception:
                    pass
        return None

    def _find_partner_column_for_dedup(self, table_name, df):
        if df is None or df.empty or table_name not in self.TABLES_UNIQUE_PARTNER:
            return None
        cols = list(df.columns)
        config_col = self._load_partner_column_config(table_name)
        if config_col:
            for c in cols:
                if str(c).strip().upper() == config_col.strip().upper():
                    return c
            if config_col in cols:
                return config_col
        col_upper = {str(c).strip().upper(): c for c in cols}
        for name in ('PARTNER', 'PARTNERS', 'PARTNER_ID', 'KUNNR', 'BP', 'CUSTOMER', 'CLIENT'):
            if name in col_upper:
                return col_upper[name]
        for cu, col in col_upper.items():
            if 'PARTNER' in cu or 'KUNNR' in cu or cu == 'BP':
                return col
        return None

    def _apply_unique_partner_dedup(self, table_name):
        if table_name not in self.TABLES_UNIQUE_PARTNER or table_name not in self.data_cache:
            return
        df = self.data_cache[table_name]
        if df is None or df.empty:
            return
        partner_col = self._find_partner_column_for_dedup(table_name, df)
        if not partner_col:
            print(f'   {_term("WARNING")} {table_name}: колонка PARTNER не найдена — таблица партнёров не создана. Укажите partner_column в conf_zbut0000p_partner.json. Колонки: {list(df.columns)[:25]}')
            return
        before = len(df)
        df_unique = df.drop_duplicates(subset=[partner_col], keep='first').copy()
        n_after = len(df_unique)
        partners_table_name = f'{table_name}_partners'
        try:
            conn = connect_sqlite(self.db_path)
            df_unique.to_sql(partners_table_name, conn, if_exists='replace', index=False)
            conn.close()
            self._unique_partner_count[table_name] = n_after
            if before > n_after:
                print(f'   {_term("INFO")} {table_name}: создана таблица {partners_table_name} для колонки «Всего записей»: {n_after:,} кастомеров (в сырых данных {before:,} строк, дубли по торговым точкам не считаются)')
            else:
                print(f'   {_term("INFO")} {table_name}: создана таблица {partners_table_name}: {n_after:,} кастомеров (дублей не было)')
        except Exception as e:
            print(f'   {_term("WARNING")} {table_name}: не удалось создать таблицу {partners_table_name}: {e}')

    def get_unique_partner_count(self, table_name):
        return self._unique_partner_count.get(table_name)

    def _get_all_table_names(self):
        conn = connect_sqlite(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        names = [row[0] for row in cursor.fetchall()]
        conn.close()
        return names

    def load_selected_tables_to_ram(self, table_names: list, add_reference_tables: bool=True):
        if not table_names:
            self.load_all_data_to_ram()
            return
        to_load = self._collect_tables_to_load(table_names, add_reference_tables)
        if not to_load:
            suffix = '...' if len(table_names) > 10 else ''
            print(f'{_term("WARNING")} Нет таблиц для загрузки (проверьте имена). Запрошено: {table_names[:10]}{suffix}')
            return
        print(f'{_term("ROCKET")} ЗАГРУЗКА В ОЗУ: {len(to_load)} таблиц')
        loaded_count = 0
        workers = min(self.LOAD_THREAD_WORKERS, max(1, len(to_load)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {t: executor.submit(self._load_single_table, t) for t in to_load}
            for table_name in to_load:
                try:
                    print(f'   [Ожидание] {table_name}...', end=' ', flush=True)
                    df = futures[table_name].result()
                    print(f'готово', flush=True)
                    loaded_count += 1
                    if df is not None:
                        self._store_loaded_table(table_name, df)
                        mem = df.memory_usage(deep=True).sum() / 1024 / 1024
                        n = len(df)
                        sym = _term("SUCCESS") if n > 0 else _term("WARNING")
                        print(f'   [{loaded_count}/{len(to_load)}] {sym} {table_name}: {n:,} строк, {mem:.1f} MB')
                    else:
                        print(f'   [{loaded_count}/{len(to_load)}] {_term("ERROR")} {table_name}: ошибка загрузки')
                except Exception as e:
                    loaded_count += 1
                    print(f'ошибка', flush=True)
                    print(f'   [{loaded_count}/{len(to_load)}] {_term("ERROR")} {table_name}: {e}')
        print(f'   {_term("INFO")} Постобработка (DFKKBPTAXNUM, AUSP, алиасы таблиц, дедупликация партнёров)...')
        self._finalize_load_postprocess()
        total_rows = sum((len(df) for df in self.data_cache.values()))
        total_memory = self.get_memory_usage()
        print(f'{_term("CHECKMARK")} ЗАГРУЗКА ЗАВЕРШЕНА!')
        print(f'   {_term("CHART_UP")} Строк в памяти: {total_rows:,}, память: {total_memory:.1f} MB')

    def load_all_data_to_ram(self):
        print(f'{_term("ROCKET")} ЗАГРУЗКА ВСЕХ ДАННЫХ В ОЗУ...')
        all_tables = self._get_all_table_names()
        print(f'{_term("INFO")} Найдено таблиц: {len(all_tables)}')
        loaded_count = 0
        workers = min(self.LOAD_THREAD_WORKERS, max(1, len(all_tables)))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {}
            for table_name in all_tables:
                future = executor.submit(self._load_single_table, table_name)
                futures[table_name] = future
            for table_name, future in futures.items():
                try:
                    print(f'   [Ожидание] {table_name}...', end=' ', flush=True)
                    df = future.result()
                    print(f'готово', flush=True)
                    loaded_count += 1
                    if df is not None:
                        self._store_loaded_table(table_name, df)
                        memory_usage = df.memory_usage(deep=True).sum() / 1024 / 1024
                        row_count = len(df)
                        if row_count > 0:
                            print(f'   [{loaded_count}/{len(all_tables)}] {_term("SUCCESS")} {table_name}: {row_count:,} строк, {memory_usage:.1f} MB')
                        else:
                            print(f'   [{loaded_count}/{len(all_tables)}] {_term("WARNING")} {table_name}: таблица пустая')
                except Exception as e:
                    loaded_count += 1
                    print(f'ошибка', flush=True)
                    print(f'   [{loaded_count}/{len(all_tables)}] {_term("ERROR")} {table_name}: ошибка загрузки - {e}')
        print(f'   {_term("INFO")} Все таблицы загружены. Постобработка...')
        self._finalize_load_postprocess()
        total_rows = sum((len(df) for df in self.data_cache.values()))
        total_memory = self.get_memory_usage()
        print(f'{_term("CHECKMARK")} ЗАГРУЗКА ЗАВЕРШЕНА!')
        print(f'   {_term("CHART_UP")} Всего строк: {total_rows:,}')
        print(f'   {_term("CHART_UP")} Использовано памяти: {total_memory:.1f} MB')

    def _resolve_table_name(self, conn, table_name):
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
        rows = cursor.fetchall()
        all_names = [name for name, in rows]
        found = self._find_table_in_db(table_name, all_names)
        if found:
            return found
        name_to_resolve = self.TABLE_NAME_ALIASES.get(table_name, table_name)
        want_upper = str(name_to_resolve).strip().upper()
        for name in all_names:
            if name and str(name).strip().upper() == want_upper:
                return name
        return table_name

    def _load_single_table(self, table_name):
        """Load table: parquet cache hit → else one-shot SQLite SELECT * (no COUNT/OFFSET)."""
        try:
            cached = self._try_load_parquet(table_name)
            if cached is not None:
                return self._filters_after_parquet(cached, table_name)

            t0 = datetime.now()
            actual_name = table_name
            conn = connect_sqlite(self.db_path, for_bulk_read=True)
            try:
                actual_name = self._resolve_table_name(conn, table_name)
                if str(actual_name) != str(table_name):
                    cached = self._try_load_parquet(actual_name)
                    if cached is not None:
                        return self._filters_after_parquet(cached, table_name)
                escaped_table_name = f'"{actual_name}"'
                df = pd.read_sql_query(f'SELECT * FROM {escaped_table_name}', conn)
            finally:
                conn.close()
            dt = (datetime.now() - t0).total_seconds()
            print(f'   {_term("INFO")} {table_name}: SQLite read {len(df):,} строк за {dt:.1f}с')
            df = self._postprocess_loaded_df(df, table_name, actual_name=actual_name)
            if df is not None and len(df) > 0:
                self._save_parquet(actual_name, df)
                if str(actual_name) != str(table_name):
                    self._save_parquet(table_name, df)
            return df
        except Exception as e:
            print(f'   {_term("ERROR")} Ошибка загрузки {table_name}: {e}')
            return None

    def _filters_after_parquet(self, df, table_name):
        if df is None:
            return None
        out = df
        if len(out) > 0 and str(table_name).strip().upper() == 'ADRC':
            out = self._apply_adrc_reserved_filter(out, table_name)
        if out is not None and len(out) > 0:
            out = self._drop_fully_empty_rows(out, log_label=table_name)
        return out

    def _apply_adrc_reserved_filter(self, df, table_name='ADRC'):
        name1_col = None
        for c in df.columns:
            if str(c).strip().upper() == 'NAME1':
                name1_col = c
                break
        if name1_col is None:
            for c in df.columns:
                if 'NAME' in str(c).upper() and '1' in str(c):
                    name1_col = c
                    break
        if name1_col is None:
            best_col, best_count = (None, 0)
            for c in df.columns:
                try:
                    cnt = (df[c].astype(str).str.strip().str.upper() == 'RESERVED').sum()
                    if cnt > best_count:
                        best_count = cnt
                        best_col = c
                except Exception:
                    pass
            if best_col and best_count > 0:
                name1_col = best_col
        if name1_col is None or name1_col not in df.columns:
            return df
        before = len(df)
        val_str = df[name1_col].astype(str).str.strip().str.upper()
        df = df[val_str != 'RESERVED'].copy()
        dropped = before - len(df)
        if dropped > 0:
            print(f'   {_term("INFO")} ADRC: исключены строки NAME1=RESERVED: {dropped:,} (в кэше {len(df):,})', flush=True)
        return df

    def _drop_fully_empty_rows(self, df, log_label: str | None=None):
        if df is None or len(df) == 0 or df.shape[1] == 0:
            return df
        mask = fully_empty_rows_mask(df)
        n = int(mask.sum())
        if n <= 0:
            return df
        label = log_label or 'таблица'
        print(f'   {_term("INFO")} {label}: исключено полностью пустых строк: {n:,} (осталось {len(df) - n:,})', flush=True)
        return df.loc[~mask].copy()

    @staticmethod
    def _downcast_numeric(series, *, kind: str='float'):
        try:
            coerced = pd.to_numeric(series, errors='coerce')
            if kind == 'integer':
                if coerced.isna().any():
                    return pd.to_numeric(coerced, downcast='float')
                return pd.to_numeric(coerced, downcast='integer')
            return pd.to_numeric(coerced, downcast='float')
        except (ValueError, TypeError):
            return series

    def _concat_dataframe_chunks(self, chunks):
        """Склеить чанки SQL без FutureWarning из-за all-NA колонок между чанками."""
        if not chunks:
            return pd.DataFrame()
        parts = [c for c in chunks if c is not None and len(c) > 0]
        if not parts:
            return pd.DataFrame()
        if len(parts) == 1:
            return parts[0].copy()
        columns = list(dict.fromkeys((col for df in parts for col in df.columns)))
        aligned = [df.reindex(columns=columns) for df in parts]
        for col in columns:
            if any((part[col].isna().all() for part in aligned)):
                aligned = [part.assign(**{col: part[col].astype(object)}) for part in aligned]
        return pd.concat(aligned, ignore_index=True)

    def _optimize_dataframe(self, df):
        if len(df) == 0:
            return df
        import gc
        for col in df.columns:
            col_type = df[col].dtype
            if col_type in ['int64', 'int32']:
                ser = df[col]
                if ser.notna().all():
                    df[col] = self._downcast_numeric(ser, kind='integer')
            elif col_type in ['float64', 'float32']:
                df[col] = self._downcast_numeric(df[col], kind='float')
            elif col_type == 'object':
                unique_ratio = df[col].nunique() / len(df)
                if unique_ratio < 0.5:
                    try:
                        df[col] = df[col].astype('category')
                    except Exception:
                        pass
                elif df[col].dtype == 'object':
                    try:
                        numeric = pd.to_numeric(df[col], errors='coerce')
                        filled = numeric.notna().sum() / len(df)
                        if filled > 0.9:
                            if numeric.isna().any():
                                df[col] = pd.to_numeric(numeric, downcast='float')
                            else:
                                df[col] = pd.to_numeric(numeric, downcast='integer')
                        elif filled > 0.5:
                            df[col] = pd.to_numeric(numeric, downcast='float')
                    except Exception:
                        pass
        gc.collect()
        return df

    def _optimize_dataframes(self):
        print(f'{_term("GEAR")} Финальная оптимизация памяти...')
        for table_name, df in self.data_cache.items():
            if len(df) == 0:
                continue
            if len(df) > 100000:
                gc.collect()

    def get_memory_usage(self):
        total_memory = 0
        for df in self.data_cache.values():
            total_memory += df.memory_usage(deep=True).sum() / 1024 / 1024
        return total_memory

    def get_table(self, table_name):
        requested_upper = str(table_name or '').strip().upper()
        df = None
        cache_key = None
        if table_name in self.data_cache:
            df = self.data_cache[table_name]
            cache_key = table_name
        else:
            physical = self.TABLE_NAME_ALIASES.get(table_name)
            if physical and physical in self.data_cache:
                df = self.data_cache[physical]
                cache_key = physical
        if df is None:
            for k in self.data_cache:
                if str(k).strip().upper() == requested_upper:
                    df = self.data_cache[k]
                    cache_key = k
                    break
        if df is None and requested_upper == 'ZBUT0000P3VVI9':
            for k in self.data_cache:
                if str(k).strip().upper().startswith('ZBUT0000P3VVI9'):
                    df = self.data_cache[k]
                    cache_key = k
                    break
        if df is not None and (not df.empty) and (requested_upper == 'ADRC'):
            df = self._apply_adrc_reserved_filter(df, 'ADRC')
            if cache_key is not None:
                self.data_cache[cache_key] = df
        if df is not None:
            return df
        return None

    def table_exists(self, table_name):
        if table_name in self.data_cache:
            return True
        physical = self.TABLE_NAME_ALIASES.get(table_name)
        if physical is not None and physical in self.data_cache:
            return True
        requested_upper = str(table_name or '').strip().upper()
        for k in self.data_cache:
            if str(k).strip().upper() == requested_upper:
                return True
        if requested_upper == 'ZBUT0000P3VVI9':
            for k in self.data_cache:
                if str(k).strip().upper().startswith('ZBUT0000P3VVI9'):
                    return True
        return False

    async def _load_single_table_async(self, table_name):
        """Async wrapper: reuse sync loader (parquet + bulk SQLite), run in thread pool."""
        try:
            loop = asyncio.get_running_loop()
            df = await loop.run_in_executor(None, self._load_single_table, table_name)
            return (table_name, df)
        except Exception as e:
            print(f'   {_term("ERROR")} {table_name}: {e}')
            return (table_name, None)

    async def load_selected_tables_to_ram_async(self, table_names: list, add_reference_tables: bool=True):
        to_load = self._collect_tables_to_load(table_names, add_reference_tables)
        if not to_load:
            print(f'   {_term("WARNING")} Нет таблиц для загрузки')
            return
        print(f'   {_term("INFO")} Async загрузка: {len(to_load)} таблиц (thread pool + parquet/SQLite)')
        tasks = [self._load_single_table_async(t) for t in to_load]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                print(f'   {_term("ERROR")} {to_load[i]}: {res}')
                continue
            tname, df = res
            if df is not None:
                self._store_loaded_table(tname, df)
                row_count = len(df)
                mem = df.memory_usage(deep=True).sum() / 1024 / 1024
                if row_count > 0:
                    print(f'   {_term("SUCCESS")} {tname}: {row_count:,} строк, {mem:.1f} MB')
        print(f'   {_term("INFO")} Постобработка (DFKKBPTAXNUM, AUSP, алиасы таблиц, дедупликация партнёров)...')
        self._finalize_load_postprocess()
        total_rows = sum((len(d) for d in self.data_cache.values()))
        total_mem = self.get_memory_usage()
        print(f'{_term("CHECKMARK")} Async загрузка завершена: {total_rows:,} строк, {total_mem:.1f} MB')

    def load_selected_tables_to_ram_async_sync(self, table_names: list, add_reference_tables: bool=True):
        # Не зависит от aiosqlite: _load_single_table_async → run_in_executor
        try:
            asyncio.run(self.load_selected_tables_to_ram_async(table_names, add_reference_tables))
        except Exception as e:
            print(f'   {_term("WARNING")} Async load failed ({e}), sync fallback')
            self.load_selected_tables_to_ram(table_names, add_reference_tables)