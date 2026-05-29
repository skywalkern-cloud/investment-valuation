#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
洛阳钼业(603993.SH) SOTP估值模型
CMOC Group - 全球铜钴钼钨龙头企业

关键参数（2024-2025）：
- 总股本: 213.9亿股
- 2024营收: 约2100亿元（+15% YoY）
- 2024归母净利润: 约120亿元
- 当前价: ~18.6元
- 总市值: ~3975亿元
- PE TTM: ~12.7x

商业模式（5个分部）：
1. 铜钴（刚果金TFM+KFM） — 核心资产，全球前十大铜矿+最大钴矿之一
2. 钼钨（中国） — 国内龙头，壁垒高
3. 铌磷（巴西） — 全球最大铌生产商之一
4. 澳洲铜金（NPM 80%） — 稳定现金流
5. 其他/投资 — 华越镍钴权益等

数据来源：腾讯行情API（实时股价），config.yaml（静态参数）
"""

import numpy as np
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List
import yaml

WORK_DIR = Path(__file__).parent.parent.parent
import sys
sys.path.insert(0, str(WORK_DIR))
sys.path.insert(0, str(WORK_DIR / 'common'))


class CmocSOTP:
    """洛阳钼业SOTP分部估值"""

    def __init__(self, segments: list, base_net_profit: float,
                 profit_adjustment: float = 0.0, shares: float = 213.9):
        self.segments = segments
        self.base_net_profit = base_net_profit
        self.profit_adjustment = profit_adjustment
        self.shares = shares  # 总股本亿股

    @classmethod
    def from_config(cls, config_path: str = None) -> 'CmocSOTP':
        """从YAML配置文件加载"""
        if config_path is None:
            config_path = str(WORK_DIR / 'stocks/603993_cmoc/config.yaml')

        with open(config_path, 'r', encoding='utf-8') as f:
            cfg = yaml.safe_load(f)

        segments = cfg['segments']
        base_net_profit = cfg.get('base_net_profit', 120.0)
        shares = cfg['meta'].get('total_shares', 213.9)
        return cls(segments, base_net_profit, 0.0, shares)

    def calculate(self, current_price: float) -> Dict[str, Any]:
        """计算SOTP估值"""
        seg_results = []
        total_cap = 0.0
        total_adjusted_cap = 0.0

        for seg in self.segments:
            nm = seg['net_profit_cny']
            pe_base = seg['pe_base']
            pe_min = seg['pe_min']
            pe_max = seg['pe_max']

            cap_base = nm * pe_base
            cap_min = nm * pe_min
            cap_max = nm * pe_max

            total_cap += cap_base
            total_adjusted_cap += cap_base

            seg_results.append({
                'name': seg['name'],
                'net_profit': nm,
                'pe_base': pe_base,
                'pe_range': f'{pe_min}-{pe_max}',
                'cap_base': cap_base,
                'cap_min': cap_min,
                'cap_max': cap_max,
            })

        # 总估值
        target_price = total_cap / self.shares
        target_low = sum(s['cap_min'] for s in seg_results) / self.shares
        target_high = sum(s['cap_max'] for s in seg_results) / self.shares

        # 加总各分部profit（用于拆分展示）
        total_profit = sum(s["net_profit_cny"] for s in self.segments)

        # 上涨空间
        if current_price > 0:
            upside = (target_price / current_price - 1) * 100
            upside_low = (target_low / current_price - 1) * 100
            upside_high = (target_high / current_price - 1) * 100
        else:
            upside = upside_low = upside_high = 0.0

        return {
            'target_price': round(target_price, 2),
            'target_low': round(target_low, 2),
            'target_high': round(target_high, 2),
            'current_price': current_price,
            'upside': round(upside, 1),
            'upside_low': round(upside_low, 1),
            'upside_high': round(upside_high, 1),
            'total_market_cap': round(total_cap, 0),
            'total_profit': round(total_profit, 1),
            'shares': self.shares,
            'segments': seg_results,
        }

    def scenario_analysis(self, current_price: float) -> Dict[str, Any]:
        """情景分析：基于商品价格变动"""
        copper_base = 9000
        cobalt_base = 15
        moly_base = 25

        scenarios = []
        # 基准情景
        base = self.calculate(current_price)
        scenarios.append({
            'label': '基准',
            'copper': copper_base,
            'cobalt': cobalt_base,
            'target_price': base['target_price'],
            'upside': base['upside'],
        })

        # 铜价涨至$10000（乐观）
        optimistic_config = self._adjust_copper_cobalt(copper_price=10000, cobalt_price=15)
        opt_segments = self._apply_segment_profits(optimistic_config)
        opt_sotp = CmocSOTP(
            opt_segments, self.base_net_profit, self.profit_adjustment, self.shares
        )
        opt = opt_sotp.calculate(current_price)
        scenarios.append({
            'label': '铜价$10000',
            'copper': 10000,
            'cobalt': 15,
            'target_price': opt['target_price'],
            'upside': opt['upside'],
        })

        # 铜价跌至$7500（悲观）
        pessimistic_config = self._adjust_copper_cobalt(copper_price=7500, cobalt_price=10)
        pess_segments = self._apply_segment_profits(pessimistic_config)
        pess_sotp = CmocSOTP(
            pess_segments, self.base_net_profit, self.profit_adjustment, self.shares
        )
        pess = pess_sotp.calculate(current_price)
        scenarios.append({
            'label': '铜价$7500',
            'copper': 7500,
            'cobalt': 10,
            'target_price': pess['target_price'],
            'upside': pess['upside'],
        })

        # 钴价涨至$25
        cobalt_config = self._adjust_copper_cobalt(copper_price=9000, cobalt_price=25)
        cobalt_segments = self._apply_segment_profits(cobalt_config)
        cobalt_sotp = CmocSOTP(
            cobalt_segments, self.base_net_profit, self.profit_adjustment, self.shares
        )
        cobalt_scenario = cobalt_sotp.calculate(current_price)
        scenarios.append({
            'label': '钴价$25/lb',
            'copper': 9000,
            'cobalt': 25,
            'target_price': cobalt_scenario['target_price'],
            'upside': cobalt_scenario['upside'],
        })

        return {'scenarios': scenarios, 'base': base}

    def _adjust_copper_cobalt(self, copper_price: int, cobalt_price: int) -> list:
        """调整铜钴分部的利润假设"""
        # 铜净利估算公式：铜产量×（铜价-成本）×权益
        # 粗略估算：铜价每变化$1000/t → 影响净利约15亿
        # 钴价每变化$5/lb → 影响净利约10亿
        copper_change = copper_price - 9000  # 美元变化
        cobalt_change = cobalt_price - 15     # 美元/lb变化

        profit_impact = (copper_change / 1000 * 30) + (cobalt_change / 5 * 8)
        adjusted_copper_profit = 160.0 + profit_impact

        # 更新铜钴分部的净利
        from copy import deepcopy
        segments = deepcopy(self.segments)
        for seg in segments:
            if 'TFM' in seg['name'] or '铜钴' in seg['name']:
                seg['net_profit_cny'] = max(0, round(adjusted_copper_profit, 1))
                seg['variables']['铜价_美元吨'] = copper_price
                seg['variables']['钴价_美元磅'] = cobalt_price
        return segments

    def _apply_segment_profits(self, segments: list) -> list:
        return segments


def test():
    """本地测试"""
    model = CmocSOTP.from_config()
    price = 18.58
    result = model.calculate(price)
    print(f"=== 洛阳钼业SOTP估值 ===\n")
    print(f"当前股价: {price}元")
    print(f"目标价: {result['target_price']}元")
    print(f"区间: {result['target_low']}-{result['target_high']}元")
    print(f"上涨空间: {result['upside']}%\n")
    print(f"--- 分部估值 ---")
    for s in result['segments']:
        print(f"  {s['name']}: PE{s['pe_base']}x × {s['net_profit']}亿 = {s['cap_base']:.0f}亿")
    print(f"\n总估值: {result['total_market_cap']:.0f}亿元")
    print(f"总股数: {result['shares']}亿股")

    # 情景分析
    scenarios = model.scenario_analysis(price)
    print(f"\n--- 情景分析 ---")
    for s in scenarios['scenarios']:
        label = s['label']
        direction = "🟢" if s['upside'] > 15 else ("🟡" if s['upside'] > 5 else "🔴")
        print(f"  {direction} {label}: 目标价{s['target_price']}元 (涨幅{s['upside']}%)")


if __name__ == "__main__":
    test()
