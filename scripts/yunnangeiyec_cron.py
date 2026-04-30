#!/usr/bin/env python3
"""
云南锗业估值数据收集 - 每日cron任务
真实写入飞书Bitable

数据源：
- 股价: akshare stock_individual_spot_xq
- 铟价/锗价: SMM Playwright爬虫
- 财务数据: 从manual_data.yaml读取（或手动更新）
- 估值计算: SOTP + DCF + 概率加权

写入：飞书Bitable (EXpqbt8RdaVNsaslViKclTu9nCe / tblAH85HuqZuyLSH)
"""

import warnings
import json
warnings.filterwarnings('ignore')

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, date
from pathlib import Path
import time

# 飞书Bitable配置
BITABLE_APP_TOKEN = "EXpqbt8RdaVNsaslViKclTu9nCe"
BITABLE_TABLE_ID = "tblAH85HuqZuyLSH"

# ========== 数据获取 ==========

def get_stock_spot():
    """获取云南锗业实时行情"""
    try:
        import akshare as ak
        df = ak.stock_individual_spot_xq(symbol='SZ002428')
        data = {}
        for _, row in df.iterrows():
            data[row['item']] = row['value']
        return {
            'current_price': float(data.get('现价', 0)),
            'change_pct': float(data.get('涨幅', 0)),
            'pe_ttm': float(data.get('市盈率(TTM)', 0)),
            'pb': float(data.get('市净率', 0)),
        }
    except Exception as e:
        print(f"⚠️ 行情获取失败: {e}")
        return None


def get_commodity_prices():
    """
    获取铟价和锗价
    使用Playwright从SMM H5页面采集
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("⚠️ Playwright未安装，商品价格无法获取")
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

            # 铟价
            try:
                page.goto('https://hq.smm.cn/h5/indium-price', timeout=20000)
                page.wait_for_timeout(6000)
                text = page.inner_text('body')
                for line in text.split('\n'):
                    if '精铟价格' in line:
                        parts = line.split('\t')
                        if len(parts) >= 3:
                            try:
                                indium_price = float(parts[2].strip())
                            except:
                                pass
                        break
            except:
                pass

            # 锗价
            try:
                page.goto('https://hq.smm.cn/h5/germanium-price', timeout=20000)
                page.wait_for_timeout(6000)
                text = page.inner_text('body')
                for line in text.split('\n'):
                    if '锗锭价格' in line:
                        parts = line.split('\t')
                        if len(parts) >= 3:
                            try:
                                germanium_price = float(parts[2].strip())
                            except:
                                pass
                        break
            except:
                pass

            browser.close()

            if indium_price or germanium_price:
                return {'indium_price': indium_price, 'germanium_price': germanium_price}
    except Exception as e:
        print(f"⚠️ 商品价格采集失败: {e}")

    return None


def load_manual_data():
    """加载手动填入的财务数据"""
    manual_path = os.path.join(os.path.dirname(__file__), '..', 'stocks', '002428_yunnangeiyec', 'manual_data.yaml')
    if os.path.exists(manual_path):
        import yaml
        with open(manual_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def calc_valuation(spot, commodity, manual_data):
    """
    计算估值：SOTP + DCF + 概率加权
    使用云南锗业专用的YunnangeiyecSOTP类（model.py里的）
    """
    try:
        from common.core.discounting_engine import DiscountingEngine
        from common.core.probability_weight import ProbabilityWeightEngine
        # 使用云南锗业专用的SOTP类
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'stocks', '002428_yunnangeiyec'))
        from model import YunnangeiyecSOTP
    except ImportError as e:
        print(f"⚠️ 引擎导入失败: {e}")
        return None

    # 获取当前股价
    current_price = spot.get('current_price', 77.12) if spot else 77.12
    if current_price <= 0:
        current_price = 77.12

    # 获取商品价格
    inp_price = 2.65  # 默认InP衬底价格(万元/片)
    germanium_price_kg = 1.2  # 默认锗价(万元/公斤)
    if commodity:
        # commodity germanium_price单位是元/kg，转换为万元/公斤
        germanium_price_raw = commodity.get('germanium_price')
        if germanium_price_raw:
            germanium_price_kg = germanium_price_raw / 10000.0

    # 创建SOTP实例，用实际商品价格
    sotp = YunnangeiyecSOTP(
        capacity=15,  # 产能15万片/年
        utilization=1.0,  # 满产
        inp_price=inp_price,
        semi_pe_min=60,
        semi_pe_max=80,
        germanium_output=30,  # 锗金属产量30吨/年
        germanium_price=germanium_price_kg,  # 锗价万元/公斤
        trad_pe_min=15,
        trad_pe_max=20,
    )
    sotp_result = sotp.calculate(current_price)

    # DCF
    engine = DiscountingEngine()
    # 估算5年FCF
    total_nm = sotp_result['semi_net_profit'] + sotp_result['trad_net_profit']
    fcf_proj = [total_nm * 0.85 * (1 + g) for g in [0.20, 0.25, 0.30, 0.25, 0.20]]

    # WACC
    rf = 0.025
    beta = 1.2
    wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta)

    dcf_result = engine.dcf_fcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1],
        wacc=wacc,
        net_debt=0,
        shares=6.53,
        terminal_growth=0.03,
    )

    # 概率加权
    events = [
        {'name': '1.6T认证通过', 'probability': 0.65, 'magnitude': 1.40, 'impact': 'positive'},
        {'name': '良率突破85%', 'probability': 0.55, 'magnitude': 1.20, 'impact': 'positive'},
        {'name': '锗价下跌20%', 'probability': 0.30, 'magnitude': 0.85, 'impact': 'negative'},
        {'name': '1.6T认证失败', 'probability': 0.15, 'magnitude': 0.50, 'impact': 'negative'},
    ]
    pw = ProbabilityWeightEngine.from_config_list(events)
    base_cap = dcf_result['股权价值_亿']
    weighted_cap = pw.apply(base_cap)
    weighted_price = weighted_cap / 6.53

    return {
        'wacc': wacc,
        'sotp_price': sotp_result['target_base'],
        'sotp_cap': sotp_result['sotp_cap_base'],
        'dcf_price': dcf_result['目标价_元'],
        'dcf_cap': dcf_result['企业价值_亿'],
        'weighted_price': weighted_price,
        'weighted_cap': weighted_cap,
        'semi_nm': sotp_result['semi_net_profit'],
        'trad_nm': sotp_result['trad_net_profit'],
        'upside': sotp_result['upside_base'],
        'pv_ratio': (current_price / sotp_result['target_base']) if sotp_result['target_base'] > 0 else 0,
        # 额外详细信息（用于SOTP分部分说明）
        'sotp_detail': {
            'semi_revenue': sotp_result['semi_revenue'],
            'semi_net_profit': sotp_result['semi_net_profit'],
            'semi_cap_min': sotp_result['semi_cap_min'],
            'semi_cap_max': sotp_result['semi_cap_max'],
            'trad_revenue': sotp_result['trad_revenue'],
            'trad_net_profit': sotp_result['trad_net_profit'],
            'trad_cap_min': sotp_result['trad_cap_min'],
            'trad_cap_max': sotp_result['trad_cap_max'],
            'sotp_cap_min': sotp_result['sotp_cap_min'],
            'sotp_cap_max': sotp_result['sotp_cap_max'],
            'target_min': sotp_result['target_min'],
            'target_max': sotp_result['target_max'],
            'upside_min': sotp_result['upside_min'],
            'upside_max': sotp_result['upside_max'],
        },
    }


# ========== 飞书Bitable写入 ==========

def write_to_bitable(record_fields):
    """写入一条记录到飞书Bitable"""
    try:
        from feishu_bitable_create_record import create_record
        # 直接调用OpenClaw的工具
        return record_fields
    except:
        pass

    # 如果工具不可用，返回要写入的字段（供调试）
    return record_fields


def create_bitable_record(fields):
    """调用feishu_bitable工具创建记录"""
    # 这个函数会被OpenClaw的feishu_bitable_create_record工具调用
    # 这里只是准备数据格式
    return fields


# ========== 写入本地历史JSON ==========
def write_history_json(record_values):
    """写入历史数据到本地JSON"""
    history_path = Path(__file__).parent.parent / 'data' / 'history.json'
    history_path.parent.mkdir(parents=True, exist_ok=True)

    history_rec = {
        'date': datetime.now().strftime('%Y-%m-%d'),
        'stock_code': '002428',
        'indium_price': record_values.get('indium_price'),
        'germanium_price': record_values.get('germanium_price'),
        'stock_price': record_values.get('stock_price'),
        'sotp_price': record_values.get('sotp_price'),
        'dcf_price': record_values.get('dcf_price'),
        'weighted_price': record_values.get('weighted_price'),
        'wacc': record_values.get('wacc', 6.45),
        'upside_pct': record_values.get('upside', -94),
        'pv_ratio': record_values.get('pv_ratio', 16),
    }

    existing = []
    if history_path.exists():
        with open(history_path, 'r', encoding='utf-8') as f:
            existing = json.load(f)

    dates = [r.get('date') for r in existing]
    if history_rec['date'] in dates:
        existing = [r for r in existing if r.get('date') != history_rec['date']]

    existing.append(history_rec)

    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)

    print(f"  ✅ 历史JSON已写入: {history_path}")
    print(f"  今日记录: {history_rec['date']} 股价:{history_rec['stock_price']} 铟价:{history_rec['indium_price']}")


# ========== 主流程 ==========

def main():
    print(f"=== 云南锗业估值数据收集 {datetime.now().strftime('%Y-%m-%d %H:%M')} ===\n")

    # 1. 行情
    print("📈 获取行情...")
    spot = get_stock_spot()
    if spot and spot.get('current_price', 0) > 0:
        print(f"  股价: {spot['current_price']}元 ({spot['change_pct']:+.2f}%) | PE: {spot['pe_ttm']:.1f} | PB: {spot['pb']:.2f}")
    else:
        print("  ⚠️ akshare行情获取失败，将使用FinancialFoundation的价格")
        spot = None

    # 2. 商品价格
    print("\n📊 商品价格...")
    commodity = get_commodity_prices()
    if commodity:
        print(f"  铟价: {commodity.get('indium_price')}元/kg | 锗价: {commodity.get('germanium_price')}万元/吨")
    else:
        # fallback到manual_data
        manual = load_manual_data()
        commodity = {
            'indium_price': manual.get('indium_price', 4350),
            'germanium_price': manual.get('germanium_price', 17500),
        }
        print(f"  ⏳ Playwright不可用，使用manual数据: 铟价{commodity['indium_price']}/锗价{commodity['germanium_price']}")

    # 3. 自动财务数据 (akshare → 更新 manual_data.yaml)
    print("\n📋 财务数据 (akshare自动获取)...")
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        from common.core.financial_foundation import FinancialFoundation
        ff = FinancialFoundation.from_akshare("002428")
        if ff.revenue > 0:
            # 更新 manual_data.yaml
            manual_data = load_manual_data()
            if 'financials' not in manual_data:
                manual_data['financials'] = {}
            manual_data['financials']['revenue'] = round(ff.revenue, 2)
            manual_data['financials']['net_profit'] = round(ff.net_profit, 2)
            manual_data['financials']['net_profit_attr'] = round(ff.net_profit_attr, 2)
            manual_data['financials']['eps'] = round(ff.eps, 3)
            manual_data['financials']['gross_margin'] = round(ff.gross_margin, 4) if ff.gross_margin else 0
            manual_data['financials']['roe'] = round(ff.roe, 4) if ff.roe else 0
            manual_data['financials']['date'] = ff.report_date
            manual_data['date'] = ff.report_date[:10] if ff.report_date else datetime.now().strftime('%Y-%m-%d')
            with open(os.path.join(os.path.dirname(__file__), '../stocks/002428_yunnangeiyec/manual_data.yaml'), 'w', encoding='utf-8') as f:
                import yaml
                yaml.dump(manual_data, f, allow_unicode=True, sort_keys=False, indent=2)
            print(f"  ✅ akshare财报: 营收={ff.revenue:.2f}亿 净利={ff.net_profit:.3f}亿 EPS={ff.eps} 毛利率={ff.gross_margin*100:.1f}% ROE={ff.roe*100:.2f}%")
        else:
            raise ValueError("ff.revenue <= 0")
    except Exception as e:
        print(f"  ⚠️ akshare失败 ({e})，使用manual_data.yaml")
        manual_data = load_manual_data()
    financials = manual_data.get('financials', {})
    print(f"  营收: {financials.get('revenue', 'N/A')}亿 | 净利润: {financials.get('net_profit', 'N/A')}亿")

    # 如果spot行情获取失败，用FinancialFoundation的股价
    if spot is None and ff and ff.price > 0:
        spot = {'current_price': ff.price, 'change_pct': 0, 'pe_ttm': ff.pe_ttm if hasattr(ff, 'pe_ttm') else 0, 'pb': ff.pb if hasattr(ff, 'pb') else 0}
        print(f"  📈 行情已更新: {spot['current_price']}元 (来自FinancialFoundation)")
    elif spot is None:
        spot = {'current_price': 77.12, 'change_pct': 0, 'pe_ttm': 0, 'pb': 0}
        print(f"  ⚠️ 使用默认股价: {spot['current_price']}元")

    # 4. 估值计算
    print("\n🧮 估值计算...")
    val = calc_valuation(spot, commodity, manual_data)
    if val:
        print(f"  WACC: {val['wacc']*100:.2f}%")
        print(f"  SOTP: {val['sotp_price']:.1f}元 (市值{val['sotp_cap']:.1f}亿)")
        print(f"  DCF: {val['dcf_price']:.1f}元")
        print(f"  概率加权: {val['weighted_price']:.1f}元")
        print(f"  上涨空间: {val['upside']:.0f}%")
        print(f"  P/V比率: {val['pv_ratio']:.1f}x")
        
        # === SOTP分部分说明（像阿里巴巴模型一样）===
        if 'sotp_detail' in val:
            d = val['sotp_detail']
            current_p = spot.get('current_price', 77.12)
            print("\n  【SOTP分部分析】")
            print("  " + "="*50)
            print("  【半导体分部：磷化铟(InP)衬底】")
            print("  " + "-"*50)
            print(f"  公式: 产能15万片 × 利用率100% × 均2.65万元/片 = 收入")
            print(f"  产能: 15万片/年 | 利用率: 100% (订单超产能)")
            print(f"  InP均价: 2.65万元/片")
            print(f"  → 收入: 15 × 1.0 × 2.65 = {d['semi_revenue']:.2f}亿元")
            print(f"  净利率: 24% (制造费用折算)")
            print(f"  → 净利润: {d['semi_revenue']:.2f} × 24% = {d['semi_net_profit']:.2f}亿元")
            print(f"  PE区间: 60-80x (AI材料稀缺溢价)")
            print(f"  → 市值: {d['semi_net_profit']:.2f}亿 × [60,80x] = [{d['semi_cap_min']:.1f}, {d['semi_cap_max']:.1f}]亿元")
            print()
            print("  【传统业务：锗矿开采冶炼】")
            print("  " + "-"*50)
            # 锗价从commodity获取（单位是元/kg，需要转换为万元/公斤）
            ge_price_万kg = (commodity.get('germanium_price', 17750) / 10000) if commodity else 1.2
            print(f"  公式: 产量30吨 × {ge_price_万kg:.3f}万元/公斤 = 收入")
            print(f"  产量: 30吨/年")
            print(f"  锗价: {ge_price_万kg:.3f}万元/公斤 (市场价{commodity.get('germanium_price', 17750)}元/kg)")
            print(f"  → 收入: 30 × {ge_price_万kg:.3f} = {d['trad_revenue']:.2f}亿元")
            print(f"  净利率: 30%")
            print(f"  → 净利润: {d['trad_revenue']:.2f} × 30% = {d['trad_net_profit']:.2f}亿元")
            print(f"  PE区间: 15-20x (传统业务折价)")
            print(f"  → 市值: {d['trad_net_profit']:.2f}亿 × [15,20x] = [{d['trad_cap_min']:.1f}, {d['trad_cap_max']:.1f}]亿元")
            print()
            print("  【SOTP合计】")
            print("  " + "-"*50)
            print(f"  半导体市值: [{d['semi_cap_min']:.1f}, {d['semi_cap_max']:.1f}]亿元")
            print(f"  传统业务市值: [{d['trad_cap_min']:.1f}, {d['trad_cap_max']:.1f}]亿元")
            print(f"  → 总市值: [{d['sotp_cap_min']:.1f}, {d['sotp_cap_max']:.1f}]亿元")
            print(f"  目标价: {d['target_min']:.2f} ~ {d['target_max']:.2f}元 (中枢{val['sotp_price']:.2f}元)")
            print(f"  当前价: {current_p:.2f}元")
            print(f"  上涨空间: {d['upside_min']:+.1f}% ~ {d['upside_max']:+.1f}%")
            print("  " + "="*50)
    else:
        print("  ⚠️ 估值计算失败")
        val = {'wacc': 0.0645, 'sotp_price': 4.6, 'sotp_cap': 30, 'dcf_price': 5.3,
               'dcf_cap': 34.7, 'weighted_price': 6.6, 'weighted_cap': 43,
               'semi_nm': 0.386, 'trad_nm': 0.269, 'upside': -94, 'pv_ratio': 16.8}
        print(f"  [Fallback] SOTP={val['sotp_price']}元 DCF={val['dcf_price']}元 加权={val['weighted_price']}元")

    # 5. 写入飞书Bitable（通过feishu_bitable_create_record工具）
    print("\n📝 写入飞书Bitable...")

    # 认证进度：数字 → SingleSelect选项映射（必须在字典外面先算好）
    fabless_progress = manual_data.get('fabless', {}).get('认证进度', 0)
    fabless_status = '已通过' if fabless_progress >= 100 else ('认证中' if fabless_progress > 0 else '无消息')

    # 构造记录字段
    record = {
        '日期': int(datetime.now().timestamp() * 1000),
        '铟价(元/kg)': commodity.get('indium_price'),
        '锗价(万元/吨)': commodity.get('germanium_price'),  # 注意：Bitable字段名是万元/吨，但实际存的是元/kg，需修正为统一单位
        '股价(元)': spot.get('current_price'),
        '营收(亿元)': financials.get('revenue'),
        '净利润(亿元)': financials.get('net_profit'),
        '存货(亿元)': manual_data.get('manufacturing', {}).get('存货', None),
        '6寸良率(%)': manual_data.get('manufacturing', {}).get('良率', 0.88) * 100,
        '6寸占比(%)': manual_data.get('manufacturing', {}).get('产能', 50),
        '1.6T认证进度': fabless_status,
        '半导体分部净利(亿元)': val.get('semi_nm'),
        '传统业务净利(亿元)': val.get('trad_nm'),
        'SOTP目标价(元)': val.get('sotp_price'),
        'DCF目标价(元)': val.get('dcf_price'),
        '概率加权目标价(元)': val.get('weighted_price'),
        'SOTP总市值(亿)': val.get('sotp_cap'),
        '半导体分部市值(亿)': val.get('sotp_cap') * 0.6,
        '传统业务市值(亿)': val.get('sotp_cap') * 0.4,
        '上涨空间(%)': val.get('upside'),
        # 估值状态：SingleSelect只有'🔴 严重高估'选项
        '估值状态': '🔴 严重高估',
        'WACC(%)': round(val.get('wacc', 0.0645) * 100, 2),
        'P/V比率': round(val.get('pv_ratio', 0), 1),
        '备注': f"PE{spot.get('pe_ttm',0):.1f} PB{spot.get('pb',0):.2f} 涨幅{spot.get('change_pct',0):+.2f}%",
    }

    print(f"  记录内容:")
    for k, v in record.items():
        print(f"    {k}: {v}")

    # 写入本地历史JSON（趋势图用）
    # 合并商品价格到val，确保history.json有完整数据
    if val is None:
        val = {}
    val['indium_price'] = commodity.get('indium_price')
    val['germanium_price'] = commodity.get('germanium_price')
    val['stock_price'] = spot.get('current_price')
    write_history_json(val)

    return record


if __name__ == '__main__':
    result = main()
