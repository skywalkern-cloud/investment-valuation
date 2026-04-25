#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取器 - Data Fetcher
第四层数据源管理: 自动降级策略

降级路径:
  优先手动录入(manual_data) → 可选akshare(需网络)

Phase 2 P0
"""

from __future__ import annotations

import warnings
import socket
from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any, List
import pandas as pd

warnings.filterwarnings('ignore')

# 全局socket超时（防止akshare网络挂起）
socket.setdefaulttimeout(10)

# ============================================================
# 数据源枚举
# ============================================================

class DataSource(Enum):
    """数据源优先级"""
    MANUAL = "手动录入"
    TONGHUASHUN = "同花顺"
    EASTMONEY = "东方财富"
    FAILED = "失败"

# ============================================================
# FetchResult - 标准返回格式
# ============================================================

@dataclass
class FetchResult:
    """数据获取结果"""
    value: Any
    source: DataSource
    success: bool
    error: Optional[str] = None
    timestamp: Optional[str] = None

    @property
    def is_success(self) -> bool:
        return self.success and self.value is not None


# ============================================================
# DataFetcher - 主入口
# ============================================================

class DataFetcher:
    """
    数据获取器 - 自动降级策略

    使用方式:
        fetcher = DataFetcher(manual_data={'stock_price': 77.12})
        result = fetcher.fetch_stock_price('002428')
        print(result.value, result.source)
    """

    def __init__(self, manual_data: Optional[Dict[str, Any]] = None):
        self.manual_data = manual_data or {}

    # ============================================================
    # 数值解析工具
    # ============================================================

    def _parse_num(self, val) -> float:
        """解析亿/万格式数值"""
        if val is None or val == '' or val == 'False':
            return 0.0
        if isinstance(val, (int, float)):
            return float(val)
        s = str(val).strip().replace(',', '')
        try:
            if '亿' in s:
                return float(s.replace('亿', '')) * 1e8
            elif '万' in s:
                return float(s.replace('万', '')) * 1e4
            else:
                return float(s)
        except (ValueError, AttributeError):
            return 0.0

    def _parse_pct(self, val) -> float:
        """解析百分比"""
        if val is None:
            return 0.0
        if isinstance(val, (int, float)):
            return float(val) / 100 if float(val) > 1 else float(val)
        s = str(val).strip()
        try:
            if '%' in s:
                return float(s.replace('%', '')) / 100
            v = float(s)
            return v / 100 if v > 1 else v
        except (ValueError, AttributeError):
            return 0.0

    # ============================================================
    # 股票行情 - 优先manual_data，完全跳过akshare
    # ============================================================

    def fetch_stock_price(self, stock_code: str, market: str = "SZ") -> FetchResult:
        """
        获取股票实时价格
        优先: 手动录入 → akshare(可选)
        """
        # P0优先: 手动录入，直接返回，无网络延迟
        if 'stock_price' in self.manual_data:
            return FetchResult(
                value=float(self.manual_data['stock_price']),
                source=DataSource.MANUAL,
                success=True,
            )

        # 可选: akshare (可能慢，仅在需要实时数据时启用)
        try:
            import akshare as ak
            price = ak.stock_zh_a_spot_em()
            code_map = {'SZ': '0', 'SH': '1'}
            full_code = code_map.get(market, '0') + stock_code
            row = price[price['代码'] == full_code]
            if not row.empty:
                return FetchResult(
                    value=float(row.iloc[0]['最新价']),
                    source=DataSource.TONGHUASHUN,
                    success=True,
                )
        except Exception:
            pass

        return FetchResult(value=None, source=DataSource.FAILED, success=False, error="全部数据源失败")

    # ============================================================
    # 国债收益率 - 优先manual_data，完全跳过akshare
    # ============================================================

    def fetch_10y_treasury_yield(self) -> FetchResult:
        """
        获取10年期中国国债收益率
        优先: 手动录入 → akshare(可选)
        """
        # P0优先: 手动录入
        if 'risk_free_rate' in self.manual_data:
            return FetchResult(
                value=float(self.manual_data['risk_free_rate']),
                source=DataSource.MANUAL,
                success=True,
            )

        # 可选: akshare
        try:
            import akshare as ak
            df = ak.bond_zh_us_rate()
            col = '中国国债收益率10年'
            if col in df.columns:
                vals = df[['日期', col]].dropna(subset=[col])
                if not vals.empty:
                    latest = vals.iloc[-1]
                    return FetchResult(
                        value=float(latest[col]) / 100,
                        source=DataSource.TONGHUASHUN,
                        success=True,
                        timestamp=str(latest['日期']),
                    )
        except Exception:
            pass

        # 最终降级
        return FetchResult(
            value=0.025,
            source=DataSource.MANUAL,
            success=True,
            error="使用fallback值2.5%",
        )

    # ============================================================
    # 财务摘要 (不常用，保留akshare路径)
    # ============================================================

    def fetch_financial_summary(self, stock_code: str) -> FetchResult:
        """获取财务摘要"""
        if 'financial_summary' in self.manual_data:
            return FetchResult(value=self.manual_data['financial_summary'], source=DataSource.MANUAL, success=True)

        try:
            import akshare as ak
            df = ak.stock_financial_abstract_ths(symbol=stock_code)
            if df is not None and not df.empty:
                return FetchResult(value=True, source=DataSource.TONGHUASHUN, success=True)
        except Exception:
            pass

        return FetchResult(value=None, source=DataSource.FAILED, success=False, error="财务摘要全部失败")
