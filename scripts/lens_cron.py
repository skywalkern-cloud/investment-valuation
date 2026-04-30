#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝思科技(HK06613) cron任务
每天16:30执行，获取最新港股股价+估值结果
"""

import sys, os, json, warnings
from datetime import datetime, date

warnings.filterwarnings('ignore')

REPO_ROOT = '/Users/vincentnie/.openclaw/workspace-valuation'
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, f'{REPO_ROOT}/stocks/300433_lens')

from model import LensHK_SOTP
from common.core.probability_weight import ProbabilityWeightEngine
from common.core.discounting_engine import DiscountingEngine


def get_hk_price(code: str = '06613') -> float:
    """获取港股蓝思科技实时股价（HKD）"""
    try:
        import requests
        resp = requests.get(f'https://qt.gtimg.cn/q=hk{code}', timeout=10)
        resp.encoding = 'gbk'
        for line in resp.text.split('\n'):
            if f'hk{code}' in line:
                parts = line.split('~')
                return float(parts[3]) if parts[3] else None
    except:
        pass
    return 16.70  # fallback


def load_config():
    """加载config.yaml"""
    import yaml
    config_path = f'{REPO_ROOT}/stocks/300433_lens/config.yaml'
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def run_lens_hk_valuation():
    """执行蓝思科技港股估值"""
    today = date.today()
    print(f"=== 蓝思科技(HK06613) 估值任务 {today} ===")
    
    # 获取港股实时股价
    live_price = get_hk_price('06613')
    print(f"港股实时股价: {live_price} HKD ({live_price*0.92:.2f} CNY)")
    
    # 加载配置
    config = load_config()
    shares = config['meta']['total_shares']  # 52.79亿股
    hkd_cny_rate = config['meta']['hkd_cny_rate']  # 0.92
    
    # WACC参数
    wacc_cfg = config.get('methodology_notes', {}).get('wacc', {})
    rf_rate = wacc_cfg.get('risk_free_rate', {}).get('fallback', 0.030)
    beta_val = wacc_cfg.get('beta', {}).get('value', 1.05)
    market_prem = wacc_cfg.get('market_premium', 0.07)
    tg_val = config.get('methodology_notes', {}).get('terminal_growth', {}).get('value', 0.03)
    
    # SOTP估值
    sotp = LensHK_SOTP.from_config()
    sotp_result = sotp.calculate(live_price)
    sotp_detail = sotp.get_sotp_detail()
    
    print(f"\n【SOTP估值结果】")
    print(f"  SOTP总市值: {sotp_result['sotp_cap_base_hkd']}亿HKD（区间{sotp_result['sotp_cap_min_hkd']}-{sotp_result['sotp_cap_max_hkd']}亿HKD）")
    print(f"  目标价: {sotp_result['target_base_hkd']} HKD（{sotp_result['target_base_cny']} CNY）")
    print(f"  区间: {sotp_result['target_min_hkd']}-{sotp_result['target_max_hkd']} HKD")
    print(f"  上涨空间: {sotp_result['upside_base']}%")
    print(f"\n  各业务线(HKD):")
    for seg in sotp_detail['segments']:
        print(f"    {seg['name']}: {seg['revenue_hkd']}亿收入 × {seg['net_margin']}%净利 = {seg['net_profit_hkd']}亿净利 → PE{seg['pe_range']} → {seg['cap_hkd']}亿市值({seg['pct']})")
    
    # WACC + DCF
    engine = DiscountingEngine()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wacc = engine.calc_wacc(risk_free_rate=rf_rate, beta=beta_val,
                                market_premium=market_prem, auto_refresh_beta=True)
    
    # DCF: 基于总净利
    total_nm = sotp_result['total_net_profit']  # HKD亿
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
    dcf_price_hkd = dcf_result['目标价_元']
    dcf_price_cny = dcf_price_hkd * hkd_cny_rate
    
    print(f"\n【DCF估值结果】")
    print(f"  WACC: {wacc:.3f}")
    print(f"  DCF目标价: {dcf_price_hkd:.2f} HKD（{dcf_price_cny:.2f} CNY）")
    
    # 概率加权
    events = config.get('events', [])
    weighted_price_hkd = None
    if events:
        pw = ProbabilityWeightEngine.from_config_list(events)
        sotp_cap_base = sotp_result['sotp_cap_base_hkd']
        weighted_cap = pw.apply(sotp_cap_base)
        weighted_price_hkd = weighted_cap / shares
        weighted_price_cny = weighted_price_hkd * hkd_cny_rate
        
        print(f"\n【概率加权估值】")
        print(f"  基准SOTP市值: {sotp_cap_base}亿HKD")
        print(f"  综合乘数: {weighted_cap/sotp_cap_base:.3f}x")
        for ev in events:
            sign = '+' if ev['impact'] == 'positive' else '-'
            print(f"    {sign} {ev['name']}: {ev['probability']*100:.0f}% × {ev['magnitude']}x")
        print(f"  概率加权市值: {weighted_cap:.0f}亿HKD")
        print(f"  概率加权目标价: {weighted_price_hkd:.2f} HKD（{weighted_price_cny:.2f} CNY）")
    
    # 汇总
    result = {
        'date': str(today),
        'stock_code': 'HK06613',
        'stock_name': '蓝思科技',
        'currency': 'HKD',
        'live_price_hkd': live_price,
        'live_price_cny': round(live_price * hkd_cny_rate, 2),
        'current_market_cap_hkd': round(live_price * shares, 1),
        'sotp': {
            'sotp_cap_base_hkd': sotp_result['sotp_cap_base_hkd'],
            'sotp_cap_min_hkd': sotp_result['sotp_cap_min_hkd'],
            'sotp_cap_max_hkd': sotp_result['sotp_cap_max_hkd'],
            'target_price_hkd': sotp_result['target_base_hkd'],
            'target_price_min_hkd': sotp_result['target_min_hkd'],
            'target_price_max_hkd': sotp_result['target_max_hkd'],
            'target_price_cny': sotp_result['target_base_cny'],
            'upside_base': sotp_result['upside_base'],
            'segments': sotp_detail['segments'],
        },
        'dcf': {
            'target_price_hkd': round(dcf_price_hkd, 2),
            'target_price_cny': round(dcf_price_cny, 2),
            'wacc': round(wacc, 3),
        },
        'weighted_price_hkd': round(weighted_price_hkd, 2) if weighted_price_hkd else None,
    }
    
    return result


if __name__ == '__main__':
    result = run_lens_hk_valuation()
    print(f"\n【最终结果】")
    print(f"  SOTP目标价: {result['sotp']['target_price_hkd']} HKD（{result['sotp']['target_price_cny']} CNY）")
    print(f"  DCF目标价: {result['dcf']['target_price_hkd']} HKD（{result['dcf']['target_price_cny']} CNY）")
    if result.get('weighted_price_hkd'):
        weighted_cny = result['weighted_price_hkd'] * 0.92
        print(f"  概率加权目标价: {result['weighted_price_hkd']} HKD（{weighted_cny:.2f} CNY）")