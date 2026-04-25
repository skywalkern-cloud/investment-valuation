#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
铟价/锗价自动采集脚本
数据来源: SMM H5页面 (https://hq.smm.cn/h5/indium-price, https://hq.smm.cn/h5/germanium-price)

使用方法:
    python3 commodity_price_scraper.py
    # 输出:
    # 铟价: 4350 元/kg (精铟, 2026-04-24)
    # 锗价: 17500 元/kg (锗锭, 2026-04-24)
"""

import re
import warnings
warnings.filterwarnings('ignore')

from datetime import datetime
from typing import Optional, Dict

# Playwright for headless browser
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️ Playwright not installed. Run: pip install playwright && python -m playwright install chromium")


def parse_price_table(text: str, keyword: str) -> Optional[Dict]:
    """从页面文本中解析价格表"""
    lines = text.split('\n')
    
    # Find the table header and data rows
    in_table = False
    headers = []
    data_rows = []
    
    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue
        
        # Detect table
        if '名称' in line and '价格范围' in line:
            in_table = True
            headers = [h.strip() for h in re.split(r'\t|\s{2,}', line) if h.strip()]
            continue
        
        if in_table:
            # Check if we've exited the table
            if line in ['铟价格走势', '锗价格走势', '更多', '首页', 'APP下载', '上海有色网']:
                break
            
            # Parse data row
            parts = [p.strip() for p in re.split(r'\t', line)]
            if len(parts) >= 5 and parts[0] and parts[1]:
                data_rows.append(parts)
    
    # Filter for the keyword we want
    for row in data_rows:
        if len(row) >= 5:
            name = row[0]
            price_range = row[1]
            avg_price = row[2]
            change = row[3]
            unit = row[4]
            date = row[5] if len(row) > 5 else ''
            
            if keyword in name:
                return {
                    'name': name,
                    'price_range': price_range,
                    'avg_price': avg_price,
                    'change': change,
                    'unit': unit,
                    'date': date,
                }
    
    return None


def get_indium_price() -> Optional[Dict]:
    """获取铟价"""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            page.goto('https://hq.smm.cn/h5/indium-price', timeout=30000)
            page.wait_for_timeout(8000)
            
            text = page.inner_text('body')
            browser.close()
            
            # Parse 精铟价格 (refined indium)
            result = parse_price_table(text, '精铟')
            if result:
                return result
            
            # Fallback: try 粗铟 (crude indium)
            result = parse_price_table(text, '铟价格')
            if result:
                return result
                
            return None
    except Exception as e:
        print(f"⚠️ 获取铟价失败: {e}")
        return None


def get_germanium_price() -> Optional[Dict]:
    """获取锗价"""
    if not PLAYWRIGHT_AVAILABLE:
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            
            page.goto('https://hq.smm.cn/h5/germanium-price', timeout=30000)
            page.wait_for_timeout(8000)
            
            text = page.inner_text('body')
            browser.close()
            
            # Parse 锗锭价格 (germanium ingot)
            result = parse_price_table(text, '锗锭价格')
            if result:
                return result
                
            return None
    except Exception as e:
        print(f"⚠️ 获取锗价失败: {e}")
        return None


def get_commodity_prices() -> Dict[str, Optional[Dict]]:
    """
    获取铟价和锗价
    返回: {'indium': {...}, 'germanium': {...}}
    """
    indium = get_indium_price()
    germanium = get_germanium_price()
    
    return {
        'indium': indium,
        'germanium': germanium,
    }


def main():
    print(f"=== 商品价格采集 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    prices = get_commodity_prices()
    
    # Format output
    if prices.get('indium'):
        ind = prices['indium']
        print(f"铟价:")
        print(f"  精铟: {ind['price_range']} 元/kg (均价 {ind['avg_price']} 元/kg, {ind['date']})")
    else:
        print("⚠️ 铟价: 获取失败")
    
    print()
    
    if prices.get('germanium'):
        ger = prices['germanium']
        print(f"锗价:")
        print(f"  锗锭: {ger['price_range']} 元/kg (均价 {ger['avg_price']} 元/kg, {ger['date']})")
    else:
        print("⚠️ 锗价: 获取失败")
    
    return prices


if __name__ == '__main__':
    main()
