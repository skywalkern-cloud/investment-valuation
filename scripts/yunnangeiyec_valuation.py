#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云南锗业(002428)估值模型数据收集
每日定时运行，收集市场价格+新闻数据，填入飞书Bitable

数据源：
- 股价: akshare stock_individual_spot_xq (Snowball)
- 铟价/锗价: 待接入SMM (目前标记为manual)
- 良率/认证: 华尔街见闻快讯搜索
- 财务数据: 季报 (手动更新)
"""

import warnings
warnings.filterwarnings('ignore')

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import akshare as ak
import requests
import json
import re
from datetime import datetime, date
import time

# 飞书Bitable配置
BITABLE_APP_TOKEN = "EXpqbt8RdaVNsaslViKclTu9nCe"
BITABLE_TABLE_ID = "tblAH85HuqZuyLSH"

# 雪球API配置
SNOWBALL_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    'Cookie': 'xq_a_token=placeholder'  # 会被akshare处理
}

# ========== 数据获取函数 ==========

def get_stock_spot():
    """获取云南锗业实时行情"""
    try:
        df = ak.stock_individual_spot_xq(symbol='SZ002428')
        data = {}
        for _, row in df.iterrows():
            data[row['item']] = row['value']
        return {
            'stock_code': 'SZ002428',
            'stock_name': data.get('名称', '云南锗业'),
            'current_price': float(data.get('现价', 0)),
            'change_pct': float(data.get('涨幅', 0)),
            'pe_ttm': float(data.get('市盈率(TTM)', 0)),
            'pb': float(data.get('市净率', 0)),
            'high_52w': float(data.get('52周最高', 0)),
            'low_52w': float(data.get('52周最低', 0)),
            'volume': float(data.get('成交量', 0)),
            'turnover_rate': float(data.get('周转率', 0)),
            'market_cap': float(data.get('流通值', 0)) / 1e8,  # 转为亿元
            'update_time': data.get('时间', ''),
        }
    except Exception as e:
        print(f"获取行情失败: {e}")
        return None

def get_commodity_prices():
    """
    获取铟价和锗价
    数据来源: SMM H5页面 (使用Playwright无头浏览器)
    - 铟: https://hq.smm.cn/h5/indium-price
    - 锗: https://hq.smm.cn/h5/germanium-price
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ Playwright not installed. Commodity prices unavailable.")
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
            
            indium_price = None
            germanium_price = None
            indium_date = None
            germanium_date = None
            
            for line in text_indium.split('\n'):
                line = line.strip()
                if '精铟价格' in line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
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
                }
    except Exception as e:
        print(f"⚠️ 商品价格采集失败: {e}")
    
    return None

def search_certification_news():
    """
    搜索1.6T认证和良率相关新闻
    使用雪球搜索
    """
    try:
        import subprocess
        result = subprocess.run(
            ['python3', '/Users/vincentnie/.openclaw/workspace-market-insight/scripts/x-search-curl.sh', 
             '--days', '7', '云南锗业 1.6T OR 磷化铟 OR 良率'],
            capture_output=True, text=True, timeout=30
        )
        return result.stdout[:500] if result.returncode == 0 else ""
    except:
        return ""

def get_quarterly_financial():
    """
    获取季度财务数据
    注: akshare无直接接口，需要手动从财报获取
    目前返回 None，待手动填入
    """
    # TODO: 接入季报数据 (4月底一季报)
    return None

# ========== SOTP估值计算 ==========

def calc_sotp_valuation(semi_nm, traditional_nm, semi_pe, trad_pe, shares=6.53):
    """
    SOTP分部估值计算
    
    Args:
        semi_nm: 半导体分部净利润(亿元)
        traditional_nm: 传统业务净利润(亿元)
        semi_pe: 半导体业务PE倍数
        trad_pe: 传统业务PE倍数
        shares: 总股本(亿股)，默认6.53亿
    """
    if semi_nm is None or traditional_nm is None:
        return None
    
    semi_market_cap = semi_nm * semi_pe
    trad_market_cap = traditional_nm * trad_pe
    total_market_cap = semi_market_cap + trad_market_cap
    target_price = total_market_cap / shares
    
    return {
        'semi_market_cap': round(semi_market_cap, 2),
        'trad_market_cap': round(trad_market_cap, 2),
        'total_market_cap': round(total_market_cap, 2),
        'target_price': round(target_price, 2),
    }

# ========== 飞书Bitable写入 ==========

def feishu_api(endpoint, data=None, method='GET'):
    """飞书Bitable API调用"""
    # 注: 需要通过feishu_bitable_*工具写入，这里只生成记录数据
    pass

def format_bitable_record(spot, commodity, financials, news, valuation):
    """格式化Bitable记录"""
    today = int(datetime.now().timestamp() * 1000)  # 毫秒时间戳
    
    record = {}
    
    # 日期
    record['日期'] = today
    
    # 行情数据
    if spot:
        record['铟价(元/kg)'] = commodity.get('indium_price') if commodity else None
        record['锗价(万元/吨)'] = commodity.get('germanium_price') if commodity else None
        record['股价(元)'] = spot.get('current_price')
        record['备注'] = f"涨幅{spot.get('change_pct',0):.2f}% | PE{spot.get('pe_ttm',0):.1f} | PB{spot.get('pb',0):.2f}"
    
    # 手动更新字段 (None表示待手动填入)
    if financials:
        record['营收(亿元)'] = financials.get('revenue')
        record['净利润(亿元)'] = financials.get('net_profit')
        record['存货(亿元)'] = financials.get('inventory')
        record['6寸良率(%)'] = financials.get('yield_6inch')
        record['6寸占比(%)'] = financials.get('ratio_6inch')
        record['1.6T认证进度'] = financials.get('cert_status')
        record['半导体分部净利(亿元)'] = financials.get('semi_nm')
        record['传统业务净利(亿元)'] = financials.get('trad_nm')
    
    if valuation:
        record['半导体PE(倍)'] = valuation.get('semi_pe')
        record['传统PE(倍)'] = valuation.get('trad_pe')
        record['半导体分部市值(亿)'] = valuation.get('semi_market_cap')
        record['传统业务市值(亿)'] = valuation.get('trad_market_cap')
        record['SOTP总市值(亿)'] = valuation.get('total_market_cap')
        record['目标股价(元)'] = valuation.get('target_price')
    
    return record

# ========== 主流程 ==========

def main():
    print(f"=== 云南锗业估值数据收集 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    # 1. 获取行情
    print("📈 获取行情数据...")
    spot = get_stock_spot()
    if spot:
        print(f"  股价: {spot['current_price']}元 ({spot['change_pct']:+.2f}%)")
        print(f"  市值: {spot['market_cap']:.2f}亿元 | PE: {spot['pe_ttm']:.1f} | PB: {spot['pb']:.2f}")
    else:
        print("  ⚠️ 行情获取失败")
    
    print()
    
    # 2. 商品价格 (手动模式)
    print("📊 商品价格...")
    commodity = get_commodity_prices()
    if commodity:
        print(f"  铟价: {commodity.get('indium_price')}元/kg")
        print(f"  锗价: {commodity.get('germanium_price')}万元/吨")
    else:
        print("  ⏳ 待手动更新 (需接入SMM API)")
    
    print()
    
    # 3. 财务数据
    print("📋 财务数据...")
    financials = get_quarterly_financial()
    if financials:
        print(f"  营收: {financials.get('revenue')}亿元 | 净利润: {financials.get('net_profit')}亿元")
    else:
        print("  ⏳ 待手动更新 (4月底一季报)")
    
    print()
    
    # 4. 示例计算 (如果有财务数据)
    if financials and financials.get('semi_nm') and financials.get('trad_nm'):
        print("💡 SOTP估值计算...")
        # 默认PE: 半导体50x, 传统15x
        semi_pe = 50
        trad_pe = 15
        valuation = calc_sotp_valuation(
            financials.get('semi_nm', 0),
            financials.get('trad_nm', 0),
            semi_pe, trad_pe
        )
        if valuation:
            print(f"  半导体分部: {financials.get('semi_nm')}亿 × {semi_pe}x = {valuation['semi_market_cap']}亿元")
            print(f"  传统业务: {financials.get('trad_nm')}亿 × {trad_pe}x = {valuation['trad_market_cap']}亿元")
            print(f"  SOTP总市值: {valuation['total_market_cap']}亿元")
            print(f"  目标股价: {valuation['target_price']}元 (股本6.53亿)")
    else:
        print("💡 SOTP估值: ⏳ 需先填入财务数据")
        # 示例计算 (假设值)
        print("  [示例] 半导体分部净利1亿×50x + 传统0.5亿×15x = 57.5亿 → 目标价8.81元")
        print("  [示例] 半导体分部净利2亿×50x + 传统0.5亿×15x = 107.5亿 → 目标价16.46元")
    
    print()
    
    # 5. 生成记录
    record = format_bitable_record(spot, commodity, financials, None, None)
    print(f"📝 Bitable记录: {json.dumps(record, ensure_ascii=False, indent=2)[:500]}")
    
    return spot, commodity, financials

if __name__ == '__main__':
    main()
