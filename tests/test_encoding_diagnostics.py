from __future__ import annotations

import os
import sys
import unittest

import pandas as pd

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from utils.encoding_diagnostics import (
    codepoints,
    inspect_frame,
    inspect_value,
    looks_damaged,
    marker_score,
    non_ascii_mask,
    repair_text,
    script_transitions,
)

CLEAN = [
    'Թարթիչ կողային  ATEGO',
    'Շկվորնի TCM15-7',
    'Ետընթացի տեսախցիկ բեռնատարի',
    'Կտրող սկավառակ125x1.0x22.23',
    'Ղեկային ձգաձող Hundai bus',
    'Silicate reagent № 2429600',
    'РЗ-STABISIP NA',
    'КРЫШКА ЛЮКА',
    'MEMBRAN FILTERS 45µM 1000',
    'ΚΑΦΕΣ ΦΙΛΤΡΟΥ',
    'KALEA AMERICANO PL 12oz',
    'HŰTŐFOLYADÉK 20L',
    'ŠROUB M8x20',
    'Uređaj za punjenje',
    'COLA ZERO Mass edit 1',
    '330 CAN 4x6 FANTA OR',
    '',
]

DAMAGED = {
    'Silicate reagent тДЦ 2429600': ('Silicate reagent № 2429600', 'cp866'),
    'Silicate reagent Ñ‚Ð”Ð¦ 2429600': ('Silicate reagent № 2429600', 'cp1252 -> cp866'),
    '╨а╨Ч-STABISIP NA': ('РЗ-STABISIP NA', 'cp866'),
    'Additive to ink 8152-4â•¨Ðµ0.8L': ('Additive to ink 8152-4Х0.8L', 'cp1252 -> cp866'),
}


class DetectorTests(unittest.TestCase):
    def test_clean_values_are_not_flagged(self):
        for text in CLEAN:
            with self.subTest(text=text):
                self.assertEqual([], repair_text(text)[1])
                self.assertFalse(looks_damaged(text))
                self.assertIsNone(inspect_value(text))

    def test_damaged_values_are_repaired_with_codec_chain(self):
        for text, (expected, chain) in DAMAGED.items():
            with self.subTest(text=text):
                self.assertTrue(looks_damaged(text))
                finding = inspect_value(text)
                self.assertIsNotNone(finding)
                self.assertEqual(expected, finding['suggested_original'])
                self.assertEqual(chain, finding['codec_chain'])

    def test_damaged_fragment_is_minimal(self):
        finding = inspect_value('Silicate reagent тДЦ 2429600')
        self.assertEqual('тДЦ', finding['damaged_fragment'])
        self.assertEqual('№', finding['fragment_suggested'])
        self.assertEqual('U+0442 U+0414 U+0426', finding['fragment_codepoints'])

    def test_marker_score_and_transitions(self):
        self.assertEqual(0, marker_score('РЗ-STABISIP NA'))
        self.assertEqual(10, marker_score('╨а╨Ч-STABISIP NA'))
        self.assertEqual(0, script_transitions('КРЫШКА ЛЮКА'))
        self.assertEqual(1, script_transitions('РЗ-STABISIP'))

    def test_none_and_ascii_are_ignored(self):
        self.assertIsNone(inspect_value(None))
        self.assertIsNone(inspect_value('PLAIN ASCII 123'))
        self.assertFalse(looks_damaged(None))

    def test_codepoints_format(self):
        self.assertEqual('U+2116', codepoints('№'))

    def test_non_ascii_mask(self):
        series = pd.Series(['ASCII', 'Թարթիչ', None, 'тДЦ'])
        self.assertEqual([False, True, False, True], non_ascii_mask(series).tolist())


class InspectFrameTests(unittest.TestCase):
    def setUp(self):
        self.df = pd.DataFrame(
            {
                'MATNR': ['000001', '000002', '000003', '000004'],
                'SPRAS': ['E', 'E', 'E', 'E'],
                'MAKTX': [
                    'Silicate reagent тДЦ 2429600',
                    'Թարթիչ կողային  ATEGO',
                    'PLAIN ASCII VALUE',
                    '╨а╨Ч-STABISIP NA',
                ],
            }
        )

    def test_only_damaged_rows_are_returned(self):
        findings = inspect_frame(self.df, ['MAKTX'], key_columns=['MATNR', 'SPRAS'], table='MAKT')

        self.assertEqual(2, len(findings))
        self.assertEqual(['000001', '000004'], [f['MATNR'] for f in findings])
        self.assertEqual({'MAKT'}, {f['table'] for f in findings})
        self.assertEqual({'MAKTX'}, {f['column'] for f in findings})
        self.assertEqual({'E'}, {f['SPRAS'] for f in findings})

    def test_missing_columns_and_empty_frame_are_safe(self):
        self.assertEqual([], inspect_frame(self.df, ['NOPE'], table='MAKT'))
        self.assertEqual([], inspect_frame(self.df.iloc[0:0], ['MAKTX'], table='MAKT'))

    def test_key_columns_absent_from_frame_are_skipped(self):
        findings = inspect_frame(self.df, ['MAKTX'], key_columns=['MATNR', 'MISSING'], table='MAKT')

        self.assertTrue(findings)
        self.assertNotIn('MISSING', findings[0])
        self.assertIn('MATNR', findings[0])


if __name__ == '__main__':
    unittest.main()
