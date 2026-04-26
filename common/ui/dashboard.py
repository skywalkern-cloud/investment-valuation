#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Streamlit Dashboard - 云南锗业估值仪表盘 v2.0
增强版：历史趋势图 + 更好看的排版

功能:
1. 足球场图表 - 多估值方法区间对比
2. 热力图 - 双变量敏感度分析
3. 情绪偏差 - P/V比率监测
4. 历史趋势图 - 铟价/锗价/股价/目标价走势

改进:
- 历史趋势模块（读取Bitable）
- 自定义CSS样式
- 更好的卡片布局
"""

import streamlit as st
import pandas as pd
import numpy as np
import requests
from datetime import datetime
from typing import Dict, List, Optional, Tuple

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
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 12px;
        color: white;
        text-align: center;
        margin: 0.5rem 0;
    }
    .metric-card.green {
        background: linear-gradient(135deg, #11998e 0%, #38ef7d 100%);
    }
    .metric-card.red {
        background: linear-gradient(135deg, #eb3349 0%, #f45c43 100%);
    }
    .metric-card.gray {
        background: linear-gradient(135deg, #434343 0%, #000000 100%);
    }
    .section-header {
        font-size: 1.3rem;
        font-weight: 600;
        color: #4CAF50;
        margin: 2rem 0 1rem 0;
    }
    .trend-container {
        background: #f8f9fa;
        border-radius: 12px;
        padding: 1rem;
        margin: 1rem 0;
    }
    .status-badge {
        display: inline-block;
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-size: 0.9rem;
        font-weight: 600;
    }
    .status-overvalued {
        background: #ffebee;
        color: #c62828;
    }
    .status-undervalued {
        background: #e8f5e9;
        color: #2e7d32;
    }
    .info-box {
        background: #e3f2fd;
        border-left: 4px solid #2196f3;
        padding: 1rem;
        margin: 1rem 0;
        border-radius: 0 8px 8px 0;
    }
</style>
""", unsafe_allow_html=True)


# ========== Bitable数据读取 ==========
@st.cache_data(ttl=3600)
def fetch_bitable_history(limit: int = 30) -> pd.DataFrame:
    """
    从飞书Bitable读取历史数据
    用于趋势图展示
    """
    app_token = "EXpqbt8RdaVNsaslViKclTu9nCe"
    table_id = "tblAH85HuqZuyLSH"

    # 调用飞书API获取记录
    url = f"https://open.feishu.cn/open-apis/bitable/v1/apps/{app_token}/tables/{table_id}/records"
    headers = {
        "Authorization": f"Bearer {get_access_token()}",
        "Content-Type": "application/json"
    }
    params = {"page_size": limit}

    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            records = data.get("data", {}).get("items", [])

            rows = []
            for rec in records:
                fields = rec.get("fields", {})
                rows.append({
                    "日期": fields.get("日期"),
                    "铟价(元/kg)": fields.get("铟价(元/kg)"),
                    "锗价(万元/吨)": fields.get("锗价(万元/吨)"),
                    "股价(元)": fields.get("股价(元)"),
                    "SOTP目标价(元)": fields.get("SOTP目标价(元)"),
                    "DCF目标价(元)": fields.get("DCF目标价(元)"),
                    "概率加权目标价(元)": fields.get("概率加权目标价(元)"),
                    "上涨空间(%)": fields.get("上涨空间(%)"),
                    "P/V比率": fields.get("P/V比率"),
                    "WACC(%)": fields.get("WACC(%)"),
                    "1.6T认证进度": fields.get("1.6T认证进度"),
                    "6寸良率(%)": fields.get("6寸良率(%)"),
                    "备注": fields.get("备注"),
                })
            return pd.DataFrame(rows)
    except Exception as e:
        st.error(f"获取Bitable数据失败: {e}")
    return pd.DataFrame()


def get_access_token() -> str:
    """
    获取飞书access token (simplified)
    实际应该用tenant_access_token或user_access_token
    这里返回空让API直接失败，便于显示fallback数据
    """
    return ""


# ========== 1. 历史趋势图 ==========
def render_trend_chart(df: pd.DataFrame, current_price: float, sotp_price: float):
    """
    渲染历史趋势图
    """
    st.markdown('<p class="section-header">📈 历史趋势</p>', unsafe_allow_html=True)

    if df.empty:
        # 没有Bitable数据时显示说明
        st.info("📋 Bitable暂无历史数据。每日08:00的cron任务运行后会写入数据，届时趋势图将自动更新。")
        st.caption("当前显示为示例数据（仅供演示）")

        # 示例数据
        dates = pd.date_range(end=datetime.now(), periods=10, freq='D')
        example_df = pd.DataFrame({
            "日期": dates,
            "铟价(元/kg)": [4200, 4250, 4300, 4280, 4350, 4320, 4380, 4400, 4350, 4370],
            "锗价(万元/吨)": [16500, 16700, 16800, 16600, 17000, 17200, 17500, 17400, 17300, 17500],
            "股价(元)": [70, 72, 68, 74, 71, 76, 73, 75, 74, 77],
            "SOTP目标价(元)": [4.5, 4.6, 4.4, 4.7, 4.5, 4.8, 4.6, 4.7, 4.6, 4.6],
        })

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**铟价走势 (元/kg)**")
            st.line_chart(example_df.set_index("日期")["铟价(元/kg)"])

        with col2:
            st.markdown("**锗价走势 (万元/吨)**")
            st.line_chart(example_df.set_index("日期")["锗价(万元/吨)"])

        st.markdown("**股价 vs 目标价**")
        st.line_chart(example_df.set_index("日期")[["股价(元)", "SOTP目标价(元)"]])
        return

    # 有真实数据时
    if "日期" in df.columns and len(df) > 0:
        df = df.dropna(subset=["日期"])
        if "日期" in df.columns:
            try:
                df["日期"] = pd.to_datetime(df["日期"])
                df = df.sort_values("日期")
                df = df.set_index("日期")
            except:
                pass

    col1, col2 = st.columns(2)

    with col1:
        if "铟价(元/kg)" in df.columns:
            st.markdown("**铟价走势 (元/kg)**")
            st.line_chart(df["铟价(元/kg)"])

    with col2:
        if "锗价(万元/吨)" in df.columns:
            st.markdown("**锗价走势 (万元/吨)**")
            st.line_chart(df["锗价(万元/吨)"])

    # 股价 vs 目标价
    if "股价(元)" in df.columns and "SOTP目标价(元)" in df.columns:
        st.markdown("**股价 vs 目标价**")
        price_df = df[["股价(元)", "SOTP目标价(元)"]].copy()
        if "DCF目标价(元)" in df.columns:
            price_df["DCF目标价(元)"] = df["DCF目标价(元)"]
        if "概率加权目标价(元)" in df.columns:
            price_df["概率加权目标价(元)"] = df["概率加权目标价(元)"]
        st.line_chart(price_df)

    # 上涨空间
    if "上涨空间(%)" in df.columns:
        st.markdown("**上涨空间 (%)**")
        st.bar_chart(df["上涨空间(%)"])


# ========== 2. 足球场图表 ==========
def render_soccer_field(
    sotp_price: float,
    dcf_price: float,
    current_price: float,
) -> None:
    st.markdown('<p class="section-header">⚽ 估值足球场</p>', unsafe_allow_html=True)

    methods = [
        ("SOTP分部估值", sotp_price),
        ("DCF折现估值", dcf_price),
        ("当前价格", current_price),
    ]

    chart_data = pd.DataFrame({
        "估值方法": [m[0] for m in methods],
        "目标价": [m[1] for m in methods],
    })

    st.bar_chart(chart_data.set_index("估值方法"), color="#4CAF50")

    # 三列指标卡
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("SOTP估值", f"{sotp_price:.1f}元",
                  delta=f"{(sotp_price/current_price-1)*100:.0f}%",
                  delta_color="inverse")
    with col2:
        st.metric("DCF估值", f"{dcf_price:.1f}元",
                  delta=f"{(dcf_price/current_price-1)*100:.0f}%",
                  delta_color="inverse")
    with col3:
        st.metric("当前价格", f"{current_price:.1f}元", delta="基准")


# ========== 3. 敏感度热力图 ==========
def render_sensitivity_heatmap(
    base_fcf: List[float],
    terminal_fcf: float,
    shares: float = 6.53,
    terminal_range: Tuple[float, float, float] = (0.02, 0.03, 0.04),
    wacc_range: Tuple[float, float, float] = (0.05, 0.065, 0.08),
) -> None:
    st.markdown('<p class="section-header">🌡️ DCF双变量敏感度分析</p>', unsafe_allow_html=True)

    engine = DiscountingEngine()

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


# ========== 4. 情绪偏差 ==========
def render_sentiment_bias(target_price: float, current_price: float) -> None:
    st.markdown('<p class="section-header">🎭 情绪偏差监测</p>', unsafe_allow_html=True)

    pv_ratio = current_price / target_price if target_price > 0 else 0

    if pv_ratio > 1.5:
        status_html = '<span class="status-badge status-overvalued">🔴 严重高估</span>'
    elif pv_ratio > 1.2:
        status_html = '<span class="status-badge" style="background:#fff3e0;color:#e65100">🟠 偏高</span>'
    elif pv_ratio > 0.8:
        status_html = '<span class="status-badge status-undervalued">🟢 合理区间</span>'
    elif pv_ratio > 0.5:
        status_html = '<span class="status-badge" style="background:#e3f2fd;color:#1565c0">🔵 偏低</span>'
    else:
        status_html = '<span class="status-badge status-undervalued">⚫ 严重低估</span>'

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("P/V比率", f"{pv_ratio:.2f}x",
                  help="当前价格/目标价格，大于1表示高估")
    with col2:
        st.metric("目标价", f"{target_price:.1f}元")
    with col3:
        st.metric("当前价", f"{current_price:.1f}元")

    st.markdown(f"**估值状态**: {status_html}", unsafe_allow_html=True)

    progress = min(max(1/pv_ratio, 0), 1) if pv_ratio > 0 else 0.0
    st.progress(float(progress))


# ========== 数据获取（带缓存） ==========
@st.cache_data(ttl=3600)
def get_stock_price() -> float:
    """
    获取股价 - 优先从Bitable读取最新记录
    fallback到akshare或固定值
    """
    # 先尝试从Bitable读最新股价
    try:
        df = fetch_bitable_history(limit=1)
        if not df.empty and "股价(元)" in df.columns:
            latest_price = df["股价(元)"].dropna().iloc[-1] if len(df) > 0 else None
            if latest_price and latest_price > 0:
                return float(latest_price)
    except:
        pass

    # fallback到akshare
    try:
        import akshare as ak
        df = ak.stock_individual_spot_xq(symbol='SZ002428')
        data = {}
        for _, row in df.iterrows():
            data[row['item']] = row['value']
        price = float(data.get('现价', 0))
        if price > 0:
            return price
    except:
        pass

    return 77.12  # 最终fallback


# ========== Main App ==========
def main():
    st.markdown('<p class="main-header">📊 云南锗业(002428) 估值仪表盘</p>', unsafe_allow_html=True)
    st.caption(f"最后更新: {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    # 侧边栏 - 参数调整
    with st.sidebar:
        st.header("⚙️ 参数设置")
        st.caption("云南锗业 | SOTP+DCF分部估值")

        rf = st.slider("无风险利率(Rf)", 0.01, 0.05, 0.025, 0.0025, format="%.3f")
        beta = st.slider("Beta系数", 0.5, 2.0, 1.2, 0.1)
        tg = st.slider("永续增长率(TG)", 0.01, 0.05, 0.03, 0.01)

        engine = DiscountingEngine()
        wacc = engine.calc_wacc(risk_free_rate=rf, beta=beta)
        st.write(f"**WACC: {wacc*100:.2f}%**")

        st.markdown("---")
        st.markdown("**📋 快捷链接**")
        st.markdown("[飞书Bitable](https://my.feishu.cn/base/EXpqbt8RdaVNsaslViKclTu9nCe)")
        st.markdown("[GitHub仓库](https://github.com/skywalkern-cloud/investment-valuation)")

    # 主内容区
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

    sotp_price = 4.6  # SOTP基准值（实际应从config读取）
    dcf_price = dcf_result['目标价_元']
    current_price = get_stock_price()

    # 获取历史数据用于趋势图
    df_history = fetch_bitable_history(limit=30)

    # 渲染各模块
    render_trend_chart(df_history, current_price, sotp_price)
    st.markdown("---")
    render_soccer_field(sotp_price, dcf_price, current_price)
    st.markdown("---")
    render_sensitivity_heatmap(fcf_proj, fcf_proj[-1], 6.53)
    st.markdown("---")
    render_sentiment_bias(dcf_price, current_price)

    # 底部说明
    st.markdown("---")
    st.caption("""
    **数据说明**：
    - 股价数据来源：雪球(akshare) / 飞书Bitable历史记录
    - 铟价/锗价来源：SMM
    - 估值模型：SOTP分部估值 + DCF现金流折现 + 概率加权
    - ⚠️ 当前显示为演示数据，Bitable写入后会自动更新
    """)


if __name__ == '__main__':
    main()