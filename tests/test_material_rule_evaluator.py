from __future__ import annotations

import unittest

import pandas as pd

from utils.material_rule_evaluator import (
    evaluate_ausp_bpp_rule,
    evaluate_makt_rule,
    evaluate_mara_rule,
)


class MaterialRuleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.makt = pd.DataFrame({
            'MATNR': [str(i) for i in range(1, 20)],
            'SPRAS': ['E'] * 19,
            'MAKTX': [f'MATERIAL {i}' for i in range(1, 19)] + ['ABP MATERIAL'],
        })

    def _assert_result(self, result, total, failed):
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(total, len(result['df']))
        self.assertEqual(failed, int((~result['ok_mask']).sum()))

    def test_rpc166_1(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3', '4', '19'],
            'MTART': ['ZFG', 'ZFGS', 'ZFG', 'ZFG', 'ZFG'],
            'MTPOS_MARA': ['NORM', 'NORM', 'ZFGD', 'ZCVI', 'NORM'],
            'MEINS': ['CS', 'EA', 'EA', 'EA', 'EA'],
        })
        result = evaluate_mara_rule(mara, 'RPCONF_166.1', 'MEINS', self.makt)
        self._assert_result(result, 2, 1)

    def test_rpc196_rules(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3', '4', '5', '6'],
            'MTART': ['ZNVL', 'ZNVL', 'ZKIT', 'ZKIT', 'ZSV', 'ZSTL'],
            'MTPOS_MARA': ['ZWST', 'BAD', 'NORM', 'ZWST', 'LEIS', 'BAD'],
        })
        r10 = evaluate_mara_rule(mara, 'RPCONF_196.10', 'MTPOS_MARA', self.makt)
        r11 = evaluate_mara_rule(mara, 'RPCONF_196.11', 'MTPOS_MARA', self.makt)
        r12 = evaluate_mara_rule(mara, 'RPCONF_196.12', 'MTPOS_MARA', self.makt)
        self._assert_result(r10, 4, 2)
        self._assert_result(r11, 1, 0)
        self._assert_result(r12, 1, 1)

    def test_rpc253_4(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3'],
            'MTART': ['ZFGC', 'ZFGC', 'ZFG'],
            'MATKL': ['1111005', '9999999', '9999999'],
        })
        result = evaluate_mara_rule(mara, 'RPCONF_253.4', 'MATKL', self.makt)
        self._assert_result(result, 2, 1)

    def test_rpc265_1(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3'],
            'MTART': ['ZFG', 'ZFGS', 'ZSV'],
            'MHDRZ': ['10', '30', '50'],
            'MHDHB': ['20', '20', '10'],
        })
        result = evaluate_mara_rule(mara, 'RPCONF_265.1', 'MHDRZ', self.makt)
        self._assert_result(result, 2, 1)

    def test_rpc371_1(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3'],
            'MTART': ['ZFG', 'ZNVM', 'ZKIT'],
            'GEWEI': ['KG', 'LB', 'LB'],
        })
        result = evaluate_mara_rule(mara, 'RPCONF_371.1', 'GEWEI', self.makt)
        self._assert_result(result, 2, 1)

    def test_makt_text_rules(self):
        makt = pd.DataFrame({
            'SPRAS': ['E', 'E', 'E', 'R'],
            'MAKTX': ['UPPER CASE', 'Mixed Case', 'DOUBLE  SPACE', 'Mixed Russian'],
        })
        upper = evaluate_makt_rule(makt, 'RPCONF_225.4', 'MAKTX')
        spaces = evaluate_makt_rule(makt, 'RPCONF_225.5', 'MAKTX')
        self._assert_result(upper, 3, 1)
        self._assert_result(spaces, 3, 1)

    def test_rpc53_1(self):
        ausp = pd.DataFrame({
            'ATINN': ['829', '829', '829'],
            'OBJEK': ['000000000000000010', '000000000000000011', '000000000000000012'],
            'ATWRT': ['BPP_OK', 'BPP_BAD', 'ZZZZZZZZZZ'],
            'KLART': ['001', '001', '001'],
            'SAP_CLUSTER': ['CL1', 'CL1', 'CL1'],
            'ATZHL': ['1', '1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12'],
                'MTART': ['ZFG', 'ZFGS', 'ZFGC'],
                'SAP_CLUSTER': ['CL1', 'CL1', 'CL1'],
            }),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('ZMDM_BPP_CODET', result['stats']['reference'])

    def test_rpc53_1_picks_bpp_atinn_from_mixed_ausp(self):
        ausp = pd.DataFrame({
            'ATINN': ['24', '143', '0000000829', '868', '829'],
            'OBJEK': ['1', '2', '000000000000000010', '000000000000000011', '000000000000000013'],
            'ATWRT': ['COOLER', 'CAF', 'BPP_OK', 'BPP_BAD', 'IGNORE_KLART'],
            'KLART': ['002', '001', '001', '001', '002'],
            'ATZHL': ['1', '1', '1', '1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '13'],
                'MTART': ['ZFG', 'ZFGS', 'ZFG'],
            }),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual(2, result['stats']['bpp_rows'])
        self.assertEqual({'BPP_OK', 'BPP_BAD'}, set(result['df']['ATWRT']))

    def test_rpc53_1_uses_cabn_atinn(self):
        ausp = pd.DataFrame({
            'ATINN': ['24', '1001', '829'],
            'OBJEK': ['1', '000000000000000010', '000000000000000099'],
            'ATWRT': ['COOLER', 'BPP_OK', 'BPP_BAD'],
            'KLART': ['002', '001', '001'],
            'ATZHL': ['1', '1', '1'],
        })
        tables = {
            'CABN': pd.DataFrame({'ATINN': ['1001'], 'ATNAM': ['CCHBC_BPP_CODE']}),
            'MARA': pd.DataFrame({'MATNR': ['10', '99'], 'MTART': ['ZFG', 'ZFG']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 1, 0)
        self.assertEqual('CABN.ATNAM=CCHBC_BPP_CODE', result['stats']['bpp_atinn_source'])
        self.assertEqual(['BPP_OK'], list(result['df']['ATWRT']))

    def test_rpc53_1_skips_equipment_only_ausp(self):
        ausp = pd.DataFrame({
            'ATINN': ['24', '27', '30', '52'],
            'OBJEK': ['1', '2', '3', '4'],
            'ATWRT': ['COOLER', 'X', 'Y', '1'],
            'KLART': ['002', '002', '002', '002'],
            'ATZHL': ['1', '1', '1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['1'], 'MTART': ['ZFG']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self.assertIsNotNone(result['skip_reason'])
        self.assertIn('24', result['skip_reason'])
        self.assertIn('equipment', result['skip_reason'].lower())


if __name__ == '__main__':
    unittest.main()
