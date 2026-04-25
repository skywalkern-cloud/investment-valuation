#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Phase 2 P1: 单元测试
测试SOTP引擎、discounting_engine和probability_weight的核心逻辑
"""

import unittest
import sys
import os

# Add workspace-valuation root to path
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class TestDiscountingEngine(unittest.TestCase):
    """DiscountingEngine单元测试"""

    def test_wacc_calculation(self):
        """WACC计算测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        # CAPM: Re = Rf + β × MP = 2.5% + 1.2×5% = 8.5%
        # WACC = 70%×8.5% + 30%×4%×(1-15%) = 5.95% + 1.02% = 6.97%
        wacc = engine.calc_wacc(risk_free_rate=0.025, beta=1.2)
        self.assertAlmostEqual(wacc, 0.0697, places=3)

    def test_wacc_no_debt(self):
        """无债务WACC测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        # debt_ratio=0 → WACC = Re = Rf + β×MP
        wacc = engine.calc_wacc(risk_free_rate=0.03, beta=1.5, debt_ratio=0.0)
        self.assertAlmostEqual(wacc, 0.03 + 1.5 * 0.05, places=4)

    def test_dcf_fcf_basic(self):
        """DCF基础测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        result = engine.dcf_fcf(
            fcf_projections=[1.0, 1.0, 1.0, 1.0, 1.0],
            terminal_fcf=1.0,
            wacc=0.10,
            net_debt=0,
            shares=1.0,
            terminal_growth=0.03,
        )
        # PV_sum ≈ 3.79亿
        self.assertAlmostEqual(result['PV_sum_亿'], 3.791, places=1)
        self.assertGreater(result['目标价_元'], 0)

    def test_dcf_zero_shares_protection(self):
        """零股本保护测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        result = engine.dcf_fcf(
            fcf_projections=[1.0],
            terminal_fcf=1.0,
            wacc=0.10,
            net_debt=0,
            shares=0,
            terminal_growth=0.03,
        )
        self.assertEqual(result['目标价_元'], 0)

    def test_dcf_sensitivity_grid(self):
        """敏感性分析网格测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        s = engine.dcf_sensitivity(
            base_fcf=[0.5] * 5,
            terminal_fcf=0.5,
            wacc=0.10,
            net_debt=0,
            shares=6.53,
            terminal_range=(0.02, 0.03, 0.04),
        )
        self.assertEqual(len(s['grid']), 3)
        for row in s['grid']:
            self.assertEqual(len(row), 3)
        # TG越高，同WACC下目标价越高
        for w_idx in range(3):
            self.assertLess(s['grid'][0][w_idx], s['grid'][1][w_idx])
            self.assertLess(s['grid'][1][w_idx], s['grid'][2][w_idx])

    def test_apply_event_positive(self):
        """正向事件加权测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        events = [{'name': '认证通过', 'probability': 0.70, 'magnitude': 1.4, 'impact': 'positive'}]
        adjusted = engine.apply_event_weights(100.0, events)
        # 100 × (1 + (1.4-1)×0.70) = 100 × 1.28 = 128
        self.assertAlmostEqual(adjusted, 128.0, places=1)

    def test_apply_event_negative(self):
        """负向事件加权测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        events = [{'name': '认证失败', 'probability': 0.20, 'magnitude': 0.5, 'impact': 'negative'}]
        adjusted = engine.apply_event_weights(100.0, events)
        # 100 × (1 - (1-0.5)×0.20) = 100 × 0.90 = 90
        self.assertAlmostEqual(adjusted, 90.0, places=1)

    def test_apply_event_mixed(self):
        """混合事件加权测试"""
        from common.core.discounting_engine import DiscountingEngine
        engine = DiscountingEngine()
        events = [
            {'name': '通过', 'probability': 0.65, 'magnitude': 1.4, 'impact': 'positive'},
            {'name': '失败', 'probability': 0.15, 'magnitude': 0.5, 'impact': 'negative'},
        ]
        adjusted = engine.apply_event_weights(100.0, events)
        # 正向: 100×1.26=126; 负向: 126×0.925=116.55
        self.assertAlmostEqual(adjusted, 116.55, places=1)


class TestProbabilityWeightEngine(unittest.TestCase):
    """ProbabilityWeightEngine单元测试"""

    def test_basic(self):
        """基础加权"""
        from common.core.probability_weight import ProbabilityWeightEngine
        pw = ProbabilityWeightEngine()
        pw.add_event('test', probability=0.5, magnitude=1.2, impact='positive')
        self.assertAlmostEqual(pw.apply(100.0), 110.0, places=1)

    def test_negative_event(self):
        """负向事件"""
        from common.core.probability_weight import ProbabilityWeightEngine
        pw = ProbabilityWeightEngine()
        pw.add_event('down', probability=0.3, magnitude=0.8, impact='negative')
        self.assertAlmostEqual(pw.apply(100.0), 94.0, places=1)

    def test_breakdown(self):
        """拆解测试"""
        from common.core.probability_weight import ProbabilityWeightEngine
        pw = ProbabilityWeightEngine()
        pw.add_event('up', probability=0.60, magnitude=1.3, impact='positive')
        bd = pw.breakdown(100.0)
        self.assertEqual(bd['base_value'], 100.0)
        self.assertIn('adjusted_value', bd)
        self.assertEqual(len(bd['events']), 1)

    def test_from_config(self):
        """从配置创建"""
        from common.core.probability_weight import ProbabilityWeightEngine
        config = [
            {'name': 'e1', 'probability': 0.5, 'magnitude': 1.2, 'impact': 'positive'},
        ]
        pw = ProbabilityWeightEngine.from_config_list(config)
        self.assertEqual(len(pw.events), 1)
        self.assertGreater(pw.apply(100.0), 0)

    def test_invalid_probability(self):
        """非法概率"""
        from common.core.probability_weight import ProbabilityWeightEngine
        pw = ProbabilityWeightEngine()
        with self.assertRaises(ValueError):
            pw.add_event('t', probability=1.5, magnitude=1.2)


class TestSOTPEngine(unittest.TestCase):
    """SOTP引擎单元测试"""

    def test_division_names(self):
        """分部名称"""
        from common.core.sotp_engine import SOTPEngine
        sotp = SOTPEngine()
        sotp.add_division('manufacturing', '传统业务', weight=0.4)
        sotp.add_division('fabless', '新业务', weight=0.6)
        self.assertEqual(len(sotp.divisions), 2)
        self.assertEqual(sotp.divisions[0].name, '传统业务')


class TestDataFetcher(unittest.TestCase):
    """DataFetcher单元测试"""

    def test_parse_num(self):
        """亿/万格式解析"""
        from common.data.fetcher import DataFetcher
        f = DataFetcher()
        self.assertAlmostEqual(f._parse_num('1.23亿'), 1.23e8, places=2)
        self.assertAlmostEqual(f._parse_num('4567万'), 4567e4, places=0)
        self.assertEqual(f._parse_num('False'), 0.0)

    def test_parse_pct(self):
        """百分号解析"""
        from common.data.fetcher import DataFetcher
        f = DataFetcher()
        self.assertAlmostEqual(f._parse_pct('28.48%'), 0.2848, places=4)
        self.assertAlmostEqual(f._parse_pct('3.68'), 0.0368, places=4)


if __name__ == '__main__':
    print("=" * 50)
    print("Phase 2 P1 Unit Tests")
    print("=" * 50)
    unittest.main(verbosity=2)
