#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DCF折现引擎 (Discounting Engine)
第三层: 计算WACC、DCF估值、终端增长率敏感性

Phase 2 P0
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass


@dataclass
class DCFConfig:
    """DCF配置"""
    forecast_years: int = 5           # 预测年数
    terminal_growth: float = 0.03     # 永续增长率
    risk_free_rate: float = 0.0      # 无风险利率
    beta: float = 1.2                # Beta系数
    market_premium: float = 0.05     # 市场风险溢价
    cost_of_debt: float = 0.04       # 债务成本
    tax_rate: float = 0.15           # 所得税率
    debt_ratio: float = 0.3          # 债务比例
    beta_last_updated: str = ""       # Beta最后更新时间 (YYYY-MM-DD)


class DiscountingEngine:
    """
    DCF折现引擎

    使用方式:
    >>> engine = DiscountingEngine()
    >>> wacc = engine.calc_wacc(risk_free_rate=0.025, beta=1.2)
    >>> dcf = engine.dcf_fcf(fcf_list=[1.0, 1.1, 1.2, 1.3, 1.5], terminal_fcf=1.6, wacc=0.10, net_debt=0.5)
    >>> print(dcf['目标价'], dcf['SOTP_市值_亿'])
    """

    def __init__(self, config: Optional[DCFConfig] = None):
        self.config = config or DCFConfig()

    # ========== WACC计算 ==========

    def calc_wacc(
        self,
        risk_free_rate: Optional[float] = None,
        beta: Optional[float] = None,
        market_premium: Optional[float] = None,
        cost_of_debt: Optional[float] = None,
        tax_rate: Optional[float] = None,
        debt_ratio: Optional[float] = None,
    ) -> float:
        """
        计算WACC (加权平均资本成本)

        WACC = E/V × Re + D/V × Rd × (1-T)

        Args:
            risk_free_rate: 无风险利率 (10年国债)
            beta: Beta系数
            market_premium: 市场风险溢价
            cost_of_debt: 债务成本
            tax_rate: 所得税率
            debt_ratio: 债务占总资本比例

        Returns:
            WACC (小数形式，如0.10表示10%)
        """
        # 使用传入值或配置值
        rf = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate
        b = beta if beta is not None else self.config.beta
        mp = market_premium if market_premium is not None else self.config.market_premium
        rd = cost_of_debt if cost_of_debt is not None else self.config.cost_of_debt
        t = tax_rate if tax_rate is not None else self.config.tax_rate
        dr = debt_ratio if debt_ratio is not None else self.config.debt_ratio

        # CAPM: Re = Rf + β × (Rm - Rf)
        re = rf + b * mp

        # WACC
        equity_ratio = 1 - dr
        wacc = equity_ratio * re + dr * rd * (1 - t)

        return wacc

    def beta_expired(self, max_days: int = 90) -> Tuple[bool, int]:
        """
        检查beta是否过期

        Args:
            max_days: 最大未更新天数

        Returns:
            (是否过期, 距今天数)
        """
        if not self.config.beta_last_updated:
            return (True, max_days)

        from datetime import datetime, timedelta
        try:
            last = datetime.strptime(self.config.beta_last_updated, '%Y-%m-%d')
            days_ago = (datetime.now() - last).days
            return (days_ago > max_days, days_ago)
        except:
            return (True, max_days)

    # ========== DCF核心 ==========

    def dcf_fcf(
        self,
        fcf_projections: List[float],
        terminal_fcf: float,
        wacc: Optional[float] = None,
        net_debt: float = 0.0,
        shares: float = 6.53,
        terminal_growth: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        FCF DCF估值

        Args:
            fcf_projections: 预测期内每年的FCF (亿元)
            terminal_fcf: 预测期末年的FCF (亿元)，用于计算终值
            wacc: 折现率，如果为None则用config里的计算值
            net_debt: 净债务 (亿元)
            shares: 总股本 (亿股)
            terminal_growth: 永续增长率，如果为None则用config里的值

        Returns:
            {
                'WACC': float,
                '当前价值_亿': float,
                '终值_亿': float,
                '企业价值_亿': float,
                '股权价值_亿': float,
                '目标价_元': float,
                'SOTP_市值_亿': float,
                '各年折现因子': list,
            }
        """
        tg = terminal_growth if terminal_growth is not None else self.config.terminal_growth
        wacc_val = wacc if wacc is not None else self.calc_wacc()
        n = len(fcf_projections)

        # 1. 预测期折现
        pv_sum = 0.0
        discount_factors = []
        for i, fcf in enumerate(fcf_projections):
            factor = 1 / (1 + wacc_val) ** (i + 1)
            pv_sum += fcf * factor
            discount_factors.append(round(factor, 4))

        # 2. 终值 (Gordon Growth Model)
        #    TV = FCF_{n+1} / (WACC - g) = FCF_n × (1+g) / (WACC - g)
        if wacc_val <= tg:
            # WACC必须大于永续增长率，否则公式无效
            terminal_value = fcf_projections[-1] * 10  # fallback保守估算
        else:
            terminal_value = terminal_fcf * (1 + tg) / (wacc_val - tg)

        # 终值折现到今天
        pv_terminal = terminal_value / (1 + wacc_val) ** n

        # 3. 企业价值
        ev = pv_sum + pv_terminal

        # 4. 股权价值 = 企业价值 - 净债务
        equity_value = ev - net_debt

        # 5. 目标价
        target_price = equity_value / shares if shares > 0 else 0

        return {
            'WACC': round(wacc_val * 100, 2),  # 百分比
            '当前价值_亿': round(pv_sum, 2),
            '终值_亿': round(terminal_value, 2),
            'PV终值_亿': round(pv_terminal, 2),
            '企业价值_亿': round(ev, 2),
            '股权价值_亿': round(equity_value, 2),
            '目标价_元': round(target_price, 2),
            'SOTP_市值_亿': round(ev, 2),  # 用于和SOTP合并
            '各年折现因子': discount_factors,
            'PV_sum_亿': round(pv_sum, 2),
            'PV_terminal_亿': round(pv_terminal, 2),
        }

    def dcf_sensitivity(
        self,
        base_fcf: List[float],
        terminal_fcf: float,
        wacc: float,
        net_debt: float,
        shares: float,
        terminal_range: Tuple[float, float, float] = (0.02, 0.03, 0.04),
        wacc_range: Tuple[float, float, float] = (0.08, 0.10, 0.12),
    ) -> Dict[str, Any]:
        """
        DCF双变量敏感性分析

        Args:
            base_fcf: 基准FCF预测
            terminal_fcf: 终年FCF
            wacc: 基准WACC
            net_debt: 净债务
            shares: 总股本
            terminal_range: (低, 中, 高) 永续增长率
            wacc_range: (低, 中, 高) WACC

        Returns:
            {
                'grid': 3x3矩阵的目标价,
                'wacc_range': [低,中,高],
                'tg_range': [低,中,高],
                'base_target': 基准目标价,
            }
        """
        wacc_vals = [wacc * (1 + delta) for delta in [-0.02, 0, 0.02]]
        tg_vals = list(terminal_range)

        grid = []
        base_target = None

        for tg in tg_vals:
            row = []
            for w in wacc_vals:
                result = self.dcf_fcf(
                    fcf_projections=base_fcf,
                    terminal_fcf=terminal_fcf,
                    wacc=w,
                    net_debt=net_debt,
                    shares=shares,
                    terminal_growth=tg,
                )
                price = result['目标价_元']
                row.append(round(price, 2))
                if tg == terminal_range[1] and w == wacc:
                    base_target = price
            grid.append(row)

        return {
            'grid': grid,
            'wacc_range': [f'{(wacc*100):.0f}%±2%' for w in wacc_vals],
            'tg_range': [f'{t*100:.0f}%' for t in tg_vals],
            'base_target': base_target,
        }

    # ========== 概率加权 ==========

    def apply_event_weights(
        self,
        base_value: float,
        events: List[Dict[str, Any]],
    ) -> float:
        """
        应用关键事件概率权重

        Args:
            base_value: 基础估值 (亿元市值)
            events: 事件列表
                [{
                    'name': '1.6T认证通过',
                    'probability': 0.65,  # 0.0 ~ 1.0
                    'magnitude': 1.40,     # 影响幅度 (1.4 = 股价×1.4)
                    'impact': 'positive',  # 'positive' | 'negative'
                }, ...]

        Returns:
            调整后估值 (亿元)
        """
        adjusted = base_value
        for ev in events:
            prob = ev.get('probability', 0)
            mag = ev.get('magnitude', 1.0)
            direction = ev.get('impact', 'positive')

            if direction == 'positive':
                # 正向影响: 概率 × (幅度-1) 计入
                adjusted *= (1 + (mag - 1) * prob)
            else:
                # 负向影响: 概率 × (1-幅度) 计入
                adjusted *= (1 - (1 - mag) * prob)

        return adjusted


    # ========== 10年国债自动获取 (P0新增) ==========

    def fetch_risk_free_rate(self) -> float:
        """
        自动获取10年国债收益率作为无风险利率

        降级路径: akshare(同花顺) → manual_data → fallback(2.5%)
        """
        try:
            from common.data.fetcher import DataFetcher
            fetcher = DataFetcher()
            result = fetcher.fetch_10y_treasury_yield()
            if result.is_success:
                return result.value
        except Exception:
            pass
        # 最终降级
        return 0.025

    def calc_wacc_auto(self, beta: Optional[float] = None) -> float:
        """
        自动获取无风险利率的WACC计算
        """
        rf = self.fetch_risk_free_rate()
        b = beta if beta is not None else self.config.beta
        return self.calc_wacc(risk_free_rate=rf, beta=b)

# ========== 独立函数 ==========

def estimate_fcf_from_ebitda(
    ebitda: float,
    tax_rate: float = 0.15,
    capex_ratio: float = 0.15,
    working_cap_change: float = 0.0,
) -> float:
    """
    从EBITDA估算FCF (简化版)

    FCF ≈ EBITDA × (1-T) - CAPEX - ΔWC

    Args:
        ebitda: EBITDA (亿元)
        tax_rate: 税率
        capex_ratio: CAPEX占EBITDA比例
        working_cap_change: 营运资本变化 (亿元)

    Returns:
        FCF估算 (亿元)
    """
    nopat = ebitda * (1 - tax_rate)
    capex = ebitda * capex_ratio
    fcf = nopat - capex - working_cap_change
    return max(0, fcf)  # FCF不能为负


def estimate_fcf_from_net_profit(
    net_profit: float,
    depreciation: float = 0.0,
    capex: float = 0.0,
    working_cap_change: float = 0.0,
) -> float:
    """
    从净利润估算FCF

    FCF = 净利润 + 折旧摊销 - CAPEX - ΔWC

    Args:
        net_profit: 净利润 (亿元)
        depreciation: 折旧摊销 (亿元)
        capex: 资本支出 (亿元)
        working_cap_change: 营运资本变化 (亿元)

    Returns:
        FCF估算 (亿元)
    """
    fcf = net_profit + depreciation - capex - working_cap_change
    return max(0, fcf)


# ========== 测试 ==========

if __name__ == '__main__':
    print("=== DiscountingEngine 测试 ===\n")

    engine = DiscountingEngine()

    # 1. WACC计算
    wacc = engine.calc_wacc(risk_free_rate=0.025, beta=1.2)
    print(f"1. WACC计算:")
    print(f"   无风险利率=2.5%, Beta=1.2, 市场溢价=5%")
    print(f"   WACC = {wacc*100:.2f}%")
    print()

    # 2. DCF估值 (云南锗业简化版)
    print(f"2. DCF估值 (云南锗业简化版):")
    print(f"   假设5年FCF: [0.3, 0.5, 0.8, 1.2, 1.8]亿元")

    fcf_projections = [0.3, 0.5, 0.8, 1.2, 1.8]
    terminal_fcf = 1.8  # 第5年FCF

    result = engine.dcf_fcf(
        fcf_projections=fcf_projections,
        terminal_fcf=terminal_fcf,
        wacc=wacc,
        net_debt=0,  # 云南锗业净债务约0
        shares=6.53,
        terminal_growth=0.03,
    )

    print(f"   WACC: {result['WACC']}%")
    print(f"   预测期PV: {result['PV_sum_亿']}亿元")
    print(f"   终值PV: {result['PV_terminal_亿']}亿元")
    print(f"   企业价值: {result['企业价值_亿']}亿元")
    print(f"   股权价值: {result['股权价值_亿']}亿元")
    print(f"   目标价: {result['目标价_元']}元")
    print()

    # 3. 敏感性分析
    print(f"3. Terminal Growth敏感性:")
    print(f"   假设WACC={wacc*100:.2f}%, TG=[2%, 3%, 4%]")

    sensitivity = engine.dcf_sensitivity(
        base_fcf=fcf_projections,
        terminal_fcf=terminal_fcf,
        wacc=wacc,
        net_debt=0,
        shares=6.53,
        terminal_range=(0.02, 0.03, 0.04),
    )

    print(f"   {'TG':>8} | {'WACC-2%':>10} | {'WACC':>10} | {'WACC+2%':>10}")
    for i, tg in enumerate(sensitivity['tg_range']):
        row = sensitivity['grid'][i]
        print(f"   {tg:>8} | {row[0]:>10} | {row[1]:>10} | {row[2]:>10}")
    print()

    # 4. 概率加权
    print(f"4. 概率加权 (1.6T认证):")
    base_cap = result['SOTP_市值_亿']
    events = [
        {'name': '1.6T认证通过', 'probability': 0.65, 'magnitude': 1.4, 'impact': 'positive'},
        {'name': '良率突破85%', 'probability': 0.55, 'magnitude': 1.2, 'impact': 'positive'},
        {'name': '锗价下跌20%', 'probability': 0.30, 'magnitude': 0.85, 'impact': 'negative'},
    ]

    weighted = engine.apply_event_weights(base_cap, events)
    print(f"   基础市值: {base_cap}亿元")
    for ev in events:
        print(f"   - {ev['name']}: prob={ev['probability']*100:.0f}%, mag={ev['magnitude']:.2f}x")
    print(f"   加权后市值: {weighted:.1f}亿元")
    print(f"   隐含目标价: {weighted/6.53:.1f}元")
