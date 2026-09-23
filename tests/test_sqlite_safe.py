from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.sqlite_safe import (
    ENV_DB_VAR,
    autopick_database_path,
    discover_database_files,
    resolve_database_path,
)


def _make_db(path: str, mtime: float | None = None) -> str:
    conn = sqlite3.connect(path)
    try:
        conn.execute('CREATE TABLE t (a TEXT)')
        conn.commit()
    finally:
        conn.close()
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def _write_config(project_root: str, database: str | None) -> None:
    cfg_dir = os.path.join(project_root, 'config')
    os.makedirs(cfg_dir, exist_ok=True)
    payload = {} if database is None else {'database': database}
    with open(os.path.join(cfg_dir, 'database.json'), 'w', encoding='utf-8') as f:
        json.dump(payload, f)


class DatabaseAutopickTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.parent = self._tmp.name
        self.root = os.path.join(self.parent, 'project')
        os.makedirs(self.root)
        self._saved_env = os.environ.pop(ENV_DB_VAR, None)

    def tearDown(self):
        if self._saved_env is not None:
            os.environ[ENV_DB_VAR] = self._saved_env
        else:
            os.environ.pop(ENV_DB_VAR, None)
        self._tmp.cleanup()

    def test_discover_prefers_newest_and_skips_empty(self):
        old = _make_db(os.path.join(self.root, 'db_april.db'), mtime=1_700_000_000)
        new = _make_db(os.path.join(self.root, 'db_august.db'), mtime=1_800_000_000)
        empty = os.path.join(self.root, 'db_june.db')
        open(empty, 'wb').close()

        found = discover_database_files(self.root)

        self.assertEqual([new, old], found)
        self.assertNotIn(empty, found)

    def test_discover_includes_parent_directory(self):
        above = _make_db(os.path.join(self.parent, 'db_august.db'))

        self.assertIn(above, discover_database_files(self.root))

    def test_same_mtime_prefers_project_root(self):
        stamp = 1_800_000_000
        inside = _make_db(os.path.join(self.root, 'db_august.db'), mtime=stamp)
        _make_db(os.path.join(self.parent, 'db_august.db'), mtime=stamp)

        self.assertEqual(inside, discover_database_files(self.root)[0])

    def test_autopick_reports_choice_and_alternatives(self):
        _make_db(os.path.join(self.root, 'db_april.db'), mtime=1_700_000_000)
        new = _make_db(os.path.join(self.root, 'db_august.db'), mtime=1_800_000_000)

        picked = autopick_database_path(self.root)

        self.assertIsNotNone(picked)
        path, source = picked
        self.assertEqual(new, path)
        self.assertIn('db_august.db', source)
        self.assertIn('db_april.db', source)

    def test_autopick_returns_none_without_candidates(self):
        self.assertIsNone(autopick_database_path(self.root))

    def test_resolve_falls_back_when_config_file_missing(self):
        _write_config(self.root, 'db_august.db')
        actual = _make_db(os.path.join(self.root, 'db_september.db'))

        path, source = resolve_database_path(self.root)

        self.assertEqual(actual, path)
        self.assertIn('авто-выбор', source)
        self.assertIn('db_august.db не найден', source)

    def test_resolve_keeps_existing_config_target(self):
        _write_config(self.root, 'db_august.db')
        configured = _make_db(os.path.join(self.root, 'db_august.db'), mtime=1_700_000_000)
        _make_db(os.path.join(self.root, 'db_september.db'), mtime=1_800_000_000)

        path, source = resolve_database_path(self.root)

        self.assertEqual(configured, path)
        self.assertNotIn('авто-выбор', source)

    def test_resolve_does_not_autopick_for_explicit_cli_path(self):
        _make_db(os.path.join(self.root, 'db_august.db'))

        path, source = resolve_database_path(self.root, cli_path='missing.db')

        self.assertEqual(os.path.join(self.root, 'missing.db'), path)
        self.assertEqual('аргумент --db', source)
        with self.assertRaises(FileNotFoundError):
            resolve_database_path(self.root, cli_path='missing.db', must_exist=True)

    def test_resolve_does_not_autopick_for_env_var(self):
        _make_db(os.path.join(self.root, 'db_august.db'))
        os.environ[ENV_DB_VAR] = 'missing.db'

        path, source = resolve_database_path(self.root)

        self.assertEqual(os.path.join(self.root, 'missing.db'), path)
        self.assertIn(ENV_DB_VAR, source)


if __name__ == '__main__':
    unittest.main()
