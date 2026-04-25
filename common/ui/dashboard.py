#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Dashboard - Phase 3
实时估值仪表盘

功能:
1. 足球场图表 - DCF/PE/PB/PS/SOTP区间对比
2. 热力图 - 双变量敏感度分析
3. 情绪偏差 - P/V比率监测

Phase 3
"""

import streamlit as st
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple

from common.core.discounting_engine import DiscountingEngine


# ========== Page Config ==========
st.set_page_config(
    page_title="云南锗业(002428) 估值仪表盘",
    page_icon="📊",
    layout="wide",
)


# ========== 1. 足球场图表 ==========
def render_soccer_field(
    sotp_price: float,
    dcf_price: float,
    current_price: float,
    pe_range: Tuple[float, float] = (10, 30),
    pb_range: Tuple[float, float] = (1, 5),
    ps_range: Tuple[float, float] = (1, 10),
) -> None:
    """
    渲染足球场图表 - 多估值方法区间对比
    """
    st.subheader("⚽ 估值足球场")

    # 构建数据
    methods = [
        ("SOTP分部估值", sotp_price, "🏢"),
        ("DCF折现估值", dcf_price, "💰"),
        ("PE估值 (15x)", current_price * 0.3, "📈"),
        ("PE估值 (25x)", current_price * 0.5, "📈"),
        ("当前价格", current_price, "🔴"),
    ]

    chart_data = pd.DataFrame({
        "估值方法": [m[0] for m in methods],
        "目标价": [m[1] for m in methods],
    })

    st.bar_chart(chart_data.set_index("估值方法"), color="#4CAF50")

    # 显示具体数值
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("SOTP估值", f"{sotp_price:.1f}元", delta=f"{(sotp_price/current_price-1)*100:.0f}%")
    with col2:
        st.metric("DCF估值", f"{dcf_price:.1f}元", delta=f"{(dcf_price/current_price-1)*100:.0f}%")
    with col3:
        st.metric("当前价格", f"{current_price:.1f}元", delta="基准")


# ========== 2. 敏感度热力图 ==========
def render_sensitivity_heatmap(
    base_fcf: List[float],
    terminal_fcf: float,
    _wacc: float,
    shares: float = 6.53,
    terminal_range: Tuple[float, float, float] = (0.02, 0.03, 0.04),
    wacc_range: Tuple[float, float, float] = (0.05, 0.07, 0.10),
) -> None:
    """
    渲染双变量敏感度热力图
    """
    st.subheader("🌡️ DCF双变量敏感度分析")

    engine = DiscountingEngine()

    # 生成网格
    tg_values = list(terminal_range)
    wacc_values = list(wacc_range)

    results = []
    for tg in tg_values:
        row = []
        for w in wacc_values:
            r = engine.dcf_fcf(
                fcf_projections=base_fcf,
                terminal_fcf=terminal_fcf,
                wacc=w,
                net_debt=0,
                shares=shares,
                terminal_growth=tg,
            )
            row.append(r['目标价_元'])
        results.append(row)

    df = pd.DataFrame(
        results,
        index=[f"TG={t*100:.0f}%" for t in tg_values],
        columns=[f"WACC={w*100:.0f}%" for w in wacc_values],
    )

    st.dataframe(
        df.style.background_gradient(cmap="RdYlGn", axis=None),
        width='stretch',
    )
    st.caption("行: 永续增长率(TG) | 列: WACC | 数值: 目标价(元)")


# ========== 3. 情绪偏差指标 ==========
def render_sentiment_bias(
    target_price: float,
    current_price: float,
) -> None:
    """
    渲染情绪偏差指标 - P/V比率
    """
    st.subheader("🎭 情绪偏差监测")

    pv_ratio = current_price / target_price if target_price > 0 else 0

    if pv_ratio > 1.5:
        status = "🔴 严重高估"
    elif pv_ratio > 1.2:
        status = "🟠 偏高"
    elif pv_ratio > 0.8:
        status = "🟢 合理区间"
    elif pv_ratio > 0.5:
        status = "🔵 偏低"
    else:
        status = "⚫ 严重低估"

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("P/V比率", f"{pv_ratio:.2f}x", help="当前价格/目标价格")
    with col2:
        st.metric("目标价", f"{target_price:.1f}元")
    with col3:
        st.metric("当前价", f"{current_price:.1f}元")

    st.write(f"**估值状态**: {status}")
    progress = float(min(max(1/pv_ratio, 0), 1)) if pv_ratio > 0 else 0.0
    st.progress(progress)


# ========== 数据获取（带缓存，不阻塞启动） ==========
@st.cache_data(ttl=3600)
def get_stock_price() -> float:
    """
    获取股价 - 用手动数据，避免akshare阻塞启动
    返回: 股价（元）
    """
    return 77.12  # 当前价固定，后续可改为实时获取


# ========== Main App ==========
def main():
    st.title("📊 云南锗业(002428) 估值仪表盘")

    # 侧边栏 - 参数调整
    st.sidebar.header("参数设置")
    st.sidebar.caption("云南锗业 | SOTP+DCF分部估值")

    # 用户可调整参数
    rf = st.sidebar.slider("无风险利率(Rf)", 0.01, 0.05, 0.025, 0.0025, format="%.3f")
    beta = st.sidebar.slider("Beta系数", 0.5, 2.0, 1.2, 0.1)
    tg = st.sidebar.slider("永续增长率(TG)", 0.01, 0.05, 0.03, 0.01, format="%.0f%%") / 100

    # 计算WACC
    engine = DiscountingEngine()
    wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta)
    st.sidebar.write(f"**WACC: {wacc*100:.2f}%**")

    # 运行DCF
    fcf_proj = [0.67, 0.87, 1.22, 1.36, 1.39]
    dcf_result = engine.dcf_fcf(
        fcf_projections=fcf_proj,
        terminal_fcf=fcf_proj[-1],
        wacc=wacc,
        net_debt=0,
        shares=6.53,
        terminal_growth=tg,
    )

    sotp_price = 4.6  # SOTP基准值
    dcf_price = dcf_result['目标价_元']
    current_price = get_stock_price()

    # 渲染
    st.markdown("---")
    render_soccer_field(sotp_price, dcf_price, current_price)
    st.markdown("---")
    render_sensitivity_heatmap(fcf_proj, fcf_proj[-1], 6.53, wacc_range=(0.05, 0.065, 0.08), terminal_range=(0.02, 0.03, 0.04))
    st.markdown("---")
    render_sentiment_bias(dcf_price, current_price)


if __name__ == '__main__':
    main()
