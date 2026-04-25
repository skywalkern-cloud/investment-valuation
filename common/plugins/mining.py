#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MiningPlugin - 矿产资源类插件 (接口预置，Phase 2 P2)

驱动公式:
    营收 = 资源量 × 回收率 × 选矿回收率 × (矿物价格 - 开采成本)
    净利 = 营收 × 净利率

适用场景:
    - 矿业公司 (铜/金/锂/稀土等)
    - 适用于以资源储量为核心驱动力的公司

使用方式:
    >>> plugin = MiningPlugin()
    >>> result = plugin.compute(financials=None, variables={}, manual_data={
    ...     '资源量': 10000,       # 吨 (金属量)
    ...     '回收率': 0.85,       # 85%
    ...     '选矿回收率': 0.90,   # 90%
    ...     '矿物价格': 50000,     # 元/吨
    ...     '开采成本': 30000,     # 元/吨
    ... })
    >>> print(result['分部净利润'])
"""

from __future__ import annotations

from typing import Dict, List, Optional
from .sector_plugins import BaseSectorPlugin


class MiningPlugin(BaseSectorPlugin):
    """
    矿产资源类插件

    驱动: [资源量 × 回收率 × 选矿回收率 × (矿物价格 - 开采成本)]

    适用于矿业公司，以资源储量为核心驱动力。
    与ManufacturingPlugin的区别：MiningPlugin关注"地下的资源量"，
    而ManufacturingPlugin关注"地上的产能"。
    """

    name = "矿产资源"
    sector_type = "mining"

    def get_required_variables(self) -> List[str]:
        """
        返回所需变量列表

        Returns:
            ['资源量', '回收率', '选矿回收率', '矿物价格', '开采成本']
        """
        return [
            '资源量',        # 金属量 (吨)
            '回收率',        # 选矿回收率 (0.0 ~ 1.0)
            '选矿回收率',    # 冶炼回收率 (0.0 ~ 1.0)
            '矿物价格',      # 元/吨 (金属价格)
            '开采成本',      # 元/吨 (现金成本)
        ]

    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        """
        计算分部净利润

        公式:
            实际产量 = 资源量 × 回收率 × 选矿回收率
            营收 = 实际产量 × 矿物价格
            毛利 = 实际产量 × (矿物价格 - 开采成本)
            净利 = 毛利 × 净利率
        """
        # 资源量 (吨)
        resource = manual_data.get('资源量', variables.get('资源量', 0))

        # 回收率 (选矿)
        recovery_rate = manual_data.get('回收率', variables.get('回收率', 0.0))

        # 选矿回收率 (冶炼)
        smelting_rate = manual_data.get('选矿回收率', variables.get('选矿回收率', 0.0))

        # 矿物价格 (元/吨)
        price = manual_data.get('矿物价格', variables.get('矿物价格', 0))

        # 开采成本 (元/吨)
        cost = manual_data.get('开采成本', variables.get('开采成本', 0))

        # 实际产量 = 资源量 × 回收率 × 选矿回收率
        output = resource * recovery_rate * smelting_rate

        # 营收 (亿元 = 吨 × 元/吨 ÷ 1e8)
        revenue = output * price / 1e8

        # 毛利
        gross_profit = output * (price - cost) / 1e8

        # EBITDA ≈ 毛利 × 85%
        ebitda = gross_profit * 0.85

        # 净利率 (矿业约15-25%)
        net_margin = manual_data.get('净利率', variables.get('净利率', 0.20))
        net_profit = gross_profit * net_margin

        return {
            '分部净利润': max(0, net_profit),
            '分部营收': revenue,
            '分部毛利': gross_profit,
            '分部EBITDA': max(0, ebitda),
        }

    def validate_config(self, config: Dict) -> bool:
        """验证配置是否合法"""
        required = ['资源量', '回收率', '矿物价格', '开采成本']
        for key in required:
            val = config.get(key, 0)
            if val is None or val <= 0:
                return False
        return True


# ========== 注册到插件注册表 ==========
# 在PLUGIN_REGISTRY中注册 (如果sector_plugins.py中已有注册，可忽略)
# from common.plugins.sector_plugins import PLUGIN_REGISTRY
# PLUGIN_REGISTRY['mining'] = MiningPlugin
