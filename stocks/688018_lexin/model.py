#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
乐鑫科技(688018) SOTP估值模型
科创板物联网WiFi芯片龙头，基于CNY计价。

关键参数（2024年报）：
- 总股本: 1.68亿股
- 流通股本: 1.47亿股
- 2024年报营收: 约13亿元（+30% YoY）
- 2024归母净利润: 约1.7亿元（+80% YoY）
- 毛利率: ~40%（产品结构改善）
- 净利率: ~13%（规模效应显现）
- 研发占比: ~25%（高研发投入）

商业模式：
1. WiFi MCU芯片（智能家居/工业控制）
2. WiFi/蓝牙Combo芯片（可穿戴/AR眼镜）
3. BLE/Thread芯片（Matter协议/超低功耗IoT）

当前价(2026-05-15): 182.00元
总市值: 约305亿
PE TTM: ~180x（高估值，成长预期强）
"""

import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import yaml

WORK_DIR = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(WORK_DIR / 'common'))


class LexinSOTP:
    """乐鑫科技SOTP分部估值"""

    def __init__(self, segments: list, base_net_profit: float,
                 profit_adjustment: float = 0.0):
        self.segments = segments
        self.base_net_profit = base_net_profit
        self.profit_adjustment = profit_adjustment

    @classmethod
    def from_config(cls, config_path: str = None, repo_root: str = None):
        if config_path is None:
            if repo_root is None:
                repo_root = WORK_DIR
            config_path = repo_root / 'stocks/688018_lexin/config.yaml'

        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)

        segments = cfg['segments']
        base_net_profit = cfg.get('base_net_profit', 1.70)
        profit_adj = cfg.get('profit_adjustment', 0.0)
        return cls(segments, base_net_profit, profit_adj)

    def calculate(self, current_price: float) -> Dict[str, Any]:
        """计算SOTP估值"""
        seg_results = []
        total_cap = 0.0

        for seg in self.segments:
            nm = seg['net_profit_cny']
            pe_base = seg['pe_base']
            cap_base = nm * pe_base
            cap_min = nm * seg['pe_min']
            cap_max = nm * seg['pe_max']

            total_cap += cap_base

            seg_results.append({
                'name': seg['name'],
                'code': seg['code'],
                'revenue_cny': seg['revenue_cny'],
                'net_margin': seg['net_margin'],
                'net_profit_cny': nm,
                'pe_range': f"{seg['pe_min']}-{seg['pe_max']}",
                'pe_base': pe_base,
                'cap_base': cap_base,
                'cap_min': cap_min,
                'cap_max': cap_max,
                'pct': f"{cap_base / total_cap * 100:.0f}%" if total_cap > 0 else "0%",
                'notes': seg.get('notes', ''),
            })

        # 调整后总市值
        sotp_cap_base = total_cap
        sotp_cap_min = sum(s['cap_min'] for s in seg_results)
        sotp_cap_max = sum(s['cap_max'] for s in seg_results)

        # 总净利
        total_nm = sum(s['net_profit_cny'] for s in seg_results) + self.profit_adjustment

        # 目标价
        shares = 1.68
        target_base = sotp_cap_base / shares
        target_min = sotp_cap_min / shares
        target_max = sotp_cap_max / shares

        # 上涨空间
        upside = target_base / current_price - 1

        return {
            'target_base': target_base,
            'target_min': target_min,
            'target_max': target_max,
            'current_price': current_price,
            'upside': upside,
            'sotp_cap_base': sotp_cap_base,
            'sotp_cap_min': sotp_cap_min,
            'sotp_cap_max': sotp_cap_max,
            'total_net_profit': total_nm,
            'profit_adjustment': self.profit_adjustment,
            'segments': seg_results,
            'shares': shares,
        }

    def get_sotp_detail(self) -> Dict[str, Any]:
        return {
            'segments': self.segments,
            'total_net_profit': self.base_net_profit,
            'profit_adjustment': self.profit_adjustment,
        }


def run_local_test():
    """本地测试：验证模型在本地环境正常工作"""
    print("=== 乐鑫科技(688018) 本地测试 ===\n")

    # 加载模型
    try:
        sotp = LexinSOTP.from_config()
        print("✅ 模型加载成功")
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        return

    # 当前价（腾讯行情实时）
    current_price = 182.00
    print(f"当前价: {current_price}元")

    # 计算估值
    result = sotp.calculate(current_price)

    print(f"\n【SOTP估值结果】")
    print(f"  目标价区间: {result['target_min']:.1f} ~ {result['target_max']:.1f}元")
    print(f"  目标价中枢: {result['target_base']:.1f}元")
    print(f"  当前价: {current_price}元")
    print(f"  上涨空间: {result['upside']*100:+.1f}%")
    print(f"  SOTP总市值: {result['sotp_cap_base']:.1f}亿元")
    print(f"  总净利润: {result['total_net_profit']:.2f}亿元")

    print(f"\n【分部明细】")
    for seg in result['segments']:
        print(f"  {seg['name']}: 收入{seg['revenue_cny']:.1f}亿 × {seg['net_margin']*100:.0f}%净利率 "
              f"= {seg['net_profit_cny']:.2f}亿净利 × PE{seg['pe_base']} "
              f"= {seg['cap_base']:.1f}亿市值 ({seg['pct']})")

    print(f"\n【DCF估值】")
    from common.core.discounting_engine import DiscountingEngine
    import warnings
    warnings.filterwarnings('ignore')

    rf = 0.025  # 10年期国债收益率约2.5%
    beta = 1.05  # 科创板物联网芯片，波动性较高
    mp = 0.045  # 市场风险溢价（中证1000约4-5%）
    wacc = rf + beta * mp
    print(f"  WACC: {wacc*100:.1f}% (rf={rf}, beta={beta}, mp={mp})")

    total_nm = result['total_net_profit']
    growth_rates = [0.30, 0.28, 0.25, 0.22, 0.20]
    fcf_conv = 0.60
    fcf_proj = [round(total_nm * (1 + g) * fcf_conv, 2) for g in growth_rates]
    print(f"  FCF预测: {fcf_proj}")

    engine = DiscountingEngine()
    dcf_result = engine.compute_dcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1] * 1.03,
        wacc=wacc,
        net_debt=-10.0,  # 净现金约10亿
        shares=1.68,
        terminal_growth=0.03,
    )
    dcf_price = dcf_result['目标价_元']
    print(f"  DCF目标价: {dcf_price:.1f}元")

    # 概率加权
    print(f"\n【概率加权估值】")
    try:
        from common.core.probability_weight import ProbabilityWeightEngine

        with open(WORK_DIR / 'stocks/688018_lexin/config.yaml') as f:
            cfg = yaml.safe_load(f)

        events = cfg.get('events', [])
        if events:
            pw = ProbabilityWeightEngine.from_config_list(events)
            weighted_cap = pw.apply(result['sotp_cap_base'])
            weighted_price = weighted_cap / 1.68
            print(f"  SOTP基准市值: {result['sotp_cap_base']:.1f}亿")
            print(f"  综合乘数: {weighted_cap/result['sotp_cap_base']:.3f}x")
            print(f"  概率加权目标价: {weighted_price:.1f}元")
        else:
            weighted_price = None
            print("  无事件驱动配置")
    except Exception as e:
        print(f"  概率加权异常: {e}")
        weighted_price = None

    print(f"\n【总结】")
    print(f"  当前价: {current_price}元")
    print(f"  SOTP目标价: {result['target_base']:.1f}元 ({result['upside']*100:+.1f}%)")
    print(f"  DCF目标价: {dcf_price:.1f}元 ({dcf_price/current_price-1:+.1f}%)")
    if weighted_price:
        print(f"  概率加权: {weighted_price:.1f}元 ({weighted_price/current_price-1:+.1f}%)")

    print("\n✅ 本地测试完成")


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(WORK_DIR))
    sys.path.insert(0, str(WORK_DIR / 'common'))
    run_local_test()