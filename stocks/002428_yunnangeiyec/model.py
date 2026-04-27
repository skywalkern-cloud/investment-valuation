#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云南锗业(002428) 估值模型入口

通用动态估值系统 v1.2

使用方式:
    python3 stocks/002428_yunnangeiyec/model.py
    python3 stocks/002428_yunnangeiyec/model.py --sensitivity
    python3 stocks/002428_yunnangeiyec/model.py --dcf  # 输出DCF+概率加权结果
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import warnings
warnings.filterwarnings('ignore')

import argparse
import yaml
from datetime import datetime

from common.core.financial_foundation import FinancialFoundation
from common.core.sotp_engine import SOTPEngine
from common.core.discounting_engine import DiscountingEngine
from common.core.probability_weight import ProbabilityWeightEngine
from common.core.sensitivity_runner import run_sensitivity_analysis, SensitivityConfig
from common.data.fetcher import DataFetcher


def load_config():
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_manual_data():
    manual_path = os.path.join(os.path.dirname(__file__), 'manual_data.yaml')
    if os.path.exists(manual_path):
        with open(manual_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def merge_manual_data(config, manual_data, auto_vars=None):
    """将config和manual_data合并，自动展开auto_variables映射"""
    auto_vars = auto_vars or {}
    merged = {}
    for plugin_cfg in config.get('plugins', []):
        name = plugin_cfg['name']
        div_data = {}
        # 1. 从plugin defaults
        div_data.update(plugin_cfg.get('defaults', {}))
        # 2. 从manual_data的标的名section
        if name in manual_data:
            div_data.update(manual_data[name])
        elif plugin_cfg['type'] in manual_data:
            div_data.update(manual_data[plugin_cfg['type']])
        # 3. 展开auto_variables映射 (商品售价=germanium_price → 17500)
        for var_name, source_key in plugin_cfg.get('auto_variables', {}).items():
            if source_key in auto_vars:
                div_data[var_name] = auto_vars[source_key]
        merged[name] = div_data
    return merged


def check_beta_expiry(config):
    """检查beta是否过期"""
    engine = DiscountingEngine()
    beta_info = config.get('methodology_notes', {}).get('wacc', {}).get('beta', {})
    engine.config.beta = beta_info.get('value', 1.2)
    engine.config.beta_last_updated = beta_info.get('last_updated', '')
    expired, days = engine.beta_expired(max_days=beta_info.get('expiry_days', 90))
    if expired:
        print(f"⚠️  WARNING: beta已过期{days}天，请更新!")
        print(f"   来源: {beta_info.get('source', 'N/A')}")
    return expired


def estimate_fcf_for_dcf(sotp_total_nm, share=0.15, capex_ratio=0.10):
    """
    从分部净利估算5年FCF (简化)

    假设:
    - 净利 ≈ FCF × (1-税率) + CAPEX
    - 取净利的85%作为FCF近似(考虑折旧摊销回加)
    """
    # 第1-3年: 净利增长假设
    projections = []
    base = sotp_total_nm
    growth_rates = [0.20, 0.25, 0.30, 0.25, 0.20]  # 逐年增长率
    for i, g in enumerate(growth_rates):
        projected = base * (1 + g) ** (i + 1)
        # FCF ≈ 净利 × 0.85
        fcf = projected * (1 - share)
        projections.append(round(fcf, 3))
    return projections


def run_full_model(show_details=True):
    """运行完整估值模型 (SOTP + DCF + 概率加权)"""
    print(f"=== 云南锗业(002428) 估值模型 v1.2 {datetime.now().strftime('%Y-%m-%d')} ===\n")

    config = load_config()
    manual_data = load_manual_data()
    meta = config['meta']

    # 1. 检查beta过期
    check_beta_expiry(config)

    # 2. 数据获取
    print("📊 获取财务数据...")
    fetcher = DataFetcher(manual_data=manual_data)
    ff = FinancialFoundation.from_akshare(meta['stock_code'])
    if ff.revenue > 0:
        print(f"  营收: {ff.revenue:.2f}亿 | 净利润: {ff.net_profit:.3f}亿")
        print(f"  EPS: {ff.eps}元 | BPS: {ff.bps}元")
    else:
        ff.revenue = manual_data.get('financials', {}).get('revenue', 0)
        ff.net_profit = manual_data.get('financials', {}).get('net_profit', 0)

    print()

    # 3. SOTP分部估值
    print("🧮 SOTP分部估值...")
    sotp = SOTPEngine()
    for plugin_cfg in config.get('plugins', []):
        sotp.add_division(
            plugin_type=plugin_cfg['type'],
            name=plugin_cfg['name'],
            weight=plugin_cfg.get('weight', 0.5),
            pe_min=plugin_cfg.get('pe_min', 15),
            pe_max=plugin_cfg.get('pe_max', 65),
            pe_base=plugin_cfg.get('pe_base', 30),
        )

    auto_vars = {}
    auto_vars['indium_price'] = manual_data.get('indium_price', 4350)
    auto_vars['germanium_price'] = manual_data.get('germanium_price', 17500)
    merged = merge_manual_data(config, manual_data, auto_vars)
    sotp_result = sotp.run(ff, auto_vars, merged)

    if show_details:
        print(f"  当前价: {sotp_result['当前价_元']}元")
        print(f"  目标价: {sotp_result['目标价_区间_元'][0]:.1f}~{sotp_result['目标价_区间_元'][1]:.1f}元 (中枢{sotp_result['目标价_中枢_元']:.1f}元)")
        print(f"  空间: {sotp_result['上涨空间_区间_%'][0]:+.0f}%~{sotp_result['上涨空间_区间_%'][1]:+.0f}%")
        print()
        for div in sotp_result['分部列表']:
            print(f"  {div['name']}: 净利={div['分部净利润_亿']:.3f}亿 | PE={div['PE区间']} | 市值={div['分部市值_亿_区间']}亿")

    # 4. DCF估值
    print()
    print("📈 DCF折现估值...")
    engine = DiscountingEngine()

    # WACC
    rf = config.get('methodology_notes', {}).get('wacc', {}).get('risk_free_rate', {})
    rf_auto = rf.get('auto', True)
    rf_fallback = rf.get('fallback', 0.025)
    # 自动获取10年国债收益率 (fetch_risk_free_rate 实现了P0功能)
    if rf_auto:
        risk_free = engine.fetch_risk_free_rate()
        print(f"  ⚡ Rf自动获取: {risk_free*100:.4f}% (来源: 10年国债)")
    else:
        risk_free = rf_fallback

    beta_val = config.get('methodology_notes', {}).get('wacc', {}).get('beta', {}).get('value', 1.2)
    beta_last_updated = config.get('methodology_notes', {}).get('wacc', {}).get('beta', {}).get('last_updated', '')
    mp = config.get('methodology_notes', {}).get('wacc', {}).get('market_premium', 0.05)
    wacc = engine.calc_wacc(risk_free_rate=risk_free, beta=beta_val, market_premium=mp, auto_refresh_beta=True)
    if engine.config.beta_last_updated and engine.config.beta_last_updated != beta_last_updated:
        print(f"  ⚡ Beta已自动刷新: {engine.config.beta:.2f} (更新于 {engine.config.beta_last_updated})")
    print(f"  WACC: {wacc*100:.2f}% (Rf={risk_free*100:.1f}%, β={engine.config.beta:.2f})")

    # Terminal Growth
    tg_config = config.get('methodology_notes', {}).get('terminal_growth', {})
    tg = tg_config.get('value', 0.03)
    print(f"  Terminal Growth: {tg*100:.0f}% ({tg_config.get('assumption', 'N/A')})")

    # 估算5年FCF
    sotp_nm = sotp_result['总净利润_亿']
    fcf_projections = estimate_fcf_for_dcf(sotp_nm)
    print(f"  5年FCF预测: {[f'{x:.2f}亿' for x in fcf_projections]}")

    # DCF计算
    dcf_result = engine.dcf_fcf(
        fcf_projections=fcf_projections,
        terminal_fcf=fcf_projections[-1],
        wacc=wacc,
        net_debt=0,
        shares=meta['total_shares'],
        terminal_growth=tg,
    )
    print(f"  预测期PV: {dcf_result['PV_sum_亿']}亿 | 终值PV: {dcf_result['PV_terminal_亿']}亿")
    print(f"  DCF目标价: {dcf_result['目标价_元']}元")
    print(f"  企业价值: {dcf_result['企业价值_亿']}亿")

    # TG敏感性
    print()
    print("📊 Terminal Growth敏感性:")
    s = engine.dcf_sensitivity(
        base_fcf=fcf_projections,
        terminal_fcf=fcf_projections[-1],
        wacc=wacc,
        net_debt=0,
        shares=meta['total_shares'],
    )
    tg_vals = [f"{t*100:.0f}%" for t in (0.02, 0.03, 0.04)]
    g_mid = s["grid"][1][1]
    print(f"  TG=2%/3%/4%: {s['grid'][0][1]} / {g_mid} / {s['grid'][2][1]} 元")

    # 5. 概率加权
    print()
    print("🎯 概率加权...")
    events_config = config.get('events', [])
    weighted_cap = None
    if events_config:
        pw = ProbabilityWeightEngine.from_config_list(events_config)
        base_cap = dcf_result['股权价值_亿']
        weighted_cap = pw.apply(base_cap)
        bd = pw.breakdown(base_cap)
        print(f"  基础市值(DCF): {base_cap:.1f}亿 → 加权市值: {weighted_cap:.1f}亿 ({bd['upside_pct']:+.1f}%)")
        for ev in bd['events']:
            d = "↑" if ev['impact'] == 'positive' else "↓"
            print(f"  {ev['name']}: {ev['probability']*100:.0f}%概率 {d}{abs(ev['magnitude']-1)*100:.0f}%")
        weighted_price = weighted_cap / meta['total_shares']
        print(f"  加权目标价: {weighted_price:.1f}元")

    # 6. 端到端敏感性分析
    print()
    print("🔬 端到端敏感性分析...")
    sa_cfg = config.get('sensitivity_analysis', {})
    sotp_params = sa_cfg.get('sotp_params', {
        '商品售价': [12000, 15000, 17500, 20000, 25000],
        '良率': [0.80, 0.85, 0.88, 0.90],
    })
    dcf_wacc_range = tuple(sa_cfg.get('dcf_wacc_range', [0.06, 0.08, 0.10]))
    dcf_tg_range = tuple(sa_cfg.get('dcf_tg_range', [0.02, 0.03, 0.04]))

    cfg = SensitivityConfig(
        sotp_params=sotp_params,
        dcf_wacc_range=dcf_wacc_range,
        dcf_tg_range=dcf_tg_range,
        shares=meta['total_shares'],
    )
    try:
        sa_result = run_sensitivity_analysis(
            financials=ff,
            manual_data=merged,
            config=cfg,
            sotp_engine=sotp,
            dcf_engine=engine,
            fcf_projections=fcf_projections,
        )
        print(f"  SOTP区间: {sa_result['sotp_range'][0]:.1f}~{sa_result['sotp_range'][1]:.1f}元")
        print(f"  DCF区间: {sa_result['dcf_range'][0]:.1f}~{sa_result['dcf_range'][1]:.1f}元")
        print(f"  综合区间: {sa_result['combined_range'][0]:.1f}~{sa_result['combined_range'][1]:.1f}元")
        print(f"  推荐中枢: {sa_result['recommended_target']:.1f}元")
        print(f"  推荐区间: {sa_result['recommended_range'][0]:.1f}~{sa_result['recommended_range'][1]:.1f}元")
    except Exception as e:
        print(f"  ⚠️ 敏感性分析失败: {e}")
        sa_result = None

    # 6. 综合结论
    print()
    print("=" * 50)
    print("【综合估值结论】")
    print("=" * 50)
    sotp_price = sotp_result['目标价_中枢_元']
    dcf_price = dcf_result['目标价_元']
    if events_config:
        final_price = weighted_price
    else:
        final_price = (sotp_price + dcf_price) / 2

    print(f"  SOTP: {sotp_price:.1f}元 ({sotp_result['上涨空间_中枢_%']:+.0f}%)")
    print(f"  DCF: {dcf_price:.1f}元")
    if events_config:
        print(f"  概率加权: {weighted_price:.1f}元")
    print(f"  当前价: {sotp_result['当前价_元']}元")
    print(f"  综合目标价: {final_price:.1f}~{max(sotp_result['目标价_区间_元'][1], dcf_price):.1f}元")

    return {
        'sotp': sotp_result,
        'dcf': dcf_result,
        'weighted': weighted_cap if events_config else None,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='云南锗业估值模型')
    parser.add_argument('--sensitivity', action='store_true', help='SOTP敏感性分析')
    parser.add_argument('--dcf', action='store_true', help='输出DCF+概率加权')
    args = parser.parse_args()

    if args.sensitivity:
        print("=== SOTP敏感性分析 ===")
        config = load_config()
        manual_data = load_manual_data()
        meta = config['meta']
        sotp = SOTPEngine()
        for plugin_cfg in config.get('plugins', []):
            sotp.add_division(
                plugin_type=plugin_cfg['type'],
                name=plugin_cfg['name'],
                weight=plugin_cfg.get('weight', 0.5),
                pe_min=plugin_cfg.get('pe_min', 15),
                pe_max=plugin_cfg.get('pe_max', 65),
                pe_base=plugin_cfg.get('pe_base', 30),
            )
        ff = FinancialFoundation.from_akshare(meta['stock_code'])
        auto_vars = {
            'indium_price': manual_data.get('indium_price', 4350),
            'germanium_price': manual_data.get('germanium_price', 17500),
        }
        merged = merge_manual_data(config, manual_data, auto_vars)

        print("\n锗价敏感性:")
        for price in [12000, 15000, 17500, 20000, 25000]:
            test = merged.copy()
            test['传统锗锭业务']['商品售价'] = price
            r = sotp.run(ff, auto_vars, test)
            print(f"  锗价={price:>6} → 目标价={r['目标价_中枢_元']:.1f}元 ({r['上涨空间_中枢_%']:+.0f}%)")

        print("\n认证进度敏感性:")
        for cert in [30, 50, 60, 70, 80, 100]:
            test = merged.copy()
            test['半导体分部']['认证进度'] = cert
            r = sotp.run(ff, auto_vars, test)
            print(f"  认证={cert:>3d}% → 目标价={r['目标价_中枢_元']:.1f}元 ({r['上涨空间_中枢_%']:+.0f}%)")
    else:
        run_full_model()
