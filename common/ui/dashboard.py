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
        "shares": 47.5,   # 亿股
        "config_path": "stocks/09988_alibaba/config.yaml",
        "manual_path": "stocks/09988_alibaba/manual_data.yaml",
        "model_path": "stocks/09988_alibaba/model.py",
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
    """获取云南锗业A股实时股价"""
    try:
        import akshare as ak
        df = ak.stock_individual_spot_xq(symbol='SZ002428')
        data = {}
        for _, row in df.iterrows():
            data[row['item']] = row['value']
        price = float(data.get('现价', 0))
        return price if price > 0 else 77.12
    except:
        return 77.12


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


def get_current_price(stock_code: str) -> float:
    """根据股票代码获取实时股价"""
    if stock_code == "002428":
        return get_price_002428()
    elif stock_code == "09988":
        return get_price_09988()
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
    """云南锗业真实估值计算 — 调用真实 SOTP + DCF + 敏感性分析"""
    import warnings
    warnings.filterwarnings('ignore')

    from common.core.sotp_engine import SOTPEngine
    from common.core.discounting_engine import DiscountingEngine
    from common.core.sensitivity_runner import run_sensitivity_analysis, SensitivityConfig
    from common.core.financial_foundation import FinancialFoundation

    repo_root = Path(__file__).parent.parent.parent

    # 加载配置和数据
    with open(repo_root / 'stocks/002428_yunnangeiyec/config.yaml') as f:
        config = yaml.safe_load(f)
    with open(repo_root / 'stocks/002428_yunnangeiyec/manual_data.yaml') as f:
        manual_data = yaml.safe_load(f) or {}

    meta = config['meta']
    shares = meta['total_shares']

    # FinancialFoundation（来自akshare，自动降级）
    try:
        ff = FinancialFoundation.from_akshare(meta['stock_code'])
    except Exception:
        ff = FinancialFoundation()
        ff.revenue = manual_data.get('financials', {}).get('revenue', 0)
        ff.net_profit = manual_data.get('financials', {}).get('net_profit', 0)

    # SOTP Engine
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

    # 构建 merged manual_data
    auto_vars = {
        'germanium_price': manual_data.get('germanium_price', 17500),
        'indium_price': manual_data.get('indium_price', 4350),
    }
    merged = {}
    for plugin_cfg in config.get('plugins', []):
        name = plugin_cfg['name']
        div_data = {}
        div_data.update(plugin_cfg.get('defaults', {}))
        if name in manual_data:
            div_data.update(manual_data[name])
        elif plugin_cfg['type'] in manual_data:
            div_data.update(manual_data[plugin_cfg['type']])
        for var_name, source_key in plugin_cfg.get('auto_variables', {}).items():
            if source_key in auto_vars:
                div_data[var_name] = auto_vars[source_key]
        merged[name] = div_data

    sotp_result = sotp.run(ff, {}, merged)
    sotp_price = sotp_result['目标价_中枢_元']

    # WACC + DCF
    engine = DiscountingEngine()
    beta_val = config.get('methodology_notes', {}).get('wacc', {}).get('beta', {}).get('value', 1.2)
    beta_last_updated = config.get('methodology_notes', {}).get('wacc', {}).get('beta', {}).get('last_updated', '')
    mp = config.get('methodology_notes', {}).get('wacc', {}).get('market_premium', 0.05)

    # 自动刷新Beta（如过期）
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta_val,
                                market_premium=mp, auto_refresh_beta=True)

    # FCF 估算
    sotp_nm = sotp_result.get('总净利润_亿', 0.655)
    growth_rates = [0.20, 0.25, 0.30, 0.25, 0.20]
    fcf_proj = []
    base = sotp_nm
    for i, g in enumerate(growth_rates):
        fcf = base * (1 + g) ** (i + 1) * 0.85
        fcf_proj.append(round(fcf, 3))

    dcf_result = engine.compute_dcf(fcf_projections=fcf_proj, terminal_fcf=fcf_proj[-1], wacc=wacc, net_debt=0.0, shares=shares, terminal_growth=tg)
    dcf_price = dcf_result['目标价_元']

    # 端到端敏感性分析
    sa_cfg = config.get('sensitivity_analysis', {})
    sa_cfg_params = sa_cfg.get('sotp_params', {
        '商品售价': [12000, 15000, 17500, 20000, 25000],
        '良率': [0.80, 0.85, 0.88, 0.90],
    })
    dcf_wacc_range = tuple(sa_cfg.get('dcf_wacc_range', [0.06, 0.08, 0.10]))
    dcf_tg_range = tuple(sa_cfg.get('dcf_tg_range', [0.02, 0.03, 0.04]))

    sensitivity_result = None
    sensitivity_error = None
    try:
        sensitivity_result = run_sensitivity_analysis(
            financials=ff,
            manual_data=merged,
            config=SensitivityConfig(
                sotp_params=sa_cfg_params,
                dcf_wacc_range=dcf_wacc_range,
                dcf_tg_range=dcf_tg_range,
                shares=shares,
            ),
            sotp_engine=sotp,
            dcf_engine=engine,
            fcf_projections=fcf_proj,
        )
    except Exception as e:
        import traceback
        sensitivity_error = repr(e) + "\n" + traceback.format_exc()[:500]
        sensitivity_result = None

    return {
        "sotp_price": sotp_price,
        "dcf_price": dcf_price,
        "wacc": wacc,
        "wacc_pct": wacc * 100,
        "current_price": current_price,
        "fcf_proj": fcf_proj,
        "currency": "CNY",
        "currency_symbol": "¥",
        "sensitivity": sensitivity_result,
        "sensitivity_error": sensitivity_error,
        "sotp_result": sotp_result,
    }


def run_alibaba_valuation(
    rf: float, beta: float, tg: float, current_price: float,
    cost_of_debt: float = 0.045, tax_rate: float = 0.15, debt_ratio: float = 0.25
) -> Dict[str, Any]:
    """阿里巴巴估值计算"""
    import sys
    import importlib.machinery
    from pathlib import Path
    repo_root = Path(__file__).parent.parent.parent
    sys.path.insert(0, str(repo_root))

    # Load Alibaba config
    with open(repo_root / 'stocks/09988_alibaba/config.yaml') as f:
        config = yaml.safe_load(f)

    stock_info = STOCK_REGISTRY["09988"]
    shares = stock_info["shares"]

    # WACC
    wacc = calc_wacc_safe(rf, beta, market_premium=0.07,
                          cost_of_debt=cost_of_debt, tax_rate=tax_rate, debt_ratio=debt_ratio)

    # FCF projections
    fcf_proj = [620, 680, 750, 830, 920]

    # SOTP calculation (SourceFileLoader to handle digit-starting module name)
    model_path = repo_root / 'stocks' / '09988_alibaba' / 'model.py'
    loader = importlib.machinery.SourceFileLoader('alibaba_model', str(model_path))
    alibaba_model = loader.load_module()
    AlibabaSOTP = alibaba_model.AlibabaSOTP
    sotp_engine = AlibabaSOTP()
    sotp_result = sotp_engine.run(current_price=current_price)

    # DCF
    engine = DiscountingEngine()
    dcf_result = engine.compute_dcf(fcf_projections=fcf_proj, terminal_fcf=fcf_proj[-1], wacc=wacc, net_debt=0.0, shares=shares, terminal_growth=tg)

    # Convert DCF from CNY to HKD
    hkd_rate = 0.92
    dcf_price_hkd = dcf_result['目标价_元'] / hkd_rate

    # Probability weighted (if events available)
    events = config.get("events", [])
    weighted_price = sotp_result.get('目标价_中枢_元', sotp_result.get('目标价_区间_元', (0, 0))[1])

    if events:
        sotp_total = sotp_result['总市值_亿_中枢']
        engine_prob = DiscountingEngine()
        weighted_total = engine_prob.apply_event_weights(sotp_total, events)
        weighted_price = weighted_total / shares / hkd_rate

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

    sensitivity_simple = {
        'sotp_range': (sotp_result.get('目标价_区间_元', (0, 0))[0] / hkd_rate,
                       sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate),
        'dcf_range': (dcf_price_hkd * 0.8, dcf_price_hkd * 1.3),
        'combined_range': (sotp_result.get('目标价_区间_元', (0, 0))[0] / hkd_rate * 0.9,
                            sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate * 1.1),
        'recommended_target': sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate,
        'recommended_range': (sotp_result.get('目标价_区间_元', (0, 0))[0] / hkd_rate,
                               sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate),
        'sotp_params': sotp_params,
        'cloud_nm': cloud_nm,
        'core_nm': core_nm,
    }

    hkd_rate = 0.92

    return {
        "sotp_price": sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate,  # 中枢→港元
        "sotp_min": sotp_result.get('目标价_区间_元', (0, 0))[0] / hkd_rate,
        "sotp_max": sotp_result.get('目标价_区间_元', (0, 0))[1] / hkd_rate,
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


# ========== 趋势图 ==========
def render_trend(df: pd.DataFrame, stock_code: str):
    st.markdown('<p class="section-header">📈 历史趋势</p>', unsafe_allow_html=True)


    if df.empty:
        st.info("📋 暂无历史数据。每日08:00 cron任务运行后会写入数据。")
        st.caption("历史数据路径: data/history.json")
        return

    try:
        import altair as alt

        if stock_code == "002428":
            cols = st.columns(2)
            with cols[0]:
                if 'indium_price' in df.columns:
                    st.markdown("**铟价 (元/kg)**")
                    indium_df = df[['indium_price']].dropna().reset_index()
                    indium_df.columns = ['date', 'value']
                    chart = alt.Chart(indium_df).mark_line(point=True).encode(
                        x='date:T', y='value:Q'
                    ).properties(height=200)
                    text_chart = alt.Chart(indium_df).mark_text(dy=-10, size=11, color='#333').encode(
                        x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f')
                    )
                    st.altair_chart(chart + text_chart, width="stretch")

            with cols[1]:
                if 'germanium_price' in df.columns:
                    st.markdown("**锗价 (万元/吨)**")
                    ge_df = df[['germanium_price']].dropna().reset_index()
                    ge_df.columns = ['date', 'value']
                    chart = alt.Chart(ge_df).mark_line(point=True).encode(
                        x='date:T', y='value:Q'
                    ).properties(height=200)
                    text_chart = alt.Chart(ge_df).mark_text(dy=-10, size=11, color='#333').encode(
                        x='date:T', y='value:Q', text=alt.Text('value:Q', format='.0f')
                    )
                    st.altair_chart(chart + text_chart, width="stretch")

        # 股价 vs 目标价
        if 'stock_price' in df.columns:
            st.markdown("**股价 vs 目标价**")
            price_cols = ['stock_price']
            for c in ['sotp_price', 'dcf_price', 'weighted_price']:
                if c in df.columns:
                    price_cols.append(c)
            price_df = df[price_cols].dropna().reset_index()
            long_df = price_df.melt('date', var_name='指标', value_name='价格')
            chart = alt.Chart(long_df).mark_line(point=True).encode(
                x='date:T', y='价格:Q', color='指标:N'
            ).properties(height=200)
            st.altair_chart(chart, width="stretch")

        # 上涨空间
        if 'upside_pct' in df.columns:
            st.markdown("**上涨空间 (%)**")
            up_df = df[['upside_pct']].dropna().reset_index()
            up_df.columns = ['date', 'value']
            chart = alt.Chart(up_df).mark_bar(color='#ff9800').encode(
                x='date:T', y='value:Q'
            ).properties(height=180)
            st.altair_chart(chart, width="stretch")

    except Exception as e:
        if stock_code == "002428":
            cols = st.columns(2)
            with cols[0]:
                if 'indium_price' in df.columns:
                    st.markdown("**铟价 (元/kg)**")
                    st.line_chart(df['indium_price'].dropna())
            with cols[1]:
                if 'germanium_price' in df.columns:
                    st.markdown("**锗价 (万元/吨)**")
                    st.line_chart(df['germanium_price'].dropna())
        if 'stock_price' in df.columns:
            st.markdown("**股价 vs 目标价**")
            price_cols = ['stock_price']
            for c in ['sotp_price', 'dcf_price', 'weighted_price']:
                if c in df.columns:
                    price_cols.append(c)
            st.line_chart(df[price_cols])


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
        delta_sotp = f"{(sotp_price/current_price-1)*100:.0f}%" if current_price > 0 else "N/A"
        st.metric("SOTP", f"{sotp_price:.1f}{currency_symbol}", delta=delta_sotp, delta_color=delta_color)
    with cols[1]:
        delta_dcf = f"{(dcf_price/current_price-1)*100:.0f}%" if current_price > 0 else "N/A"
        st.metric("DCF", f"{dcf_price:.1f}{currency_symbol}", delta=delta_dcf, delta_color=delta_color)
    with cols[2]:
        st.metric("PE×20", f"{current_price*0.4:.1f}{currency_symbol}")
    with cols[3]:
        st.metric("当前价", f"{current_price:.1f}{currency_symbol}", delta="基准")


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
            row.append(r)
        rows.append(row)

    df = pd.DataFrame(rows, index=[f"TG={t*100:.0f}%" for t in tg_vals],
                      columns=[f"WACC={w*100:.0f}%" for w in wacc_vals])
    st.dataframe(df)
    st.caption(f"行: 永续增长率(TG) | 列: WACC | 单位: {currency_symbol}")


# ========== 情绪偏差 ==========
def render_sentiment(target: float, current: float, currency_symbol: str = "¥"):
    st.markdown('<p class="section-header">🎭 情绪偏差监测</p>', unsafe_allow_html=True)
    pv = current / target if target > 0 else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("P/V比率", f"{pv:.2f}x", help="当前价/目标价，大于1高估")
    with c2:
        st.metric("目标价", f"{target:.1f}{currency_symbol}")
    with c3:
        st.metric("当前价", f"{current:.1f}{currency_symbol}")

    badge = "🔴 严重高估" if pv > 1.5 else "🟠 偏高" if pv > 1.2 else "🟢 合理" if pv > 0.8 else "🔵 偏低"
    st.markdown(f"**状态**: {badge}")
    st.progress(min(max(1/pv, 0), 1) if pv > 0 else 0)


# ========== SOTP详情（阿里巴巴） ==========
def render_sotp_detail(sotp_detail: Dict[str, Any], currency_symbol: str = "HK$"):
    """渲染阿里巴巴SOTP分部详情"""
    st.markdown('<p class="section-header">📊 SOTP分部详情</p>', unsafe_allow_html=True)

    divisions = sotp_detail.get('分部列表', [])
    if divisions:
        rows = []
        for div in divisions:
            min_cap, max_cap = div.get('分部市值_亿_区间', (0, 0))
            rows.append({
                '分部': div.get('name', ''),
                '净利润(亿)': div.get('分部净利润_亿', 0),
                'PE区间': div.get('PE区间', ''),
                '市值(亿)': f"{min_cap:.0f}~{max_cap:.0f}",
            })
        df = pd.DataFrame(rows)
        st.dataframe(df, width="stretch")

    holdings = sotp_detail.get('控股权益_亿', 0)
    total_mid = sotp_detail.get('总市值_亿_中枢', 0)
    sotp_min, sotp_max = sotp_detail.get('目标价_区间_元', (0, 0))

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("控股权益(亿)", f"¥{holdings:.0f}")
    with col2:
        st.metric("总市值中枢(亿)", f"¥{total_mid:.0f}")
    with col3:
        st.metric("SOTP目标价区间", f"{sotp_min:.0f}~{sotp_max:.0f}{currency_symbol}")
    with col4:
        upside = sotp_detail.get('上涨空间_中枢_%', 0)
        st.metric("上涨空间", f"{upside:+.0f}%")


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
        weighted_price = None
        sotp_min = None
        sotp_max = None
        df_history = load_history()
    else:
        val = run_alibaba_valuation(
            rf=rf_val, beta=beta, tg=tg, current_price=current_price
        )
        sotp_price = val.get("sotp_price", 0)
        sotp_min = val.get("sotp_min", 0)
        sotp_max = val.get("sotp_max", 0)
        dcf_price = val.get("dcf_price", 0)
        weighted_price = val.get("weighted_price", None)
        df_history = load_history(selected)  # 根据选择的股票加载对应历史数据

    # 渲染
    render_trend(df_history, selected)
    st.markdown("---")
    render_soccer(
        sotp_price, dcf_price, current_price,
        currency_symbol=currency_symbol,
        sotp_min=sotp_min, sotp_max=sotp_max,
        weighted_price=weighted_price
    )

    if selected == "09988" and val.get("sotp_detail"):
        st.markdown("---")
        render_sotp_detail(val["sotp_detail"], currency_symbol=currency_symbol)

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
                      delta=f"区间: {sa['recommended_range'][0]:.1f} ~ {sa['recommended_range'][1]:.1f} HK$")
        st.caption(f"🔬 SOTP参数×DCF(WACC×TG) | 阿里云净利={sa.get('cloud_nm',0):.0f}亿 | 核心商业净利={sa.get('core_nm',0):.0f}亿")

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
                          delta="P10~P90: " + str(round(sa["recommended_range"][0], 1)) + " ~ " + str(round(sa["recommended_range"][1], 1)) + " 元")
            st.caption("🔬 SOTP参数×DCF(WACC×TG) 双维敏感性分析")
        else:
            err = val.get("sensitivity_error", "未知")
            st.error(f"⚠️ 敏感性分析异常: {err[:300]}")

    st.markdown("---")
    render_heatmap(
        val["fcf_proj"],
        shares=stock_info["shares"],
        currency_symbol=currency_symbol
    )
    st.markdown("---")

    # 使用DCF价格作为目标价基准
    target_price = dcf_price if dcf_price > 0 else sotp_price
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
