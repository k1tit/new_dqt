from __future__ import annotations
import json
import os
import sqlite3
import time
from typing import Optional, Tuple
DEFAULT_DB_FILENAME = 'db_april.db'
DB_CONFIG_REL = os.path.join('config', 'database.json')
ENV_DB_VAR = 'DQ_DATABASE'
SQLITE_CONNECT_TIMEOUT_SEC = 120.0
SQLITE_BUSY_TIMEOUT_MS = 120000

def find_project_root(start_file: str) -> str:
    return find_dq_project_root(start_file)

def find_dq_project_root(start_file: str | None=None) -> str:
    here = os.path.dirname(os.path.abspath(start_file or __file__))
    cur = here
    for _ in range(12):
        if os.path.isfile(os.path.join(cur, 'main.py')):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    parent = os.path.dirname(here)
    for folder_name in ('data_quality_checker', 'job_project_clean'):
        candidate = os.path.join(parent, folder_name)
        if os.path.isfile(os.path.join(candidate, 'main.py')):
            return candidate
    return here

def default_db_path(project_file: str) -> str:
    root = find_project_root(project_file)
    path, _ = resolve_database_path(root)
    return path

def _normalize_db_spec(project_root: str, spec: str) -> str:
    spec = (spec or '').strip()
    if not spec:
        raise ValueError('пустое имя/путь к базе данных')
    if os.path.isabs(spec):
        return os.path.normpath(spec)
    return os.path.normpath(os.path.join(project_root, spec))

def load_database_config(project_root: str) -> dict:
    path = os.path.join(project_root, DB_CONFIG_REL)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}

def resolve_database_path(project_root: str, cli_path: Optional[str]=None, *, must_exist: bool=False) -> Tuple[str, str]:
    if cli_path and str(cli_path).strip():
        path = _normalize_db_spec(project_root, str(cli_path))
        source = 'аргумент --db'
    elif os.environ.get(ENV_DB_VAR, '').strip():
        path = _normalize_db_spec(project_root, os.environ[ENV_DB_VAR])
        source = f'переменная окружения {ENV_DB_VAR}'
    else:
        cfg = load_database_config(project_root)
        db_spec = (cfg.get('database') or '').strip()
        if db_spec:
            path = _normalize_db_spec(project_root, db_spec)
            period = (cfg.get('period') or '').strip()
            source = DB_CONFIG_REL.replace('\\', '/')
            if period:
                source += f' (period={period})'
        else:
            path = _normalize_db_spec(project_root, DEFAULT_DB_FILENAME)
            source = f'запасной DEFAULT_DB_FILENAME ({DEFAULT_DB_FILENAME})'
    if must_exist and (not os.path.isfile(path)):
        raise FileNotFoundError(f'Файл базы данных не найден: {path}\nИсточник: {source}. Положите .db в корень проекта и обновите {DB_CONFIG_REL} (поле database) или задайте {ENV_DB_VAR} / --db.')
    return (path, source)

def connect_sqlite(db_path: str, *, timeout: Optional[float]=None, busy_timeout_ms: Optional[int]=None, **kwargs) -> sqlite3.Connection:
    t = SQLITE_CONNECT_TIMEOUT_SEC if timeout is None else timeout
    bt = SQLITE_BUSY_TIMEOUT_MS if busy_timeout_ms is None else busy_timeout_ms
    conn = sqlite3.connect(db_path, timeout=t, **kwargs)
    try:
        conn.execute(f'PRAGMA busy_timeout = {int(bt)}')
    except Exception:
        pass
    return conn

def probe_db_writable(db_path: str, *, retries: int=8, sleep_sec: float=1.5) -> Tuple[bool, Optional[BaseException]]:
    last: Optional[BaseException] = None
    for _ in range(max(1, retries)):
        conn = None
        try:
            conn = connect_sqlite(db_path)
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('ROLLBACK')
            return (True, None)
        except sqlite3.OperationalError as e:
            last = e
            msg = str(e).lower()
            if 'locked' in msg or 'busy' in msg:
                time.sleep(sleep_sec)
                continue
            return (False, e)
        except Exception as e:
            return (False, e)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
    return (False, last)

def is_lock_error(exc: BaseException) -> bool:
    s = str(exc).lower()
    return 'locked' in s or 'busy' in s
__all__ = ['DEFAULT_DB_FILENAME', 'DB_CONFIG_REL', 'ENV_DB_VAR', 'connect_sqlite', 'resolve_database_path', 'load_database_config', 'find_project_root', 'find_dq_project_root', 'default_db_path', 'probe_db_writable', 'is_lock_error']