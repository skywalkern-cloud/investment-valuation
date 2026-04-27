#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据获取统一入口 + 降级策略 (Data Fetcher)
Phase 2 P0

提供统一的 `get_financials` 和 `get_market_data` 接口，
底层委托给 `common.data.fetcher.DataFetcher`。

降级路径 (设计文档定义):
    1. 手动录入 (manual_data)  — 最高优先级，零延迟
    2. akshare同花顺           — 免费，无需API Key
    3. akshare东方财富备用     — 降级路径
    4. 手动录入兜底            — 使用配置的fallback值

使用方式:
    >>> from common.core.data_fetcher import DataFetcher
    >>> fetcher = DataFetcher(manual_data={'stock_price': 77.12, 'revenue': 8.5})
    >>> mkt = fetcher.get_market_data('002428')
    >>> fin = fetcher.get_financials('002428')
"""

from __future__ import annotations

from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from enum import Enum
import warnings

# 委托给 common.data.fetcher（内部已有完整实现）
from common.data.fetcher import DataFetcher as _InnerFetcher, FetchResult, DataSource


# ============================================================
# ExtendedFetchResult — 扩展返回格式
# ============================================================

@dataclass
class ExtendedFetchResult:
    """扩展数据获取结果（带使用建议）"""
    value: Any
    source: str               # DataSource枚举值
    success: bool
    error: Optional[str] = None
    used_fallback: bool = False   # 是否使用了降级fallback
    suggestions: List[str] = field(default_factory=list)

    @property
    def is_success(self) -> bool:
        return self.success and self.value is not None


# ============================================================
# DataFetcher — 统一入口 (common/core/)
# ============================================================

class DataFetcher:
    """
    数据获取统一入口 + 降级策略 — Phase 2 P0

    封装 common.data.fetcher.DataFetcher，暴露：
        - get_financials():   财务数据（三表+衍生指标）
        - get_market_data():  市场数据（股价+宏观）

    支持 manual_data 注入（用于测试、离线、配置优先场景）。

    使用方式:
        >>> fetcher = DataFetcher(manual_data={'stock_price': 77.12, 'revenue': 8.5})
        >>> mkt = fetcher.get_market_data('002428')
        >>> fin = fetcher.get_financials('002428', manual_override={'net_profit': 0.66})
    """

    def __init__(
        self,
        manual_data: Optional[Dict[str, Any]] = None,
        fallback_risk_free_rate: float = 0.025,
        fallback_beta: float = 1.2,
    ):
        """
        Args:
            manual_data: 手动数据注入 (key-value)，用于测试/离线/配置优先
            fallback_risk_free_rate: 10年国债fallback值 (default 2.5%)
            fallback_beta: Beta系数fallback值 (default 1.2)
        """
        self._manual = manual_data or {}
        self._fallback_rf = fallback_risk_free_rate
        self._fallback_beta = fallback_beta
        self._inner = _InnerFetcher(manual_data=self._manual)

    # ============================================================
    # 市场数据
    # ============================================================

    def get_market_data(
        self,
        stock_code: str,
        market: str = "SZ",
        include_macro: bool = True,
    ) -> ExtendedFetchResult:
        """
        获取市场数据（股价 + 宏观）— Phase 2 P0

        降级路径:
            manual_data['stock_price'] → akshare → 东方财富备用 → error

        Args:
            stock_code:  股票代码 (如 '002428')
            market:     市场 ('SZ' 或 'SH')
            include_macro: 是否同时获取10年国债收益率

        Returns:
            ExtendedFetchResult:
                {
                    'stock_price': float,     # 股价 (元)
                    'shares': float,          # 总股本 (亿股)
                    'market_cap': float,       # 总市值 (亿元)
                    'risk_free_rate': float,   # 无风险利率 (小数)
                    'source': str,
                    'success': bool,
                }
        """
        suggestions: List[str] = []
        used_fallback = False

        # 1. 优先: manual_data
        if 'stock_price' in self._manual:
            price = float(self._manual['stock_price'])
            shares = float(self._manual.get('shares', 0))
            rf = float(self._manual.get('risk_free_rate', self._fallback_rf))

            result = {
                'stock_price': price,
                'shares': shares,
                'market_cap': price * shares if shares > 0 else 0.0,
                'risk_free_rate': rf,
            }
            return ExtendedFetchResult(
                value=result,
                source='manual',
                success=True,
                used_fallback=False,
                suggestions=["使用manual_data，零延迟"],
            )

        # 2. akshare
        price_result = self._inner.fetch_stock_price(stock_code, market)
        if price_result.is_success:
            result = {
                'stock_price': price_result.value,
                'shares': 0.0,          # 行情接口暂不支持股本
                'market_cap': 0.0,
                'risk_free_rate': self._fallback_rf,
            }

            # 3. 尝试获取国债
            if include_macro:
                rf_result = self._inner.fetch_10y_treasury_yield()
                if rf_result.is_success:
                    result['risk_free_rate'] = rf_result.value
                else:
                    suggestions.append("国债收益率获取失败，使用fallback 2.5%")
                    result['risk_free_rate'] = self._fallback_rf
                    used_fallback = True

            return ExtendedFetchResult(
                value=result,
                source=price_result.source.value,
                success=True,
                used_fallback=used_fallback,
                suggestions=suggestions,
            )

        # 4. 全部失败
        return ExtendedFetchResult(
            value=None,
            source='failed',
            success=False,
            error="股票行情全部数据源失败",
            suggestions=["请检查网络或注入manual_data{'stock_price': ...}"],
        )

    # ============================================================
    # 财务数据
    # ============================================================

    def get_financials(
        self,
        stock_code: str,
        report_type: str = 'annual',
        manual_override: Optional[Dict[str, Any]] = None,
    ) -> ExtendedFetchResult:
        """
        获取财务数据（三表+衍生指标）— Phase 2 P0

        降级路径:
            manual_override → akshare同花顺 → 东方财富备用 → 手动录入fallback

        Args:
            stock_code:   股票代码 (如 '002428')
            report_type:  'annual' 或 'quarter'
            manual_override: 手动覆盖特定字段 (key-value)

        Returns:
            ExtendedFetchResult:
                {
                    'revenue': float,         # 营业收入 (亿元)
                    'net_profit': float,      # 净利润 (亿元)
                    'net_profit_attr': float, # 归母净利润 (亿元)
                    'gross_margin': float,    # 毛利率 (小数)
                    'net_margin': float,      # 净利率 (小数)
                    'roe': float,             # ROE (小数)
                    'eps': float,             # 每股收益 (元)
                    'bps': float,             # 每股净资产 (元)
                    'shares': float,          # 总股本 (亿股)
                    'price': float,           # 当前股价 (元)
                    'market_cap': float,      # 总市值 (亿元)
                    'data_source': str,       # 数据来源标签
                    'report_date': str,       # 报告期
                    ... (更多字段参考 FinancialFoundation)
                }
        """
        suggestions: List[str] = []
        used_fallback = False
        override = manual_override.copy() if manual_override else {}

        # 1. FinancialFoundation (akshare封装)
        try:
            from common.core.financial_foundation import FinancialFoundation
            ff = FinancialFoundation.from_akshare(stock_code, report_type)

            # 合并manual_override
            for k, v in override.items():
                if hasattr(ff, k):
                    setattr(ff, k, v)

            result = {
                'revenue': ff.revenue,
                'operating_profit': ff.operating_profit,
                'net_profit': ff.net_profit,
                'net_profit_attr': ff.net_profit_attr,
                'gross_margin': ff.gross_margin,
                'net_margin': ff.net_margin,
                'roe': ff.roe,
                'roic': ff.roic,
                'eps': ff.eps,
                'bps': ff.bps,
                'shares': ff.shares,
                'price': ff.price,
                'market_cap': ff.market_cap,
                'ev': ff.ev,
                'data_source': ff.data_source or 'akshare',
                'report_date': ff.report_date,
                'update_time': ff.update_time,
            }
            return ExtendedFetchResult(
                value=result,
                source='akshare',
                success=True,
                used_fallback=False,
                suggestions=["使用akshare同花顺数据"],
            )

        except Exception as e:
            suggestions.append(f"akshare获取失败: {e}")

        # 2. 东方财富备用
        try:
            import akshare as ak
            df = ak.stock_financial_abstract_ths(symbol=stock_code)
            if df is not None and len(df) > 0:
                latest = df.iloc[-1]
                result = {
                    'revenue': float(latest.get('营业总收入', 0)) / 1e8,
                    'net_profit': float(latest.get('净利润', 0)) / 1e8,
                    'net_profit_attr': float(latest.get('净利润', 0)) / 1e8,
                    'gross_margin': 0.0,
                    'net_margin': 0.0,
                    'roe': 0.0,
                    'eps': float(latest.get('基本每股收益', 0) or 0),
                    'bps': float(latest.get('每股净资产', 0) or 0),
                    'shares': 0.0,
                    'price': 0.0,
                    'market_cap': 0.0,
                    'ev': 0.0,
                    'data_source': 'eastmoney_backup',
                    'report_date': str(latest.get('报告期', '')),
                }
                return ExtendedFetchResult(
                    value=result,
                    source='eastmoney',
                    success=True,
                    used_fallback=True,
                    suggestions=["使用东方财富备用数据"],
                )
        except Exception as e2:
            suggestions.append(f"东方财富备用也失败: {e2}")

        # 3. 手动录入兜底
        if override:
            result = {
                'revenue': override.get('revenue', 0.0),
                'net_profit': override.get('net_profit', 0.0),
                'net_profit_attr': override.get('net_profit_attr', override.get('net_profit', 0.0)),
                'gross_margin': override.get('gross_margin', 0.0),
                'net_margin': override.get('net_margin', 0.0),
                'roe': override.get('roe', 0.0),
                'eps': override.get('eps', 0.0),
                'bps': override.get('bps', 0.0),
                'shares': override.get('shares', 0.0),
                'price': override.get('price', 0.0),
                'market_cap': override.get('market_cap', 0.0),
                'ev': override.get('ev', 0.0),
                'data_source': 'manual_override',
                'report_date': override.get('report_date', 'N/A'),
            }
            return ExtendedFetchResult(
                value=result,
                source='manual',
                success=True,
                used_fallback=True,
                suggestions=["使用manual_override兜底数据"],
            )

        # 4. 全部失败
        return ExtendedFetchResult(
            value=None,
            source='failed',
            success=False,
            error="财务数据全部来源失败",
            suggestions=[
                "请注入 manual_override={'revenue': ..., 'net_profit': ...}",
                "或检查网络连接",
            ],
        )

    # ============================================================
    # 工具方法
    # ============================================================

    def fetch_10y_treasury_yield(self) -> ExtendedFetchResult:
        """获取10年国债收益率（委托内部fetcher）"""
        inner = self._inner.fetch_10y_treasury_yield()
        return ExtendedFetchResult(
            value=inner.value,
            source=inner.source.value,
            success=inner.success,
            error=inner.error,
            used_fallback=(inner.source == DataSource.MANUAL),
        )

    def fetch_stock_price(self, stock_code: str, market: str = "SZ") -> ExtendedFetchResult:
        """获取股票价格（委托内部fetcher）"""
        inner = self._inner.fetch_stock_price(stock_code, market)
        return ExtendedFetchResult(
            value=inner.value,
            source=inner.source.value,
            success=inner.success,
            error=inner.error,
        )

    def get_beta_status(self) -> Dict[str, Any]:
        """
        获取Beta状态（含过期警告）

        Returns:
            {'beta': float, 'last_updated': str, 'expired': bool, 'days_ago': int}
        """
        return {
            'beta': self._fallback_beta,
            'last_updated': '',          # 需外部注入
            'expired': True,             # 默认过期，需外部注入更新
            'days_ago': 999,
            'suggestion': '建议每季度更新Beta，参考Wind历史Beta计算',
        }


# ============================================================
# 快速函数
# ============================================================

def quick_fetch(stock_code: str, manual_data: Optional[Dict] = None) -> Dict[str, Any]:
    """
    快速获取股票完整数据（市场+财务）

    Args:
        stock_code: 股票代码
        manual_data: 手动数据

    Returns:
        {'market': {...}, 'financials': {...}, 'errors': [...]}
    """
    fetcher = DataFetcher(manual_data=manual_data or {})

    mkt = fetcher.get_market_data(stock_code)
    fin = fetcher.get_financials(stock_code)

    errors = []
    if not mkt.success:
        errors.append(f"market: {mkt.error}")
    if not fin.success:
        errors.append(f"financials: {fin.error}")

    return {
        'market': mkt.value if mkt.success else None,
        'financials': fin.value if fin.success else None,
        'errors': errors,
        'full_success': mkt.success and fin.success,
    }


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    print("=== DataFetcher 测试 ===\n")

    fetcher = DataFetcher(manual_data={
        'stock_price': 77.12,
        'shares': 6.53,
        'revenue': 8.5,
        'net_profit': 0.66,
    })

    # 1. 市场数据
    print("1. get_market_data:")
    mkt = fetcher.get_market_data('002428')
    print(f"   success: {mkt.success} | source: {mkt.source}")
    if mkt.is_success:
        print(f"   股价: {mkt.value['stock_price']}元")
        print(f"   国债: {mkt.value['risk_free_rate']*100:.2f}%")
    else:
        print(f"   error: {mkt.error}")
    print()

    # 2. 财务数据
    print("2. get_financials:")
    fin = fetcher.get_financials('002428')
    print(f"   success: {fin.success} | source: {fin.source}")
    if fin.is_success:
        print(f"   营收: {fin.value['revenue']:.2f}亿元")
        print(f"   净利: {fin.value['net_profit']:.2f}亿元")
    else:
        print(f"   error: {fin.error}")
    print()

    # 3. 快速获取
    print("3. quick_fetch:")
    q = quick_fetch('002428', {'stock_price': 77.12})
    print(f"   full_success: {q['full_success']}")
    print(f"   errors: {q['errors']}")
