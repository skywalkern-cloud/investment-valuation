#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Beta系数自动刷新器 (Beta Auto-Refresh)
Phase 2 P1

提供 Beta 系数的自动获取与过期刷新能力。

刷新路径:
    1. 手动配置 (manual_beta)     — 最高优先级
    2. akshare 获取             — 免费，无需API Key
    3. fallback (1.2)           — 最终降级

使用方式:
    >>> from common.core.beta_auto_refresh import BetaAutoRefresh
    >>> refresher = BetaAutoRefresh(manual_beta=1.2, manual_last_updated='2026-01-15')
    >>> beta, date, source, did_refresh = refresher.get_beta_with_auto_refresh('002428')
    >>> print(f"Beta={beta}, 刷新={did_refresh}, 来源={source.value}")
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional, Tuple


class BetaSource(Enum):
    """Beta数据来源"""
    MANUAL = "manual"
    AKSHARE = "akshare"
    FALLBACK = "fallback"


@dataclass
class BetaResult:
    """Beta获取结果"""
    beta: float
    source: BetaSource
    last_updated: str   # YYYY-MM-DD，Beta值对应的"基准日"
    fetched_at: str     # YYYY-MM-DD，实际获取时间


class BetaAutoRefresh:
    """
    Beta系数自动刷新器

    使用方式:
        >>> refresher = BetaAutoRefresh(manual_beta=1.2, manual_last_updated='2026-01-15')
        >>> beta, date, source, did_refresh = refresher.get_beta_with_auto_refresh('002428', 'SZ', max_days=90)
    """

    def __init__(
        self,
        fallback_beta: float = 1.2,
        manual_beta: Optional[float] = None,
        manual_last_updated: Optional[str] = None,
    ):
        """
        Args:
            fallback_beta:        所有路径失败时的默认值 (default 1.2)
            manual_beta:         手动配置的Beta值 (最高优先级)
            manual_last_updated: 手动Beta的"基准日" (YYYY-MM-DD)
        """
        self.fallback_beta = fallback_beta
        self.manual_beta = manual_beta
        self.manual_last_updated = manual_last_updated

    # ============================================================
    # 主入口
    # ============================================================

    def get_beta_with_auto_refresh(
        self,
        stock_code: str = "002428",
        market: str = "SZ",
        max_days: int = 90,
    ) -> Tuple[float, str, BetaSource, bool]:
        """
        统一入口：检查过期则自动刷新

        Args:
            stock_code: 股票代码
            market:     市场 ('SZ' 或 'SH')
            max_days:   最大未更新天数 (default 90)

        Returns:
            (beta, last_updated, source, did_refresh)
            - did_refresh=True 表示发生了自动刷新
        """
        return self.refresh_if_expired(
            current_beta=self.manual_beta or self.fallback_beta,
            last_updated=self.manual_last_updated or "",
            max_days=max_days,
            stock_code=stock_code,
            market=market,
        )

    def refresh_if_expired(
        self,
        current_beta: float,
        last_updated: str,
        max_days: int,
        stock_code: str = "002428",
        market: str = "SZ",
    ) -> Tuple[float, str, BetaSource, bool]:
        """
        检查过期则自动刷新

        Args:
            current_beta: 当前Beta值
            last_updated: 上次更新时间 (YYYY-MM-DD)
            max_days:     最大未更新天数
            stock_code:   股票代码
            market:       市场

        Returns:
            (beta, last_updated, source, did_refresh)
        """
        from datetime import datetime

        # 1. 未过期: 直接返回当前值
        if last_updated:
            try:
                last_dt = datetime.strptime(last_updated, '%Y-%m-%d')
                days_ago = (datetime.now() - last_dt).days
                if days_ago <= max_days:
                    source = BetaSource.MANUAL if self.manual_beta is not None else BetaSource.AKSHARE
                    return (current_beta, last_updated, source, False)
            except (ValueError, TypeError):
                pass

        # 2. 过期/无效: 自动刷新
        result = self.fetch_beta(stock_code, market)
        return (result.beta, result.last_updated, result.source, True)

    # ============================================================
    # Beta 获取
    # ============================================================

    def fetch_beta(
        self,
        stock_code: str,
        market: str = "SZ",
    ) -> BetaResult:
        """
        获取Beta系数

        降级路径:
            手动配置 → akshare → fallback(1.2)

        Args:
            stock_code: 股票代码
            market:     市场 ('SZ' 或 'SH')

        Returns:
            BetaResult(beta, source, last_updated, fetched_at)
        """
        today = self._today()

        # 1. 优先手动配置
        if self.manual_beta is not None:
            return BetaResult(
                beta=self.manual_beta,
                source=BetaSource.MANUAL,
                last_updated=self.manual_last_updated or today,
                fetched_at=today,
            )

        # 2. akshare
        try:
            beta = self._fetch_from_akshare(stock_code, market)
            if beta is not None:
                return BetaResult(
                    beta=beta,
                    source=BetaSource.AKSHARE,
                    last_updated=today,
                    fetched_at=today,
                )
        except NotImplementedError:
            pass
        except Exception:
            pass

        # 3. 最终降级
        return BetaResult(
            beta=self.fallback_beta,
            source=BetaSource.FALLBACK,
            last_updated="",
            fetched_at=today,
        )

    def _fetch_from_akshare(self, stock_code: str, market: str) -> Optional[float]:
        """
        从 akshare 获取 Beta 系数

        实现策略:
            股票历史Beta通常需要:
            1. 获取个股历史收益率
            2. 获取指数(沪深300)历史收益率
            3. 线性回归计算Beta

        目前抛出 NotImplementedError，后续可扩展实现。

        Returns:
            Beta 系数 (原始值)，或 None
        """
        raise NotImplementedError(
            "akshare Beta获取尚未实现。"
            "请注入 manual_beta 参数或等待后续版本。"
        )

    # ============================================================
    # 工具
    # ============================================================

    def _today(self) -> str:
        return date.today().isoformat()

    def is_expired(self, last_updated: str, max_days: int = 90) -> Tuple[bool, int]:
        """
        检查给定日期是否过期

        Returns:
            (是否过期, 距今天数)
        """
        from datetime import datetime
        if not last_updated:
            return (True, max_days)
        try:
            last_dt = datetime.strptime(last_updated, '%Y-%m-%d')
            days_ago = (datetime.now() - last_dt).days
            return (days_ago > max_days, days_ago)
        except Exception:
            return (True, max_days)


# ============================================================
# 便捷函数
# ============================================================

def get_beta(
    stock_code: str = "002428",
    market: str = "SZ",
    manual_beta: Optional[float] = None,
    manual_last_updated: Optional[str] = None,
    max_days: int = 90,
) -> Tuple[float, str, BetaSource, bool]:
    """
    便捷函数：一行获取Beta（自动处理过期刷新）

    Args:
        stock_code:          股票代码
        market:              市场
        manual_beta:         手动Beta（优先于自动获取）
        manual_last_updated: 手动Beta的基准日
        max_days:            最大有效天数

    Returns:
        (beta, last_updated, source, did_refresh)
    """
    refresher = BetaAutoRefresh(
        fallback_beta=1.2,
        manual_beta=manual_beta,
        manual_last_updated=manual_last_updated,
    )
    return refresher.get_beta_with_auto_refresh(
        stock_code=stock_code, market=market, max_days=max_days
    )


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    from datetime import datetime, timedelta

    print("=== BetaAutoRefresh 测试 ===\n")

    # 1. 手动配置优先
    refresher = BetaAutoRefresh(
        manual_beta=1.25,
        manual_last_updated='2026-01-15',
    )
    result = refresher.fetch_beta('002428')
    print(f"1. 手动配置: Beta={result.beta}, 来源={result.source.value}")

    # 2. 过期时自动刷新
    refresher2 = BetaAutoRefresh(fallback_beta=1.2)
    today = datetime.now().strftime('%Y-%m-%d')
    expired_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
    beta, date, source, did = refresher2.refresh_if_expired(
        current_beta=1.2,
        last_updated=expired_date,
        max_days=90,
        stock_code='002428',
    )
    print(f"2. 过期自动刷新: Beta={beta}, 日期={date}, 来源={source.value}, 刷新={did}")

    # 3. 未过期不刷新
    beta2, date2, source2, did2 = refresher2.refresh_if_expired(
        current_beta=1.2,
        last_updated=today,
        max_days=90,
        stock_code='002428',
    )
    print(f"3. 未过期不刷新: Beta={beta2}, 日期={date2}, 来源={source2.value}, 刷新={did2}")

    # 4. 便捷函数
    print()
    print("4. 便捷函数 get_beta:")
    beta, date, source, did = get_beta(
        manual_beta=1.3,
        manual_last_updated='2026-03-01',
    )
    print(f"   Beta={beta}, 日期={date}, 来源={source.value}, 刷新={did}")
