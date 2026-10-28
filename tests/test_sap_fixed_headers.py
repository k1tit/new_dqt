from __future__ import annotations

import unittest

import pandas as pd

from utils.sap_fixed_headers import AUSP_HEADER, MAKT_HEADER, MARA_HEADER, MARC_HEADER, apply_fixed_sap_header


class FixedSapHeaderTests(unittest.TestCase):
    def test_ausp_unnamed_columns_take_the_fixed_header(self):
        frame = pd.DataFrame([['100', '15', '829']], columns=['col_0', 'col_1', 'col_2'])
        wide = pd.concat(
            [frame, pd.DataFrame([[''] * (len(AUSP_HEADER) - 3)], columns=[f'col_{i}' for i in range(3, len(AUSP_HEADER))])],
            axis=1,
        )
        bound = apply_fixed_sap_header(wide, 'AUSP')
        self.assertEqual(list(AUSP_HEADER), list(bound.columns))
        self.assertEqual('829', bound.iloc[0]['ATINN'])

    def test_ausp_header_row_is_promoted(self):
        columns = [f'col_{i}' for i in range(len(AUSP_HEADER))]
        frame = pd.DataFrame([list(AUSP_HEADER), ['100', '15', '829'] + [''] * (len(AUSP_HEADER) - 3)], columns=columns)
        bound = apply_fixed_sap_header(frame, 'AUSP 829.861')
        self.assertEqual(list(AUSP_HEADER), list(bound.columns))
        self.assertEqual(1, len(bound))
        self.assertEqual('829', bound.iloc[0]['ATINN'])

    def test_named_ausp_header_stays(self):
        frame = pd.DataFrame({'MANDT': ['100'], 'OBJEK': ['15'], 'ATINN': ['829'], 'ATWRT': ['ABC']})
        bound = apply_fixed_sap_header(frame, 'AUSP')
        self.assertEqual(['MANDT', 'OBJEK', 'ATINN', 'ATWRT'], list(bound.columns))

    def test_makt_uses_its_own_header(self):
        frame = pd.DataFrame([['100', '10', 'E', 'COKE', 'COKE']], columns=['c0', 'c1', 'c2', 'c3', 'c4'])
        bound = apply_fixed_sap_header(frame, 'MAKT')
        self.assertEqual(list(MAKT_HEADER), list(bound.columns))
        self.assertEqual('E', bound.iloc[0]['SPRAS'])

    def test_marc_unnamed_columns_take_the_fixed_header(self):
        row = ['100', '10', '3600'] + [''] * (len(MARC_HEADER) - 3)
        frame = pd.DataFrame([row], columns=[f'col_{i}' for i in range(len(MARC_HEADER))])
        bound = apply_fixed_sap_header(frame, 'MARC')
        self.assertEqual(list(MARC_HEADER), list(bound.columns))
        self.assertEqual('3600', bound.iloc[0]['WERKS'])
        self.assertEqual('DISMM', bound.columns[37])

    def test_named_marc_header_stays(self):
        frame = pd.DataFrame({'MATNR': ['10'], 'WERKS': ['3600'], 'DISMM': ['ND']})
        bound = apply_fixed_sap_header(frame, 'MARC')
        self.assertEqual(['MATNR', 'WERKS', 'DISMM'], list(bound.columns))

    def test_mara_unnamed_columns_take_the_fixed_header(self):
        row = [''] * len(MARA_HEADER)
        row[1] = '10'
        row[10] = 'ZFG'
        row[-2] = 'COLA'
        frame = pd.DataFrame([row], columns=[f'col_{i}' for i in range(len(MARA_HEADER))])
        bound = apply_fixed_sap_header(frame, 'MARA')
        self.assertEqual(list(MARA_HEADER), list(bound.columns))
        self.assertEqual('ZFG', bound.iloc[0]['MTART'])
        self.assertEqual('COLA', bound.iloc[0]['MAKTX'])

    def test_ausp_width_is_not_renamed_as_makt(self):
        frame = pd.DataFrame([['x'] * len(AUSP_HEADER)], columns=[f'col_{i}' for i in range(len(AUSP_HEADER))])
        bound = apply_fixed_sap_header(frame, 'MAKT')
        self.assertEqual([f'col_{i}' for i in range(len(AUSP_HEADER))], list(bound.columns))


if __name__ == '__main__':
    unittest.main()
