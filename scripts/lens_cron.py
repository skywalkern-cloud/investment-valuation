#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝思科技(300433) cron任务
每天16:30执行，获取最新股价+估值结果写入历史JSON
"""

import sys, os, json, warnings
from datetime import datetime, date

warnings.filterwarnings('ignore')

# 路径设置
REPO_ROOT = '/Users/vincentnie/.openclaw/workspace-valuation'
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, f'{REPO_ROOT}/stocks/300433_lens')

from model import LensSOTP
from common.core.probability_weight import ProbabilityWeightEngine
from common.core.discounting_engine import DiscountingEngine
from common.stock_api import get_a_stock_quote


def get_live_price() -> float:
    """获取蓝思科技实时股价"""
    try:
        quotes = get_a_stock_quote(['300433'])
        if quotes and quotes[0].get('price', 0) > 0:
            return float(quotes[0]['price'])
    except:
        pass
    try:
        import akshare as ak
        df = ak.stock_individual_spot_xq(symbol='SZ300433')
        data = {row['item']: row['value'] for _, row in df.iterrows()}
        price = float(data.get('现价', 0))
        return price if price > 0 else 25.72
    except:
        return 25.72


def load_config():
    """加载config.yaml"""
    import yaml
    config_path = f'{REPO_ROOT}/stocks/300433_lens/config.yaml'
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def run_lens_valuation():
    """执行蓝思科技估值"""
    today = date.today()
    print(f"=== 蓝思科技(300433) 估值任务 {today} ===")
    
    # 获取实时股价
    live_price = get_live_price()
    print(f"实时股价: {live_price}元")
    
    # 加载配置
    config = load_config()
    shares = config['meta']['total_shares']  # 52.79亿股
    
    # WACC参数从config读取
    wacc_cfg = config.get('methodology_notes', {}).get('wacc', {})
    rf_rate = wacc_cfg.get('risk_free_rate', {}).get('fallback', 0.030)
    beta_val = wacc_cfg.get('beta', {}).get('value', 1.10)
    market_prem = wacc_cfg.get('market_premium', 0.07)
    tg_val = config.get('methodology_notes', {}).get('terminal_growth', {}).get('value', 0.03)
    
    # SOTP估值（从config加载参数）
    sotp = LensSOTP.from_config()
    sotp_result = sotp.calculate(live_price)
    sotp_detail = sotp.get_sotp_detail()
    
    print(f"\n【SOTP估值结果】")
    print(f"  SOTP总市值: {sotp_result['sotp_cap_base']}亿（区间{sotp_result['sotp_cap_min']}-{sotp_result['sotp_cap_max']}亿）")
    print(f"  目标价: {sotp_result['target_base']}元（区间{sotp_result['target_min']}-{sotp_result['target_max']}元）")
    print(f"  上涨空间: {sotp_result['upside_base']}%")
    print(f"\n  各业务线:")
    for seg in sotp_detail['segments']:
        print(f"    {seg['name']}: 净利{seg['net_profit']}亿 × PE{seg['pe_range']} = {seg['cap']}亿({seg['pct']})")
    
    # WACC + DCF（WACC参数从config读取）
    engine = DiscountingEngine()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wacc = engine.calc_wacc(risk_free_rate=rf_rate, beta=beta_val,
                                market_premium=market_prem, auto_refresh_beta=True)
    
    # DCF: 基于总净利估算FCF
    total_nm = sotp_result['total_net_profit']  # 43.7亿
    growth_rates = [0.15, 0.18, 0.20, 0.18, 0.15]
    fcf_proj = [total_nm * (1 + g) ** (i + 1) * 0.85 for i, g in enumerate(growth_rates)]
    fcf_proj = [round(x, 3) for x in fcf_proj]
    
    dcf_result = engine.compute_dcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1],
        wacc=wacc,
        net_debt=0.0,
        shares=shares,
        terminal_growth=tg_val,
    )
    dcf_price = dcf_result['目标价_元']
    print(f"\n【DCF估值结果】")
    print(f"  WACC: {wacc:.3f}")
    print(f"  DCF目标价: {dcf_price:.1f}元")
    
    # 概率加权
    events = config.get('events', [])
    weighted_price = None
    weighted_detail = {}
    if events:
        pw = ProbabilityWeightEngine.from_config_list(events)
        sotp_cap_base = sotp_result['sotp_cap_base']
        weighted_cap = pw.apply(sotp_cap_base)
        weighted_price = weighted_cap / shares
        
        print(f"\n【概率加权估值】")
        print(f"  基准SOTP市值: {sotp_cap_base}亿")
        print(f"  综合乘数: {weighted_cap/sotp_cap_base:.3f}x")
        for ev in events:
            sign = '+' if ev['impact'] == 'positive' else '-'
            print(f"    {sign} {ev['name']}: {ev['probability']*100:.0f}% × {ev['magnitude']}x")
        print(f"  概率加权市值: {weighted_cap:.0f}亿")
        print(f"  概率加权目标价: {weighted_price:.1f}元")
    
    # 汇总
    result = {
        'date': str(today),
        'stock_code': '300433',
        'stock_name': '蓝思科技',
        'live_price': live_price,
        'current_market_cap': round(live_price * shares, 1),
        'sotp': {
            'sotp_cap_base': sotp_result['sotp_cap_base'],
            'sotp_cap_min': sotp_result['sotp_cap_min'],
            'sotp_cap_max': sotp_result['sotp_cap_max'],
            'target_price': sotp_result['target_base'],
            'target_price_min': sotp_result['target_min'],
            'target_price_max': sotp_result['target_max'],
            'upside_base': sotp_result['upside_base'],
            'upside_min': sotp_result['upside_min'],
            'upside_max': sotp_result['upside_max'],
            'segments': sotp_detail['segments'],
        },
        'dcf': {
            'target_price': round(dcf_price, 1),
            'wacc': round(wacc, 3),
        },
        'weighted_price': round(weighted_price, 1) if weighted_price else None,
    }
    
    return result


if __name__ == '__main__':
    result = run_lens_valuation()
    print(f"\n【最终结果】")
    print(f"  SOTP目标价: {result['sotp']['target_price']}元")
    print(f"  DCF目标价: {result['dcf']['target_price']}元")
    if result['weighted_price']:
        print(f"  概率加权目标价: {result['weighted_price']}元")