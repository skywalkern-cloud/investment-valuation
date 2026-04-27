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

    # ── 简化SOTP参数 ─────────────────────────────────────────
    # 估值单位: 亿元 CNY (转换为HKD除以 hkd_rate)
    # 数据来源:
    #   - FY2025年报 (年营收~9600亿RMB, 年净利~800亿RMB)
    #   - akshare TTM指标 (总股本191.9亿H股, TTM营收9963亿HKD)
    #   - FY2026一致预期 ~1100亿 CNY 净利 (non-GAAP)
    TOTAL_NM_CNY = 1100   # FY2026E 归母净利 (亿元 CNY)
    SHARES = 191.9        # 亿H股 (akshare HK总股本)

    # 核心商业: 总净利×80%, 成熟业务给予 18-28x PE
    CORE_NM_PCT = 0.80
    CORE_PE_MIN, CORE_PE_MAX = 18, 28

    # 云智能: FY2026E营收~1300亿CNY, 净利率~22%, 给予 30-45x PE
    CLOUD_REV_CNY = 1300   # 亿元 CNY (FY2026E)
    CLOUD_NM_PCT = 0.22   # 净利率
    CLOUD_PE_MIN, CLOUD_PE_MAX = 30, 45

    # 国际商业: Lazada/Trendyol等 FY2026E营收~1000亿CNY, 仍亏损
    #           给予 0.8x PS (参考 Shopify 1.5x, 考虑亏损折价)
    INTL_REV_CNY = 1000    # 亿元 CNY (FY2026E)
    INTL_PS = 0.8          # Price/Sales

    # 其他业务 (菜鸟/数字媒体/创新等): 合计约300亿CNY市值
    OTHER_VALUE_CNY = 300  # 亿元 CNY (残值)

    DIVISIONS = [
        # (name, net_profit_亿, pe_min, pe_max, pe_base)
        # 核心商业：FY2026E 1100亿×80%=880亿 CNY, PE 18-28x
        ("核心商业", round(TOTAL_NM_CNY * CORE_NM_PCT, 0), CORE_PE_MIN, CORE_PE_MAX, 23),
        # 阿里云：FY2026E 1300亿×22%=286亿 CNY, PE 30-45x
        ("云智能", round(CLOUD_REV_CNY * CLOUD_NM_PCT, 0), CLOUD_PE_MIN, CLOUD_PE_MAX, 38),
        # 国际商业：PS 0.8x (亏损业务, 用PS而非PE)
        ("国际商业(PS)", 0, 0, 0, 0),   # PS模式, 单独处理
        # 其他业务
        ("其他业务", 0, 0, 0, 0),
    ]

    HOLDINGS = {
        "蚂蚁集团": 500,    # 亿元 CNY (33%×1500亿估值, 保守)
    }

    def __init__(
        self,
        core_pe_min: int = 18,
        core_pe_max: int = 28,
        cloud_pe_min: int = 30,
        cloud_pe_max: int = 45,
        intl_ps: float = 0.8,
        other_value: float = 300.0,
    ):
        """可调节SOTP参数"""
        self.CORE_PE_MIN = core_pe_min
        self.CORE_PE_MAX = core_pe_max
        self.CLOUD_PE_MIN = cloud_pe_min
        self.CLOUD_PE_MAX = cloud_pe_max
        self.INTL_PS = intl_ps
        self.OTHER_VALUE_CNY = other_value

    def run(self, current_price: float = 95.0) -> Dict[str, Any]:
        """
        简化SOTP估值:
        - 核心商业: PE×净利 (可调PE区间)
        - 云智能: PE×净利 (可调PE区间)
        - 国际商业: PS×营收 (亏损业务, 可调PS)
        - 其他业务: 固定残值 (可调)
        """
        hkd_rate = 0.92  # 1 HKD ≈ 0.92 CNY
        shares = self.SHARES  # 亿H股

        divisions_result = []
        total_min = 0.0
        total_max = 0.0
        total_nm = 0.0

        # PE maps: use instance-level (adjustable) values
        pe_map = {
            "核心商业": (self.CORE_PE_MIN, self.CORE_PE_MAX),
            "云智能":   (self.CLOUD_PE_MIN, self.CLOUD_PE_MAX),
        }

        for name, nm, _, _, _ in self.DIVISIONS:
            if name in ("国际商业(PS)", "其他业务"):
                continue  # handled separately below
            pe_min_v, pe_max_v = pe_map.get(name, (10, 20))
            min_cap = nm * pe_min_v
            max_cap = nm * pe_max_v
            divisions_result.append({
                'name': name,
                '分部净利润_亿': nm,
                'PE区间': f"{pe_min_v}x~{pe_max_v}x",
                'PE_base': (pe_min_v + pe_max_v) / 2,
                '分部市值_亿_区间': (min_cap, max_cap),
                '分部市值_亿_中枢': (min_cap + max_cap) / 2,
            })
            total_min += min_cap
            total_max += max_cap
            total_nm += nm

        # 国际商业: PS×营收
        intl_val = self.INTL_REV_CNY * self.INTL_PS
        divisions_result.append({
            'name': '国际商业',
            '分部净利润_亿': 0,
            'PE区间': f"PS={self.INTL_PS}x",
            'PE_base': self.INTL_PS,
            '分部市值_亿_区间': (intl_val, intl_val),
            '分部市值_亿_中枢': intl_val,
        })
        total_min += intl_val
        total_max += intl_val

        # 其他业务: 残值
        other_val = self.OTHER_VALUE_CNY
        divisions_result.append({
            'name': '其他(菜鸟/媒体/创新)',
            '分部净利润_亿': 0,
            'PE区间': '残值',
            'PE_base': 0,
            '分部市值_亿_区间': (other_val, other_val),
            '分部市值_亿_中枢': other_val,
        })
        total_min += other_val
        total_max += other_val

        # 控股权益
        holdings_value = sum(self.HOLDINGS.values())
        total_min += holdings_value
        total_max += holdings_value
        total_mid = (total_min + total_max) / 2

        sotp_min_hkd = total_min / shares / hkd_rate
        sotp_max_hkd = total_max / shares / hkd_rate
        sotp_mid_hkd = (sotp_min_hkd + sotp_max_hkd) / 2

        upside_min = (sotp_min_hkd / current_price - 1) * 100
        upside_max = (sotp_max_hkd / current_price - 1) * 100
        upside_mid = (sotp_mid_hkd / current_price - 1) * 100

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
            'fcf_projections': [700, 780, 870, 970, 1080],
        }

# ========== DCF Model ==========

def run_dcf(
    rf: float = 0.035,
    beta: float = 0.9,
    tg: float = 0.04,
    fcf_proj: Optional[List[float]] = None,
    shares: float = 191.9,  # 亿H股 (akshare)
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
    # 可调节SOTP参数
    core_pe_min: int = 18,
    core_pe_max: int = 28,
    cloud_pe_min: int = 30,
    cloud_pe_max: int = 45,
    intl_ps: float = 0.8,
    other_value: float = 300.0,
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
    sotp = AlibabaSOTP(
        core_pe_min=core_pe_min,
        core_pe_max=core_pe_max,
        cloud_pe_min=cloud_pe_min,
        cloud_pe_max=cloud_pe_max,
        intl_ps=intl_ps,
        other_value=other_value,
    )
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
