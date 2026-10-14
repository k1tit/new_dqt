from __future__ import annotations

import unittest

import pandas as pd

from utils.material_rule_evaluator import (
    evaluate_ausp_bpp_rule,
    evaluate_makt_rule,
    evaluate_mara_rule,
    evaluate_rpcomp_149_1,
    evaluate_rpcomp_153_1,
    evaluate_rpcomp_199_1,
    evaluate_rpcomp_252_1,
    evaluate_rpcomp_262_1,
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
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
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

    def test_rpc53_1_uses_zmdm_bpp_code_without_codet(self):
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
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('ZMDM_BPP_CODE', result['stats']['reference'])

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
            'CAWN': pd.DataFrame({
                'ATINN': ['829', '829', '24'],
                'ATWRT': ['BPP_OK', 'OTHER', 'COOLER'],
            }),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertIn('CAWN', result['stats']['reference'])

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
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK', 'BPP_BAD']}),
        }
        result = evaluate_ausp_bpp_rule(
            ausp,
            'RPCONF_53.1',
            'ATWRT',
            lambda name: tables.get(name, pd.DataFrame()),
        )
        self._assert_result(result, 2, 1)
        self.assertEqual('CAWN_M+CAWNT_M', result['stats']['reference'])
        self.assertEqual({'BPP_OK'}, set(result['df'].loc[result['ok_mask'], 'ATWRT']))

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
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
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
            'ZMDM_BPP_CODET': pd.DataFrame({'ATWRT': ['BPP_OK'], 'ATWTB': ['VALID']}),
            'ZMDM_BPP_CODE': pd.DataFrame(),
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


if __name__ == '__main__':
    unittest.main()
