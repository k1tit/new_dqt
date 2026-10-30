from __future__ import annotations

import unittest

import pandas as pd

from utils.material_rule_evaluator import (
    evaluate_ausp_bpp_rule,
    evaluate_makt_rule,
    evaluate_mara_rule,
    evaluate_rpcomp_148_1,
    evaluate_rpcomp_149_1,
    evaluate_rpcomp_284_1,
    evaluate_rpcomp_288_1,
    evaluate_rpcomp_153_1,
    evaluate_rpcomp_199_1,
    evaluate_rpcomp_252_1,
    evaluate_rpcomp_262_1,
    evaluate_rpcomp_263_1,
    evaluate_rpconf_149_8,
    evaluate_material_rule,
    evaluate_rpconf_199_6,
    evaluate_rpconf_160_4,
    evaluate_rpconf_284_1,
    evaluate_rpconf_284_2,
    filter_frame_to_marc_matnrs,
    marc_matnr_key_set,
)


class MaterialRuleEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.makt = pd.DataFrame({
            'MATNR': [str(i) for i in range(1, 20)],
            'SPRAS': ['E'] * 19,
            'MAKTX': [f'MATERIAL {i} RU' for i in range(1, 19)] + ['ABP MATERIAL'],
        })

    def _assert_result(self, result, total, failed):
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(total, len(result['df']))
        self.assertEqual(failed, int((~result['ok_mask']).sum()))

    def test_mara_keeps_only_standalone_ru(self):
        mara = pd.DataFrame({
            'MATNR': ['1', '2', '3', '4', '5', '6'],
            'MTART': ['ZFG', 'ZFG', 'ZFG', 'ZFG', 'ZFG', 'ZFG'],
            'GEWEI': ['KG', 'KG', 'KG', 'KG', 'KG', 'LB'],
        })
        makt = pd.DataFrame({
            'MATNR': ['1', '2', '3', '4', '5', '6'],
            'SPRAS': ['E', 'E', 'E', 'E', 'E', 'E'],
            'MAKTX': ['COLA RU', 'RUSSIA', 'CRUSH', 'ru', 'PRODUCT-RU 1L', 'TRU COKE'],
        })
        result = evaluate_mara_rule(mara, 'RPCONF_371.1', 'GEWEI', makt)
        self._assert_result(result, 2, 0)
        self.assertEqual(['1', '5'], list(result['df']['MATNR']))

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
        self._assert_result(upper, 4, 2)
        self._assert_result(spaces, 4, 1)

    def test_makt_text_rules_without_spras(self):
        makt = pd.DataFrame({'MAKTX': ['UPPER CASE', 'Mixed Case', 'DOUBLE  SPACE']})
        upper = evaluate_makt_rule(makt, 'RPCONF_225.4', 'MAKTX')
        spaces = evaluate_makt_rule(makt, 'RPCONF_225.5', 'MAKTX')
        self.assertIsNone(upper['skip_reason'])
        self.assertIsNone(spaces['skip_reason'])
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
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'CAWNT_M': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_BAD'], 'ATWTB': ['SHOULD NOT COUNT']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('CAWN_M+CAWNT_M', result['stats']['reference'])

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
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_BAD'], 'ATWTB': ['SHOULD NOT COUNT']}),
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
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
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

    def test_rpc53_1_does_not_read_equipment_or_customer_ausp(self):
        customer = pd.DataFrame({
            'ATINN': ['143', '868'],
            'OBJEK': ['1', '000000000000000011'],
            'ATWRT': ['CAF', 'BPP_BAD'],
            'KLART': ['001', '001'],
            'ATZHL': ['1', '1'],
        })
        equipment = pd.DataFrame({
            'ATINN': ['24', '829'],
            'OBJEK': ['1', '000000000000000099'],
            'ATWRT': ['COOLER', 'FROM_EQUIPMENT'],
            'KLART': ['002', '001'],
            'ATZHL': ['1', '1'],
        })
        pinned = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['BPP_OK'],
            'KLART': ['001'],
            'ATZHL': ['1'],
        })
        tables = {
            'AUSP': customer,
            'AUSP_EQUIPMENT': equipment,
            'AUSP 829.861': pinned,
            'CABN': pd.DataFrame({'ATINN': ['829'], 'ATNAM': ['CCHBC_BPP_CODE']}),
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['FROM_EQUIPMENT'], 'ATWTB': ['NO']}),
        }
        result = evaluate_ausp_bpp_rule(
            equipment,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
            table_name='AUSP_EQUIPMENT',
        )
        self._assert_result(result, 1, 0)
        self.assertEqual('AUSP 829.861', result['stats']['ausp_table'])
        self.assertEqual(['BPP_OK'], list(result['df']['ATWRT']))

    def test_rpc53_1_ignores_zmdm_and_plain_cawn(self):
        ausp = pd.DataFrame({
            'ATINN': ['829', '829'],
            'OBJEK': ['000000000000000010', '000000000000000011'],
            'ATWRT': ['BPP_OK', 'BPP_BAD'],
            'KLART': ['001', '001'],
            'ATZHL': ['1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10', '11'], 'MTART': ['ZFG', 'ZFG']}),
            'ZMDM_BPP_CODE': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'CAWN': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'CAWNT': pd.DataFrame({'ATWRT': ['BPP_OK']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self.assertIn('CAWN_M/CAWNT_M', result['skip_reason'])

    def test_rpc53_1_uses_cawn_when_zmdm_missing(self):
        ausp = pd.DataFrame({
            'ATINN': ['829', '829'],
            'OBJEK': ['000000000000000010', '000000000000000011'],
            'ATWRT': ['BPP_OK', 'BPP_BAD'],
            'KLART': ['001', '001'],
            'ATZHL': ['1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10', '11'], 'MTART': ['ZFG', 'ZFG']}),
            'CAWN_M': pd.DataFrame({
                'ATINN': ['829', '829', '24'],
                'ATWRT': ['BPP_OK', 'OTHER', 'COOLER'],
            }),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_BAD'], 'ATWTB': ['NO']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('CAWN_M', result['stats']['reference'])

    def test_rpc53_1_uses_cawn_atwrt_when_atinn_is_not_829(self):
        ausp = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['BPP_OK'],
            'KLART': ['001'],
            'ATZHL': ['1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({'ATINN': ['7'], 'ATWRT': ['BPP_OK']}),
            'CAWNT_M': pd.DataFrame({'ATINN': ['7'], 'ATWRT': ['BPP_OK'], 'ATWTB': ['NAME']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 1, 0)
        self.assertEqual('CAWN_M+CAWNT_M', result['stats']['reference'])

    def test_rpc53_1_uses_cawn_m_and_cawnt_m(self):
        ausp = pd.DataFrame({
            'ATINN': ['829', '829'],
            'OBJEK': ['000000000000000010', '000000000000000011'],
            'ATWRT': ['BPP_OK', 'BPP_BAD'],
            'KLART': ['001', '001'],
            'ATZHL': ['1', '1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10', '11'], 'MTART': ['ZFG', 'ZFG']}),
            'CAWN_M': pd.DataFrame({
                'ATINN': ['829', '829', '24'],
                'ATZHL': ['1', '2', '1'],
                'ATWRT': ['BPP_OK', 'BPP_OTHER', 'COOLER'],
            }),
            'CAWNT_M': pd.DataFrame({
                'ATINN': ['829', '829', '24'],
                'ATZHL': ['1', '2', '1'],
                'SPRAS': ['E', 'E', 'E'],
                'ATWTB': ['OK NAME', 'OTHER NAME', 'COOLER NAME'],
            }),
            'ZMDM_BPP_CODET': pd.DataFrame({
                'ATWRT': ['BPP_OK', 'BPP_BAD'],
                'ATWTB': ['OK NAME', None],
            }),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('CAWN_M', result['stats']['reference'])
        self.assertEqual({'BPP_OK'}, set(result['df'].loc[result['ok_mask'], 'ATWRT']))

    def test_rpc53_1_uses_zmdm_when_cawn_slice_does_not_contain_the_code(self):
        ausp = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['00123'],
            'KLART': ['001'],
            'ATZHL': ['1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({
                'ATINN': ['829'],
                'ATZHL': ['9'],
                'ATWRT': ['OTHER'],
            }),
            'CAWNT_M': pd.DataFrame({
                'ATINN': ['829'],
                'ATZHL': ['9'],
                'SPRAS': ['E'],
                'ATWTB': ['OTHER NAME'],
            }),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['123'], 'ATWTB': ['REAL NAME']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 1, 1)
        self.assertEqual('CAWN_M', result['stats']['reference'])

    def test_rpc53_1_accepts_reference_name_in_any_language(self):
        ausp = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['BPP_OK'],
            'KLART': ['001'],
            'ATZHL': ['1'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({'ATINN': ['829'], 'ATZHL': ['1'], 'ATWRT': ['BPP_OK']}),
            'CAWNT_M': pd.DataFrame({
                'ATINN': ['829'],
                'ATZHL': ['1'],
                'SPRAS': ['R'],
                'ATWTB': ['ИМЯ'],
            }),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 1, 0)

    def test_rpc53_1_ignores_plain_ausp(self):
        customer = pd.DataFrame({
            'ATINN': ['143'],
            'OBJEK': ['1'],
            'ATWRT': ['CAF'],
            'KLART': ['001'],
        })
        material = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['BPP_OK'],
            'KLART': ['1'],
            'ATZHL': ['1'],
        })
        tables = {
            'AUSP': customer,
            'AUSP_EQUIPMENT': pd.DataFrame({
                'ATINN': ['24'],
                'OBJEK': ['9'],
                'ATWRT': ['COOLER'],
                'KLART': ['002'],
            }),
            'AUSP_MATERIAL': material,
            'AUSP 829.861': material,
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
        }
        result = evaluate_ausp_bpp_rule(
            customer,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
            table_name='AUSP',
        )
        self._assert_result(result, 1, 0)
        self.assertEqual('AUSP 829.861', result['stats']['ausp_table'])
        self.assertEqual(['BPP_OK'], list(result['df']['ATWRT']))

    def test_rpc53_1_uses_ausp_829_861(self):
        dump = pd.DataFrame({
            'ATINN': ['829'],
            'OBJEK': ['000000000000000010'],
            'ATWRT': ['BPP_OK'],
            'KLART': ['001'],
            'ATZHL': ['1'],
        })
        equipment = pd.DataFrame({
            'ATINN': ['24'],
            'OBJEK': ['9'],
            'ATWRT': ['COOLER'],
            'KLART': ['002'],
            'ATZHL': ['1'],
        })
        tables = {
            'AUSP 829.861': dump,
            'AUSP': equipment,
            'AUSP_EQUIPMENT': equipment,
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'CAWN_M': pd.DataFrame({'ATWRT': ['BPP_OK']}),
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['COOLER'], 'ATWTB': ['NO']}),
        }
        result = evaluate_ausp_bpp_rule(
            equipment,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
            table_name='AUSP',
        )
        self._assert_result(result, 1, 0)
        self.assertEqual('AUSP 829.861', result['stats']['ausp_table'])
        self.assertEqual(['BPP_OK'], list(result['df']['ATWRT']))

    def test_rpc160_4_skips_empty_mtvfp(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '15', '19'],
            'MTVFP': ['02', None, 'KP', 'Z2', 'KP', 'KP'],
            'WERKS': ['3600', '3800', '3900', '3610', '1000', '4100'],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12', '13', '14', '15', '19'],
                'MTART': ['ZNVM', 'ZNVM', 'ZNVM', 'ZFG', 'ZNVM', 'ZNVM', 'ZNVM'],
            }),
            'MAKT': self.makt,
        }
        result = evaluate_rpconf_160_4(
            marc,
            'MTVFP',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual(1, result['stats']['skipped_empty_mtvfp'])
        self.assertEqual(['02', 'KP'], list(result['df']['MTVFP']))
        self.assertEqual([True, False], list(result['ok_mask']))
        self.assertNotIn('1000', set(result['df']['WERKS'].astype(str)))
        self.assertNotIn('4100', set(result['df']['WERKS'].astype(str)))

    def test_rpc160_4_applies_abp_without_spras(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12'],
            'MTVFP': ['02', 'KP', '02'],
            'WERKS': ['3600', '3600', '3600'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10', '11', '12'], 'MTART': ['ZNVM', 'ZNVM', 'ZNVM']}),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '11', '12'],
                'MAKTX': ['COLA RU', 'ABP COLA RU', 'RUSSIA'],
            }),
        }
        result = evaluate_rpconf_160_4(
            marc,
            'MTVFP',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 1, 0)
        self.assertEqual(['10'], list(result['df']['MATNR'].astype(str)))

    def test_rpc148_1_skips_blocked_mmsta_and_uses_mara_name(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '14', '15', '16', '17'],
            'WERKS': ['3600', '3600', '3800', '3900', '3600', '3600', '4100', '3600'],
            'MMSTA': ['01', '99', '98', '97', '01', '01', '01', '01'],
            'MAABC': [None, None, None, None, 'A', None, None, None],
        })
        mara = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '14', '15', '16', '17'],
            'MTART': ['ZFG', 'ZFG', 'ZFGS', 'ZFGC', 'ZNVM', 'ZFG', 'ZFG', 'ZFG'],
            'MAKTX': ['COLA RU', 'COLA RU', 'COLA RU', 'COLA RU', 'WATER RU', 'ABP SYRUP RU', 'COLA RU', 'RUSSIA'],
        })
        result = evaluate_rpcomp_148_1(
            marc,
            'MAABC',
            lambda name: {'MARA': mara}.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual(['10', '14'], list(result['df']['MATNR'].astype(str)))
        self.assertEqual(['ZFG', 'ZNVM'], list(result['df']['LOOKUP_MATERIAL_TYPE']))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_rpccomp_284_1_applies_ru_abp_and_type(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '14', '19'],
            'WERKS': ['3600', '3600', '3600', '4100', '3600', '3600'],
            'DISMM': [None, 'ND', None, None, None, None],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12', '13', '14', '19'],
                'MTART': ['ZFG', 'ZFG', 'ZCDN', 'ZFG', 'ZFG', 'ZFG'],
            }),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '11', '12', '13', '14', '19'],
                'MAKTX': ['COLA RU', 'COLA RU', 'COLA RU', 'COLA RU', 'RUSSIA', 'ABP COLA RU'],
            }),
        }
        result = evaluate_rpcomp_284_1(marc, 'DISMM', lambda name: tables.get(name, pd.DataFrame()))
        self._assert_result(result, 2, 1)
        self.assertEqual(['10', '11'], list(result['df']['MATNR'].astype(str)))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_rpccomp_288_1_applies_the_same_description_filters(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12'],
            'WERKS': ['3600', '3800', '3600'],
            'BESKZ': [None, 'F', None],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12'],
                'MTART': ['ZFG', 'ZFG', 'ZWST'],
            }),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '11', '12'],
                'MAKTX': ['COLA RU', 'WATER RU', 'COLA RU'],
            }),
        }
        result = evaluate_rpcomp_288_1(marc, 'BESKZ', lambda name: tables.get(name, pd.DataFrame()))
        self._assert_result(result, 2, 1)
        self.assertEqual(['10', '11'], list(result['df']['MATNR'].astype(str)))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_rpc284_1_skips_empty_dismm(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '14', '15'],
            'DISMM': ['ND', None, 'PD', 'X0', 'ND', 'VB'],
            'MMSTA': ['99', '99', '99', '99', '01', '99'],
            'Plnt': ['3600', '3801', '3900', '36', '3899', '4100'],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12', '13', '14', '15'],
                'MTART': ['ZFG', 'ZFG', 'ZFG', 'ZFG', 'ZFG', 'ZPAL'],
                'MSTAE': ['99', '99', '99', '01', '99', '99'],
            }),
            'MAKT': self.makt,
        }
        result = evaluate_rpconf_284_1(
            marc,
            'DISMM',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 3, 1)
        self.assertEqual(1, result['stats']['skipped_empty_dismm'])
        self.assertEqual(['ND', 'PD', 'X0'], list(result['df']['DISMM']))
        self.assertEqual([True, False, True], list(result['ok_mask']))

    def test_rpc284_2_skips_empty_dismm(self):
        marc = pd.DataFrame({
            'MATNR': ['10', '11', '12', '13', '14'],
            'DISMM': ['ZB', None, 'X0', 'PD', 'ND'],
            'MMSTA': ['99', '99', '99', '99', '01'],
            'WERKS': ['3600.0', '3800', '3900', '3610', '49'],
        })
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '12', '13', '14'],
                'MTART': ['ZSPS', 'ZSPS', 'ZSPS', 'ZFG', 'ZSPS'],
            }),
            'MAKT': self.makt,
        }
        result = evaluate_rpconf_284_2(
            marc,
            'DISMM',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual(1, result['stats']['skipped_empty_dismm'])
        self.assertEqual(['ZB', 'X0'], list(result['df']['DISMM']))
        self.assertEqual([True, False], list(result['ok_mask']))

    def test_rpc284_2_empty_scope_is_success_without_rows(self):
        marc = pd.DataFrame({
            'MATNR': ['10'],
            'DISMM': ['ZB'],
            'MMSTA': ['01'],
            'WERKS': ['3600'],
        })
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10'], 'MTART': ['ZFG']}),
            'MAKT': pd.DataFrame({'MATNR': ['10'], 'MAKTX': ['COLA RU']}),
        }
        result = evaluate_rpconf_284_2(marc, 'DISMM', lambda name: tables.get(name, pd.DataFrame()))
        self.assertTrue(result['no_rows_after_filters'])
        self.assertEqual(0, len(result['df']))
        self.assertIn('ZSPS', result['skip_reason'])


class MarcMatnrScopeTests(unittest.TestCase):
    def test_keeps_only_materials_present_in_marc(self):
        marc = pd.DataFrame({'MATNR': ['000000000000000010', '20', '000000000000000010']})
        allowed = marc_matnr_key_set(marc)
        mara = pd.DataFrame({'MATNR': ['10', '30', '000000000000000020'], 'MTART': ['ZFG', 'ZCDN', 'ZNVM']})
        scoped, col, reason = filter_frame_to_marc_matnrs(mara, 'MARA', allowed)
        self.assertEqual('MATNR', col)
        self.assertIsNone(reason)
        self.assertEqual(['10', '000000000000000020'], list(scoped['MATNR']))

    def test_ausp_is_not_limited_to_marc_matnr(self):
        allowed = marc_matnr_key_set(pd.DataFrame({'MATNR': ['15']}))
        ausp = pd.DataFrame({'OBJEK': ['000000000000000015', '99'], 'ATWRT': ['A', 'B']})
        scoped, col, reason = filter_frame_to_marc_matnrs(ausp, 'AUSP 829.861', allowed)
        self.assertIsNone(col)
        self.assertIsNone(reason)
        self.assertEqual(['000000000000000015', '99'], list(scoped['OBJEK']))


class MvkeCompletenessTests(unittest.TestCase):
    def setUp(self):
        self.mara = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'MTART': ['ZFG', 'ZRW', 'ZFG', 'ZNVM'],
            'MATKL': ['100', '100', '1110000', '100'],
        })
        self.makt = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'SPRAS': ['E', 'E', 'E', 'E'],
            'MAKTX': ['COKE', 'WATER', 'ABP COKE', 'JUICE'],
        })

    def _load(self, name):
        return {'MARA': self.mara, 'MAKT': self.makt}.get(name, pd.DataFrame())

    def test_ktgrm_flags_empty_outside_technical_sales_org(self):
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '20', '30', '40'],
            'VKORG': ['3600', '0001', '3900', '3600', '3600'],
            'KTGRM': [None, None, '01', None, None],
        })
        result = evaluate_rpcomp_149_1(mvke, 'KTGRM', self._load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20', '40'], list(result['df']['MATNR']))
        self.assertEqual([False, True, False], list(result['ok_mask']))

    def test_zz_kondm_uses_hierarchy_prefix_on_technical_sales_org(self):
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '20', '30'],
            'VKORG': ['0001', '0001', '0001', '3600'],
            'VTWEG': ['01', '01', '01', '01'],
            'PRODH': ['01010012001XXXX', '010100120832085', '0206008999', '01010012001'],
            'ZZ_KONDM': [None, 'SS', None, None],
        })
        result = evaluate_rpcomp_153_1(mvke, 'ZZ_KONDM', self._load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '10'], list(result['df']['MATNR']))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_mtpos_is_required_for_every_type_except_zcds(self):
        mara = pd.DataFrame({
            'MATNR': ['10', '30', '50'],
            'MTART': ['ZFG', 'ZFG', 'ZCDS'],
            'MATKL': ['100', '1110000', '100'],
        })
        makt = pd.DataFrame({
            'MATNR': ['10', '30', '50'],
            'SPRAS': ['E', 'E', 'E'],
            'MAKTX': ['COKE', 'ABP COKE', 'SPARE'],
        })
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '30', '50'],
            'MTPOS': [None, 'NORM', None, None],
        })

        def load(name):
            return {'MARA': mara, 'MAKT': makt}.get(name, pd.DataFrame())

        result = evaluate_rpcomp_199_1(mvke, 'MTPOS', load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '10'], list(result['df']['MATNR']))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_kondm_uses_the_same_technical_sales_org_scope(self):
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '20', '30'],
            'VKORG': ['0001', '0001', '0001', '3600'],
            'VTWEG': ['01', '01', '01', '01'],
            'PRODH': ['01010012001XXXX', '010100120832085', '0206008999', '01010012001'],
            'KONDM': [None, '01', None, None],
        })
        result = evaluate_rpcomp_252_1(mvke, 'KONDM', self._load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '10'], list(result['df']['MATNR']))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_mvgr3_covers_finished_goods_and_listed_semi_groups(self):
        mara = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'MTART': ['ZFG', 'ZSF', 'ZNVL', 'ZSTL'],
            'MATKL': ['100', '1001009', '999', '1003012'],
        })
        makt = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'SPRAS': ['E', 'E', 'E', 'E'],
            'MAKTX': ['ABP COKE', 'SEMI', 'OTHER', 'SERVICE'],
        })
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'MVGR3': [None, None, 'CAN', None],
        })

        def load(name):
            return {'MARA': mara, 'MAKT': makt}.get(name, pd.DataFrame())

        result = evaluate_rpcomp_262_1(mvke, 'MVGR3', load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20'], list(result['df']['MATNR']))
        self.assertEqual([False, False], list(result['ok_mask']))

    def test_mvgr4_uses_finished_goods_and_group_1003012(self):
        mara = pd.DataFrame({
            'MATNR': ['10', '20', '30'],
            'MTART': ['ZFG', 'ZNVL', 'ZNVL'],
            'MATKL': ['100', '1003012', '1001009'],
        })
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30'],
            'MVGR4': [None, '01', None],
        })

        def load(name):
            return {'MARA': mara}.get(name, pd.DataFrame())

        result = evaluate_rpcomp_263_1(mvke, 'MVGR4', load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20'], list(result['df']['MATNR']))
        self.assertEqual([False, True], list(result['ok_mask']))

    def test_zsps_ktgrm_accepts_20_and_86(self):
        mara = pd.DataFrame({
            'MATNR': ['10', '20', '30'],
            'MTART': ['ZSPS', 'ZSPS', 'ZFG'],
            'MATKL': ['100', '100', '100'],
        })
        makt = pd.DataFrame({
            'MATNR': ['10', '20', '30'],
            'MAKTX': ['COLA RU', 'COLA RU', 'COLA RU'],
        })
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30'],
            'VKORG': ['3600', '3800', '3600'],
            'KTGRM': ['20', '01', '86'],
        })

        def load(name):
            return {'MARA': mara, 'MAKT': makt}.get(name, pd.DataFrame())

        result = evaluate_rpconf_149_8(mvke, 'KTGRM', load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20'], list(result['df']['MATNR']))
        self.assertEqual([True, False], list(result['ok_mask']))

    def test_znvm_mtpos_allows_norm_zfgr_zcvi_zfgm(self):
        mara = pd.DataFrame({
            'MATNR': ['10', '20'],
            'MTART': ['ZNVM', 'ZNVM'],
            'MATKL': ['100', '100'],
        })
        makt = pd.DataFrame({
            'MATNR': ['10', '20'],
            'MAKTX': ['COLA RU', 'COLA RU'],
        })
        mvke = pd.DataFrame({
            'MATNR': ['10', '20'],
            'MTPOS': ['NORM', 'LEIS'],
        })

        def load(name):
            return {'MARA': mara, 'MAKT': makt}.get(name, pd.DataFrame())

        result = evaluate_rpconf_199_6(mvke, 'MTPOS', load)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual([True, False], list(result['ok_mask']))

    def _run(self, mvke, rule_code, column, tables):
        def load(name):
            return tables.get(name, pd.DataFrame())
        return evaluate_material_rule(mvke, 'MVKE', rule_code, column, load)

    def test_channel_01_ktgrm_matches_channel_04_for_zrw(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '20', '30', '40'],
                'MTART': ['ZRW', 'ZRW', 'ZRW', 'ZFG'],
                'MATKL': ['100', '100', '100', '100'],
            }),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '20', '30', '40'],
                'MAKTX': ['COLA', 'COLA', 'ABP COLA', 'COLA'],
            }),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '20', '20', '30', '30', '40', '40'],
            'VKORG': ['3600', '3600', '3600', '3600', '3600', '3600', '3600', '3600'],
            'VTWEG': ['01', '04', '01', '04', '01', '04', '01', '04'],
            'KTGRM': ['20', '20', '20', '86', '20', '20', '20', '20'],
        })
        result = self._run(mvke, 'RPCONF_149.9', 'KTGRM', tables)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20'], list(result['df']['MATNR']))
        self.assertEqual([True, False], list(result['ok_mask']))

    def test_pack_size_ss_ms_uses_volume_from_description(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '20', '30'],
                'MTART': ['ZFG', 'ZFG', 'ZFG'],
                'MATKL': ['100', '100', '100'],
            }),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '20', '30'],
                'MAKTX': ['COLA 330ML', 'COLA 1000ML', 'COLA ZZ'],
            }),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30', '30'],
            'VKORG': ['0001', '0001', '0001', '0001'],
            'VTWEG': ['01', '01', '01', '01'],
            'PRODH': ['01010012001XXXX', '01010012001XXXX', '01010012001XXXX', '01010012001XXXX'],
            'MVGR3': ['CAN', 'CAN', 'CAN', 'OTH'],
            'MVGR4': ['01', '01', 'ZZ', 'ZZ'],
            'ZZ_KONDM': ['SS', 'MS', 'SS', 'MS'],
        })
        small = self._run(mvke.iloc[[0]], 'RPCONF_153.2', 'ZZ_KONDM', tables)
        large = self._run(mvke.iloc[[1]], 'RPCONF_153.2', 'ZZ_KONDM', tables)
        bulk = self._run(mvke.iloc[[2]], 'RPCONF_153.2', 'ZZ_KONDM', tables)
        other = self._run(mvke.iloc[[3]], 'RPCONF_153.2', 'ZZ_KONDM', tables)
        self.assertEqual([True], list(small['ok_mask']))
        self.assertEqual([True], list(large['ok_mask']))
        self.assertEqual([True], list(bulk['ok_mask']))
        self.assertEqual([True], list(other['ok_mask']))
        wrong = self._run(mvke.iloc[[0]].assign(ZZ_KONDM='MS'), 'RPCONF_153.2', 'ZZ_KONDM', tables)
        self.assertEqual([False], list(wrong['ok_mask']))

    def test_price_group_for_bulk_pack_does_not_need_coffee(self):
        tables = {
            'MARA': pd.DataFrame({'MATNR': ['10', '20'], 'MTART': ['ZFG', 'ZFG'], 'MATKL': ['100', '100']}),
            'MAKT': pd.DataFrame({'MATNR': ['10', '20'], 'MAKTX': ['COLA', 'COLA']}),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'VKORG': ['0001', '0001', '0001', '0001'],
            'VTWEG': ['01', '01', '01', '01'],
            'PRODH': ['01010012001XXXX', '01010012001XXXX', '01010012001XXXX', '01010012001XXXX'],
            'MVGR3': ['TNK', 'TNK', 'CAN', 'TNK'],
            'MVGR4': ['01', '01', '01', '01'],
            'ZZ_KONDM': ['SS', 'SS', 'SS', 'SS'],
            'KONDM': ['03', '04', '03', '03'],
        })
        tables['MARA'] = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'MTART': ['ZFG', 'ZFG', 'ZFG', 'ZFG'],
            'MATKL': ['100', '100', '100', '100'],
        })
        tables['MAKT'] = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40'],
            'MAKTX': ['COLA', 'COLA', 'COLA', 'ABP COLA'],
        })
        result = self._run(mvke, 'RPCONF_252.1', 'KONDM', tables)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual(['10', '20'], list(result['df']['MATNR']))
        self.assertEqual([True, False], list(result['ok_mask']))

    def test_pack_type_and_hierarchy_are_stable_across_sales_orgs(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '20'],
                'MTART': ['ZRW', 'ZRW'],
                'MATKL': ['1001004', '1001004'],
            }),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '20', '20'],
            'VKORG': ['3600', '3800', '3600', '3800'],
            'VTWEG': ['01', '01', '01', '01'],
            'MVGR3': ['CAN', 'CAN', 'CAN', 'PET'],
            'PRODH': ['H1', 'H1', 'H1', 'H1'],
        })
        result = self._run(mvke, 'RPCONF_262.3', 'MVGR3', tables)
        self.assertIsNone(result['skip_reason'])
        self.assertEqual([True, True, False, False], list(result['ok_mask']))

    def test_finished_goods_description_contains_pack_type(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '20'],
                'MTART': ['ZFG', 'ZFG'],
                'MATKL': ['100', '100'],
                'MTPOS_MARA': ['NORM', 'NORM'],
            }),
            'MAKT': pd.DataFrame({'MATNR': ['10', '20'], 'MAKTX': ['COLA PET 1L', 'COLA PET 1L']}),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '20'],
            'PRODH': ['01010012001XXXX', '01010012001XXXX'],
            'MVGR3': ['PET', 'CAN'],
        })
        result = self._run(mvke, 'RPCONF_262.5', 'MVGR3', tables)
        self.assertEqual([True, False], list(result['ok_mask']))

    def test_description_contains_pack_volume_from_groes(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '20', '30', '40', '50'],
                'MTART': ['ZFG', 'ZFG', 'ZFG', 'ZFG', 'ZFG'],
                'MATKL': ['100', '100', '100', '100', '100'],
                'GROES': ['330ML', '330ML', '', '', '330ML'],
                'VOLUM': ['', '', '0.33', '', ''],
                'VOLEH': ['', '', 'L', '', ''],
                'MTPOS_MARA': ['NORM', 'NORM', 'NORM', 'NORM', 'NORM'],
            }),
            'MAKT': pd.DataFrame({
                'MATNR': ['10', '20', '30', '40', '50'],
                'MAKTX': ['COLA 330ML', 'COLA PET', 'COLA 330 ML', 'ABP COLA 330ML', 'COLA 330ML'],
            }),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '20', '30', '40', '50'],
            'VKORG': ['0001', '0001', '0001', '0001', '3600'],
            'VTWEG': ['01', '01', '01', '01', '01'],
            'PRODH': ['01010012001XXXX'] * 5,
            'MVGR4': ['01', '01', '033', '033', '01'],
        })
        result = self._run(mvke, 'RPCONF_263.5', 'MVGR4', tables)
        self.assertEqual(['10', '20', '30'], list(result['df']['MATNR']))
        self.assertEqual([True, False, True], list(result['ok_mask']))

    def test_prodh_must_match_inside_one_sales_org_and_the_ban(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '11', '99', '98'],
                'MTART': ['ZFG', 'ZFG', 'ZFG', 'ZFG'],
                'MATKL': ['100', '100', '100', '100'],
                'WRKST': ['99', '98', '', ''],
            }),
        }
        same = self._run(pd.DataFrame({
            'MATNR': ['10', '10'],
            'VKORG': ['3600', '3600'],
            'VTWEG': ['01', '04'],
            'PRODH': ['01010012001XXXX', '01010012001XXXX'],
        }), 'RPCONF_290.3', 'PRODH', tables)
        different = self._run(pd.DataFrame({
            'MATNR': ['11', '11'],
            'VKORG': ['3600', '3600'],
            'VTWEG': ['01', '04'],
            'PRODH': ['01010012001XXXX', '01010012015YYYY'],
        }), 'RPCONF_290.3', 'PRODH', tables)
        self.assertEqual([True, True], list(same['ok_mask']))
        self.assertEqual([False, False], list(different['ok_mask']))
        ban = self._run(pd.DataFrame({
            'MATNR': ['10', '99', '11', '98'],
            'VKORG': ['3600', '3600', '3600', '3600'],
            'VTWEG': ['01', '01', '01', '01'],
            'PRODH': ['AAA', 'AAA', 'BBB', 'CCC'],
        }), 'RPCONF_290.4', 'PRODH', tables)
        self.assertEqual(['10', '11'], list(ban['df']['MATNR']))
        self.assertEqual([True, False], list(ban['ok_mask']))

    def test_brand_outside_technical_sales_org_matches_0001_and_ban(self):
        tables = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '99'],
                'MTART': ['ZRW', 'ZFG'],
                'MATKL': ['1001004', '100'],
                'WRKST': ['99', ''],
            }),
            'MAKT': pd.DataFrame({'MATNR': ['10', '99'], 'MAKTX': ['COLA', 'BAN']}),
        }
        mvke = pd.DataFrame({
            'MATNR': ['10', '10', '10', '99', '99'],
            'VKORG': ['0001', '3600', '3800', '0001', '0001'],
            'VTWEG': ['01', '01', '01', '01', '01'],
            'MVGR1': ['BB', 'BB', 'XX', 'BB', 'CC'],
            'MVGR3': ['CAN', 'CAN', 'CAN', 'CAN', 'CAN'],
            'PRODH': ['H1', 'H1', 'H1', 'H1', 'H1'],
        })
        brand = self._run(mvke.iloc[:3], 'RPCONF_30.3', 'MVGR1', tables)
        self.assertEqual(['3600', '3800'], list(brand['df']['VKORG']))
        self.assertEqual([True, False], list(brand['ok_mask']))
        finished = {
            'MARA': pd.DataFrame({
                'MATNR': ['10', '99'],
                'MTART': ['ZFG', 'ZFG'],
                'MATKL': ['100', '100'],
                'WRKST': ['99', ''],
            }),
        }
        ban = self._run(pd.DataFrame({
            'MATNR': ['10', '99'],
            'VKORG': ['0001', '0001'],
            'VTWEG': ['01', '01'],
            'MVGR3': ['CAN', 'PET'],
            'PRODH': ['01010012001XXXX', '01010012001XXXX'],
        }), 'RPCONF_262.6', 'MVGR3', finished)
        self.assertEqual(['10'], list(ban['df']['MATNR']))
        self.assertEqual([False], list(ban['ok_mask']))


if __name__ == '__main__':
    unittest.main()
