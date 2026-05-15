#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腾讯控股(00700) SOTP估值模型
港股科技龙头，港元HKD计价。

关键参数（2024年报）：
- 总股本: 93.7亿股
- 流通股本: 92.5亿股
- 2024年报营收: 约6600亿元（+8% YoY）
- 2024Non-IFRS净利: 约1950亿元（+36% YoY）
- 毛利率: ~50%（高毛利平台型）
- 净利率: ~30%
- ROE: ~20%

商业模式：
1. 微信与社交广告（微信12亿用户，小程序生态）
2. 游戏（手游+端游+海外，全球最大）
3. 金融科技与企业服务（支付+云+ToB）
4. 投资组合（京东/美团/拼多多等联营公司）

当前价(2026-05-15): 459.8港元
总市值: ~43000亿港元
PE TTM: ~22x
"""

import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import yaml

WORK_DIR = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(WORK_DIR / 'common'))


class TencentSOTP:
    """腾讯控股SOTP分部估值"""

    def __init__(self, segments: list, base_net_profit: float,
                 profit_adjustment: float = 0.0, hkd_cny_rate: float = 0.92):
        self.segments = segments
        self.base_net_profit = base_net_profit
        self.profit_adjustment = profit_adjustment
        self.hkd_cny_rate = hkd_cny_rate

    @classmethod
    def from_config(cls, config_path: str = None, repo_root: str = None):
        if config_path is None:
            if repo_root is None:
                repo_root = WORK_DIR
            config_path = repo_root / 'stocks/HK00700_tencent/config.yaml'

        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)

        segments = cfg['segments']
        base_net_profit = cfg.get('base_net_profit', 1950)
        profit_adj = cfg.get('profit_adjustment', 0.0)
        hkd_cny_rate = cfg.get('stock_info', {}).get('hkd_cny_rate', 0.92)
        return cls(segments, base_net_profit, profit_adj, hkd_cny_rate)

    def calculate(self, current_price_hkd: float) -> Dict[str, Any]:
        """计算SOTP估值"""
        seg_results = []
        total_cap = 0.0
        total_nm = 0.0

        for seg in self.segments:
            nm = seg['net_profit_cny']
            pe_base = seg['pe_base']
            cap_base = nm * pe_base
            cap_min = nm * seg['pe_min']
            cap_max = nm * seg['pe_max']

            total_cap += cap_base
            total_nm += nm

            seg_results.append({
                'name': seg['name'],
                'code': seg['code'],
                'revenue_cny': seg.get('revenue_cny', 0),
                'net_margin': seg.get('net_margin', 0),
                'net_profit_cny': nm,
                'pe_range': f"{seg['pe_min']}-{seg['pe_max']}",
                'pe_base': pe_base,
                'cap_base': cap_base,
                'cap_min': cap_min,
                'cap_max': cap_max,
                'pct': f"{cap_base / total_cap * 100:.0f}%" if total_cap > 0 else "0%",
                'notes': seg.get('notes', ''),
                'is_residual': seg.get('is_residual', False),
            })

        # SOTP总市值（CNY）
        sotp_cap_base_cny = total_cap
        sotp_cap_min_cny = sum(s['cap_min'] for s in seg_results)
        sotp_cap_max_cny = sum(s['cap_max'] for s in seg_results)

        # 转换为HKD
        sotp_cap_base_hkd = sotp_cap_base_cny / self.hkd_cny_rate
        sotp_cap_min_hkd = sotp_cap_min_cny / self.hkd_cny_rate
        sotp_cap_max_hkd = sotp_cap_max_cny / self.hkd_cny_rate

        # 目标价（HKD）
        shares = 93.7
        target_base_hkd = sotp_cap_base_hkd / shares
        target_min_hkd = sotp_cap_min_hkd / shares
        target_max_hkd = sotp_cap_max_hkd / shares

        # 上涨空间
        upside = target_base_hkd / current_price_hkd - 1

        return {
            'target_base_hkd': target_base_hkd,
            'target_min_hkd': target_min_hkd,
            'target_max_hkd': target_max_hkd,
            'current_price_hkd': current_price_hkd,
            'upside': upside,
            'sotp_cap_base_hkd': sotp_cap_base_hkd,
            'sotp_cap_min_hkd': sotp_cap_min_hkd,
            'sotp_cap_max_hkd': sotp_cap_max_hkd,
            'sotp_cap_base_cny': sotp_cap_base_cny,
            'total_net_profit_cny': total_nm,
            'profit_adjustment': self.profit_adjustment,
            'segments': seg_results,
            'shares': shares,
            'hkd_cny_rate': self.hkd_cny_rate,
        }

    def get_sotp_detail(self) -> Dict[str, Any]:
        return {
            'segments': self.segments,
            'total_net_profit': self.base_net_profit,
            'profit_adjustment': self.profit_adjustment,
        }


def run_local_test():
    """本地测试：验证模型在本地环境正常工作"""
    print("=== 腾讯控股(00700) 本地测试 ===\n")

    # 加载模型
    try:
        sotp = TencentSOTP.from_config()
        print("✅ 模型加载成功")
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        return

    # 当前价（腾讯行情实时）
    current_price_hkd = 459.80
    print(f"当前价: {current_price_hkd}港元")

    # 计算估值
    result = sotp.calculate(current_price_hkd)

    print(f"\n【SOTP估值结果】")
    print(f"  目标价区间: {result['target_min_hkd']:.1f} ~ {result['target_max_hkd']:.1f}港元")
    print(f"  目标价中枢: {result['target_base_hkd']:.1f}港元")
    print(f"  当前价: {current_price_hkd}港元")
    print(f"  上涨空间: {result['upside']*100:+.1f}%")
    print(f"  SOTP总市值: {result['sotp_cap_base_hkd']:.0f}亿港元 (CNY {result['sotp_cap_base_cny']:.0f}亿)")
    print(f"  总净利润(CNY): {result['total_net_profit_cny']:.0f}亿元")

    print(f"\n【分部明细】")
    for seg in result['segments']:
        print(f"  {seg['name']}: 净利{seg['net_profit_cny']:.0f}亿CNY × PE{seg['pe_base']} "
              f"= {seg['cap_base']:.0f}亿CNY ({seg['pct']})")

    print(f"\n【DCF估值】")
    from common.core.discounting_engine import DiscountingEngine
    import warnings
    warnings.filterwarnings('ignore')

    rf = 0.025  # 10年期国债收益率约2.5%
    beta = 0.90  # 港股科技龙头，波动性中等
    mp = 0.05   # 市场风险溢价（恒生指数约5%）
    wacc = rf + beta * mp
    print(f"  WACC: {wacc*100:.1f}% (rf={rf}, beta={beta}, mp={mp})")

    total_nm = result['total_net_profit_cny']
    growth_rates = [0.12, 0.11, 0.10, 0.09, 0.08]
    fcf_conv = 0.70
    fcf_proj = [round(total_nm * (1 + g) * fcf_conv, 2) for g in growth_rates]
    print(f"  FCF预测: {fcf_proj}")

    engine = DiscountingEngine()
    # DCF用CNY计算，再转HKD
    dcf_result_cny = engine.compute_dcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1] * 1.04,
        wacc=wacc,
        net_debt=-3000,  # 净现金约3000亿CNY
        shares=93.7,
        terminal_growth=0.04,
    )
    dcf_price_hkd = dcf_result_cny['目标价_元'] / 0.92  # 转HKD
    print(f"  DCF目标价: {dcf_price_hkd:.1f}港元")

    # 概率加权
    print(f"\n【概率加权估值】")
    try:
        from common.core.probability_weight import ProbabilityWeightEngine

        with open(WORK_DIR / 'stocks/HK00700_tencent/config.yaml') as f:
            cfg = yaml.safe_load(f)

        events = cfg.get('events', [])
        if events:
            pw = ProbabilityWeightEngine.from_config_list(events)
            sotp_cap_hkd = result['sotp_cap_base_hkd']
            weighted_cap_hkd = pw.apply(sotp_cap_hkd)
            weighted_price_hkd = weighted_cap_hkd / 93.7

            sotp_cap_cny = result['sotp_cap_base_cny']
            weighted_cap_cny = pw.apply(sotp_cap_cny)

            print(f"  SOTP基准市值: {sotp_cap_hkd:.0f}亿港元 ({sotp_cap_cny:.0f}亿CNY)")
            print(f"  综合乘数: {weighted_cap_hkd/sotp_cap_hkd:.3f}x")
            print(f"  概率加权目标价: {weighted_price_hkd:.1f}港元")
        else:
            weighted_price_hkd = None
            print("  无事件驱动配置")
    except Exception as e:
        print(f"  概率加权异常: {e}")
        weighted_price_hkd = None

    print(f"\n【总结】")
    print(f"  当前价: {current_price_hkd}港元")
    print(f"  SOTP目标价: {result['target_base_hkd']:.1f}港元 ({result['upside']*100:+.1f}%)")
    if weighted_price_hkd:
        print(f"  概率加权: {weighted_price_hkd:.1f}港元 ({weighted_price_hkd/current_price_hkd-1:+.1f}%)")

    print("\n✅ 本地测试完成")


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(WORK_DIR))
    sys.path.insert(0, str(WORK_DIR / 'common'))
    run_local_test()