#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
金信诺(300252) SOTP估值模型
深交所创业板，信号互联产品龙头，基于CNY计价。

关键参数（2025年报估算）：
- 总股本: 6.84亿股
- 流通股本: ~5.59亿股（流通比例约82%）
- 2025年报营收: ~26亿元
- 2025归母净利润(TTM): ~1.22亿元
- EPS: 0.18元
- PE TTM: 92.92x（市场给与成长预期溢价）
- PB: 4.60

商业模式：
1. 军工与航空航天信号互联（射频电缆/连接器，壁垒高）
2. 通信互联产品（5G天线/RF/光模块，800G新品）
3. PCB/HDI业务（近期毛利转负，收缩中）
4. 光纤光缆（受益AI数据中心光互联）

当前价(2026-06-04): ~16.63元（深交所行情）
总市值: ~113.8亿元
PE TTM: ~92.92x（成长预期高度定价）

数据来源（硬编码，财务数据为公开信息综合估计）：
- 总股本/流通股本: 行情数据
- 营收/净利润: PE TTM倒推
- 分部营收: 公开信息综合估计
"""

import numpy as np
from pathlib import Path
from typing import Dict, Any
import yaml

WORK_DIR = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(WORK_DIR / 'common'))


class JinxinnuoSOTP:
    """金信诺SOTP分部估值"""

    def __init__(self, segments: list, base_net_profit: float,
                 profit_adjustment: float = 0.0, shares: float = 6.84):
        self.segments = segments
        self.base_net_profit = base_net_profit
        self.profit_adjustment = profit_adjustment
        self.shares = shares

    @classmethod
    def from_config(cls, config_path: str = None, repo_root: str = None):
        if config_path is None:
            if repo_root is None:
                repo_root = WORK_DIR
            config_path = repo_root / 'stocks/300252_jinxinnuo/config.yaml'

        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)

        segments = cfg['segments']
        base_net_profit = cfg.get('base_net_profit', 1.22)
        profit_adj = cfg.get('profit_adjustment', 0.0)
        shares = cfg.get('stock_info', {}).get('total_shares', 6.84)
        return cls(segments, base_net_profit, profit_adj, shares)

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
                'pct': '0%',  # 将在下方重新计算
                'notes': seg.get('notes', ''),
            })

        sotp_cap_base = total_cap
        # 重新计算分部百分比（需要在所有segments处理完后）
        for s in seg_results:
            if sotp_cap_base > 0:
                s['pct'] = f"{s['cap_base'] / sotp_cap_base * 100:.0f}%"
        sotp_cap_min = sum(s['cap_min'] for s in seg_results)
        sotp_cap_max = sum(s['cap_max'] for s in seg_results)

        total_nm = sum(s['net_profit_cny'] for s in seg_results) + self.profit_adjustment

        target_base = sotp_cap_base / self.shares
        target_min = sotp_cap_min / self.shares
        target_max = sotp_cap_max / self.shares

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
        }

    def get_sotp_detail(self) -> Dict[str, Any]:
        return {
            'segments': self.segments,
            'total_net_profit': self.base_net_profit,
            'profit_adjustment': self.profit_adjustment,
        }


def run_local_test():
    """本地测试：验证模型在本地环境正常工作"""
    print("=== 金信诺(300252) 本地测试 ===\n")

    # 加载模型
    try:
        sotp = JinxinnuoSOTP.from_config()
        print("✅ 模型加载成功")
    except Exception as e:
        print(f"❌ 模型加载失败: {e}")
        return

    # 当前价（2026-06-04，深交所sz300252行情）
    current_price = 16.63
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
    beta = 1.30  # 创业板，beta较高
    mp = 0.045  # 市场风险溢价
    wacc = rf + beta * mp
    print(f"  WACC: {wacc*100:.1f}% (rf={rf}, beta={beta}, mp={mp})")

    total_nm = result['total_net_profit']
    if total_nm <= 0:
        print("  ⚠️ 净利润为0，跳过DCF计算")
        dcf_price = None
    else:
        growth_rates = [0.15, 0.14, 0.12, 0.10, 0.08]
        fcf_conv = 0.65
        base_fcf = total_nm * fcf_conv
        fcf_proj = []
        cf = base_fcf
        for g in growth_rates:
            cf *= (1 + g)
            fcf_proj.append(round(cf, 2))
        print(f"  FCF预测: {fcf_proj}")

        # 从config读取总股本
        engine = DiscountingEngine()
        dcf_result = engine.compute_dcf(
            fcf_projections=fcf_proj,
            terminal_fcf=fcf_proj[-1] * 1.03,
            wacc=wacc,
            net_debt=-2.0,
            shares=sotp.shares,
            terminal_growth=0.03,
        )
        dcf_price = dcf_result.get('目标价_元', 0)
        print(f"  DCF目标价: {dcf_price:.1f}元")

    # 概率加权
    print(f"\n【概率加权估值】")
    try:
        from common.core.probability_weight import ProbabilityWeightEngine

        with open(WORK_DIR / 'stocks/300252_jinxinnuo/config.yaml') as f:
            cfg = yaml.safe_load(f)

        events = cfg.get('events', [])
        if events:
            pw = ProbabilityWeightEngine.from_config_list(events)
            weighted_cap = pw.apply(result['sotp_cap_base'])
            weighted_price = weighted_cap / 6.84  # 使用总股本
            print(f"  SOTP基准市值: {result['sotp_cap_base']:.1f}亿")
            print(f"  总股本: 6.84亿股")
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
    if dcf_price:
        print(f"  DCF目标价: {dcf_price:.1f}元 ({dcf_price/current_price-1:+.1f}%)")
    if weighted_price:
        print(f"  概率加权: {weighted_price:.1f}元 ({weighted_price/current_price-1:+.1f}%)")

    print("\n✅ 本地测试完成")


if __name__ == '__main__':
    import sys
    sys.path.insert(0, str(WORK_DIR))
    sys.path.insert(0, str(WORK_DIR / 'common'))
    run_local_test()
