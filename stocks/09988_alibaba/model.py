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
    1. 核心商业 (淘宝/天猫) - PE×18-28x
    2. 云业务 (阿里云) - PE×30-45x
    3. 国际商业 - PS×0.8x
    4. 其他业务 (菜鸟/数字媒体/创新等) - 残值
    5. 控股权益 (蚂蚁集团+其他投资)

    FY2026 实际数据（官方业绩公告）:
    - 总营收: 10236.70亿 CNY（同口径+11%）
    - 非GAAP净利: 606.58亿 CNY（-62% YoY）
    - 自由现金流: -466.09亿 CNY（投入期）
    - 云智能: 1471亿 CNY（+18%），Q4单季416亿（+38%）
    - 国际商业: Q4接近盈亏平衡（亏损1.38亿）
    """

    # ── FY2026 实际参数 ─────────────────────────────────────
    TOTAL_NM_CNY = 607   # FY2026 实际非GAAP归母净利（亿元 CNY）
    SHARES = 191.9       # 亿H股

    # 核心商业: 总净利×87%，给予 PE 18-28x
    # FY2026经调整EBITA下降40%（闪购投入），但CMR同口径+8%证明平台仍健康
    CORE_NM_PCT = 0.87
    CORE_PE_MIN, CORE_PE_MAX = 18, 28

    # 云智能: FY2026全年云智能集团收入1471亿CNY, +18%
    # Q4单季416亿（+38%），AI相关收入359亿（连续11季度三位数增长）
    # 经调整EBITA利润率约9%（FY2025为7.4%），尚未恢复到此前的20%+水平
    CLOUD_REV_CNY = 1471   # 亿元 CNY (FY2026实际)
    CLOUD_NM_PCT = 0.09   # 净利率约9%（Q4利润率9%，随规模改善有望回归15-20%）
    CLOUD_PE_MIN, CLOUD_PE_MAX = 30, 45

    # 国际商业: FY2026Q4收入289亿+65亿=354亿，接近盈亏平衡
    INTL_REV_CNY = 1050    # FY2026全年估算（亿元 CNY）
    INTL_PS = 0.8          # Price/Sales（接近盈亏平衡，给0.8x）

    # 其他业务 (菜鸟/数字媒体/创新等): 残值
    # FY2026 All Others亏损扩大至428亿（千问App用户获取成本）
    OTHER_VALUE_CNY = 150  # 亿元 CNY (残值，下调)

    HOLDINGS = {
        "蚂蚁集团": 500,    # 亿元 CNY (33%×1500亿估值)
        "其他投资": 150,    # 亿元 CNY (联营上市公司权益)
    }

    def __init__(
        self,
        core_pe_min: int = 18,
        core_pe_max: int = 28,
        cloud_pe_min: int = 30,
        cloud_pe_max: int = 45,
        intl_ps: float = 0.8,
    ):
        """可调节SOTP参数"""
        self.CORE_PE_MIN = core_pe_min
        self.CORE_PE_MAX = core_pe_max
        self.CLOUD_PE_MIN = cloud_pe_min
        self.CLOUD_PE_MAX = cloud_pe_max
        self.INTL_PS = intl_ps

    def run(self, current_price: float = 143.1) -> Dict[str, Any]:
        """
        简化SOTP估值:
        - 核心商业: PE×净利
        - 云智能: PE×净利
        - 国际商业: PS×营收 (亏损业务)
        - 其他业务: 残值合计
        """
        hkd_rate = 0.92  # 1 HKD = 0.92 CNY

        divisions_result = []
        total_min = 0.0
        total_max = 0.0
        total_nm = 0.0

        # ── 核心商业 ──
        core_nm = round(self.TOTAL_NM_CNY * self.CORE_NM_PCT, 0)
        core_min = core_nm * self.CORE_PE_MIN
        core_max = core_nm * self.CORE_PE_MAX
        core_mid = (core_min + core_max) / 2
        total_min += core_min
        total_max += core_max
        total_nm += core_nm
        divisions_result.append({
            'name': '核心商业(淘宝/天猫)',
            '分部净利润_亿': core_nm,
            'PE区间': f"{self.CORE_PE_MIN}x~{self.CORE_PE_MAX}x",
            '分部市值_亿_区间': (core_min, core_max),
            '分部市值_亿_中枢': core_mid,
        })

        # ── 云智能 ──
        cloud_nm = round(self.CLOUD_REV_CNY * self.CLOUD_NM_PCT, 0)
        cloud_min = cloud_nm * self.CLOUD_PE_MIN
        cloud_max = cloud_nm * self.CLOUD_PE_MAX
        cloud_mid = (cloud_min + cloud_max) / 2
        total_min += cloud_min
        total_max += cloud_max
        total_nm += cloud_nm
        divisions_result.append({
            'name': '云智能(阿里云)',
            '分部净利润_亿': cloud_nm,
            'PE区间': f"{self.CLOUD_PE_MIN}x~{self.CLOUD_PE_MAX}x",
            '分部市值_亿_区间': (cloud_min, cloud_max),
            '分部市值_亿_中枢': cloud_mid,
        })

        # ── 国际商业(PS) ──
        intl_min = self.INTL_REV_CNY * self.INTL_PS
        intl_max = intl_min
        intl_mid = intl_min
        total_min += intl_min
        total_max += intl_max
        divisions_result.append({
            'name': '国际商业(Lazada/Trendyol)',
            '分部净利润_亿': 0,
            'PE区间': f"PS={self.INTL_PS}x",
            '分部市值_亿_区间': (intl_min, intl_max),
            '分部市值_亿_中枢': intl_mid,
        })

        # ── 其他业务: 残值 ──
        other_val = self.OTHER_VALUE_CNY
        total_min += other_val
        total_max += other_val
        divisions_result.append({
            'name': '其他(菜鸟/媒体/创新)',
            '分部净利润_亿': 0,
            'PE区间': '残值',
            '分部市值_亿_区间': (other_val, other_val),
            '分部市值_亿_中枢': other_val,
        })

        # ── 控股权益 ──
        holdings_value = sum(self.HOLDINGS.values())
        total_min += holdings_value
        total_max += holdings_value

        total_mid = (total_min + total_max) / 2

        # 转换为每股价格 (港元)
        shares = self.SHARES  # 亿H股
        sotp_min_hkd = total_min / shares / hkd_rate
        sotp_max_hkd = total_max / shares / hkd_rate
        sotp_mid_hkd = total_mid / shares / hkd_rate

        upside_min = (sotp_min_hkd / current_price - 1) * 100
        upside_max = (sotp_max_hkd / current_price - 1) * 100
        upside_mid = (sotp_mid_hkd / current_price - 1) * 100

        # FCF projections (亿元) — FY2026实际-466亿，恢复期预测
        fcf_projections = [-466, 150, 400, 600, 800]  # FY2026~FY2030E

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
            # FY2026关键数据
            'fy2026': {
                'revenue': 10237,
                'non_gaap_net_profit': 607,
                'fcf': -466,
                'cloud_revenue': 1471,
                'cloud_growth': 0.18,
                'cloud_q4_growth': 0.38,
            }
        }


# ========== DCF Model ==========

def run_dcf(
    rf: float = 0.035,
    beta: float = 0.9,
    tg: float = 0.04,
    fcf_proj: Optional[List[float]] = None,
    shares: float = 191.9,  # 亿H股
    net_debt: float = 0.0,
) -> Dict[str, Any]:
    """运行DCF估值"""
    engine = DiscountingEngine()

    # WACC
    wacc = engine.calc_wacc(rf, beta, market_premium=0.07)

    # FCF projections
    if fcf_proj is None:
        fcf_proj = [-466, 150, 400, 600, 800]  # FY2026E~FY2030E

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
        current_price = manual_data.get('market', {}).get('current_price', 143.1)

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
        hkd_rate = 0.92
        sotp_total_cny = sotp_result['总市值_亿_中枢']
        return_factor = 1.0
        for ev in events_config:
            if ev['impact'] == 'positive':
                return_factor += ev['probability'] * (ev['magnitude'] - 1)
            else:
                return_factor -= ev['probability'] * (1 - ev['magnitude'])
        weighted_total = sotp_total_cny * return_factor
        weighted_price_hkd = weighted_total / sotp_result['shares'] / hkd_rate
        sotp_result['加权目标价_元'] = weighted_price_hkd
    else:
        sotp_result['加权目标价_元'] = sotp_result['目标价_中枢_元']

    return sotp_result, dcf_result


# ========== CLI ==========

if __name__ == '__main__':
    print("=== 阿里巴巴(09988) 估值模型 v2.0 (FY2026财报更新) ===\n")

    sotp_r, dcf_r = run_valuation(current_price=143.1)

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