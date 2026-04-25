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
import sys
import os

from common.core.discounting_engine import DiscountingEngine
from common.core.sotp_engine import SOTPEngine
from common.core.financial_foundation import FinancialFoundation


# ========== Page Config ==========
st.set_page_config(
    page_title="云南锗业估值仪表盘",
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
    
    df = pd.DataFrame(methods, columns=["方法", "价格", "图标"])
    
    # 简化柱状图
    chart_data = pd.DataFrame({
        "估值方法": [m[0] for m in methods],
        "目标价": [m[1] for m in methods],
    })
    
    st.bar_chart(chart_data.set_index("估值方法"), color=["#4CAF50", "#2196F3", "#FF9800", "#E91E63", "#F44336"][:len(methods)])
    
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
    wacc: float,
    shares: float,
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
    
    # 转为DataFrame
    df = pd.DataFrame(
        results,
        index=[f"TG={t*100:.0f}%" for t in tg_values],
        columns=[f"WACC={w*100:.0f}%" for w in wacc_values],
    )
    
    # 热力图
    st.dataframe(
        df.style.background_gradient(cmap="RdYlGn", axis=None),
        use_container_width=True,
    )
    
    # 说明
    st.caption("行: 永续增长率(TG) | 列: WACC | 数值: 目标价(元)")


# ========== 3. 情绪偏差指标 ==========
def render_sentiment_bias(
    target_price: float,
    current_price: float,
    consensus_price: Optional[float] = None,
) -> None:
    """
    渲染情绪偏差指标 - P/V比率
    """
    st.subheader("🎭 情绪偏差监测")
    
    # P/V = Price / Valuation
    pv_ratio = current_price / target_price if target_price > 0 else 0
    
    # 状态
    if pv_ratio > 1.5:
        status = "🔴 严重高估"
        color = "red"
    elif pv_ratio > 1.2:
        status = "🟠 偏高"
        color = "orange"
    elif pv_ratio > 0.8:
        status = "🟢 合理区间"
        color = "green"
    elif pv_ratio > 0.5:
        status = "🔵 偏低"
        color = "blue"
    else:
        status = "⚫ 严重低估"
        color = "purple"
    
    # 显示
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("P/V比率", f"{pv_ratio:.2f}x", help="当前价格/目标价格")
    with col2:
        st.metric("目标价", f"{target_price:.1f}元")
    with col3:
        st.metric("当前价", f"{current_price:.1f}元")
    
    st.write(f"**估值状态**: {status}")
    
    # 进度条
    progress = min(max(1/pv_ratio, 0), 1) if pv_ratio > 0 else 0
    st.progress(progress)


# ========== Main App ==========
def main():
    st.title("📊 云南锗业(002428) 估值仪表盘")
    
    # 侧边栏 - 参数调整
    st.sidebar.header("参数设置")
    
    # 获取实时数据
    try:
        from common.data.fetcher import DataFetcher
        fetcher = DataFetcher(manual_data={
            'stock_price': 77.12,
            'germanium_price': 17500,
            'indium_price': 4350,
        })
        price_result = fetcher.fetch_stock_price('002428')
        current_price = price_result.value if price_result.is_success else 77.12
    except:
        current_price = 77.12
    
    # 用户可调整参数
    rf = st.sidebar.slider("无风险利率", 0.01, 0.05, 0.025, 0.0025)
    beta = st.sidebar.slider("Beta", 0.5, 2.0, 1.2, 0.1)
    tg = st.sidebar.slider("永续增长率", 0.01, 0.05, 0.03, 0.01)
    
    # 计算WACC
    engine = DiscountingEngine()
    wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta)
    st.sidebar.write(f"WACC: {wacc*100:.2f}%")
    
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
    
    sotp_price = 4.6  # SOTP固定值
    dcf_price = dcf_result['目标价_元']
    
    # 渲染三个组件
    render_soccer_field(sotp_price, dcf_price, current_price)
    st.markdown("---")
    render_sensitivity_heatmap(fcf_proj, fcf_proj[-1], wacc, 6.53)
    st.markdown("---")
    render_sentiment_bias(dcf_price, current_price)


if __name__ == '__main__':
    main()
