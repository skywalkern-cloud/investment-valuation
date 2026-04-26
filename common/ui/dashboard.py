#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Dashboard - 云南锗业估值仪表盘 v2.1
趋势图 + 本地JSON历史数据

数据流：
- 历史数据：data/history.json（每日cron写入）
- 实时股价：akshare（每次刷新读取）
- 估值计算：本地引擎
"""

import streamlit as st
import pandas as pd
import json
from pathlib import Path
from datetime import datetime
from typing import List, Tuple

from common.core.discounting_engine import DiscountingEngine

# ========== Page Config ==========
st.set_page_config(
    page_title="云南锗业(002428) 估值仪表盘",
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


# ========== 历史数据（本地JSON） ==========
@st.cache_data(ttl=3600)
def load_history() -> pd.DataFrame:
    """从 data/history.json 读取历史数据"""
    path = Path(__file__).parent.parent.parent / 'data' / 'history.json'
    if path.exists():
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        df = pd.DataFrame(data)
        if 'date' in df.columns:
            df['date'] = pd.to_datetime(df['date'])
            df = df.sort_values('date').set_index('date')
        return df
    return pd.DataFrame()


@st.cache_data(ttl=300)
def get_stock_price() -> float:
    """从akshare获取实时股价"""
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


# ========== 趋势图 ==========
def render_trend(df: pd.DataFrame):
    st.markdown('<p class="section-header">📈 历史趋势</p>', unsafe_allow_html=True)

    if df.empty:
        st.info("📋 暂无历史数据。每日08:00 cron任务运行后会写入数据。")
        st.caption("历史数据路径: data/history.json")
        return

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

    if 'upside_pct' in df.columns:
        st.markdown("**上涨空间 (%)**")
        st.bar_chart(df['upside_pct'].dropna())


# ========== 足球场 ==========
def render_soccer(sotp_price: float, dcf_price: float, current_price: float):
    st.markdown('<p class="section-header">⚽ 估值足球场</p>', unsafe_allow_html=True)

    chart_data = pd.DataFrame({
        "估值方法": ["SOTP分部估值", "DCF折现估值", "当前价格"],
        "目标价": [sotp_price, dcf_price, current_price],
    })
    st.bar_chart(chart_data.set_index("估值方法"), color="#4CAF50")

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("SOTP估值", f"{sotp_price:.1f}元",
                  delta=f"{(sotp_price/current_price-1)*100:.0f}%", delta_color="inverse")
    with c2:
        st.metric("DCF估值", f"{dcf_price:.1f}元",
                  delta=f"{(dcf_price/current_price-1)*100:.0f}%", delta_color="inverse")
    with c3:
        st.metric("当前价格", f"{current_price:.1f}元", delta="基准")


# ========== 敏感度热力图 ==========
def render_heatmap(fcf_proj: List[float]):
    st.markdown('<p class="section-header">🌡️ DCF双变量敏感度分析</p>', unsafe_allow_html=True)
    engine = DiscountingEngine()

    tg_vals = [0.02, 0.03, 0.04]
    wacc_vals = [0.05, 0.065, 0.08]

    rows = []
    for tg in tg_vals:
        row = []
        for w in wacc_vals:
            r = engine.dcf_fcf(fcf_proj, fcf_proj[-1], w, 0, 6.53, tg)
            row.append(r['目标价_元'])
        rows.append(row)

    df = pd.DataFrame(rows, index=[f"TG={t*100:.0f}%" for t in tg_vals],
                      columns=[f"WACC={w*100:.0f}%" for w in wacc_vals])
    st.dataframe(df.style.background_gradient(cmap="RdYlGn", axis=None), width='stretch')
    st.caption("行: 永续增长率(TG) | 列: WACC | 单位: 元")


# ========== 情绪偏差 ==========
def render_sentiment(target: float, current: float):
    st.markdown('<p class="section-header">🎭 情绪偏差监测</p>', unsafe_allow_html=True)
    pv = current / target if target > 0 else 0

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("P/V比率", f"{pv:.2f}x", help="当前价/目标价，大于1高估")
    with c2:
        st.metric("目标价", f"{target:.1f}元")
    with c3:
        st.metric("当前价", f"{current:.1f}元")

    badge = "🔴 严重高估" if pv > 1.5 else "🟠 偏高" if pv > 1.2 else "🟢 合理" if pv > 0.8 else "🔵 偏低"
    st.markdown(f"**状态**: {badge}")
    st.progress(min(max(1/pv, 0), 1) if pv > 0 else 0)


# ========== Main ==========
def main():
    st.markdown('<p class="main-header">📊 云南锗业(002428) 估值仪表盘</p>', unsafe_allow_html=True)
    st.caption(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 侧边栏
    with st.sidebar:
        st.header("⚙️ 参数")
        rf = st.slider("无风险利率(Rf)", 0.01, 0.05, 0.025, 0.0025, format="%.3f")
        beta = st.slider("Beta", 0.5, 2.0, 1.2, 0.1)
        tg = st.slider("永续增长率(TG)", 0.01, 0.05, 0.03, 0.01)
        engine = DiscountingEngine()
        wacc = engine.calc_wacc(rf, beta)
        st.write(f"**WACC: {wacc*100:.2f}%**")
        st.markdown("---")
        st.markdown("**📂 数据文件**")
        st.markdown("`data/history.json`")
        st.markdown("[GitHub](https://github.com/skywalkern-cloud/investment-valuation)")

    # 数据
    df_history = load_history()
    current_price = get_stock_price()
    fcf_proj = [0.67, 0.87, 1.22, 1.36, 1.39]
    dcf_result = engine.dcf_fcf(fcf_proj, fcf_proj[-1], wacc, 0, 6.53, tg)
    sotp_price = 4.6
    dcf_price = dcf_result['目标价_元']

    # 渲染
    render_trend(df_history)
    st.markdown("---")
    render_soccer(sotp_price, dcf_price, current_price)
    st.markdown("---")
    render_heatmap(fcf_proj)
    st.markdown("---")
    render_sentiment(dcf_price, current_price)

    st.markdown("---")
    st.caption("""
    **说明**：历史数据由每日08:00 cron任务写入 `data/history.json`。
    股价每次刷新从akshare实时读取。
    """)


if __name__ == '__main__':
    main()