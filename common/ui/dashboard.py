#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Dashboard - 股票估值仪表盘 v3.0
支持多股票切换：云南锗业(002428) / 阿里巴巴(09988)

数据流：
- 历史数据：data/history.json（每日cron写入）
- 实时股价：akshare（A股）/ 新浪API（港股）
- 估值计算：本地引擎
"""

import sys
import streamlit as st
import pandas as pd
import json
import yaml
import re
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

from common.core.discounting_engine import DiscountingEngine

# ========== Page Config ==========
st.set_page_config(
    page_title="股票估值仪表盘",
    page_icon="📊",
    layout="wide",
)

# ========== 自定义CSS ==========
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1a1a2e;
        padding-bottom: 1rem;
        border-bottom: 2px solid #4CAF50;
        margin-bottom: 1.5rem;
    }
    .section-header {
        font-size: 1.3rem;
        font-weight: 600;
        color: #4CAF50;
        margin: 2rem 0 1rem 0;
    }
    .status-overvalued { background: #ffebee; color: #c62828; padding: 0.3rem 0.8rem; border-radius: 20px; }
    .status-undervalued { background: #e8f5e9; color: #2e7d32; padding: 0.3rem 0.8rem; border-radius: 20px; }
</style>
""", unsafe_allow_html=True)


# ========== Stock Registry ==========
STOCK_REGISTRY = {
    "002428": {
        "name": "云南锗业",
        "code": "002428",
        "market": "SZ",
        "currency": "CNY",
        "symbol_akshare": "SZ002428",
        "shares": 6.53,   # 亿股
        "config_path": "stocks/002428_yunnangeiyec/config.yaml",
        "manual_path": "stocks/002428_yunnangeiyec/manual_data.yaml",
        "fcf_proj": [0.67, 0.87, 1.22, 1.36, 1.39],  # 亿元
        "sotp_price_fixed": 4.6,  # 元 (中枢目标价)
    },
    "09988": {
        "name": "阿里巴巴",
        "code": "09988",
        "market": "HK",
        "currency": "HKD",
        "currency_symbol": "HK$",
        "symbol_sina": "hk09988",
        "shares": 191.9,  # 亿H股 (akshare总股本)
        "config_path": "stocks/09988_alibaba/config.yaml",
        "manual_path": "stocks/09988_alibaba/manual_data.yaml",
        "model_path": "stocks/09988_alibaba/model.py",
    },
    "06613": {
        "name": "蓝思科技",
        "code": "06613",
        "market": "HK",
        "currency": "HKD",
        "currency_symbol": "HK$",
        "symbol_tencent": "hk06613",
        "shares": 52.79,  # 亿股
        "config_path": "stocks/300433_lens/config.yaml",
        "manual_path": "stocks/300433_lens/manual_data.yaml",
        "model_path": "stocks/300433_lens/model.py",
        "hkd_cny_rate": 0.92,
    },
    "688608": {
        "name": "恒玄科技",
        "code": "688608",
        "market": "SH",
        "currency": "CNY",
        "symbol_tencent": "sh688608",
        "shares": 1.69,
        "config_path": "stocks/688608_hengxuan/config.yaml",
    },
}


# ========== Config Loading ==========
def load_stock_config(stock_code: str) -> Dict[str, Any]:
    """加载股票配置文件"""
    repo_root = Path(__file__).parent.parent.parent
    stock_info = STOCK_REGISTRY[stock_code]
    config_path = repo_root / stock_info["config_path"]
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def load_manual_data(stock_code: str) -> Dict[str, Any]:
    """加载股票手动数据"""
    repo_root = Path(__file__).parent.parent.parent
    stock_info = STOCK_REGISTRY[stock_code]
    manual_path = repo_root / stock_info["manual_path"]
    if manual_path.exists():
        with open(manual_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


# ========== Price Fetching ==========
@st.cache_data(ttl=300)
def get_price_002428() -> float:
    """获取云南锗业A股实时股价（腾讯行情API，优先）"""
    # 优先：腾讯行情API（不走代理，稳定）
    try:
        from common.stock_api import get_a_stock_quote
        quotes = get_a_stock_quote(['002428'])
        if quotes and quotes[0].get('price', 0) > 0:
            return float(quotes[0]['price'])
    except Exception as e:
        print(f"⚠️ 腾讯行情失败: {e}")
    except Exception:
        pass
    # fallback: akshare雪球API（可能失败）
    try:
        import akshare as ak
        df = ak.stock_individual_spot_xq(symbol='SZ002428')
        data = {}
        for _, row in df.iterrows():
            data[row['item']] = row['value']
        price = float(data.get('现价', 0))
        return price if price > 0 else 69.67  # 最新市场价fallback
    except Exception:
        return 69.67  # 最新市场价fallback


@st.cache_data(ttl=60)
def get_price_09988() -> float:
    """获取阿里巴巴港股实时股价（新浪API）"""
    try:
        import requests
        url = "https://hq.sinajs.cn/list=hk09988"
        headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}
        resp = requests.get(url, headers=headers, timeout=5)
        resp.encoding = 'gbk'
        text = resp.text.strip()
        # 格式: var hq_str_hk09988="阿里巴巴,131.800,131.600,131.800,132.200,130.600,131.600,131.800,..."
        m = re.search(r'"([^"]+)"', text)
        if m:
            fields = m.group(1).split(',')
            if len(fields) > 6:
                price = float(fields[6])  # 字段6是当前价
                if price > 0:
                    return price
    except Exception as e:
        pass
    # fallback: 从manual_data读取
    manual = load_manual_data("09988")
    return manual.get("market", {}).get("current_price", 131.8)


@st.cache_data(ttl=300)
def get_price_06613() -> float:
    """获取蓝思科技港股实时股价（HKD）"""
    try:
        import requests
        resp = requests.get('https://qt.gtimg.cn/q=hk06613', timeout=10)
        resp.encoding = 'gbk'
        for line in resp.text.split('\n'):
            if 'hk06613' in line:
                parts = line.split('~')
                price = float(parts[3]) if parts[3] else None
                return price if price and price > 0 else 16.70
    except Exception as e:
        print(f"⚠️ 腾讯行情HK06613失败: {e}")
    return 16.70  # fallback


def get_price_688608() -> float:
    """获取恒玄科技A股实时股价（CNY）"""
    try:
        import requests
        resp = requests.get('https://qt.gtimg.cn/q=sh688608', timeout=10)
        resp.encoding = 'gbk'
        for line in resp.text.split('\n'):
            if 'sh688608' in line:
                parts = line.split('~')
                price = float(parts[3]) if parts[3] else None
                return price if price and price > 0 else 170.70
    except Exception as e:
        print(f"⚠️ 腾讯行情SH688608失败: {e}")
    return 170.70  # fallback


def get_current_price(stock_code: str) -> float:
    """根据股票代码获取实时股价"""
    if stock_code == "002428":
        return get_price_002428()
    elif stock_code == "09988":
        return get_price_09988()
    elif stock_code == "06613":
        return get_price_06613()
    elif stock_code == "688608":
        return get_price_688608()
    return 0.0


# ========== WACC Calculation (with explicit units) ==========
def calc_wacc_safe(rf: float, beta: float, market_premium: float = 0.05,
                   cost_of_debt: float = 0.04, tax_rate: float = 0.15,
                   debt_ratio: float = 0.3) -> float:
    """
    安全计算WACC，确保单位一致。
    所有输入都应该是小数形式（如0.025表示2.5%）
    """
    engine = DiscountingEngine()
    # Explicitly pass all parameters to avoid config defaults issues
    wacc = engine.calc_wacc(
        risk_free_rate=rf,
        beta=beta,
        market_premium=market_premium,
        cost_of_debt=cost_of_debt,
        tax_rate=tax_rate,
        debt_ratio=debt_ratio,
    )
    return wacc


# ========== Valuation Models ==========
def run_yunnangeiyec_valuation(
    rf: float, beta: float, tg: float, current_price: float,
    cost_of_debt: float = 0.04, tax_rate: float = 0.15, debt_ratio: float = 0.3
) -> Dict[str, Any]:
    """
    云南锗业估值计算 — 使用直接计算的YunnangeiyecSOTP类

    与旧SOTPEngine的区别：
    - 旧: FablessPlugin，用"订单管道/BOM"算收入（65.7亿收入→15.8亿净利）
    - 新: YunnangeiyecSOTP，用"产能×利用率×单价"算收入（39.75亿收入→9.54亿净利）

    新公式（磷化铟衬底实际业务逻辑）：
      收入 = 产能(15万片) × 利用率(100%) × 单价(2.65万/片) = 39.75亿
      净利 = 收入 × 24% = 9.54亿
      市值 = 净利 × PE(60-80x) = [572, 763]亿
    """
    import warnings
    import sys
    warnings.filterwarnings('ignore')

    from common.core.discounting_engine import DiscountingEngine
    from common.core.sensitivity_runner import run_sensitivity_analysis, SensitivityConfig
    from common.core.financial_foundation import FinancialFoundation
    from pathlib import Path
    import importlib.machinery

    repo_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(repo_root))

    model_path = repo_root / 'stocks' / '002428_yunnangeiyec' / 'model.py'
    loader = importlib.machinery.SourceFileLoader('yunnangeiyec_model', str(model_path))
    yunnangeiyec_module = loader.load_module()
    YunnangeiyecSOTP = yunnangeiyec_module.YunnangeiyecSOTP
    # 验证导入成功
    _ = YunnangeiyecSOTP()

    # 加载配置和数据
    with open(repo_root / 'stocks/002428_yunnangeiyec/config.yaml') as f:
        config = yaml.safe_load(f)
    with open(repo_root / 'stocks/002428_yunnangeiyec/manual_data.yaml') as f:
        manual_data = yaml.safe_load(f) or {}

    meta = config['meta']
    shares = meta['total_shares']

    # 获取实时股价（优先腾讯API）
    ff = FinancialFoundation.from_akshare(meta['stock_code'])
    live_price = ff.price if ff.price > 0 else current_price

    # SOTP估值 — 使用YunnangeiyecSOTP直接计算（不走旧plugin系统）
    sotp = YunnangeiyecSOTP()
    sotp_result = sotp.calculate(live_price)

    sotp_price_min = sotp_result['target_min']
    sotp_price_max = sotp_result['target_max']
    sotp_price = sotp_result['target_base']
    sotp_cap_min = sotp_result['sotp_cap_min']
    sotp_cap_max = sotp_result['sotp_cap_max']
    sotp_cap_base = sotp_result['sotp_cap_base']
    semi_nm = sotp_result['semi_net_profit']
    trad_nm = sotp_result['trad_net_profit']
    total_nm = semi_nm + trad_nm

    # 兼容旧sotp_result格式（用于sensitivity runner）
    sotp_result_legacy = {
        '目标价_中枢_元': sotp_price,
        '目标价_区间_元': (sotp_price_min, sotp_price_max),
        'SOTP_总市値_中枢_亿': sotp_cap_base,
        'SOTP_总市値_区间_亿': (sotp_cap_min, sotp_cap_max),
        '总净利润_亿': total_nm,
        '当前价_元': live_price,
        '上涨空间_中枢_%': sotp_result['upside_base'],
        '上涨空间_区间_%': (sotp_result['upside_min'], sotp_result['upside_max']),
        '分部列表': [],
    }

    # WACC + DCF
    engine = DiscountingEngine()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta,
                                market_premium=0.05, auto_refresh_beta=True)

    # FCF估算（基于SOTP总净利）
    growth_rates = [0.20, 0.25, 0.30, 0.25, 0.20]
    fcf_proj = [total_nm * (1 + g) ** (i + 1) * 0.85 for i, g in enumerate(growth_rates)]
    fcf_proj = [round(x, 3) for x in fcf_proj]

    dcf_result = engine.compute_dcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1],
        wacc=wacc,
        net_debt=0.0,
        shares=shares,
        terminal_growth=tg,
    )
    dcf_price = dcf_result['目标价_元']

    # 概率加权
    events = config.get('events', [])
    weighted_price = None
    if events:
        from common.core.probability_weight import ProbabilityWeightEngine
        pw = ProbabilityWeightEngine.from_config_list(events)
        weighted_cap = pw.apply(sotp_cap_base)
        weighted_price = weighted_cap / shares

    # 敏感性分析（仅当sotp_engine可用且有配置时才运行）
    sa_cfg = config.get('sensitivity_analysis', {})
    sensitivity_result = None
    sensitivity_error = None
    if sa_cfg:  # 有敏感性分析配置才运行
        try:
            sensitivity_result = run_sensitivity_analysis(
                financials=ff,
                manual_data={},
                config=SensitivityConfig(
                    sotp_params=sa_cfg.get('sotp_params', {}),
                    dcf_wacc_range=tuple(sa_cfg.get('dcf_wacc_range', [0.06, 0.08, 0.10])),
                    dcf_tg_range=tuple(sa_cfg.get('dcf_tg_range', [0.02, 0.03, 0.04])),
                    shares=shares,
                ),
                sotp_engine=None,
                dcf_engine=engine,
                fcf_projections=fcf_proj,
            )
        except Exception as e:
            import traceback
            sensitivity_error = repr(e) + "\n" + traceback.format_exc()[:500]

    return {
        "sotp_price": sotp_price,
        "sotp_price_min": sotp_price_min,
        "sotp_price_max": sotp_price_max,
        "dcf_price": dcf_price,
        "weighted_price": weighted_price,
        "wacc": wacc,
        "wacc_pct": wacc * 100,
        "current_price": live_price,
        "fcf_proj": fcf_proj,
        "currency": "CNY",
        "currency_symbol": "¥",
        "sensitivity": sensitivity_result,
        "sensitivity_error": sensitivity_error,
        "sotp_result": sotp_result_legacy,
        # 额外诊断信息
        "semi_nm": semi_nm,
        "trad_nm": trad_nm,
        "total_nm": total_nm,
        "inp_revenue": sotp_result['semi_revenue'],
        "inp_price": 2.65,
        "capacity": 15,
    }


def run_alibaba_valuation(
    rf: float, beta: float, tg: float, current_price: float,
    cost_of_debt: float = 0.045, tax_rate: float = 0.15, debt_ratio: float = 0.25,
    core_pe_min: int = 18, core_pe_max: int = 28,
    cloud_pe_min: int = 30, cloud_pe_max: int = 45, intl_ps: float = 0.8
) -> Dict[str, Any]:
    """阿里巴巴估值计算"""
    import sys
    import importlib.machinery
    from pathlib import Path
    repo_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(repo_root))

    stock_info = STOCK_REGISTRY["09988"]
    shares = stock_info["shares"]

    # WACC
    wacc = calc_wacc_safe(rf, beta, market_premium=0.07,
                          cost_of_debt=cost_of_debt, tax_rate=tax_rate, debt_ratio=debt_ratio)

    # FCF projections (FY2026E~FY2030E)
    fcf_proj = [700, 780, 870, 970, 1080]

    # SOTP calculation (SourceFileLoader to handle digit-starting module name)
    model_path = repo_root / 'stocks' / '09988_alibaba' / 'model.py'
    loader = importlib.machinery.SourceFileLoader('alibaba_model', str(model_path))
    alibaba_model = loader.load_module()
    AlibabaSOTP = alibaba_model.AlibabaSOTP
    sotp_engine = AlibabaSOTP(
        core_pe_min=core_pe_min, core_pe_max=core_pe_max,
        cloud_pe_min=cloud_pe_min, cloud_pe_max=cloud_pe_max, intl_ps=intl_ps
    )
    sotp_result = sotp_engine.run(current_price=current_price)

    # DCF
    engine = DiscountingEngine()
    dcf_result = engine.compute_dcf(fcf_projections=fcf_proj, terminal_fcf=fcf_proj[-1], wacc=wacc, net_debt=0.0, shares=shares, terminal_growth=tg)

    # Convert DCF from CNY to HKD
    hkd_rate = 0.92
    dcf_price_hkd = dcf_result['目标价_元'] / hkd_rate

    # Probability weighted: additive expected value E[return] = Σ p_i×(m_i-1)
    config = load_stock_config("09988")
    events = config.get("events", [])
    sotp_mid_hkd = sotp_result.get('目标价_中枢_元', 0)  # sotp_result values are already in HKD

    if events:
        sotp_total_cny = sotp_result['总市值_亿_中枢']  # CNY亿
        return_factor = 1.0
        for ev in events:
            if ev['impact'] == 'positive':
                return_factor += ev['probability'] * (ev['magnitude'] - 1)
            else:
                return_factor -= ev['probability'] * (1 - ev['magnitude'])
        weighted_total = sotp_total_cny * return_factor
        weighted_price = weighted_total / shares / hkd_rate
    else:
        weighted_price = sotp_mid_hkd

    # 简化敏感性分析（基于SOTP参数档位）
    # 阿里巴巴的SOTP分部净利是核心驱动因素
    sa_cfg = config.get('sensitivity_analysis', {})
    sotp_params = sa_cfg.get('sotp_params', {
        '云业务净利': [0, 50, 100, 200],
        '核心商业净利': [500, 700, 900, 1100],
    })
    dcf_wacc_range = tuple(sa_cfg.get('dcf_wacc_range', [0.06, 0.08, 0.10]))
    dcf_tg_range = tuple(sa_cfg.get('dcf_tg_range', [0.02, 0.03, 0.04]))

    # 用当前分部净利做基准
    cloud_nm = sotp_result.get('分部列表', [{}])[1].get('分部净利润_亿', 0) if len(sotp_result.get('分部列表', [])) > 1 else 0
    core_nm = sotp_result.get('分部列表', [{}])[0].get('分部净利润_亿', 700) if sotp_result.get('分部列表', []) else 700

    # sotp_result['目标价_*'] 已经是 HKD，无需再除 hkd_rate
    sotp_min_hkd = sotp_result.get('目标价_区间_元', (0, 0))[0]
    sotp_max_hkd = sotp_result.get('目标价_区间_元', (0, 0))[1]

    sensitivity_simple = {
        'sotp_range': (sotp_min_hkd, sotp_max_hkd),
        'dcf_range': (dcf_price_hkd * 0.8, dcf_price_hkd * 1.3),
        'combined_range': (sotp_min_hkd * 0.9, sotp_max_hkd * 1.1),
        'recommended_target': sotp_mid_hkd,
        'recommended_range': (sotp_min_hkd, sotp_max_hkd),
        'sotp_params': sotp_params,
        'cloud_nm': cloud_nm,
        'core_nm': core_nm,
    }

    return {
        "sotp_price": sotp_mid_hkd,      # 中枢 (HKD)
        "sotp_min": sotp_min_hkd,          # 下限 (HKD)
        "sotp_max": sotp_max_hkd,          # 上限 (HKD)
        "dcf_price": dcf_price_hkd,
        "weighted_price": weighted_price,
        "wacc": wacc,
        "wacc_pct": wacc * 100,
        "current_price": current_price,
        "fcf_proj": fcf_proj,
        "currency": "HKD",
        "currency_symbol": "HK$",
        "sotp_detail": sotp_result,
        "sensitivity": sensitivity_simple,
    }


def run_lens_valuation(
    rf: float, beta: float, tg: float, current_price: float,
    cost_of_debt: float = 0.05, tax_rate: float = 0.15, debt_ratio: float = 0.3
) -> Dict[str, Any]:
    """蓝思科技(HK06613)估值计算"""
    import sys
    import importlib.machinery
    import warnings
    from pathlib import Path
    warnings.filterwarnings('ignore')

    repo_root = Path(__file__).parent.parent.parent
    # 先删除缓存的model，防止Python用错缓存的module
    import sys
    if 'model' in sys.modules:
        del sys.modules['model']
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / 'stocks' / '300433_lens'))

    try:
        from model import LensHK_SOTP
        from common.core.discounting_engine import DiscountingEngine
        from common.core.probability_weight import ProbabilityWeightEngine
        import yaml

        sotp = LensHK_SOTP.from_config()
        sotp_result = sotp.calculate(current_price)
        sotp_detail = sotp.get_sotp_detail()
        total_nm = sotp_result.get('total_net_profit', 0)
        shares = sotp_result.get('shares', 52.79)
        hkd_cny_rate = sotp_result.get('hkd_cny_rate', 0.92)

        growth_rates = [0.15, 0.18, 0.20, 0.18, 0.15]
        fcf_conv = 0.85
        fcf_proj = [round(total_nm * (1 + g) * fcf_conv, 2) for g in growth_rates]

        # DCF估值
        engine = DiscountingEngine()
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta,
                                    market_premium=0.07, auto_refresh_beta=True)
        dcf_result = engine.compute_dcf(
            fcf_projections=fcf_proj,
            terminal_fcf=fcf_proj[-1],
            wacc=wacc,
            net_debt=0.0,
            shares=shares,
            terminal_growth=tg,
        )
        dcf_price_hkd = dcf_result['目标价_元']

        # 概率加权
        import sys
        if 'yaml' not in sys.modules:
            import yaml
        config_path = repo_root / 'stocks/300433_lens/config.yaml'
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        events = cfg.get('events', [])
        weighted_price_hkd = None
        if events:
            pw = ProbabilityWeightEngine.from_config_list(events)
            sotp_cap_base = sotp_result.get('sotp_cap_base_hkd', 0)
            weighted_cap = pw.apply(sotp_cap_base)
            weighted_price_hkd = weighted_cap / shares

        return {
            "sotp_price": sotp_result.get('target_base_hkd'),
            "sotp_min": sotp_result.get('target_min_hkd', None),
            "sotp_max": sotp_result.get('target_max_hkd', None),
            "sotp_cap_base_hkd": sotp_result.get('sotp_cap_base_hkd'),
            "dcf_price": dcf_price_hkd,
            "weighted_price": weighted_price_hkd,
            "current_price": current_price,
            "sotp_detail": sotp_detail,
            "fcf_proj": fcf_proj,
            "wacc": wacc,
        }
    except Exception as e:
        import traceback
        st.error(f"⚠️ 蓝思科技估值计算失败: {str(e)[:200]}\n{traceback.format_exc()[:500]}")
        return {"sotp_price": 0, "dcf_price": 0, "current_price": current_price, "fcf_proj": [0, 0, 0, 0, 0]}



def run_hengxuan_valuation(
    rf: float, beta: float, tg: float, current_price: float,
    cost_of_debt: float = 0.04, tax_rate: float = 0.15, debt_ratio: float = 0.2
) -> Dict[str, Any]:
    """恒玄科技(688608)估值计算"""
    import warnings
    import yaml
    from pathlib import Path
    warnings.filterwarnings('ignore')

    repo_root = Path(__file__).parent.parent.parent
    # 先删除缓存的model，防止Python用错缓存的module
    import sys
    if 'model' in sys.modules:
        del sys.modules['model']
    sys.path.insert(0, str(repo_root))
    sys.path.insert(0, str(repo_root / 'stocks' / '688608_hengxuan'))
    sys.path.insert(0, str(repo_root / 'common'))

    try:
        from model import HengxuanSOTP
        from common.core.discounting_engine import DiscountingEngine
        from common.core.probability_weight import ProbabilityWeightEngine

        sotp = HengxuanSOTP.from_config()
        sotp_result = sotp.calculate(current_price)

        # 读取config中的events用于概率加权
        config_path = repo_root / 'stocks/688608_hengxuan/config.yaml'
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # DCF计算
        total_nm = sotp_result.get('total_net_profit', 0)
        shares = 1.69
        wacc = rf + beta * 0.045  # 科创板成长股WACC
        growth_rates = [0.20, 0.22, 0.20, 0.18, 0.15]
        fcf_conv = 0.65
        fcf_proj = [round(total_nm * (1 + g) * fcf_conv, 2) for g in growth_rates]

        engine = DiscountingEngine()
        dcf_result = engine.compute_dcf(
            fcf_projections=fcf_proj,
            terminal_fcf=fcf_proj[-1] * 1.03,
            wacc=wacc,
            net_debt=-5.0,  # 净现金约5亿
            shares=shares,
            terminal_growth=tg,
        )
        dcf_price = dcf_result['目标价_元']

        # 概率加权
        sotp_cap_base = sotp_result.get('sotp_cap_base', 0)
        events = config.get('events', [])
        weighted_price = None
        if events:
            pw = ProbabilityWeightEngine.from_config_list(events)
            weighted_cap = pw.apply(sotp_cap_base)
            weighted_price = weighted_cap / shares

        return {
            "sotp_price": sotp_result.get('target_base', 0),
            "sotp_min": sotp_result.get('target_min', None),
            "sotp_max": sotp_result.get('target_max', None),
            "dcf_price": dcf_price,
            "weighted_price": weighted_price,
            "current_price": current_price,
            "sotp_detail": sotp_result,
            "total_net_profit": total_nm,
            "fcf_proj": fcf_proj,
            "wacc": wacc,
            "wacc_pct": wacc * 100,
            "sotp_cap_base": sotp_cap_base,
        }
    except Exception as e:
        st.error(f"⚠️ 恒玄科技估值计算失败: {str(e)[:200]}")
        return {"sotp_price": 0, "dcf_price": 0, "current_price": current_price, "fcf_proj": [0, 0, 0, 0, 0]}

# ========== 趋势图 ==========
def render_trend(df: pd.DataFrame, stock_code: str):
    st.markdown('<p class="section-header">📈 历史趋势</p>', unsafe_allow_html=True)

    if df.empty:
        st.info("📋 暂无历史数据。每日08:00 cron任务运行后会写入数据。")
        st.caption("历史数据路径: data/history.json")
        return

    import altair as alt

    if stock_code == "002428":
        cols = st.columns(2)
        with cols[0]:
            if 'indium_price' in df.columns:
                st.markdown("**铟价 (元/kg)**")
                try:
                    indium_df = df[['indium_price']].dropna().reset_index()
                    indium_df.columns = ['date', 'value']
                    chart = alt.Chart(indium_df).mark_line(point=True).encode(x='date:T', y='value:Q').properties(height=200)
                    text_chart = alt.Chart(indium_df).mark_text(dy=-10, size=11, color='#333').encode(x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f'))
                    st.altair_chart(chart + text_chart, width="stretch")
                except Exception:
                    st.line_chart(df['indium_price'].dropna())
        with cols[1]:
            if 'germanium_price' in df.columns:
                st.markdown("**锗价 (万元/吨)**")
                try:
                    ge_df = df[['germanium_price']].dropna().reset_index()
                    ge_df.columns = ['date', 'value']
                    chart = alt.Chart(ge_df).mark_line(point=True).encode(x='date:T', y='value:Q').properties(height=200)
                    text_chart = alt.Chart(ge_df).mark_text(dy=-10, size=11, color='#333').encode(x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f'))
                    st.altair_chart(chart + text_chart, width="stretch")
                except Exception:
                    st.line_chart(df['germanium_price'].dropna())

    # 股价 vs 目标价
    if 'stock_price' in df.columns:
        st.markdown("**股价 vs 目标价**")
        price_cols = ['stock_price']
        for c in ['sotp_price', 'dcf_price', 'weighted_price']:
            if c in df.columns:
                price_cols.append(c)
        try:
            price_df = df[price_cols].dropna().reset_index()
            long_df = price_df.melt('date', var_name='指标', value_name='价格')
            chart = alt.Chart(long_df).mark_line(point=True).encode(
                x='date:T', y='价格:Q', color=alt.Color('指标:N', legend=alt.Legend(orient='bottom', title=None))
            ).properties(height=200)
            st.altair_chart(chart, width="stretch")
        except Exception:
            st.line_chart(df[price_cols])

    # 上涨空间：正值=绿柱，负值=红柱
    if 'upside_pct' in df.columns:
        st.markdown("**上涨空间 (%)**")
        up_df = df[['upside_pct']].dropna().reset_index()
        up_df.columns = ['date', 'value']
        pos = up_df[up_df['value'] >= 0].copy()
        neg = up_df[up_df['value'] < 0].copy()
        try:
            layers = []
            if not pos.empty:
                layers.append(
                    alt.Chart(pos).mark_bar(color='#4caf50').encode(
                        x='date:T', y=alt.Y('value:Q', title='上涨空间(%)'))
                )
                layers.append(
                    alt.Chart(pos).mark_text(dy=-8, size=11).encode(
                        x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f'),
                        color=alt.value('#4caf50'))
                )
            if not neg.empty:
                layers.append(
                    alt.Chart(neg).mark_bar(color='#f44336').encode(
                        x='date:T', y='value:Q')
                )
                layers.append(
                    alt.Chart(neg).mark_text(dy=15, size=11).encode(
                        x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f'),
                        color=alt.value('#f44336'))
                )
            if layers:
                st.altair_chart(alt.layer(*layers).properties(height=200), width="stretch")
            else:
                st.bar_chart(up_df.set_index('date'))
        except Exception:
            st.bar_chart(up_df.set_index('date'))





# ========== 足球场 ==========
def render_soccer(sotp_price: float, dcf_price: float, current_price: float,
                  currency_symbol: str = "¥", sotp_min: float = None,
                  sotp_max: float = None, weighted_price: float = None):
    st.markdown('<p class="section-header">⚽ 估值足球场</p>', unsafe_allow_html=True)

    labels = ["SOTP", "DCF", "PE×15", "PE×20", "PE×25", "当前价"]
    prices = [sotp_price, dcf_price, current_price * 0.3, current_price * 0.4,
              current_price * 0.5, current_price]
    if weighted_price:
        labels.insert(2, "概率加权")
        prices.insert(2, weighted_price)

    data = pd.DataFrame({
        "估值方法": labels,
        "目标价": prices,
    })

    try:
        import altair as alt
        chart = alt.Chart(data).mark_bar().encode(
            x=alt.X('估值方法', sort=None),
            y='目标价',
            color=alt.condition(
                alt.datum.目标价 < current_price,
                alt.value('#4CAF50'),
                alt.value('#f44336')
            )
        ).properties(height=250)

        text_chart = alt.Chart(data).mark_text(dy=-10, size=12, color='black').encode(
            x='估值方法',
            y='目标价:Q',
            text=alt.Text('目标价:Q', format='.1f')
        )
        st.altair_chart(chart + text_chart, width="stretch")
    except:
        st.bar_chart(data.set_index("估值方法"), color="#4CAF50")

    # 数值卡片
    cols = st.columns(4)
    delta_color = "inverse"
    with cols[0]:
        delta_sotp = f"{((sotp_price or 0)/(max(current_price or 1, 0.001))-1)*100:.0f}%"
        st.metric("SOTP", f"{(sotp_price or 0):.1f}{currency_symbol}", delta=delta_sotp, delta_color=delta_color)
    with cols[1]:
        if dcf_price and dcf_price > 0:
            delta_dcf = f"{((dcf_price or 0)/(max(current_price or 1, 0.001))-1)*100:.0f}%"
            st.metric("DCF", f"{(dcf_price or 0):.1f}{currency_symbol}", delta=delta_dcf, delta_color=delta_color)
        else:
            st.metric("DCF", "N/A", delta="-", delta_color="off")
    with cols[2]:
        st.metric("PE×20", f"{(current_price or 0)*0.4:.1f}{currency_symbol}")
    with cols[3]:
        st.metric("当前价", f"{(current_price or 0):.1f}{currency_symbol}", delta="基准")


# ========== 敏感度热力图 ==========
def render_heatmap(fcf_proj: List[float], shares: float = 6.53, currency_symbol: str = "¥"):
    st.markdown('<p class="section-header">🌡️ DCF双变量敏感度分析</p>', unsafe_allow_html=True)
    engine = DiscountingEngine()

    tg_vals = [0.02, 0.03, 0.04]
    wacc_vals = [0.05, 0.065, 0.08]

    rows = []
    for tg in tg_vals:
        row = []
        for w in wacc_vals:
            r = engine.compute_dcf(fcf_projections=fcf_proj, terminal_fcf=fcf_proj[-1], wacc=w, net_debt=0.0, shares=shares, terminal_growth=tg)['目标价_元']
            row.append(r)  # r is already the float value from ['目标价_元']
        rows.append(row)

    df = pd.DataFrame(rows, index=[f"TG={t*100:.0f}%" for t in tg_vals],
                      columns=[f"WACC={w*100:.0f}%" for w in wacc_vals])
    st.dataframe(df)
    st.caption(f"行: 永续增长率(TG) | 列: WACC | 单位: {currency_symbol}")


# ========== 情绪偏差 ==========
def render_sentiment(target: float, current: float, currency_symbol: str = "¥"):
    st.markdown('<p class="section-header">🎭 情绪偏差监测</p>', unsafe_allow_html=True)
    pv = (current or 0) / (target or 1) if (target or 1) > 0 else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("P/V比率", f"{(pv or 0):.2f}x", help="当前价/目标价，大于1高估")
    with c2:
        st.metric("目标价", f"{(target or 0):.1f}{currency_symbol}")
    with c3:
        st.metric("当前价", f"{(current or 0):.1f}{currency_symbol}")

    badge = "🔴 严重高估" if pv > 1.5 else "🟠 偏高" if pv > 1.2 else "🟢 合理" if pv > 0.8 else "🔵 偏低"
    st.markdown(f"**状态**: {badge}")
    st.progress(min(max(1/(pv or 1), 0), 1) if (pv or 1) > 0 else 0)


# ========== SOTP详情（阿里巴巴） ==========
def render_sotp_detail(sotp_detail: Dict[str, Any], currency_symbol: str = "HK$"):
    """渲染阿里巴巴SOTP分部详情"""
    st.markdown('<p class="section-header">📊 SOTP分部详情</p>', unsafe_allow_html=True)

    divisions = sotp_detail.get('分部列表', [])
    if divisions:
        rows = []
        for div in divisions:
            min_cap, max_cap = div.get('分部市值_亿_区间') or (0, 0)
            rows.append({
                '分部': div.get('name', ''),
                '净利润(亿)': div.get('分部净利润_亿', 0),
                'PE区间': div.get('PE区间', ''),
                '市值(亿)': f"{(min_cap or 0):.0f}~{(max_cap or 0):.0f}",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch")

    holdings = sotp_detail.get('控股权益_亿', 0)
    total_mid = sotp_detail.get('总市值_亿_中枢', 0)
    sotp_min, sotp_max = sotp_detail.get('目标价_区间_元', (0, 0))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("控股权益(亿)", f"¥{(holdings or 0):.0f}")
    with col2:
        st.metric("总市值中枢(亿)", f"¥{(total_mid or 0):.0f}")
    with col3:
        st.metric("SOTP目标价区间", f"{(sotp_min or 0):.0f}~{(sotp_max or 0):.0f}{currency_symbol}")
    with col4:
        upside = sotp_detail.get('上涨空间_中枢_%', 0)
        st.metric("上涨空间", f"{(upside or 0):+.0f}%")


# ========== 历史数据加载 ==========
@st.cache_data(ttl=3600)
def load_history(stock_code: str = None) -> pd.DataFrame:
    """从 data/history.json 读取历史数据"""
    path = Path(__file__).parent.parent.parent / 'data' / 'history.json'
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if stock_code:
            data = [r for r in data if r.get('stock_code') == stock_code]
        df = pd.DataFrame(data)
        if 'date' in df.columns and len(df) > 0:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').set_index('date')
        return df
    return pd.DataFrame()


# ========== Main ==========
def main():
    repo_root = Path(__file__).parent.parent.parent

    # === 侧边栏：股票选择 ===
    with st.sidebar:
        st.header("📊 股票选择")
        stock_options = {
            "002428": "🇨🇳 云南锗业 (002428)",
            "09988": "🇭🇰 阿里巴巴 (09988)",
            "06613": "🇭🇰 蓝思科技 (06613)",
            "688608": "🇨🇳 恒玄科技 (688608)",
        }
        selected = st.selectbox(
            "选择股票",
            options=list(stock_options.keys()),
            format_func=lambda x: stock_options[x],
            index=0,
        )

        stock_info = STOCK_REGISTRY[selected]
        st.markdown("---")

        st.header("⚙️ DCF参数")
        # WACC参数
        mp_note = "市场风险溢价(A股5%/港股7%)"
        rf = st.slider("无风险利率(Rf)", 0.010, 0.050, 0.030, 0.0025,
                       format="%.3f", help="10年期国债收益率")
        beta = st.slider("Beta系数", 0.5, 2.0, 1.0, 0.1,
                         help="个股Beta，相对市场波动性")

        # 使用滑块值直接作为小数（slider min=0.010表示1.0%，step=0.0025）
        # 修正: slider返回0.030 = 3.0%，即 rf=0.030
        # 但CAPM期望小数，所以直接用 rf_val = rf
        rf_val = rf  # 0.030 = 3.0%

        # 根据股票设置默认market_premium
        if selected == "002428":
            mp = 0.05   # A股 5%
            beta_default = 1.2
            tg_default = 0.03
        elif selected == "06613":
            mp = 0.07   # 港股 7%
            beta_default = 1.05
            tg_default = 0.03
        elif selected == "688608":
            mp = 0.05   # 科创板 5%
            beta_default = 0.95
            tg_default = 0.03
        else:
            mp = 0.07   # 港股 7%
            beta_default = 0.9
            tg_default = 0.04

        # 如果用户没动过slider，用股票默认值
        # 注意：st.slider不支持动态default，需要在session_state处理
        tg = st.slider("永续增长率(TG)", 0.01, 0.06, tg_default, 0.01)

        # 计算WACC
        wacc = calc_wacc_safe(rf_val, beta, mp)
        st.write(f"**WACC: {wacc*100:.2f}%**")
        st.caption(mp_note)

        # 健康检查
        if wacc > 0.5:
            st.error(f"⚠️ WACC异常({wacc*100:.1f}%)，请检查参数")
        elif wacc < 0.02:
            st.warning(f"⚠️ WACC偏低({wacc*100:.1f}%)")

        # 阿里巴巴 SOTP 参数滑块
        if selected == "09988":
            st.markdown("---")
            st.markdown("**📐 SOTP参数**")
            core_pe_min = int(st.slider("核心商业PE下限", 10, 25, 18))
            core_pe_max = int(st.slider("核心商业PE上限", 15, 35, 28))
            cloud_pe_min = int(st.slider("云智能PE下限", 20, 40, 30))
            cloud_pe_max = int(st.slider("云智能PE上限", 25, 55, 45))
            intl_ps = st.slider("国际商业PS倍数", 0.3, 1.5, 0.8, 0.1, format="%.1f")
        else:
            core_pe_min, core_pe_max, cloud_pe_min, cloud_pe_max, intl_ps = 18, 28, 30, 45, 0.8

        st.markdown("---")
        st.markdown("**📂 数据文件**")
        st.markdown(f"`stocks/{selected}/`")
        st.markdown("[GitHub](https://github.com/skywalkern-cloud/investment-valuation)")

    # === 主区域 ===
    currency_symbol = stock_info.get("currency_symbol", "¥")

    st.markdown(f'<p class="main-header">📊 {stock_info["name"]}({selected}) 估值仪表盘</p>',
                unsafe_allow_html=True)
    st.caption(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')} | {stock_info['currency']}")

    # 获取当前股价
    current_price = get_current_price(selected)

    # 根据股票运行估值
    if selected == "002428":
        val = run_yunnangeiyec_valuation(
            rf=rf_val, beta=beta, tg=tg, current_price=current_price
        )
        sotp_price = val["sotp_price"]
        dcf_price = val["dcf_price"]
        weighted_price = val.get("weighted_price", None)
        sotp_min = None
        sotp_max = None
        df_history = load_history()
    elif selected == "06613":
        val = run_lens_valuation(
            rf=rf_val, beta=beta, tg=tg, current_price=current_price
        )
        sotp_price = val.get("sotp_price", 0)
        dcf_price = val["dcf_price"]
        weighted_price = val.get("weighted_price", None)
        sotp_min = val.get("sotp_min", None)
        sotp_max = val.get("sotp_max", None)
        df_history = pd.DataFrame()  # 蓝思暂无历史数据
    elif selected == "688608":
        val = run_hengxuan_valuation(
            rf=rf_val, beta=beta, tg=tg, current_price=current_price
        )
        sotp_price = val.get("sotp_price", val.get("target_base", 0))
        dcf_price = val.get("dcf_price", 0)
        weighted_price = val.get("weighted_price", None)
        sotp_min = val.get("sotp_min", None)
        sotp_max = val.get("sotp_max", None)
        df_history = pd.DataFrame()  # 恒玄暂无历史数据
    else:
        val = run_alibaba_valuation(
            rf=rf_val, beta=beta, tg=tg, current_price=current_price,
            core_pe_min=core_pe_min, core_pe_max=core_pe_max,
            cloud_pe_min=cloud_pe_min, cloud_pe_max=cloud_pe_max, intl_ps=intl_ps
        )
        sotp_price = val.get("sotp_price", 0)
        sotp_min = val.get("sotp_min", 0)
        sotp_max = val.get("sotp_max", 0)
        dcf_price = val.get("dcf_price", 0)
        weighted_price = val.get("weighted_price", None)
        df_history = load_history("09988")  # 阿里巴巴历史数据

    # 渲染
    render_trend(df_history, selected)
    st.markdown("---")
    render_soccer(
        (sotp_price or 0), (dcf_price or 0), (current_price or 0),
        currency_symbol=currency_symbol,
        sotp_min=sotp_min, sotp_max=sotp_max,
        weighted_price=weighted_price
    )

    if selected == "09988" and val.get("sotp_detail"):
        st.markdown("---")
        render_sotp_detail(val["sotp_detail"], currency_symbol=currency_symbol)

    # 002428: SOTP分部分说明
    if selected == "002428":
        st.markdown("---")
        st.markdown('<p class="section-header">📊 SOTP分部分说明</p>', unsafe_allow_html=True)
        # 半导体分部
        st.markdown("**【半导体分部：磷化铟(InP)衬底】**")
        st.markdown(f"""
        | 参数 | 值 |
        |---|---|
        | 产能 | 15万片/年 |
        | 利用率 | 100% (订单超产能) |
        | InP均价 | 2.65万元/片 |
        | 收入 | 15 × 1.0 × 2.65 = **{(val.get('inp_revenue') or 39.75):.2f}亿元** |
        | 净利率 | 24% (制造费用折算) |
        | 净利润 | **{(val.get('semi_nm') or 0):.2f}亿元** |
        | PE区间 | 60-80x (AI材料稀缺溢价) |
        | 市值区间 | {(val.get('semi_nm') or 0)*60:.1f} ~ {(val.get('semi_nm') or 0)*80:.1f}亿元 |
        """)
        # 传统业务
        st.markdown("**【传统业务：锗矿开采冶炼】**")
        trad_nm = val.get('trad_nm', 0)
        st.markdown(f"""
        | 参数 | 值 |
        |---|---|
        | 产量 | 30吨/年 |
        | 锗价 | 1.775万元/公斤 (市场价17750元/kg) |
        | 收入 | 53.25亿元 |
        | 净利率 | 30% |
        | 净利润 | **{trad_nm:.2f}亿元** |
        | PE区间 | 15-20x (传统业务折价) |
        | 市值区间 | {(trad_nm or 0)*15:.1f} ~ {(trad_nm or 0)*20:.1f}亿元 |
        """)
        # SOTP合计
        _sotp_428 = (val.get("sotp_price") or 0)
        _cur_428 = (val.get("current_price") or 0)
        _up_428 = ((_sotp_428 / max(_cur_428, 1)) - 1) * 100 if _cur_428 > 0 else -100
        st.markdown("**【SOTP合计】**")
        sotp_cap = val.get('sotp_price', 0) * 6.53
        semi_cap = val.get('semi_nm', 0) * 70
        trad_cap = val.get('trad_nm', 0) * 18
        sotp_min_total = (val.get('semi_nm', 0)*60 + trad_nm*15) / 6.53
        sotp_max_total = (val.get('semi_nm', 0)*80 + trad_nm*20) / 6.53
        st.markdown(f"""
        | 指标 | 值 |
        |---|---|
        | 半导体市值 | {(semi_cap or 0):.1f}亿元 |
        | 传统业务市值 | {(trad_cap or 0):.1f}亿元 |
        | SOTP总市值 | {((semi_cap or 0)+(trad_cap or 0)):.1f}亿元 |
        | 目标价区间 | {(sotp_min_total or 0):.1f} ~ {(sotp_max_total or 0):.1f}元 |
        | 目标价中枢 | **{(val.get('sotp_price') or 0):.1f}元** |
        | 当前价 | {(val.get('current_price') or 0):.2f}元 |
        | 上涨空间 | {_up_428:+.1f}% |
        """)

    # 06613: SOTP分部分说明
    if selected == "06613":
        st.markdown("---")
        st.markdown('<p class="section-header">📊 SOTP分部分说明（蓝思科技HK06613）</p>', unsafe_allow_html=True)
        sotp_detail = val.get('sotp_detail', {})
        segments = sotp_detail.get('segments', [])
        if segments:
            for seg in segments:
                st.markdown(f"""
                **【{seg['name']}】**
                | 参数 | 值 |
                |---|---|
                | 收入(HKD) | **{(seg.get('revenue_hkd') or 0):.0f}亿元** |
                | 净利率 | {(seg.get('net_margin') or 0) * 100:.1f}% |
                | 净利润(HKD) | **{(seg.get('net_profit_hkd') or 0):.2f}亿元** |
                | PE区间 | {seg['pe_range']} (中枢{seg['pe_base']}x) |
                | 市值(HKD) | **{(seg.get('cap_hkd') or 0):.1f}亿元** ({seg['pct']}) |
                """)
            # SOTP合计
            total_nm = sotp_detail.get('total_net_profit_hkd', 0)
            sotp_cap = val.get('sotp_cap_base_hkd', 0)
            _sotp_613 = (val.get("sotp_price") or 0)
            _cur_613 = (val.get("current_price") or 0)
            _up_613 = ((_sotp_613 / max(_cur_613, 1)) - 1) * 100 if _cur_613 > 0 else -100
            st.markdown(f"""
            **【SOTP合计】**
            | 指标 | 值 |
            |---|---|
            | 总净利润(HKD) | **{(total_nm or 0):.2f}亿元** (含合并调整{(sotp_detail.get('profit_adjustment') or 0):.1f}亿) |
            | SOTP总市值(HKD) | **{(sotp_cap or 0):.1f}亿元** |
            | 当前价(HKD) | {(val.get('current_price') or 0):.2f} |
            | 上涨空间 | {_up_613:+.1f}% |
            | DCF目标价 | {(val.get('dcf_price') or 0):.2f} HKD ({((val.get('dcf_price') or 0) * (val.get('hkd_cny_rate') or 0.92)):.2f} CNY) |
            | 概率加权 | {(val.get('weighted_price') or 0):.2f} HKD |
            """)

    # 688608: SOTP分部分说明
    if selected == "688608":
        sotp_detail = val.get('sotp_detail', {})
        segments = sotp_detail.get('segments', [])
        if segments:
            st.markdown("---")
            st.markdown('<p class="section-header">📊 SOTP分部分说明（恒玄科技688608）</p>', unsafe_allow_html=True)
            for seg in segments:
                st.markdown(f"""
                **【{seg['name']}】**
                | 参数 | 值 |
                |---|---|
                | 收入(CNY) | **{(seg.get('revenue_cny') or 0):.1f}亿元** |
                | 净利率 | {(seg.get('net_margin') or 0) * 100:.1f}% |
                | 净利润(CNY) | **{(seg.get('net_profit_cny') or 0):.2f}亿元** |
                | PE区间 | {seg['pe_range']} (中枢{seg['pe_base']}x) |
                | 市值(CNY) | **{(seg.get('cap_base') or 0):.1f}亿元** ({seg['pct']}) |
                """)
            # SOTP合计
            _sotp_608 = (val.get("sotp_price") or 0)
            _cur_608 = (val.get("current_price") or 0)
            _up_608 = ((_sotp_608 / max(_cur_608, 1)) - 1) * 100 if _cur_608 > 0 else -100
            total_nm_608 = sotp_detail.get('total_net_profit', 0)
            st.markdown(f"""
            **【SOTP合计】**
            | 指标 | 值 |
            |---|---|
            | 总净利润(CNY) | **{(total_nm_608 or 0):.2f}亿元** |
            | SOTP总市值(CNY) | **{(val.get('sotp_cap_base') or 0):.1f}亿元** |
            | 当前价(CNY) | {(_cur_608 or 0):.2f} |
            | 上涨空间 | {_up_608:+.1f}% |
            | DCF目标价 | {(val.get('dcf_price') or 0):.2f}元 |
            | 概率加权 | {(val.get('weighted_price') or 0):.2f}元 |
            """)

    # 09988: 端到端敏感性分析展示
    if selected == "09988" and val.get("sensitivity"):
        st.markdown("---")
        st.markdown("**🔬 端到端敏感性分析**")
        sa = val["sensitivity"]
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("SOTP区间", f"{sa['sotp_range'][0]:.0f}~{sa['sotp_range'][1]:.0f}HK$")
        with col2:
            st.metric("DCF区间", f"{sa['dcf_range'][0]:.0f}~{sa['dcf_range'][1]:.0f}HK$")
        with col3:
            st.metric("综合区间", f"{sa['combined_range'][0]:.0f}~{sa['combined_range'][1]:.0f}HK$")
        with col4:
            st.metric("推荐中枢", f"{sa['recommended_target']:.0f}HK$",
                      delta=f"区间: {sa['recommended_range'][0]:.0f}~{sa['recommended_range'][1]:.0f}HK$")
        st.caption(f"🔬 SOTP参数×DCF(WACC×TG) | 阿里云净利={(sa.get('cloud_nm') or 0):.0f}亿 | 核心商业净利={(sa.get('core_nm') or 0):.0f}亿")

    # 002428: 端到端敏感性分析展示
    if selected == "002428":
        sa = val.get("sensitivity")
        if sa:
            st.markdown("---")
            st.markdown("**🔬 端到端敏感性分析**")
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.metric("SOTP区间", f"{sa['sotp_range'][0]:.1f}~{sa['sotp_range'][1]:.1f}元")
            with col2:
                st.metric("DCF区间", f"{sa['dcf_range'][0]:.1f}~{sa['dcf_range'][1]:.1f}元")
            with col3:
                st.metric("综合区间", f"{sa['combined_range'][0]:.1f}~{sa['combined_range'][1]:.1f}元")
            with col4:
                st.metric("推荐中枢", f"{sa['recommended_target']:.1f}元",
                          delta=f"P10~P90: {sa['recommended_range'][0]:.1f}~{sa['recommended_range'][1]:.1f}元")
            st.caption("🔬 SOTP参数×DCF(WACC×TG) 双维敏感性分析 | 配置: sensitivity_analysis")
        else:
            err = val.get("sensitivity_error")
            if err:
                st.error(f"⚠️ 敏感性分析异常: {err[:300]}")

    st.markdown("---")
    render_heatmap(
        val.get("fcf_proj", []),
        shares=stock_info["shares"],
        currency_symbol=currency_symbol
    )
    st.markdown("---")

    # 使用DCF价格作为目标价基准
    target_price = weighted_price if weighted_price else (dcf_price if dcf_price > 0 else sotp_price)
    render_sentiment(target_price, current_price, currency_symbol=currency_symbol)

    st.markdown("---")
    st.caption("""
    **说明**：
    - A股股价每次刷新从akshare实时读取
    - 港股股价从新浪API实时读取（每5分钟缓存）
    - WACC = E/V×Re + D/V×Rd×(1-T)，Re = Rf + β×(Rm-Rf)
    - 云南锗业历史数据由每日08:00 cron任务写入 `data/history.json`
    """)


if __name__ == '__main__':
    main()
