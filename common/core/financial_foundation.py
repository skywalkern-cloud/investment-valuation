#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标准化财务底座 (Standardized Financial Foundation)
第一层: 对接三表, 计算ROIC/WACC/EBITDA/FCF

所有标的共用, 与具体行业无关.
"""

from __future__ import annotations

import warnings
warnings.filterwarnings('ignore')

from typing import Optional, Dict, Any, List
from dataclasses import dataclass, field
from datetime import datetime
import pandas as pd
import numpy as np


@dataclass
class FinancialFoundation:
    """
    标准化财务底座

    使用方式:
    >>> ff = FinancialFoundation.from_akshare('002428')
    >>> print(ff.revenue, ff.ebitda, ff.roic, ff.wacc)
    """

    # === 基础信息 ===
    stock_code: str
    stock_name: str = ""
    report_date: str = ""           # 报告期 (YYYY-MM-DD)

    # === 利润表核心 ===
    revenue: float = 0.0            # 营业收入 (亿元)
    operating_profit: float = 0.0  # 营业利润 (亿元)
    net_profit: float = 0.0        # 净利润 (亿元)
    net_profit_attr: float = 0.0   # 归母净利润 (亿元)
    ebitda: float = 0.0            # EBITDA (亿元)

    # === 资产负债表核心 ===
    total_assets: float = 0.0      # 总资产 (亿元)
    total_liabilities: float = 0.0  # 总负债 (亿元)
    total_equity: float = 0.0       # 归母权益 (亿元)
    cash: float = 0.0               # 货币资金 (亿元)
    net_debt: float = 0.0          # 净债务 = 总负债 - 货币资金

    # === 现金流量表核心 ===
    operating_cf: float = 0.0      # 经营活动现金流 (亿元)
    capex: float = 0.0              # 资本支出 (亿元)
    fcf: float = 0.0               # 自由现金流 = 经营现金流 - CAPEX

    # === 股份 ===
    shares: float = 0.0            # 总股本 (亿股)
    price: float = 0.0             # 当前股价 (元)
    market_cap: float = 0.0        # 总市值 = price × shares (亿元)

    # === 衍生指标 ===
    ev: float = 0.0               # 企业价值 = 市值 + 净债务
    roic: float = 0.0             # 投入资本回报率 = NOPAT / 投入资本
    wacc: float = 0.0              # 加权平均资本成本
    net_margin: float = 0.0        # 净利率
    gross_margin: float = 0.0      # 毛利率
    gross_profit: float = 0.0      # 毛利润

    # === EPS/BPS ===
    eps: float = 0.0              # 每股收益 (元)
    bps: float = 0.0              # 每股净资产 (元)
    roe: float = 0.0              # 净资产收益率

    # === 宏观数据 (可选) ===
    risk_free_rate: float = 0.0   # 无风险利率 (10年国债)

    # === 元数据 ===
    data_source: str = ""
    update_time: str = ""

    # ========== 工厂方法 ==========

    @classmethod
    def from_akshare(cls, stock_code: str, report_type: str = 'annual') -> 'FinancialFoundation':
        """
        从akshare获取财务数据并构建FinancialFoundation

        Args:
            stock_code: 股票代码 (如 '002428')
            report_type: 'annual' 或 'quarter'
        """
        import sys

        ff = cls(stock_code=stock_code)

        # 1. 获取财务摘要
        try:
            df_fin = ak.stock_financial_abstract_ths(symbol=stock_code)
            if len(df_fin) > 0:
                # 数据按时间倒序排列(最新在前),取最新年报
                # 年报: 12-31日期, 取最接近当前日期的12-31
                annual = df_fin[df_fin['报告期'].str.endswith('12-31', na=False)]
                if len(annual) > 0:
                    # 取最新年报(最后一个12-31)
                    latest = annual.iloc[-1]
                else:
                    latest = df_fin.iloc[-1]  # fallback

                ff.report_date = str(latest.get('报告期', ''))

                # 解析数值 (处理"1.23亿" "4567万"格式)
                def parse_val(v):
                    if v is None or str(v) == 'False' or pd.isna(v):
                        return 0.0
                    s = str(v).strip()
                    try:
                        if '亿' in s:
                            return float(s.replace('亿', '')) * 1e8
                        elif '万' in s:
                            return float(s.replace('万', '')) * 1e4
                        elif '万亿' in s:
                            return float(s.replace('万亿', '')) * 1e12
                        elif '%' in s:
                            return float(s.replace('%', ''))  # 留百分数形式,后续处理
                        else:
                            return float(s) * 1e8 if float(s) < 1000 else float(s)
                    except:
                        return 0.0

                ff.revenue = parse_val(latest.get('营业总收入', 0)) / 1e8
                ff.net_profit = parse_val(latest.get('净利润', 0)) / 1e8
                ff.net_profit_attr = ff.net_profit
                ff.eps = float(latest.get('基本每股收益', 0) or 0)
                ff.bps = float(latest.get('每股净资产', 0) or 0)

                # 毛利率
                gm_raw = latest.get('销售毛利率', 0)
                if gm_raw and str(gm_raw) != 'False':
                    gm_str = str(gm_raw).replace('%', '')
                    try:
                        ff.gross_margin = float(gm_str) / 100.0 if abs(float(gm_str)) > 1 else float(gm_str)
                    except:
                        ff.gross_margin = 0.0
                else:
                    ff.gross_margin = 0.0

                # ROE
                roe_raw = latest.get('净资产收益率', 0)
                if roe_raw and str(roe_raw) != 'False':
                    roe_str = str(roe_raw).replace('%', '')
                    try:
                        ff.roe = float(roe_str) / 100.0 if abs(float(roe_str)) > 1 else float(roe_str)
                    except:
                        ff.roe = 0.0
                else:
                    ff.roe = 0.0

                ff.data_source = 'ths'
        except Exception as e:
            print(f"⚠️ 财务摘要获取失败: {e}")

        # 2. 获取实时行情 (优先腾讯API，akshare静默失败)
        ff.price = 0
        try:
            # 尝试腾讯行情API（不走代理）
            sys.path.insert(0, '/Users/vincentnie/.openclaw/workspace-market-insight/scripts')
            from data.stock_api import get_a_stock_quote
            quotes = get_a_stock_quote([stock_code])
            if quotes:
                ff.price = float(quotes[0]['price'])
                print(f"  ⚡ 股价获取成功: {ff.price}元 (腾讯行情)")
        except Exception:
            pass

        # fallback: akshare（可能失败，返回0）
        if ff.price == 0:
            try:
                df_spot = ak.stock_individual_spot_xq(symbol=f'SZ{stock_code}' if stock_code.startswith('00') else f'SH{stock_code}')
                data_spot = {row['item']: row['value'] for _, row in df_spot.iterrows()}
                ff.price = float(data_spot.get('现价', 0))
                if ff.price > 0:
                    print(f"  ⚡ 股价获取成功: {ff.price}元 (雪球)")
            except Exception as e:
                print(f"  ⚠️ 行情获取失败: {e}")

        # 获取总股本
        try:
            shares_raw = data_spot.get('总股本', data_spot.get('基金份额/总股本', 0)) if 'data_spot' in dir() else 0
            ff.shares = float(shares_raw or 0) / 1e8  # 转为亿股
            ff.market_cap = ff.price * ff.shares if ff.shares else 0
        except Exception:
            pass

        # 3. 计算衍生指标
        ff._calculate_derived()

        # 4. 更新时间
        ff.update_time = datetime.now().strftime('%Y-%m-%d %H:%M')

        return ff

    def _calculate_derived(self):
        """计算所有衍生指标"""
        # 净债务
        self.net_debt = self.total_liabilities - self.cash

        # 毛利率 → 毛利润
        if self.revenue > 0 and self.gross_margin > 0:
            self.gross_profit = self.revenue * self.gross_margin

        # 净利率
        if self.revenue > 0:
            self.net_margin = self.net_profit / self.revenue

        # EBITDA (简化: 营业利润 + 折旧摊销估算)
        # 这里用营业利润近似, 实际应加上D&A
        self.ebitda = self.operating_profit if self.operating_profit > 0 else self.net_profit * 1.2

        # FCF (如果没从财报获取,用简化公式)
        if self.fcf == 0 and self.operating_cf != 0:
            self.fcf = self.operating_cf - self.capex

        # 企业价值 EV = 市值 + 净债务
        if self.net_debt > 0:
            self.ev = self.market_cap + self.net_debt
        else:
            self.ev = self.market_cap  # 净现金为负时

        # ROIC = NOPAT / 投入资本
        # 简化: NOPAT ≈ 净利润, 投入资本 = 总资产 - 流动负债
        invested_capital = self.total_assets - (self.total_liabilities * 0.3)  # 用30%流动负债近似
        if invested_capital > 0 and self.net_profit > 0:
            self.roic = self.net_profit / invested_capital
        else:
            self.roic = 0.0

    def calc_wacc(
        self,
        risk_free_rate: float = 0.0,
        beta: float = 1.0,
        market_premium: float = 0.05,
        cost_of_debt: float = 0.04,
        tax_rate: float = 0.15,
        debt_ratio: float = 0.3,
    ) -> float:
        """
        计算WACC (加权平均资本成本)

        WACC = E/V × Re + D/V × Rd × (1-T)

        Args:
            risk_free_rate: 无风险利率 (10年国债)
            beta: Beta系数
            market_premium: 市场风险溢价
            cost_of_debt: 债务成本
            tax_rate: 所得税率
            debt_ratio: 债务占总资本比例
        """
        # CAPM: Re = Rf + β × (Rm - Rf)
        re = risk_free_rate + beta * market_premium

        # 更新属性
        self.risk_free_rate = risk_free_rate
        equity_ratio = 1 - debt_ratio

        # WACC
        self.wacc = equity_ratio * re + debt_ratio * cost_of_debt * (1 - tax_rate)
        return self.wacc

    def to_dict(self) -> Dict[str, Any]:
        """导出为字典 (用于日志/JSON)"""
        return {
            'stock_code': self.stock_code,
            'stock_name': self.stock_name,
            'report_date': self.report_date,
            'revenue_亿': round(self.revenue, 2),
            'net_profit_亿': round(self.net_profit, 2),
            'net_profit_attr_亿': round(self.net_profit_attr, 2),
            'eps_元': round(self.eps, 4),
            'bps_元': round(self.bps, 2),
            'gross_margin': f"{self.gross_margin*100:.1f}%" if self.gross_margin else "N/A",
            'net_margin': f"{self.net_margin*100:.1f}%" if self.net_margin else "N/A",
            'roe': f"{self.roe*100:.1f}%" if self.roe else "N/A",
            'roic': f"{self.roic*100:.1f}%" if self.roic else "N/A",
            'wacc': f"{self.wacc*100:.2f}%" if self.wacc else "N/A",
            'market_cap_亿': round(self.market_cap, 1),
            'ev_亿': round(self.ev, 1),
            'shares_亿': round(self.shares, 2),
            'price_元': round(self.price, 2),
            'pe': round(self.market_cap / self.net_profit, 0) if self.net_profit > 0 else "N/A",
            'pb': round(self.price / self.bps, 1) if self.bps > 0 else "N/A",
        }


# ========== 测试 ==========
if __name__ == '__main__':
    print("=== FinancialFoundation 测试 ===\n")

    ff = FinancialFoundation.from_akshare('002428')

    print(f"股票: {ff.stock_code} {ff.stock_name}")
    print(f"报告期: {ff.report_date}")
    print(f"股价: {ff.price}元 | 市値: {ff.market_cap:.1f}亿元")
    print(f"股本: {ff.shares:.2f}亿股")
    print()
    print(f"营收: {ff.revenue:.2f}亿元")
    print(f"净利润: {ff.net_profit:.2f}亿元 (归母)")
    print(f"每股收益: {ff.eps}元")
    print(f"每股净资产: {ff.bps}元")
    print()
    print(f"毛利率: {ff.gross_margin*100:.1f}%" if ff.gross_margin else "毛利率: N/A")
    print(f"净利率: {ff.net_margin*100:.1f}%" if ff.net_margin else "净利率: N/A")
    print(f"ROE: {ff.roe*100:.1f}%" if ff.roe else "ROE: N/A")
    print(f"ROIC: {ff.roic*100:.1f}%" if ff.roic else "ROIC: N/A")
    print()
    print(f"PE: {ff.market_cap/ff.net_profit:.0f}x" if ff.net_profit > 0 else "PE: N/A")
    print(f"PB: {ff.price/ff.bps:.1f}x" if ff.bps > 0 else "PB: N/A")
