#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
估值模型通用框架 v1.0
支持多股票的SOTP分步估值 + 飞书Bitable自动填表

设计目标：
- 新增股票只需修改 STOCK_CONFIG
- 数据自动采集 + 手动字段分离
- 每日Cron自动运行
"""

import warnings
warnings.filterwarnings('ignore')

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import requests
import json
from datetime import datetime, date
from typing import Optional, Dict, List, Any

# ============ 股票配置 ============
# 新增股票：在这里加一行配置即可
STOCK_CONFIG = {
    '002428': {
        'name': '云南锗业',
        'market': 'SZ',
        'name_en': 'Yunnan Germanium',
        # SOTP配置
        'shares': 6.53,  # 总股本（亿股）
        'semi_pe_min': 50, 'semi_pe_max': 65,  # 半导体业务PE区间
        'trad_pe_min': 15, 'trad_pe_max': 20,   # 传统业务PE区间
        # 飞书Bitable
        'bitable_app': 'EXpqbt8RdaVNsaslViKclTu9nCe',
        'bitable_table': 'tblAH85HuqZuyLSH',
        # 自动/手动字段
        'auto_fields': ['stock_code', 'stock_name', 'current_price', 'change_pct', 
                        'pe_ttm', 'pb', 'high_52w', 'low_52w', 'volume', 
                        'turnover_rate', 'market_cap', 'update_time'],
        'manual_fields': ['indium_price', 'germanium_price', 'yield_6inch', 
                         'ratio_6inch', 'cert_status', 'revenue', 'net_profit',
                         'inventory', 'semi_nm', 'trad_nm'],
    },
    # 【示例】新增股票只需复制上方配置，修改以下字段即可：
    # '006240': {
    #     'name': '某公司',
    #     'market': 'SH',
    #     'shares': 10.0,
    #     'semi_pe_min': 40, 'semi_pe_max': 60,
    #     'trad_pe_min': 12, 'trad_pe_max': 18,
    #     'bitable_app': 'APP_TOKEN',
    #     'bitable_table': 'TABLE_ID',
    #     ...
    # },
}

# ============ 商品价格采集 ============
# 使用 Playwright 从 SMM H5 页面采集
SCRAPER_AVAILABLE = False
try:
    from playwright.sync_api import sync_playwright
    SCRAPER_AVAILABLE = True
except ImportError:
    pass


def get_commodity_prices() -> Optional[Dict]:
    """
    获取铟价、锗价等商品价格
    数据来源: SMM H5页面
    - 铟: https://hq.smm.cn/h5/indium-price
    - 锗: https://hq.smm.cn/h5/germanium-price
    """
    if not SCRAPER_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            # 获取铟价
            page.goto('https://hq.smm.cn/h5/indium-price', timeout=30000)
            page.wait_for_timeout(8000)
            text_indium = page.inner_text('body')
            
            # 获取锗价
            page.goto('https://hq.smm.cn/h5/germanium-price', timeout=30000)
            page.wait_for_timeout(8000)
            text_germanium = page.inner_text('body')
            
            browser.close()
            
            # 解析价格
            indium_price = None
            germanium_price = None
            indium_date = None
            germanium_date = None
            
            for line in text_indium.split('\n'):
                line = line.strip()
                if '精铟价格' in line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        # 精铟价格  4300 - 4400  4350  0  元/千克  2026-04-24
                        try:
                            avg = parts[2].strip()
                            indium_price = float(avg)
                            indium_date = parts[5].strip() if len(parts) > 5 else None
                        except:
                            pass
                    break
            
            for line in text_germanium.split('\n'):
                line = line.strip()
                if '锗锭价格' in line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        try:
                            avg = parts[2].strip()
                            germanium_price = float(avg)
                            germanium_date = parts[5].strip() if len(parts) > 5 else None
                        except:
                            pass
                    break
            
            if indium_price or germanium_price:
                return {
                    'indium_price': indium_price,
                    'indium_date': indium_date,
                    'germanium_price': germanium_price,
                    'germanium_date': germanium_date,
                    'source': 'SMM',
                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                }
    except Exception as e:
        print(f"⚠️ 商品价格采集失败: {e}")
    
    return None


# ============ 数据获取 ============

def get_stock_spot(code: str, market: str = 'SZ') -> Optional[Dict]:
    """获取个股实时行情"""
    symbol = f'{market}{code}'
    try:
        df = ak.stock_individual_spot_xq(symbol=symbol)
        data = {row['item']: row['value'] for _, row in df.iterrows()}
        
        return {
            'stock_code': code,
            'stock_name': data.get('名称', ''),
            'current_price': float(data.get('现价', 0)),
            'change_pct': float(data.get('涨幅', 0)),
            'pe_ttm': float(data.get('市盈率(TTM)', 0)),
            'pb': float(data.get('市净率', 0)),
            'high_52w': float(data.get('52周最高', 0)),
            'low_52w': float(data.get('52周最低', 0)),
            'volume': float(data.get('成交量', 0)),
            'turnover_rate': float(data.get('周转率', 0)),
            'market_cap': float(data.get('流通值', 0)) / 1e8,
            'update_time': data.get('时间', ''),
        }
    except Exception as e:
        print(f"⚠️ 获取 {code} 行情失败: {e}")
        return None

# ============ SOTP估值 ============

def calc_sotp(spot: Dict, manual: Dict, config: Dict) -> Optional[Dict]:
    """
    计算 SOTP 分部估值
    
    Args:
        spot: 自动行情数据
        manual: 手动填入数据（铟价/良率/净利等）
        config: 股票配置
    
    Returns:
        估值结果 dict
    """
    # 提取关键手动字段
    semi_nm = manual.get('semi_nm')      # 半导体分部净利
    trad_nm = manual.get('trad_nm')       # 传统业务净利
    semi_pe = manual.get('semi_pe')       # 半导体PE（可动态调节）
    trad_pe = manual.get('trad_pe')       # 传统业务PE
    
    if semi_nm is None or trad_nm is None:
        return None
    
    # PE默认值
    if semi_pe is None:
        semi_pe = (config['semi_pe_min'] + config['semi_pe_max']) / 2
    if trad_pe is None:
        trad_pe = (config['trad_pe_min'] + config['trad_pe_max']) / 2
    
    shares = config['shares']
    
    # 分部估值
    semi_cap = semi_nm * semi_pe
    trad_cap = trad_nm * trad_pe
    total_cap = semi_cap + trad_cap
    target_price = total_cap / shares
    
    # 敏感性区间
    target_low = (semi_nm * config['semi_pe_min'] + trad_nm * config['trad_pe_min']) / shares
    target_high = (semi_nm * config['semi_pe_max'] + trad_nm * config['trad_pe_max']) / shares
    
    return {
        'semi_nm': semi_nm,
        'trad_nm': trad_nm,
        'semi_pe': semi_pe,
        'trad_pe': trad_pe,
        'semi_cap': round(semi_cap, 2),
        'trad_cap': round(trad_cap, 2),
        'total_cap': round(total_cap, 2),
        'target_price': round(target_price, 2),
        'target_low': round(target_low, 2),
        'target_high': round(target_high, 2),
    }

# ============ 报告生成 ============

def generate_report(code: str, spot: Dict, commodity: Dict, manual: Dict, 
                   valuation: Dict, config: Dict) -> str:
    """生成每日报告文本"""
    today = datetime.now().strftime('%Y-%m-%d')
    lines = []
    lines.append(f"📊 {config['name']}({code}) 估值日报 {today}")
    lines.append("")
    
    # 行情
    if spot:
        lines.append("【行情】")
        lines.append(f"  股价: {spot['current_price']}元 ({spot['change_pct']:+.2f}%)")
        lines.append(f"  市值: {spot['market_cap']:.1f}亿 | PE: {spot['pe_ttm']:.0f} | PB: {spot['pb']:.1f}")
        lines.append(f"  52周: {spot['low_52w']} - {spot['high_52w']}元")
        lines.append("")
    
    # 商品价格
    lines.append("【商品价格】")
    if commodity:
        lines.append(f"  铟价: {commodity.get('indium_price')}元/kg")
        lines.append(f"  锗价: {commodity.get('germanium_price')}万元/吨")
    else:
        lines.append("  ⏳ 待手动更新")
    lines.append("")
    
    # 手动字段摘要
    if any(manual.values()):
        lines.append("【核心监控指标】")
        for k, v in manual.items():
            if v is not None:
                label = {'yield_6inch': '6寸良率', 'ratio_6inch': '6寸占比',
                         'revenue': '营收', 'net_profit': '净利润',
                         'semi_nm': '半导体净利', 'trad_nm': '传统净利'}.get(k, k)
                unit = {'yield_6inch': '%', 'ratio_6inch': '%', 
                        'revenue': '亿', 'net_profit': '亿',
                        'semi_nm': '亿', 'trad_nm': '亿'}.get(k, '')
                lines.append(f"  {label}: {v}{unit}")
        lines.append("")
    
    # SOTP估值
    if valuation:
        lines.append("【SOTP估值】")
        current_price = spot['current_price'] if spot else 0
        upside = (valuation['target_price'] / current_price - 1) * 100 if current_price else 0
        upside_low = (valuation['target_low'] / current_price - 1) * 100 if current_price else 0
        upside_high = (valuation['target_high'] / current_price - 1) * 100 if current_price else 0
        
        lines.append(f"  半导体分部: {valuation['semi_nm']}亿 × {valuation['semi_pe']:.0f}x = {valuation['semi_cap']}亿")
        lines.append(f"  传统业务: {valuation['trad_nm']}亿 × {valuation['trad_pe']:.0f}x = {valuation['trad_cap']}亿")
        lines.append(f"  SOTP总市值: {valuation['total_cap']}亿")
        lines.append(f"  目标股价: {valuation['target_low']} - {valuation['target_high']}元 (中枢{valuation['target_price']}元)")
        lines.append(f"  当前价 {current_price}元 → 潜在空间: {upside_low:+.0f}% ~ {upside_high:+.0f}%")
        lines.append("")
    
    return '\n'.join(lines)

# ============ 主流程 ============

def main():
    print(f"=== 估值模型框架 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    results = {}
    
    for code, config in STOCK_CONFIG.items():
        print(f"📈 {config['name']}({code})...")
        
        # 自动数据
        spot = get_stock_spot(code, config.get('market', 'SZ'))
        commodity = get_commodity_prices()
        
        # 手动数据（需人工填入）
        # TODO: 从飞书Bitable读取已有手动字段
        manual = {
            'indium_price': None,
            'germanium_price': None,
            'yield_6inch': None,
            'ratio_6inch': None,
            'cert_status': None,
            'revenue': None,
            'net_profit': None,
            'semi_nm': None,
            'trad_nm': None,
            'semi_pe': None,
            'trad_pe': None,
        }
        
        # 计算SOTP
        valuation = calc_sotp(spot, manual, config)
        
        # 生成报告
        report = generate_report(code, spot, commodity, manual, valuation, config)
        print(report)
        
        results[code] = {
            'config': config,
            'spot': spot,
            'commodity': commodity,
            'manual': manual,
            'valuation': valuation,
            'report': report,
        }
    
    return results

if __name__ == '__main__':
    main()
