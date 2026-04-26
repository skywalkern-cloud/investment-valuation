#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
阿里巴巴(HK09988) 估值模型
SOTP + DCF + 概率加权

使用方式:
    from stocks.09988_alibaba import model
    sotp_result, dcf_result = model.run_valuation(rf=0.035, beta=0.9, tg=0.04)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Any, List, Tuple, Optional
import yaml

# Add workspace root to path
WORK_DIR = Path(__file__).parent.parent.parent
sys.path.insert(0, str(WORK_DIR))

from common.core.discounting_engine import DiscountingEngine

# ========== Config Loading ==========

def load_config():
    config_path = Path(__file__).parent / 'config.yaml'
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def load_manual_data():
    manual_path = Path(__file__).parent / 'manual_data.yaml'
    if manual_path.exists():
        with open(manual_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}

# ========== SOTP Model ==========

class AlibabaSOTP:
    """
    阿里巴巴SOTP (Sum-of-the-parts) 估值模型

    分部:
    1. 核心商业 (淘宝/天猫) - PE×14
    2. 云业务 (阿里云) - PE×20
    3. 国际商业 - PE×12
    4. 菜鸟物流 - PE×10
    5. 数字媒体 - PE×7
    6. 创新及其他 - PE×8
    7. 蚂蚁集团(成本法) - +约3300亿元
    """

    DIVISIONS = [
        # (name, net_profit_亿, pe_min, pe_max, pe_base)
        ("核心商业", 620, 10, 18, 14),
        ("云业务", 220, 15, 25, 20),
        ("国际商业", 80, 8, 15, 12),
        ("菜鸟物流", 16, 8, 15, 10),
        ("数字媒体娱乐", 6, 5, 10, 7),
        ("创新及其他", 20, 5, 10, 8),
    ]

    HOLDINGS = {
        "蚂蚁集团": 3300,    # 亿元 (33%×约10000亿估值)
    }

    def run(self, current_price: float = 95.0) -> Dict[str, Any]:
        divisions_result = []
        total_min = 0.0
        total_max = 0.0
        total_nm = 0.0

        for name, nm, pe_min, pe_max, pe_base in self.DIVISIONS:
            min_cap = nm * pe_min
            max_cap = nm * pe_max
            mid_cap = (min_cap + max_cap) / 2
            total_min += min_cap
            total_max += max_cap
            total_nm += nm

            divisions_result.append({
                'name': name,
                '分部净利润_亿': nm,
                'PE区间': f"{pe_min}x~{pe_max}x",
                'PE_base': pe_base,
                '分部市值_亿_区间': (min_cap, max_cap),
                '分部市值_亿_中枢': mid_cap,
            })

        # 加回控股权益
        holdings_value = sum(self.HOLDINGS.values())
        total_min += holdings_value
        total_max += holdings_value
        total_mid = (total_min + total_max) / 2

        # 转换为每股价格 (港元)
        # 假设1 HKD ≈ 0.92 CNY
        hkd_rate = 0.92
        shares = 47.5  # 亿股

        sotp_min_hkd = total_min / shares / hkd_rate
        sotp_max_hkd = total_max / shares / hkd_rate
        sotp_mid_hkd = total_mid / shares / hkd_rate

        upside_min = (sotp_min_hkd / current_price - 1) * 100
        upside_max = (sotp_max_hkd / current_price - 1) * 100
        upside_mid = (sotp_mid_hkd / current_price - 1) * 100

        # FCF projections (亿元)
        fcf_projections = [620, 680, 750, 830, 920]

        return {
            '分部列表': divisions_result,
            '控股权益_亿': holdings_value,
            '总市值_亿_区间': (total_min, total_max),
            '总市值_亿_中枢': total_mid,
            '目标价_区间_元': (sotp_min_hkd, sotp_max_hkd),
            '目标价_中枢_元': sotp_mid_hkd,
            '当前价_元': current_price,
            '上涨空间_区间_%': (upside_min, upside_max),
            '上涨空间_中枢_%': upside_mid,
            'shares': shares,
            'net_debt': 0,
            'fcf_projections': fcf_projections,
        }


# ========== DCF Model ==========

def run_dcf(
    rf: float = 0.035,
    beta: float = 0.9,
    tg: float = 0.04,
    fcf_proj: Optional[List[float]] = None,
    shares: float = 47.5,
    net_debt: float = 0.0,
) -> Dict[str, Any]:
    """运行DCF估值"""
    engine = DiscountingEngine()

    # WACC
    wacc = engine.calc_wacc(rf, beta, market_premium=0.07)

    # FCF projections
    if fcf_proj is None:
        fcf_proj = [620, 680, 750, 830, 920]

    # Terminal FCF
    terminal_fcf = fcf_proj[-1]

    result = engine.dcf_fcf(
        fcf_projections=fcf_proj,
        terminal_fcf=terminal_fcf,
        wacc=wacc,
        net_debt=net_debt,
        shares=shares,
        terminal_growth=tg,
    )

    # Convert CNY to HKD
    hkd_rate = 0.92
    dcf_price_hkd = result['目标价_元'] / hkd_rate

    return {
        'wacc': wacc,
        'wacc_pct': result['WACC'],
        'terminal_growth': tg,
        'PV_sum_亿': result['PV_sum_亿'],
        'PV_terminal_亿': result['PV_terminal_亿'],
        '企业价值_亿': result['企业价值_亿'],
        '股权价值_亿': result['股权价值_亿'],
        '目标价_元': dcf_price_hkd,
        'fcf_projections': fcf_proj,
        'shares': shares,
        'net_debt': net_debt,
    }


# ========== Probability Weighted ==========

def apply_events(base_value: float, events: List[Dict]) -> float:
    """应用关键事件概率权重"""
    engine = DiscountingEngine()
    return engine.apply_event_weights(base_value, events)


# ========== Main Entry Point ==========

def run_valuation(
    rf: float = 0.035,
    beta: float = 0.9,
    tg: float = 0.04,
    current_price: Optional[float] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    运行完整阿里巴巴估值

    Returns:
        (sotp_result, dcf_result)
    """
    config = load_config()
    manual_data = load_manual_data()

    if current_price is None:
        current_price = manual_data.get('market', {}).get('current_price', 95.0)

    # SOTP
    sotp = AlibabaSOTP()
    sotp_result = sotp.run(current_price=current_price)
    sotp_result['当前价_元'] = current_price

    # DCF
    dcf_result = run_dcf(
        rf=rf, beta=beta, tg=tg,
        fcf_proj=sotp_result['fcf_projections'],
        shares=sotp_result['shares'],
        net_debt=sotp_result['net_debt'],
    )

    # Probability weighted
    events_config = config.get('events', [])
    if events_config:
        # Use SOTP mid value (in CNY) as base
        hkd_rate = 0.92
        sotp_mid_cny = sotp_result['目标价_中枢_元'] * hkd_rate
        sotp_total_mid_cny = sotp_mid_cny * sotp_result['shares']

        weighted_cny = apply_events(sotp_total_mid_cny, events_config)
        weighted_price_hkd = weighted_cny / sotp_result['shares'] / hkd_rate
        sotp_result['加权目标价_元'] = weighted_price_hkd
    else:
        sotp_result['加权目标价_元'] = sotp_result['目标价_中枢_元']

    return sotp_result, dcf_result


# ========== CLI ==========

if __name__ == '__main__':
    print("=== 阿里巴巴(09988) 估值模型 v1.0 ===\n")

    sotp_r, dcf_r = run_valuation()

    print(f"📊 SOTP分部估值:")
    for div in sotp_r['分部列表']:
        print(f"  {div['name']}: 净利={div['分部净利润_亿']:.0f}亿 | PE={div['PE区间']} | 市值={div['分部市值_亿_区间'][0]:.0f}~{div['分部市值_亿_区间'][1]:.0f}亿")

    print(f"\n📌 SOTP合计: {sotp_r['总市值_亿_中枢']:.0f}亿元")
    print(f"📌 控股权益(蚂蚁等): {sotp_r['控股权益_亿']:.0f}亿元")
    print(f"\n🎯 SOTP目标价: {sotp_r['目标价_区间_元'][0]:.1f}~{sotp_r['目标价_区间_元'][1]:.1f}港元 (中枢{sotp_r['目标价_中枢_元']:.1f}港元)")
    print(f"🎯 当前价: {sotp_r['当前价_元']:.1f}港元")
    print(f"🎯 上涨空间: {sotp_r['上涨空间_中枢_%']:+.0f}%")

    print(f"\n📈 DCF估值:")
    print(f"   WACC: {dcf_r['wacc_pct']:.1f}%")
    print(f"   TG: {dcf_r['terminal_growth']*100:.0f}%")
    print(f"   5年FCF: {[f'{x:.0f}亿' for x in dcf_r['fcf_projections']]}")
    print(f"   企业价值: {dcf_r['企业价值_亿']:.0f}亿元")
    print(f"   DCF目标价: {dcf_r['目标价_元']:.1f}港元")

    if '加权目标价_元' in sotp_r:
        print(f"\n🎯 概率加权目标价: {sotp_r['加权目标价_元']:.1f}港元")

    print(f"\n{'='*50}")
    print(f"综合: SOTP中枢={sotp_r['目标价_中枢_元']:.1f} | DCF={dcf_r['目标价_元']:.1f} | 当前={sotp_r['当前价_元']:.1f}")
