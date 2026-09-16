from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from edit_table.drop_table import (
    collect_targets,
    derived_for,
    drop_tables,
    is_sqlite_internal,
    list_user_tables,
    quote_ident,
    resolve_table_name,
)


class DropTableHelpersTests(unittest.TestCase):
    def test_quote_and_internal(self):
        self.assertEqual('"KNA1"', quote_ident('KNA1'))
        self.assertEqual('"A""B"', quote_ident('A"B'))
        self.assertTrue(is_sqlite_internal('sqlite_master'))
        self.assertFalse(is_sqlite_internal('AUSP'))

    def test_resolve_and_derived(self):
        existing = ['AUSP', 'AUSP_143', 'AUSP_604', 'KNA1', 'AUSP_EQUIPMENT']
        self.assertEqual('KNA1', resolve_table_name(existing, 'kna1'))
        self.assertEqual('AUSP_EQUIPMENT', resolve_table_name(existing, 'AUSP_EQUIPMEN'))
        self.assertIsNone(resolve_table_name(existing, 'sqlite_stat1'))
        self.assertEqual(['AUSP_143', 'AUSP_604'], derived_for('AUSP', existing))
        targets, missing = collect_targets(existing, ['AUSP'], [], with_derived=True)
        self.assertEqual(['AUSP', 'AUSP_143', 'AUSP_604'], targets)
        self.assertEqual([], missing)

    def test_drop_in_temp_db(self):
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        try:
            conn = sqlite3.connect(path)
            conn.execute('CREATE TABLE KNA1 (x INTEGER)')
            conn.execute('CREATE TABLE KEEPME (x INTEGER)')
            conn.commit()
            dropped = drop_tables(conn, ['KNA1'])
            self.assertEqual(['KNA1'], dropped)
            self.assertEqual(['KEEPME'], list_user_tables(conn))
            conn.close()
        finally:
            try:
                os.remove(path)
            except OSError:
                pass


if __name__ == '__main__':
    unittest.main()
