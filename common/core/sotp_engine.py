#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SOTP分部估值引擎

将多个行业插件的分部净利润, 按不同PE倍数计算分部市値, 合并为SOTP总市値.

使用方式:
>>> from sotp_engine import SOTPEngine, get_plugin
>>> engine = SOTPEngine()
>>> engine.add分部('fabless', weight=0.6, plugin_config={...})
>>> engine.add分部('manufacturing', weight=0.4, plugin_config={...})
>>> result = engine.run(financials, auto_vars, manual_data)
>>> print(result['目标价'], result['SOTP_总市値'])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
import numpy as np

from ..plugins.sector_plugins import BaseSectorPlugin, get_plugin, PLUGIN_REGISTRY


@dataclass
class SOTPDivision:
    """单个分部的配置和计算结果"""

    # 配置
    plugin_type: str                    # manufacturing | fabless | platform
    name: str                           # 分部名称 (如 "半导体分部")
    weight: float = 0.5                # 利润权重 (0.0 ~ 1.0)

    # PE配置
    pe_min: float = 15.0              # PE下限
    pe_max: float = 65.0              # PE上限
    pe_base: float = 30.0             # PE中枢

    # 计算结果 (run()后填充)
    分部净利润: float = 0.0
    分部营收: float = 0.0
    分部毛利: float = 0.0
    分部EBITDA: float = 0.0
    分部市値_区间: tuple = field(default_factory=lambda: (0.0, 0.0))
    分部市値_中枢: float = 0.0

    @property
    def pe_range(self) -> tuple:
        return (self.pe_min, self.pe_max)


class SOTPEngine:
    """
    SOTP (Sum Of The Parts) 分部估值引擎

    使用方式:
        engine = SOTPEngine()
        engine.add_division(SOTPDivision(...))
        engine.add_division(SOTPDivision(...))
        result = engine.run(financials, variables, manual_data)
    """

    def __init__(self):
        self.divisions: List[SOTPDivision] = []
        self._plugin_cache: Dict[str, BaseSectorPlugin] = {}

    def add_division(
        self,
        plugin_type: str,
        name: str,
        weight: float = 0.5,
        pe_min: float = 15.0,
        pe_max: float = 65.0,
        pe_base: float = 30.0,
        plugin_config: Optional[Dict] = None,
    ) -> 'SOTPEngine':
        """
        添加一个分部

        Args:
            plugin_type: 插件类型
            name: 分部名称
            weight: 利润贡献权重
            pe_min/max/base: PE估值区间
        """
        div = SOTPDivision(
            plugin_type=plugin_type,
            name=name,
            weight=weight,
            pe_min=pe_min,
            pe_max=pe_max,
            pe_base=pe_base,
        )
        self.divisions.append(div)
        return self

    def add_division_from_config(
        self, config: Dict, variables: Dict, manual_data: Dict
    ) -> 'SOTPEngine':
        """
        从config.yaml配置字典添加分部
        """
        return self.add_division(
            plugin_type=config['type'],
            name=config.get('name', config['type']),
            weight=config.get('weight', 0.5),
            pe_min=config.get('pe_min', 15.0),
            pe_max=config.get('pe_max', 65.0),
            pe_base=config.get('pe_base', 30.0),
            plugin_config=config,
        )

    def _get_plugin(self, plugin_type: str) -> BaseSectorPlugin:
        """获取插件实例 (带缓存)"""
        if plugin_type not in self._plugin_cache:
            self._plugin_cache[plugin_type] = get_plugin(plugin_type)
        return self._plugin_cache[plugin_type]

    def run(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, Any]:
        """
        执行SOTP计算

        Args:
            financials: FinancialFoundation对象
            variables: 自动获取的实时变量
            manual_data: 手动填入的配置

        Returns:
            {
                'SOTP_总市値_中枢': float,
                'SOTP_总市値_区间': tuple(min, max),
                '目标价_中枢': float,
                '目标价_区间': tuple(min, max),
                '分部列表': [ {...}, {...} ],
                '上涨空间': float (%),
                '上涨空间_区间': tuple(min%, max%),
            }
        """
        total_nm = 0.0  # 总净利润
        total_nm_min = 0.0  # 悲观总净利润
        total_nm_max = 0.0  # 乐观总净利润

        division_results = []

        # 1. 计算每个分部
        for div in self.divisions:
            plugin = self._get_plugin(div.plugin_type)

            # 获取分部特有配置
            div_manual = manual_data.get(div.name, manual_data)
            div_vars = variables

            result = plugin.compute(financials, div_vars, div_manual)

            # 填充分部结果
            div.分部净利润 = result['分部净利润']
            div.分部营收 = result['分部营收']
            div.分部毛利 = result['分部毛利']
            div.分部EBITDA = result['分部EBITDA']

            # 计算分部市値区间
            cap_min = div.分部净利润 * div.pe_min
            cap_max = div.分部净利润 * div.pe_max
            cap_base = div.分部净利润 * div.pe_base

            div.分部市値_区间 = (cap_min, cap_max)
            div.分部市値_中枢 = cap_base

            total_nm += result['分部净利润']
            total_nm_min += cap_min
            total_nm_max += cap_max

            division_results.append({
                'name': div.name,
                'type': div.plugin_type,
                'weight': div.weight,
                '分部净利润_亿': result['分部净利润'],
                '分部营收_亿': result['分部营收'],
                '分部毛利_亿': result['分部毛利'],
                '分部EBITDA_亿': result['分部EBITDA'],
                'PE区间': f"{div.pe_min:.0f}x ~ {div.pe_max:.0f}x",
                'PE中枢': f"{div.pe_base:.0f}x",
                '分部市值_亿_区间': f"{cap_min:.1f} ~ {cap_max:.1f}",
                '分部市值_亿_中枢': f"{cap_base:.1f}",
            })

        # 2. 计算SOTP总市値
        sotp_cap_base = sum(d.分部市値_中枢 for d in self.divisions)
        sotp_cap_min = total_nm_min
        sotp_cap_max = total_nm_max

        # 3. 计算目标价
        shares = financials.shares if financials and financials.shares > 0 else 6.53  # 默认6.53亿股
        if shares <= 0:
            shares = 6.53

        target_base = sotp_cap_base / shares
        target_min = sotp_cap_min / shares
        target_max = sotp_cap_max / shares

        # 4. 计算上涨空间
        current_price = financials.price if financials and financials.price > 0 else 77.12

        upside_base = (target_base / current_price - 1) * 100
        upside_min = (target_min / current_price - 1) * 100
        upside_max = (target_max / current_price - 1) * 100

        return {
            'SOTP_总市値_中枢_亿': round(sotp_cap_base, 1),
            'SOTP_总市値_区间_亿': (round(sotp_cap_min, 1), round(sotp_cap_max, 1)),
            '目标价_中枢_元': round(target_base, 2),
            '目标价_区间_元': (round(target_min, 2), round(target_max, 2)),
            '分部列表': division_results,
            '当前价_元': round(current_price, 2),
            '上涨空间_中枢_%': round(upside_base, 1),
            '上涨空间_区间_%': (round(upside_min, 1), round(upside_max, 1)),
            '总净利润_亿': round(total_nm, 3),
            'shares_亿': round(shares, 2),
        }

    def run_sensitivity(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
        param_name: str,
        param_range: List[float],
        fixed_params: Optional[Dict] = None,
    ) -> List[Dict]:
        """
        单参数敏感性分析

        Args:
            param_name: 参数名 (如 '良率')
            param_range: 参数范围 (如 [0.6, 0.7, 0.8, 0.9])
            fixed_params: 其他固定参数

        Returns:
            [{param_value, 目标价, 上涨空间, ...}, ...]
        """
        results = []
        base_manual = manual_data.copy() if manual_data else {}

        for val in param_range:
            # 设置参数
            test_manual = base_manual.copy()
            test_manual[param_name] = val

            # 如果有fixed_params,也加进去
            if fixed_params:
                test_manual.update(fixed_params)

            # 运行SOTP
            r = self.run(financials, variables, test_manual)
            results.append({
                param_name: val,
                '目标价': r['目标价_中枢_元'],
                '上涨空间_%': r['上涨空间_中枢_%'],
                'SOTP_市値_亿': r['SOTP_总市値_中枢_亿'],
            })

        return results

    def summary(self, result: Dict) -> str:
        """生成文字摘要"""
        lines = []
        lines.append("【SOTP分部估值结果】")
        lines.append(f"当前价: {result['当前价_元']}元")
        lines.append(f"目标价: {result['目标价_区间_元'][0]:.1f} ~ {result['目标价_区间_元'][1]:.1f}元 (中枢{result['目标价_中枢_元']:.1f}元)")
        lines.append(f"上涨空间: {result['上涨空间_区间_%'][0]:+.0f}% ~ {result['上涨空间_区间_%'][1]:+.0f}% (中枢{result['上涨空间_中枢_%']:+.0f}%)")
        lines.append("")
        lines.append("【分部明细】")
        for div in result['分部列表']:
            lines.append(f"  {div['name']} ({div['type']}):")
            lines.append(f"    净利: {div['分部净利润_亿']:.3f}亿 | PE: {div['PE区间']}")
            lines.append(f"    市値: {div['分部市值_亿_区间']}亿 (中枢{div['分部市值_亿_中枢']}亿)")
        return '\n'.join(lines)


# ========== 快速加载函数 ==========

def load_from_yaml_config(config: Dict, financials, auto_vars: Dict, manual_data: Dict) -> Dict:
    """
    从YAML配置快速加载并运行SOTP

    Args:
        config: stocks/002428_yunnangeiyec/config.yaml 解析结果
        financials: FinancialFoundation
        auto_vars: 自动获取的实时变量
        manual_data: stocks/002428_yunnangeiyec/manual_data.yaml 解析结果
    """
    sotp_config = config.get('plugins', [])

    engine = SOTPEngine()
    for plugin_cfg in sotp_config:
        engine.add_division_from_config(plugin_cfg, auto_vars, manual_data)

    return engine.run(financials, auto_vars, manual_data)


if __name__ == '__main__':
    # 快速演示
    from common.core.financial_foundation import FinancialFoundation

    print("=== SOTP引擎演示 ===\n")

    # 获取财务数据
    ff = FinancialFoundation.from_akshare('002428')

    # 云南锗业配置
    sotp = SOTPEngine()
    sotp.add_division(
        plugin_type='manufacturing',
        name='传统锗锭业务',
        weight=0.4,
        pe_min=12,
        pe_max=25,
        pe_base=18,
    ).add_division(
        plugin_type='fabless',
        name='半导体分部',
        weight=0.6,
        pe_min=50,
        pe_max=80,
        pe_base=65,
    )

    # 手动数据
    manual = {
        # 制造业 (锗锭)
        '传统锗锭业务': {
            '产能': 50,        # 吨/年
            '良率': 0.88,
            '稼动率': 0.85,
            '商品售价': 17500,  # 元/kg
            '原料成本': 8500,   # 元/kg
            '净利率': 0.08,
        },
        # Fabless (磷化铟)
        '半导体分部': {
            '订单管道': 5.0,
            '研发成功率': 0.75,
            '终端渗透率': 0.15,
            '认证进度': 60,
            'BOM占比': 0.35,
            '净利率': 0.30,
        },
    }

    result = sotp.run(ff, {}, manual)

    print(f"当前价: {result['当前价_元']}元")
    print(f"目标价区间: {result['目标价_区间_元'][0]:.2f} ~ {result['目标价_区间_元'][1]:.2f}元")
    print(f"中枢目标价: {result['目标价_中枢_元']:.2f}元")
    print(f"上涨空间: {result['上涨空间_区间_%'][0]:+.0f}% ~ {result['上涨空间_区间_%'][1]:+.0f}%")
    print()
    print("分部明细:")
    for div in result['分部列表']:
        print(f"  {div['name']}: 净利={div['分部净利润_亿']:.3f}亿, PE={div['PE区间']}, 市値={div['分部市値_亿_区间']}亿")
