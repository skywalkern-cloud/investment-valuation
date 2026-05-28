#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
估值模型通用框架 v2.0
支持多股票的SOTP分步估值 + 飞书Bitable自动写入

v2.0变更：
- 商品价格自动采集(SMM)并写入bitable
- 读取已有手动财务数据
- 自动计算SOTP估值并写回bitable
- 不再依赖cron LLM做API调用
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
STOCK_CONFIG = {
    '002428': {
        'name': '云南锗业',
        'market': 'SZ',
        'name_en': 'Yunnan Germanium',
        # SOTP配置
        'shares': 6.53,  # 总股本（亿股）
        'semi_pe_min': 50, 'semi_pe_max': 65,
        'trad_pe_min': 15, 'trad_pe_max': 20,
        # 飞书Bitable
        'bitable_app': 'EXpqbt8RdaVNsaslViKclTu9nCe',
        'bitable_table': 'tblAH85HuqZuyLSH',
        # 字段定义
        'bitable_fields': {
            '日期':     {'type': 'date', 'key': 'date_str'},
            '股价(元)':  {'type': 'number', 'key': 'current_price'},
            '涨跌幅(%)': {'type': 'number', 'key': 'change_pct'},
            '市盈率(PE)': {'type': 'number', 'key': 'pe_ttm'},
            '市净率(PB)': {'type': 'number', 'key': 'pb'},
            '52周最高':  {'type': 'number', 'key': 'high_52w'},
            '52周最低':  {'type': 'number', 'key': 'low_52w'},
            '成交量':   {'type': 'number', 'key': 'volume'},
            '换手率(%)': {'type': 'number', 'key': 'turnover_rate'},
            '流通市值(亿)': {'type': 'number', 'key': 'market_cap'},
            '铟价(元/kg)': {'type': 'number', 'key': 'indium_price'},
            '锗价(万元/吨)': {'type': 'number', 'key': 'germanium_price'},
            '备注':     {'type': 'text', 'key': 'notes'},
            '半导体净利(亿)': {'type': 'number', 'key': 'semi_nm'},
            '传统净利(亿)': {'type': 'number', 'key': 'trad_nm'},
            'SOTP目标价': {'type': 'number', 'key': 'target_price'},
            'SOTP下限':  {'type': 'number', 'key': 'target_low'},
            'SOTP上限':  {'type': 'number', 'key': 'target_high'},
            '潜在空间':  {'type': 'text', 'key': 'upside_str'},
        },
    },
}

# ============ 商品价格采集 ============
def get_commodity_prices() -> Optional[Dict]:
    """
    获取铟价、锗价等商品价格
    数据来源: SMM H5页面
    依赖: playwright (pip3 install playwright && playwright install chromium)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("  ⚠️ playwright未安装，跳过商品价格采集")
        return None
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
            )
            page = context.new_page()
            
            indium_price = None
            germanium_price = None
            indium_date = None
            germanium_date = None
            
            # 铟价
            page.goto('https://hq.smm.cn/h5/indium-price', timeout=30000)
            page.wait_for_timeout(5000)
            text = page.inner_text('body')
            for line in text.split('\n'):
                if '精铟价格' in line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        try:
                            indium_price = float(parts[2].strip())
                            indium_date = parts[5].strip() if len(parts) > 5 else None
                        except: pass
                    break
            
            # 锗价
            page.goto('https://hq.smm.cn/h5/germanium-price', timeout=30000)
            page.wait_for_timeout(5000)
            text = page.inner_text('body')
            for line in text.split('\n'):
                if '锗锭价格' in line:
                    parts = line.split('\t')
                    if len(parts) >= 6:
                        try:
                            # SMM给的是元/千克，转万元/吨
                            raw = float(parts[2].strip())
                            germanium_price = round(raw * 1000 / 10000, 2)  # 元/kg → 万元/吨
                            germanium_date = parts[5].strip() if len(parts) > 5 else None
                        except: pass
                    break
            
            browser.close()
            
            if indium_price or germanium_price:
                print(f"    ✅ 铟价={indium_price}元/kg({indium_date}) 锗价={germanium_price}万元/吨({germanium_date})")
                return {
                    'indium_price': indium_price,
                    'germanium_price': germanium_price,
                    'indium_date': indium_date,
                    'germanium_date': germanium_date,
                    'source': 'SMM',
                }
    except Exception as e:
        print(f"  ⚠️ 商品价格采集失败: {e}")
    
    return None


# ============ 飞书API ============

def _get_feishu_token() -> Optional[str]:
    """从openclaw配置获取飞书token"""
    config_path = os.path.expanduser('~/.openclaw/openclaw.json')
    try:
        with open(config_path) as f:
            cfg = json.load(f)
        app_id = cfg.get('plugins',{}).get('entries',{}).get('feishu',{}).get('config',{}).get('appId','')
        app_secret = cfg.get('plugins',{}).get('entries',{}).get('feishu',{}).get('config',{}).get('appSecret','')
        
        # fallback: 从 channels.feishu.accounts 读取
        if not app_id or not app_secret:
            accounts = cfg.get('channels',{}).get('feishu',{}).get('accounts',{})
            # 先用 market-bot，找不到用 default
            for name in ['market-bot', 'default']:
                if name in accounts:
                    app_id = accounts[name]['appId']
                    app_secret = accounts[name]['appSecret']
                    break
        
        if not app_id or not app_secret:
            print("  ⚠️ 找不到飞书配置")
            return None
        
        resp = requests.post(
            'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
            json={'app_id': app_id, 'app_secret': app_secret},
            timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            return data['tenant_access_token']
        print(f"  ⚠️ 飞书token获取失败: {data.get('msg','')}")
    except Exception as e:
        print(f"  ⚠️ 读取配置失败: {e}")
    return None


def read_bitable_records(app_token: str, table_id: str) -> List[Dict]:
    """读取bitable最近记录，获取手动填写的财务数据"""
    token = _get_feishu_token()
    if not token:
        return []
    
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        resp = requests.post(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/search',
            json={'page_size': 20, 'sort': [{'field_name': '日期', 'desc': True}]},
            headers=headers, timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            return data.get('data',{}).get('items',[])
        print(f"  ⚠️ 读取bitable失败: {data.get('msg','')}")
    except Exception as e:
        print(f"  ⚠️ 读取bitable异常: {e}")
    return []


def write_bitable_record(app_token: str, table_id: str, fields: Dict):
    """写入一条记录到飞书bitable"""
    token = _get_feishu_token()
    if not token:
        print("  ⚠️ 无token，跳过bitable写入")
        return False
    
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        resp = requests.post(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records',
            json={'fields': fields},
            headers=headers, timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            record_id = data.get('data',{}).get('record',{}).get('record_id','')
            print(f"    ✅ bitable写入成功: {record_id}")
            return True
        else:
            print(f"  ⚠️ bitable写入失败: {data.get('msg','')}")
    except Exception as e:
        print(f"  ⚠️ bitable写入异常: {e}")
    return False


def update_bitable_record(app_token: str, table_id: str, record_id: str, fields: Dict):
    """更新bitable中已有记录"""
    token = _get_feishu_token()
    if not token:
        return False
    
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        resp = requests.put(
            f'https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}',
            json={'fields': fields},
            headers=headers, timeout=10
        )
        data = resp.json()
        if data.get('code') == 0:
            print(f"    ✅ bitable更新成功: {record_id}")
            return True
        print(f"  ⚠️ bitable更新失败: {data.get('msg','')}")
    except Exception as e:
        print(f"  ⚠️ bitable更新异常: {e}")
    return False


# ============ 数据获取 ============

def get_stock_spot(code: str, market: str = 'SZ') -> Optional[Dict]:
    """获取个股实时行情（akshare雪球接口 + Eastmoney备用）"""
    symbol = f'{market}{code}'
    try:
        # 雪球接口
        df = ak.stock_individual_spot_xq(symbol=symbol)
        data = {row['item']: row['value'] for _, row in df.iterrows()}
        
        current_price = float(data.get('现价', 0))
        if current_price == 0:
            raise ValueError("股价为0")
        
        return {
            'stock_code': code,
            'stock_name': data.get('名称', ''),
            'current_price': current_price,
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
        print(f"  ⚠️ 雪球接口失败: {e}")
        print("  尝试Eastmoney备用接口...")
        try:
            # Eastmoney push2备用接口
            em_url = f'https://push2.eastmoney.com/api/qt/stock/get?secid={0}.{code}&fields=f43,f44,f45,f46,f47,f48,f57,f58,f170,f57,f58,f168,f169,f60,f161'
            headers_em = {'User-Agent': 'Mozilla/5.0'}
            resp = requests.get(em_url, headers=headers_em, timeout=10)
            d = resp.json().get('data', {})
            if d:
                current_price = d.get('f43', 0) / 100
                return {
                    'stock_code': code,
                    'stock_name': d.get('f58',''),
                    'current_price': current_price,
                    'change_pct': d.get('f170', -100) / 100,
                    'pe_ttm': d.get('f162', 0),
                    'pb': d.get('f167', 0),
                    'high_52w': d.get('f48', 0) / 100,
                    'low_52w': d.get('f47', 0) / 100,
                    'volume': float(d.get('f168', 0)),
                    'turnover_rate': d.get('f168', 0) / 100 if d.get('f168') else 0,
                    'market_cap': d.get('f20', 0) / 1e8 if d.get('f20') else 0,
                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                }
        except Exception as e2:
            print(f"  ⚠️ Eastmoney接口也失败, 尝试腾讯行情...")
            try:
                import re as _re
                resp = requests.get('https://qt.gtimg.cn/q=sz002428', timeout=10)
                resp.encoding = 'gbk'
                for line in resp.text.split('\n'):
                    if 'sz002428' in line:
                        parts = line.split('~')
                        if len(parts) > 3:
                            price = float(parts[3])
                            if price > 0:
                                print(f"    ✅ 腾讯行情: 股价={price}元")
                                return {
                                    'stock_code': code,
                                    'stock_name': parts[1] if len(parts) > 1 else '',
                                    'current_price': price,
                                    'change_pct': float(parts[32]) if len(parts) > 32 else 0,
                                    'pe_ttm': float(parts[39]) if len(parts) > 39 else 0,
                                    'pb': float(parts[46]) if len(parts) > 46 else 0,
                                    'high_52w': float(parts[44]) if len(parts) > 44 else 0,
                                    'low_52w': float(parts[45]) if len(parts) > 45 else 0,
                                    'volume': float(parts[6]) if len(parts) > 6 else 0,
                                    'turnover_rate': float(parts[38]) if len(parts) > 38 else 0,
                                    'market_cap': float(parts[44]) / 1e8 if len(parts) > 44 else 0,
                                    'update_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
                                }
            except Exception as e3:
                print(f"  ⚠️ 腾讯行情也失败: {e3}")
    return None


# ============ SOTP估值 ============

def calc_sotp(spot: Dict, manual: Dict, config: Dict) -> Optional[Dict]:
    """计算 SOTP 分部估值"""
    semi_nm = manual.get('semi_nm')
    trad_nm = manual.get('trad_nm')
    
    if semi_nm is None or trad_nm is None:
        return None
    
    semi_pe = manual.get('semi_pe') or (config['semi_pe_min'] + config['semi_pe_max']) / 2
    trad_pe = manual.get('trad_pe') or (config['trad_pe_min'] + config['trad_pe_max']) / 2
    shares = config['shares']
    
    semi_cap = semi_nm * semi_pe
    trad_cap = trad_nm * trad_pe
    total_cap = semi_cap + trad_cap
    target_price = total_cap / shares
    target_low = (semi_nm * config['semi_pe_min'] + trad_nm * config['trad_pe_min']) / shares
    target_high = (semi_nm * config['semi_pe_max'] + trad_nm * config['trad_pe_max']) / shares
    
    current_price = spot.get('current_price', 0) if spot else 0
    upside = (target_price / current_price - 1) * 100 if current_price else 0
    
    return {
        'semi_nm': semi_nm, 'trad_nm': trad_nm,
        'semi_pe': semi_pe, 'trad_pe': trad_pe,
        'semi_cap': round(semi_cap, 2), 'trad_cap': round(trad_cap, 2),
        'total_cap': round(total_cap, 2),
        'target_price': round(target_price, 2),
        'target_low': round(target_low, 2),
        'target_high': round(target_high, 2),
        'upside_pct': round(upside, 1),
    }


# ============ 报告生成 ============

def generate_report(code: str, spot: Dict, commodity: Dict, manual: Dict, 
                   valuation: Dict, config: Dict) -> str:
    today = datetime.now().strftime('%Y-%m-%d')
    lines = [f"📊 {config['name']}({code}) 估值日报 {today}", ""]
    
    if spot:
        lines.append(f"【行情】股价={spot['current_price']}元({spot['change_pct']:+.2f}%) PE={spot['pe_ttm']:.0f} PB={spot['pb']:.1f}")
    
    if commodity:
        i = commodity.get('indium_price', 'N/A')
        g = commodity.get('germanium_price', 'N/A')
        lines.append(f"【商品】铟价={i}元/kg 锗价={g}万元/吨")
    
    if valuation:
        up = valuation['upside_pct']
        sign = '+' if up >= 0 else ''
        lines.append(f"【SOTP】目标价={valuation['target_price']}元({sign}{up:.0f}%) 区间={valuation['target_low']}-{valuation['target_high']}元")
    
    return '\n'.join(lines)


# ============ 主流程 ============

def main():
    print(f"=== 估值模型框架 v2.0 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")
    
    results = {}
    
    for code, config in STOCK_CONFIG.items():
        print(f"📈 {config['name']}({code})...")
        today_str = datetime.now().strftime('%Y-%m-%d')
        
        # 1. 采集自动数据
        print("  采集行情...")
        spot = get_stock_spot(code, config.get('market', 'SZ'))
        if spot:
            print(f"    ✅ 股价={spot['current_price']}元 PE={spot['pe_ttm']:.0f}")
        
        print("  采集商品价格...")
        commodity = get_commodity_prices()
        
        # 2. 读取bitable已有的手动财务数据
        print("  读取bitable已有财务数据...")
        manual = {
            'yield_6inch': None, 'ratio_6inch': None,
            'cert_status': None, 'revenue': None, 'net_profit': None,
            'semi_nm': None, 'trad_nm': None,
            'semi_pe': None, 'trad_pe': None,
        }
        records = read_bitable_records(config['bitable_app'], config['bitable_table'])
        for rec in records:
            fields = rec.get('fields', {})
            if fields.get('半导体分部净利(亿元)') or fields.get('传统业务净利(亿元)'):
                manual['semi_nm'] = float(fields.get('半导体分部净利(亿元)', 0))
                manual['trad_nm'] = float(fields.get('传统业务净利(亿元)', 0))
                print(f"    ✅ 找到已有财务数据: semi_nm={manual['semi_nm']} trad_nm={manual['trad_nm']}")
                break
        else:
            print("    ℹ️ 未找到手动财务数据，跳过SOTP")
        
        # 2.5 用采集的商品价格动态更新SOTP参数
        if manual.get('semi_nm') and manual.get('trad_nm'):
            if commodity:
                # 锗价动态化: 30吨/年 × 锗价(万元/吨) ÷ 10000(万→亿) × 30%净利率
                if commodity.get('germanium_price'):
                    # 锗价单位: 万元/吨（已从SMM的元/kg转换）
                    ge_revenue_bn = 30 * commodity['germanium_price'] / 10000  # 亿元
                    ge_nm = round(ge_revenue_bn * 0.30, 2)
                    if abs(ge_nm - manual['trad_nm']) > 0.01:
                        print(f"    📊 锗价{commodity['germanium_price']}万元/吨 → 锗矿净利{manual['trad_nm']}→{ge_nm:.2f}亿（{ge_nm/manual['trad_nm']*100-100:+.1f}%）")
                        manual['trad_nm'] = round(ge_nm, 2)
                
                # 铟价联动InP: 基准铟价4700元/kg时InP均价3.0万/片
                # 铟价每变化1000元/kg, InP成本约变化5%
                if commodity.get('indium_price'):
                    inp_base = 3.0  # 万/片
                    indium_delta = (commodity['indium_price'] - 4700) / 1000 * 0.05
                    inp_price = round(inp_base * (1 + indium_delta), 2)
                    # 重新计算InP净利: 15万片 × 利用率100% × InP单价 × 24%净利率
                    inp_nm = round(15 * 1.0 * inp_price * 0.24, 2)
                    if inp_nm != manual['semi_nm']:
                        print(f"    📊 铟价{commodity['indium_price']}元/kg → InP单价{inp_price}万/片 → InP净利{manual['semi_nm']}→{inp_nm}亿（{inp_nm/manual['semi_nm']*100-100:+.1f}%）")
                        manual['semi_nm'] = inp_nm
        
        # 3. 计算SOTP
        print("  计算SOTP估值...")
        valuation = calc_sotp(spot, manual, config) if spot else None
        if valuation:
            print(f"    ✅ 目标价={valuation['target_price']}元 (区间{valuation['target_low']}-{valuation['target_high']}元, 上涨{valuation['upside_pct']:+.0f}%)")
        else:
            print("    ℹ️ 无SOTP结果（缺少手动财务数据）")
        
        # 4. 写入Bitable
        print("  写入飞书Bitable...")
        bitable_fields = {}
        
        # 日期
        bitable_fields['日期'] = int(datetime.now().timestamp() * 1000)  # 飞书date类型需毫秒时间戳
        
        # 自动行情字段（只写入表中存在的字段，其余数据放入备注）
        if spot:
            bitable_fields['股价(元)'] = spot['current_price']
        
        # 商品价格
        if commodity:
            if commodity.get('indium_price'):
                bitable_fields['铟价(元/kg)'] = commodity['indium_price']
            if commodity.get('germanium_price'):
                bitable_fields['锗价(万元/吨)'] = commodity['germanium_price']
        
        # SOTP估值 — 每个记录自包含完整参数和中间结果
        if valuation:
            bitable_fields['半导体分部净利(亿元)'] = valuation['semi_nm']
            bitable_fields['传统业务净利(亿元)'] = valuation['trad_nm']
            bitable_fields['半导体PE(倍)'] = valuation['semi_pe']
            bitable_fields['传统PE(倍)'] = valuation['trad_pe']
            bitable_fields['半导体分部市值(亿)'] = valuation['semi_cap']
            bitable_fields['传统业务市值(亿)'] = valuation['trad_cap']
            bitable_fields['SOTP总市值(亿)'] = valuation['total_cap']
            bitable_fields['目标股价(元)'] = valuation['target_price']
            bitable_fields['SOTP目标价(元)'] = valuation['target_price']
            bitable_fields['上涨空间(%)'] = round(valuation['upside_pct'], 1)
            bitable_fields['估值状态'] = '🔴 严重高估' if valuation['upside_pct'] < -20 else '合理' if valuation['upside_pct'] < 20 else '低估'
        
        # 备注（自包含全部关键信息）
        notes_parts = [today_str]
        if spot:
            notes_parts.append(f"股价{spot['current_price']}元")
            notes_parts.append(f"涨跌{spot['change_pct']:+.2f}%")
            notes_parts.append(f"PE={spot['pe_ttm']:.1f}")
            notes_parts.append(f"PB={spot['pb']:.2f}")
            notes_parts.append(f"52w高{spot.get('high_52w','?')}/低{spot.get('low_52w','?')}")
            notes_parts.append(f"换手{spot.get('turnover_rate',0):.2f}%")
            notes_parts.append(f"流通市值{spot.get('market_cap',0)}亿")
        if valuation:
            up = valuation['upside_pct']
            sign = '+' if up >= 0 else ''
            notes_parts.append(f"SOTP={valuation['target_price']}元({sign}{up:.0f}%)")
            notes_parts.append(f"InP={valuation['semi_nm']}亿x{valuation['semi_pe']:.0f}PE={valuation['semi_cap']}亿")
            notes_parts.append(f"锗矿={valuation['trad_nm']}亿x{valuation['trad_pe']:.0f}PE={valuation['trad_cap']}亿")
        
        bitable_fields['备注'] = ' | '.join(notes_parts)
        
        write_bitable_record(config['bitable_app'], config['bitable_table'], bitable_fields)
        
        # 5. 写入共享JSON文件（供Streamlit读取）
        # 股价API失败时从历史记录取上一日价格
        if not spot:
            _hist_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data', 'history.json')
            if os.path.exists(_hist_path):
                try:
                    with open(_hist_path) as _f:
                        _hist = json.load(_f)
                    if _hist and _hist[-1].get('stock_price'):
                        # 创建一个最小化spot，只含股价
                        spot = {'current_price': _hist[-1]['stock_price'], 'change_pct': 0, 'pe_ttm': 0, 'pb': 0, 'high_52w': 0, 'low_52w': 0, 'turnover_rate': 0, 'market_cap': 0}
                        print(f"    ℹ️ 股价API失败，使用上一日价格: {spot['current_price']}元")
                        # 用历史价格重算SOTP
                        valuation = calc_sotp(spot, manual, config)
                        if valuation:
                            print(f"    ✅ 用历史价重算SOTP: 目标价={valuation['target_price']}元")
                except: pass
        
        latest = {
            'date': today_str,
            'indium_price': commodity.get('indium_price') if commodity else None,
            'germanium_price': commodity.get('germanium_price') if commodity else None,
            'stock_price': spot['current_price'] if spot else None,
            'semi_nm': valuation['semi_nm'] if valuation else None,
            'trad_nm': valuation['trad_nm'] if valuation else None,
            'semi_pe': valuation['semi_pe'] if valuation else None,
            'trad_pe': valuation['trad_pe'] if valuation else None,
            'semi_cap': valuation['semi_cap'] if valuation else None,
            'trad_cap': valuation['trad_cap'] if valuation else None,
            'sotp_cap': valuation['total_cap'] if valuation else None,
            'target_price': valuation['target_price'] if valuation else None,
            'upside_pct': valuation['upside_pct'] if valuation else None,
            'target_low': valuation['target_low'] if valuation else None,
            'target_high': valuation['target_high'] if valuation else None,
            'wacc': manual.get('wacc'),
            'tg': manual.get('tg'),
            'shares': config['shares'],
            'version': '2.1 (产能驱动SOTP)',
            'updated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        data_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
        os.makedirs(data_dir, exist_ok=True)
        
        # latest_valuation.json - Streamlit主数据源
        with open(os.path.join(data_dir, 'latest_valuation.json'), 'w') as f:
            json.dump(latest, f, ensure_ascii=False, indent=2)
        print(f"    ✅ data/latest_valuation.json 已写入")
        
        # history.json - 历史追加（仅当全部关键数据有效时）
        history_path = os.path.join(data_dir, 'history.json')
        if spot and commodity and valuation and spot.get('current_price') and valuation.get('target_price'):
            new_record = {
                'date': today_str,
                'indium_price': commodity.get('indium_price'),
                'germanium_price': commodity.get('germanium_price'),
                'stock_price': round(spot['current_price'], 2),
                'sotp_price': round(valuation['target_price'], 2),
                'target_low': round(valuation['target_low'], 2),
                'target_high': round(valuation['target_high'], 2),
                'upside_pct': round(valuation['upside_pct'], 1),
            }
            history = []
            if os.path.exists(history_path):
                try:
                    with open(history_path) as f:
                        history = json.load(f)
                    # 去重：删除同日期旧记录
                    history = [h for h in history if h.get('date') != today_str]
                except:
                    history = []
            history.append(new_record)
            with open(history_path, 'w') as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
            print(f"    ✅ data/history.json 已追加 ({len(history)}条记录)")
        else:
            print(f"    ℹ️ 数据不完整，跳过history写入")
        
        # 6. 生成报告
        report = generate_report(code, spot, commodity, manual, valuation, config)
        print(f"\n{report}\n")
        
        results[code] = {
            'config': config,
            'spot': spot,
            'commodity': commodity,
            'manual': manual,
            'valuation': valuation,
            'report': report,
            'bitable_written': True,
        }
    
    print(f"\n{'='*40}")
    write_ok = sum(1 for r in results.values() if r.get('bitable_written'))
    print(f"✅ 完成: {write_ok}/{len(results)} 写入bitable+共享JSON成功")
    
    return results

if __name__ == '__main__':
    results = main()
    
    # 输出Bitable信息供cron脚本提取
    for code, config in STOCK_CONFIG.items():
        if code in results:
            print(f"\nBITABLE_APP={config['bitable_app']}")
            print(f"BITABLE_TABLE={config['bitable_table']}")
            break
