"""Локальный HTTP-сервис: загрузка выгрузок из папки в новую SQLite-базу.

Текущий файл из config/database.json не перезаписывается.
Уже существующий файл базы тоже не принимается.

Запуск из каталога new_dqt:
  python scripts/db_load_service.py
  python scripts/db_load_service.py --host 127.0.0.1 --port 8765
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import threading
import traceback
import uuid
from contextlib import redirect_stdout
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from utils.sqlite_safe import load_database_config, resolve_database_path

_DB_NAME = re.compile(r'^db_[A-Za-z0-9_]+\.db$')
_JOBS: dict[str, dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_LOAD_LOCK = threading.Lock()
_LOG_DIR = os.path.join(_PROJECT_ROOT, 'logs', 'db_load')


def _configured_db_path() -> str:
    path, _src = resolve_database_path(_PROJECT_ROOT)
    return os.path.normcase(os.path.abspath(path))


def _new_db_path(database: str) -> str:
    name = str(database or '').strip()
    if not _DB_NAME.match(name):
        raise ValueError('имя базы должно быть вида db_<месяц>.db, без пути')
    path = os.path.normpath(os.path.join(_PROJECT_ROOT, name))
    root = os.path.normcase(os.path.abspath(_PROJECT_ROOT))
    full = os.path.normcase(os.path.abspath(path))
    if os.path.dirname(full) != root:
        raise ValueError('база создаётся только в корне проекта')
    if full == _configured_db_path():
        cfg = load_database_config(_PROJECT_ROOT).get('database') or ''
        raise ValueError(f'это текущая база из config/database.json ({cfg}), для загрузки укажите новое имя')
    if os.path.exists(path):
        raise ValueError(f'файл уже есть: {name}. Сервис пишет только в новую базу')
    return path


def _folder_path(folder: str | None) -> str:
    raw = str(folder or 'db').strip() or 'db'
    path = raw if os.path.isabs(raw) else os.path.join(_PROJECT_ROOT, raw)
    path = os.path.normpath(path)
    root = os.path.normcase(os.path.abspath(_PROJECT_ROOT))
    full = os.path.normcase(os.path.abspath(path))
    if full != root and not full.startswith(root + os.sep):
        raise ValueError('папка выгрузок должна быть внутри проекта')
    if not os.path.isdir(path):
        raise ValueError(f'папка не найдена: {path}')
    return path


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    return {
        'id': job['id'],
        'status': job['status'],
        'database': job['database'],
        'folder': job['folder'],
        'tables': job['tables'],
        'method': job['method'],
        'created_at': job['created_at'],
        'started_at': job.get('started_at'),
        'finished_at': job.get('finished_at'),
        'error': job.get('error'),
        'loaded': job.get('loaded') or [],
        'log': job.get('log'),
    }


def _run_job(job_id: str) -> None:
    with _JOBS_LOCK:
        job = _JOBS[job_id]
        job['status'] = 'running'
        job['started_at'] = datetime.now().isoformat(timespec='seconds')
        log_path = job['log']
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    try:
        from edit_table.add_table import load_all_tables_from_db_folders
        with _LOAD_LOCK:
            with open(log_path, 'w', encoding='utf-8') as log_file:
                with redirect_stdout(log_file):
                    results = load_all_tables_from_db_folders(
                        db_path=job['database_path'],
                        base_folder=job['folder'],
                        method=job['method'],
                        skip_final_dedup=bool(job['skip_final_dedup']),
                        only_tables=job['tables'],
                    )
        loaded = []
        for row in results or []:
            if isinstance(row, dict):
                loaded.append({
                    'table': row.get('table_name'),
                    'rows': row.get('db_rows'),
                    'files': row.get('source_files'),
                })
        with _JOBS_LOCK:
            job['status'] = 'done' if loaded else 'failed'
            job['loaded'] = loaded
            job['finished_at'] = datetime.now().isoformat(timespec='seconds')
            if not loaded:
                job['error'] = 'ни одна таблица не загружена, см. лог'
    except Exception as exc:
        with _JOBS_LOCK:
            job['status'] = 'failed'
            job['finished_at'] = datetime.now().isoformat(timespec='seconds')
            job['error'] = f'{type(exc).__name__}: {exc}'
        with open(log_path, 'a', encoding='utf-8') as log_file:
            log_file.write('\n' + traceback.format_exc())


class LoadHandler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt: str, *args: Any) -> None:
        sys.stderr.write('%s - %s\n' % (self.address_string(), fmt % args))

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get('Content-Length') or '0')
        if length <= 0 or length > 1_000_000:
            raise ValueError('пустое или слишком большое тело запроса')
        raw = self.rfile.read(length)
        data = json.loads(raw.decode('utf-8'))
        if not isinstance(data, dict):
            raise ValueError('ожидался JSON-объект')
        return data

    def do_GET(self) -> None:
        path = urlparse(self.path).path.rstrip('/') or '/'
        if path == '/health':
            self._send(200, {'status': 'ok', 'configured_database': os.path.basename(_configured_db_path())})
            return
        if path == '/v1/loads':
            with _JOBS_LOCK:
                jobs = [_public_job(job) for job in _JOBS.values()]
            self._send(200, {'jobs': jobs})
            return
        prefix = '/v1/loads/'
        if path.startswith(prefix):
            job_id = path[len(prefix):]
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
            if job is None:
                self._send(404, {'error': 'задача не найдена'})
                return
            self._send(200, _public_job(job))
            return
        self._send(404, {'error': 'неизвестный путь'})

    def do_POST(self) -> None:
        path = urlparse(self.path).path.rstrip('/')
        if path != '/v1/loads':
            self._send(404, {'error': 'неизвестный путь'})
            return
        try:
            data = self._read_json()
            database_path = _new_db_path(str(data.get('database') or ''))
            folder = _folder_path(data.get('folder'))
            method = str(data.get('method') or 'fast').strip()
            if method not in ('fast', 'ultra_fast'):
                raise ValueError('method: fast или ultra_fast')
            tables = data.get('tables')
            if tables is not None:
                if not isinstance(tables, list) or not all(isinstance(item, str) and item.strip() for item in tables):
                    raise ValueError('tables: список имён таблиц')
                tables = [item.strip() for item in tables]
        except (ValueError, json.JSONDecodeError) as exc:
            self._send(400, {'error': str(exc)})
            return
        with _JOBS_LOCK:
            if any(job['status'] in ('queued', 'running') for job in _JOBS.values()):
                self._send(409, {'error': 'уже идёт загрузка, дождитесь её окончания'})
                return
            job_id = uuid.uuid4().hex[:12]
            job = {
                'id': job_id,
                'status': 'queued',
                'database': os.path.basename(database_path),
                'database_path': database_path,
                'folder': folder,
                'tables': tables,
                'method': method,
                'skip_final_dedup': bool(data.get('skip_final_dedup')),
                'created_at': datetime.now().isoformat(timespec='seconds'),
                'log': os.path.join(_LOG_DIR, f'{job_id}.log'),
                'loaded': [],
            }
            _JOBS[job_id] = job
        threading.Thread(target=_run_job, args=(job_id,), daemon=True).start()
        self._send(202, _public_job(job))


def main() -> int:
    parser = argparse.ArgumentParser(description='Сервис загрузки таблиц в новую SQLite-базу')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    os.makedirs(_LOG_DIR, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), LoadHandler)
    print(f'Сервис загрузки: http://{args.host}:{args.port}')
    print(f'Текущая база не используется: {os.path.basename(_configured_db_path())}')
    print('POST /v1/loads  {"database":"db_september.db","folder":"db"}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nОстановлен')
    finally:
        server.server_close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
