#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DCF折现引擎 (Discounting Engine)
第三层: 计算WACC、DCF估值、终端增长率敏感性

Phase 2 P0

要求的方法:
    - compute_dcf:     执行DCF估值
    - compute_wacc:    计算WACC（含Beta过期警告）
    - sensitivity_analysis: 双变量敏感性分析
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

from .beta_auto_refresh import BetaAutoRefresh, BetaSource


# ============================================================
# DCF配置
# ============================================================

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


# ============================================================
# DiscountingEngine
# ============================================================

class DiscountingEngine:
    """
    DCF折现引擎

    使用方式:
    >>> engine = DiscountingEngine()
    >>> wacc = engine.compute_wacc(risk_free_rate=0.025, beta=1.2)
    >>> dcf = engine.compute_dcf(
    ...     fcf_projections=[0.3, 0.5, 0.8, 1.2, 1.8],
    ...     terminal_fcf=1.8,
    ...     wacc=wacc,
    ...     net_debt=0.0,
    ...     shares=6.53,
    ... )
    >>> print(dcf['目标价_元'], dcf['股权价值_亿'])
    """

    def __init__(
        self,
        config: Optional[DCFConfig] = None,
        beta_refresher: Optional[BetaAutoRefresh] = None,
    ):
        self.config = config or DCFConfig()
        self._last_wacc: Optional[float] = None
        self._last_dcf: Optional[Dict[str, Any]] = None
        self._beta_refresher = beta_refresher or BetaAutoRefresh(
            fallback_beta=self.config.beta,
            manual_beta=self.config.beta,
            manual_last_updated=self.config.beta_last_updated,
        )

    # ============================================================
    # WACC计算 (P0核心)
    # ============================================================

    def compute_wacc(
        self,
        risk_free_rate: Optional[float] = None,
        beta: Optional[float] = None,
        market_premium: Optional[float] = None,
        cost_of_debt: Optional[float] = None,
        tax_rate: Optional[float] = None,
        debt_ratio: Optional[float] = None,
        auto_fetch_rf: bool = False,
        auto_refresh_beta: bool = True,
    ) -> float:
        """
        计算WACC (加权平均资本成本) — Phase 2 P0

        WACC = E/V × Re + D/V × Rd × (1-T)
        其中 CAPM: Re = Rf + β × (Rm - Rf)

        Args:
            risk_free_rate: 无风险利率 (10年国债)
            beta: Beta系数
            market_premium: 市场风险溢价
            cost_of_debt: 债务成本
            tax_rate: 所得税率
            debt_ratio: 债务占总资本比例
            auto_fetch_rf: 是否自动从DataFetcher获取10年国债

        Returns:
            WACC (小数形式，如0.10表示10%)

        Note:
            Beta过期警告: 超过90天未更新则发出warnings.warn提示
        """
        # Beta过期检查 + 自动刷新
        expired, days = self.beta_expired()
        if expired and beta is None and auto_refresh_beta:
            new_beta, new_date, source, did_refresh = (
                self._beta_refresher.get_beta_with_auto_refresh(
                    stock_code=getattr(self.config, 'stock_code', '002428'),
                    max_days=90,
                )
            )
            if did_refresh:
                self.config.beta = new_beta
                self.config.beta_last_updated = new_date
                warnings.warn(
                    f"⚡ [DiscountingEngine] Beta自动刷新: {new_beta:.2f} "
                    f"(来源: {source.value})"
                )
        elif expired and beta is None:
            warnings.warn(
                f"⚠️ [DiscountingEngine] Beta已过期 {days} 天 (>{90}天)，建议更新\n"
                f"   当前值: {self.config.beta} | 更新时间: "
                f"{self.config.beta_last_updated or '未知'}"
            )

        # 自动获取无风险利率
        if auto_fetch_rf:
            rf = self.fetch_risk_free_rate()
        else:
            rf = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate

        b = beta if beta is not None else self.config.beta
        mp = market_premium if market_premium is not None else self.config.market_premium
        rd = cost_of_debt if cost_of_debt is not None else self.config.cost_of_debt
        t = tax_rate if tax_rate is not None else self.config.tax_rate
        dr = debt_ratio if debt_ratio is not None else self.config.debt_ratio

        # CAPM: Re = Rf + β × (Rm - Rf)
        re = rf + b * mp
        equity_ratio = 1 - dr
        wacc = equity_ratio * re + dr * rd * (1 - t)

        self._last_wacc = wacc
        return wacc

    # calc_wacc 别名，保留向后兼容
    def calc_wacc(self, **kwargs) -> float:
        """calc_wacc 别名，保留向后兼容"""
        return self.compute_wacc(**kwargs)

    def beta_expired(self, max_days: int = 90) -> Tuple[bool, int]:
        """
        检查Beta是否过期

        Args:
            max_days: 最大未更新天数 (默认90天)

        Returns:
            (是否过期, 距今天数)
        """
        if not self.config.beta_last_updated:
            return (True, max_days)
        from datetime import datetime
        try:
            last = datetime.strptime(self.config.beta_last_updated, '%Y-%m-%d')
            days_ago = (datetime.now() - last).days
            return (days_ago > max_days, days_ago)
        except Exception:
            return (True, max_days)

    # ============================================================
    # DCF核心 (P0核心)
    # ============================================================

    def compute_dcf(
        self,
        fcf_projections: List[float],
        terminal_fcf: float,
        wacc: Optional[float] = None,
        net_debt: float = 0.0,
        shares: float = 6.53,
        terminal_growth: Optional[float] = None,
        risk_free_rate: Optional[float] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """
        执行FCF DCF估值 — Phase 2 P0

        企业价值 = Σ [ FCF_t / (1+WACC)^t ] + 终值 / (1+WACC)^n
        股权价值 = 企业价值 - 净债务
        目标价   = 股权价值 / 总股本

        Args:
            fcf_projections: 预测期内每年的FCF (亿元)，长度为n年
            terminal_fcf:     预测期末年的FCF (亿元)，用于计算终值
            wacc:             折现率，如果为None则自动计算
            net_debt:         净债务 (亿元)
            shares:           总股本 (亿股)
            terminal_growth:  永续增长率，如果为None则用config值
            risk_free_rate:   无风险利率（wacc=None时用于计算WACC）

        Returns:
            {
                'WACC_pct':      float,   # WACC百分比，如10.0表示10%
                'WACC':          float,   # WACC小数，如0.10
                'PV_sum_亿':     float,   # 预测期PV合计
                'PV_terminal_亿': float,  # 终值PV
                '终值_亿':       float,   # Gordon模型计算的终值
                '企业价值_亿':   float,   # EV
                '股权价值_亿':   float,   # Equity Value
                '目标价_元':     float,   # 目标价
                '各年折现因子':  list,    # 每年的折现因子
                '各年PV_亿':     list,    # 每年的PV
                'shares_亿':     float,   # 股本
                'net_debt_亿':   float,   # 净债务
                'terminal_growth': float,  # 永续增长率
                'warnings':      list,    # 警告信息列表
            }
        """
        tg = terminal_growth if terminal_growth is not None else self.config.terminal_growth
        warnings_list: List[str] = []

        # 自动计算WACC
        if wacc is None:
            rf = risk_free_rate if risk_free_rate is not None else self.config.risk_free_rate
            wacc_val = self.compute_wacc(risk_free_rate=rf)
            warnings_list.append("WACC为自动计算，请确认参数")
        else:
            wacc_val = wacc

        n = len(fcf_projections)

        # 1. 预测期折现
        pv_sum = 0.0
        discount_factors = []
        pv_list = []
        for i, fcf in enumerate(fcf_projections):
            factor = 1 / (1 + wacc_val) ** (i + 1)
            pv = fcf * factor
            pv_sum += pv
            discount_factors.append(round(factor, 4))
            pv_list.append(round(pv, 3))

        # 2. 终值 (Gordon Growth Model)
        if wacc_val <= tg:
            warnings_list.append(f"WACC({wacc_val:.3f})<=TG({tg:.3f})，终值使用保守估算")
            terminal_value = fcf_projections[-1] * 10
        else:
            terminal_value = terminal_fcf * (1 + tg) / (wacc_val - tg)

        # 终值折现到今天
        pv_terminal = terminal_value / (1 + wacc_val) ** n

        # 3. 企业价值
        ev = pv_sum + pv_terminal

        # 4. 股权价值
        equity_value = ev - net_debt

        # 5. 目标价
        target_price = equity_value / shares if shares > 0 else 0.0

        result = {
            'WACC_pct': round(wacc_val * 100, 2),
            'WACC': round(wacc_val, 4),
            'PV_sum_亿': round(pv_sum, 2),
            'PV_terminal_亿': round(pv_terminal, 2),
            '终值_亿': round(terminal_value, 2),
            '企业价值_亿': round(ev, 2),
            '股权价值_亿': round(equity_value, 2),
            '目标价_元': round(target_price, 2),
            '各年折现因子': discount_factors,
            '各年PV_亿': pv_list,
            'shares_亿': round(shares, 2),
            'net_debt_亿': round(net_debt, 2),
            'terminal_growth': tg,
            'warnings': warnings_list,
        }

        self._last_dcf = result
        return result

    # dcf_fcf 别名，保留向后兼容
    def dcf_fcf(self, **kwargs) -> Dict[str, Any]:
        """dcf_fcf 别名，保留向后兼容"""
        return self.compute_dcf(**kwargs)

    # ============================================================
    # 敏感性分析 (P1)
    # ============================================================

    def sensitivity_analysis(
        self,
        fcf_projections: List[float],
        terminal_fcf: float,
        wacc: Optional[float] = None,
        net_debt: float = 0.0,
        shares: float = 6.53,
        terminal_range: Tuple[float, float, float] = (0.02, 0.03, 0.04),
        wacc_delta: float = 0.02,
    ) -> Dict[str, Any]:
        """
        DCF双变量敏感性分析 — Phase 2 P1

        生成 WACC × Terminal Growth 的3×3目标价矩阵。

        Args:
            fcf_projections: 预测期内每年的FCF (亿元)
            terminal_fcf:     预测期末年的FCF (亿元)
            wacc:             基准WACC，如果为None则自动计算
            net_debt:         净债务 (亿元)
            shares:           总股本 (亿股)
            terminal_range:   (min, mid, max) 永续增长率
            wacc_delta:       WACC上下波动幅度 (默认±2%)

        Returns:
            {
                'base_wacc': float,       # 基准WACC
                'base_target': float,     # 基准目标价 (mid, mid)
                'grid': [[str,str,str],...],  # 3×3目标价矩阵
                'wacc_labels': [str,str,str], # WACC列标签
                'tg_labels': [str,str,str],   # TG行标签
                'unit': '元',
            }
        """
        base_wacc = wacc if wacc is not None else self.compute_wacc()

        tg_min, tg_mid, tg_max = terminal_range
        wacc_vals = [
            base_wacc - wacc_delta,
            base_wacc,
            base_wacc + wacc_delta,
        ]
        tg_vals = [tg_min, tg_mid, tg_max]

        grid: List[List[str]] = []
        base_target: Optional[float] = None

        for tg in tg_vals:
            row: List[str] = []
            for w in wacc_vals:
                if w <= tg:
                    row.append("N/A")
                    continue
                result = self.compute_dcf(
                    fcf_projections=fcf_projections,
                    terminal_fcf=terminal_fcf,
                    wacc=w,
                    net_debt=net_debt,
                    shares=shares,
                    terminal_growth=tg,
                )
                price = result['目标价_元']
                row.append(f"{price:.2f}")
                if tg == tg_mid and abs(w - base_wacc) < 1e-6:
                    base_target = price
            grid.append(row)

        return {
            'base_wacc': round(base_wacc * 100, 2),
            'base_target': base_target,
            'grid': grid,
            'wacc_labels': [f"{w*100:.1f}%" for w in wacc_vals],
            'tg_labels': [f"{t*100:.0f}%" for t in tg_vals],
            'unit': '元',
        }

    # dcf_sensitivity 别名，保留向后兼容
    def dcf_sensitivity(self, **kwargs) -> Dict[str, Any]:
        """dcf_sensitivity 别名，保留向后兼容"""
        # 参数名映射: base_fcf → fcf_projections
        if 'base_fcf' in kwargs:
            kwargs['fcf_projections'] = kwargs.pop('base_fcf')
        return self.sensitivity_analysis(**kwargs)

    # ============================================================
    # 概率加权 (复用ProbabilityWeightEngine逻辑)
    # ============================================================

    def apply_event_weights(
        self,
        base_value: float,
        events: List[Dict[str, Any]],
    ) -> float:
        """
        应用关键事件概率权重

        Args:
            base_value:  基础估值 (亿元)
            events:      事件列表
                         [{name, probability, magnitude, impact}, ...]

        Returns:
            调整后估值 (亿元)
        """
        from .probability_weight import ProbabilityWeightEngine
        engine = ProbabilityWeightEngine.from_config_list(events)
        return engine.apply(base_value)

    # ============================================================
    # 10年国债自动获取
    # ============================================================

    def fetch_risk_free_rate(self) -> float:
        """
        自动获取10年国债收益率作为无风险利率

        降级路径:
            DataFetcher (同花顺→东方财富→manual_data→2.5%)
        """
        try:
            from common.data.fetcher import DataFetcher
            fetcher = DataFetcher()
            result = fetcher.fetch_10y_treasury_yield()
            if result.is_success:
                return result.value
        except Exception:
            pass
        return 0.025  # 最终降级

    def calc_wacc_auto(self, beta: Optional[float] = None) -> float:
        """calc_wacc_auto: 自动获取无风险利率的WACC计算"""
        rf = self.fetch_risk_free_rate()
        b = beta if beta is not None else self.config.beta
        return self.compute_wacc(risk_free_rate=rf, beta=b)


# ============================================================
# 独立工具函数
# ============================================================

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
        ebitda:            EBITDA (亿元)
        tax_rate:          税率
        capex_ratio:        CAPEX占EBITDA比例
        working_cap_change: 营运资本变化 (亿元)

    Returns:
        FCF估算 (亿元，>=0)
    """
    nopat = ebitda * (1 - tax_rate)
    capex = ebitda * capex_ratio
    fcf = nopat - capex - working_cap_change
    return max(0.0, fcf)


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
        net_profit:        净利润 (亿元)
        depreciation:       折旧摊销 (亿元)
        capex:             资本支出 (亿元)
        working_cap_change: 营运资本变化 (亿元)

    Returns:
        FCF估算 (亿元，>=0)
    """
    fcf = net_profit + depreciation - capex - working_cap_change
    return max(0.0, fcf)


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    print("=== DiscountingEngine 测试 ===\n")

    engine = DiscountingEngine()

    # 1. WACC计算
    wacc = engine.compute_wacc(risk_free_rate=0.025, beta=1.2)
    print(f"1. WACC计算:")
    print(f"   无风险利率=2.5%, Beta=1.2, 市场溢价=5%")
    print(f"   WACC = {wacc*100:.2f}%")
    print()

    # 2. DCF估值
    print("2. DCF估值 (云南锗业简化版):")
    print("   假设5年FCF: [0.3, 0.5, 0.8, 1.2, 1.8]亿元")

    fcf_projections = [0.3, 0.5, 0.8, 1.2, 1.8]
    terminal_fcf = 1.8

    result = engine.compute_dcf(
        fcf_projections=fcf_projections,
        terminal_fcf=terminal_fcf,
        wacc=wacc,
        net_debt=0.0,
        shares=6.53,
        terminal_growth=0.03,
    )

    print(f"   WACC: {result['WACC_pct']}%")
    print(f"   预测期PV: {result['PV_sum_亿']}亿元")
    print(f"   终值PV: {result['PV_terminal_亿']}亿元")
    print(f"   企业价值: {result['企业价值_亿']}亿元")
    print(f"   股权价值: {result['股权价值_亿']}亿元")
    print(f"   目标价: {result['目标价_元']}元")
    if result['warnings']:
        for w in result['warnings']:
            print(f"   ⚠️ {w}")
    print()

    # 3. 敏感性分析
    print("3. Terminal Growth敏感性:")
    print(f"   WACC={wacc*100:.2f}%, TG=[2%, 3%, 4%]")

    sens = engine.sensitivity_analysis(
        fcf_projections=fcf_projections,
        terminal_fcf=terminal_fcf,
        wacc=wacc,
        net_debt=0.0,
        shares=6.53,
        terminal_range=(0.02, 0.03, 0.04),
    )

    print(f"   {'TG':>8} | {sens['wacc_labels'][0]:>8} | {sens['wacc_labels'][1]:>8} | {sens['wacc_labels'][2]:>8}")
    for i, tg_label in enumerate(sens['tg_labels']):
        row = sens['grid'][i]
        print(f"   {tg_label:>8} | {row[0]:>8} | {row[1]:>8} | {row[2]:>8}")
    print()

    # 4. 概率加权
    print("4. 概率加权 (1.6T认证):")
    base_cap = result['企业价值_亿']
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
