#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
股票行情API - 内嵌版本，不依赖外部路径
数据源：腾讯行情 API (qt.gtimg.cn)
"""

import requests
import re

TENCENT_BASE = "https://qt.gtimg.cn"
PROXIES = {}

def get_a_stock_quote(symbols):
    """获取A股实时行情"""
    if not symbols:
        return []
    
    query_parts = []
    for s in symbols:
        if s.startswith(('6', '5', '7', '8', '9')):
            query_parts.append(f"sh{s}")
        elif s.startswith(('0', '1', '2', '3')):
            query_parts.append(f"sz{s}")
    
    if not query_parts:
        return []
    
    query = ','.join(query_parts)
    
    try:
        resp = requests.get(f"{TENCENT_BASE}/q={query}", timeout=10, proxies=PROXIES)
        resp.encoding = 'gbk'
        
        results = []
        for symbol in symbols:
            for prefix in ['sh', 'sz']:
                pattern = rf'v_{prefix}{symbol}[^"]*"([^"]+)"'
                match = re.search(pattern, resp.text)
                
                if match:
                    parts = match.group(1).split('~')
                    if len(parts) >= 6:
                        try:
                            price = float(parts[3])
                            yesterday_close = float(parts[4])
                            change_pct = round((price - yesterday_close) / yesterday_close * 100, 2)
                            change = round(price - yesterday_close, 2)
                            
                            results.append({
                                'code': symbol,
                                'name': parts[1],
                                'price': price,
                                'yesterday_close': yesterday_close,
                                'change_pct': change_pct,
                                'change': change,
                                'volume': float(parts[6]) if len(parts) > 6 and parts[6] else 0,
                            })
                        except (ValueError, IndexError):
                            continue
                    break
        
        return results
    except Exception as e:
        print(f"获取A股行情失败: {e}")
        return []
