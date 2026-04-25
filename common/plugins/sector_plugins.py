#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
行业驱动插件基类及三种行业插件实现

第二层: 将"行业黑话"转化为"数学变量"

插件类型:
- ManufacturingPlugin: 制造与材料类
- FablessPlugin: 研发与设计类
- PlatformPlugin: 平台与流量类
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Any, Optional, Tuple
import numpy as np


# ========== 插件基类 ==========

class BaseSectorPlugin(ABC):
    """
    行业插件抽象基类

    新增行业插件步骤:
    1. 继承 BaseSectorPlugin
    2. 实现 name, sector_type, get_required_variables()
    3. 实现 compute() 方法
    4. 在 config.yaml 中注册
    """

    name: str = "base"
    sector_type: str = "generic"  # manufacturing | fabless | platform | generic

    @abstractmethod
    def get_required_variables(self) -> List[str]:
        """
        返回所需变量列表
        返回: ['良率', '产能', '商品售价', '原料成本', ...]
        """
        pass

    @abstractmethod
    def compute(
        self,
        financials,  # FinancialFoundation
        variables: Dict[str, float],    # 自动获取的实时变量
        manual_data: Dict[str, float], # 手动填入的数据
    ) -> Dict[str, float]:
        """
        计算分部净利润及其他指标

        Args:
            financials: FinancialFoundation对象
            variables: 实时变量 (商品价格/API获取)
            manual_data: 手动数据 (配置文件或yaml)

        Returns:
            {
                '分部净利润': float (亿元),
                '分部营收': float (亿元),
                '分部毛利': float (亿元),
                '分部EBITDA': float (亿元),
            }
        """
        pass

    def validate_config(self, config: Dict) -> bool:
        """验证配置是否合法"""
        return True

    def get_info(self) -> Dict[str, str]:
        """返回插件信息"""
        return {
            'name': self.name,
            'type': self.sector_type,
            'variables': ', '.join(self.get_required_variables()),
        }


# ========== 制造与材料类插件 ==========

class ManufacturingPlugin(BaseSectorPlugin):
    """
    制造与材料类插件

    驱动公式:
        利润 = 产能 × 良率 × 稼动率 × (售价 - 原料成本)

    适用场景:
    - 金属冶炼 (云南锗业锗锭)
    - 化工
    - 半导体晶圆厂
    - 锂电池材料
    """

    name = "制造与材料"
    sector_type = "manufacturing"

    def get_required_variables(self) -> List[str]:
        return [
            '产能',        # 吨/年 或 万件/年
            '良率',        # 0.0 ~ 1.0
            '稼动率',      # 0.0 ~ 1.0
            '商品售价',    # 元/吨 或 元/件
            '原料成本',    # 元/吨 或 元/件
            '单位损耗',    # 可选, 默认0
        ]

    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 产能 (吨/年)
        capacity = manual_data.get('产能', variables.get('产能', 0))

        # 良率 (0.0 ~ 1.0)
        yield_rate = manual_data.get('良率', variables.get('良率', 0.0))

        # 稼动率 (0.0 ~ 1.0)
        utilization = manual_data.get('稼动率', variables.get('稼动率', 1.0))

        # 售价和原料成本 (元/kg → 转换为元/吨需要×1000)
        price_per_kg = manual_data.get('商品售价', variables.get('商品售价', 0))
        material_cost_per_kg = manual_data.get('原料成本', variables.get('原料成本', 0))

        # 单位损耗
        loss_rate = manual_data.get('单位损耗', variables.get('loss_rate', 0.0))

        # 实际产量 (吨/年)
        output = capacity * yield_rate * utilization * (1 - loss_rate)

        # 售价和原料成本统一转为: 元/吨
        # 判断: 如果 < 100000 通常是元/kg (需要×1000)
        # 如果 >= 100000 已经是元/吨
        price_per_ton = price_per_kg * 1000 if price_per_kg < 100000 else price_per_kg
        material_cost_per_ton = material_cost_per_kg * 1000 if material_cost_per_kg < 100000 else material_cost_per_kg

        # 收入 (吨 × 元/吨 = 元) → /1e8 转为亿元
        revenue分部 = output * price_per_ton / 1e8

        # 毛利润
        gross_profit分部 = output * (price_per_ton - material_cost_per_ton) / 1e8

        # EBITDA ≈ 毛利润 × 85%
        ebitda分部 = gross_profit分部 * 0.85

        # 净利率 (制造类约8-15%)
        net_margin = manual_data.get('净利率', variables.get('net_margin', 0.08))
        net_profit分部 = gross_profit分部 * net_margin

        return {
            '分部净利润': max(0, net_profit分部),
            '分部营收': revenue分部,
            '分部毛利': gross_profit分部,
            '分部EBITDA': max(0, ebitda分部),
        }


# ========== 研发与设计类插件 (Fabless) ==========

class FablessPlugin(BaseSectorPlugin):
    """
    研发与设计类插件 (Fabless/IP/Design)

    驱动公式:
        营收 = 订单管道 × 研发成功率 × 终端渗透率 × 认证因子
        净利 = 营收 × 净利率

    适用场景:
    - 半导体设计 (英伟达/AMD模式)
    - 创新药 (临床成功率)
    - 云南锗业磷化铟/1.6T业务
    """

    name = "研发与设计"
    sector_type = "fabless"

    def get_required_variables(self) -> List[str]:
        return [
            '订单管道',      # 预期订单金额 (亿元)
            '研发成功率',    # 0.0 ~ 1.0
            '终端渗透率',    # 0.0 ~ 1.0
            '认证进度',      # 0 ~ 100 (百分比)
            'BOM占比',      # 原材料占终端售价比例
            '净利率',        # 可选, 默认0.30
        ]

    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 订单管道 (预期订单金额, 亿元)
        pipeline = manual_data.get('订单管道', variables.get('订单管道', 0))

        # 研发成功率 (临床成功/BOM通过)
        success_rate = manual_data.get('研发成功率', variables.get('研发成功率', 0.0))

        # 终端渗透率 (市场渗透率)
        penetration = manual_data.get('终端渗透率', variables.get('终端渗透率', 0.0))

        # 认证进度因子 (0.3=未认证 → 1.0=已认证)
        cert_progress = manual_data.get('认证进度', variables.get('认证进度', 0))
        cert_factor = cert_progress / 100.0 if cert_progress else 0.3

        # BOM占比 (用于推算终端市场规模)
        bom_share = manual_data.get('BOM占比', variables.get('BOM占比', 0.0))

        # 有效营收 = 订单管道 × 成功率 × 渗透率 × 认证因子
        revenue分部 = pipeline * success_rate * penetration * cert_factor

        # 如果有BOM占比,用终端市场反推
        if bom_share > 0 and pipeline > 0:
            terminal_market = pipeline / bom_share
            revenue分部 = terminal_market * penetration * cert_factor

        # 净利率 (Fabless通常30%+)
        net_margin = manual_data.get('净利率', variables.get('净利率', 0.30))

        # 毛利 (Fabless毛利约50-70%)
        gross_margin = manual_data.get('毛利率', variables.get('毛利率', 0.55))
        gross_profit分部 = revenue分部 * gross_margin
        ebitda分部 = revenue分部 * (gross_margin - 0.15)  # 研发费用约占15%

        net_profit分部 = revenue分部 * net_margin

        return {
            '分部净利润': max(0, net_profit分部),
            '分部营收': revenue分部,
            '分部毛利': gross_profit分部,
            '分部EBITDA': max(0, ebitda分部),
        }


# ========== 平台与流量类插件 ==========

class PlatformPlugin(BaseSectorPlugin):
    """
    平台与流量类插件 (Platform/SaaS)

    驱动公式:
        营收 = 用户基数 × ARPU × (1 - 流失率)
        净利 = 营收 - 获客成本摊销 - 留存成本

    适用场景:
    - SaaS公司
    - 社交平台
    - 游戏
    - 电商
    """

    name = "平台与流量"
    sector_type = "platform"

    def get_required_variables(self) -> List[str]:
        return [
            '用户基数',      # MAU 或 注册用户数 (万)
            'ARPU',         # 每用户平均收入 (元/月 或 元/年)
            '流失率',        # 0.0 ~ 1.0 (年化)
            'CAC',          # 获客成本 (元/人)
            '留存率',        # 0.0 ~ 1.0
            '付费率',        # 0.0 ~ 1.0
        ]

    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 用户基数 (万)
        users = manual_data.get('用户基数', variables.get('用户基数', 0))

        # ARPU (元/年)
        arpu = manual_data.get('ARPU', variables.get('ARPU', 0))

        # 流失率 (年化)
        churn = manual_data.get('流失率', variables.get('流失率', 0.0))

        # 付费率
        paid_rate = manual_data.get('付费率', variables.get('付费率', 0.05))

        # 有效用户 = 用户基数 × 付费率 × (1 - 流失率)
        effective_users = users * paid_rate * (1 - churn)

        # 营收 = 有效用户 × ARPU (转换为亿)
        revenue分部 = effective_users * arpu / 1e8

        # 毛利 (平台类通常60-80%)
        gross_margin = manual_data.get('毛利率', variables.get('毛利率', 0.70))
        gross_profit分部 = revenue分部 * gross_margin

        # CAC摊销 (假设CAC在12个月摊销)
        cac = manual_data.get('CAC', variables.get('CAC', 0))
        cac_annual = users * paid_rate * cac / 1e8 * 0.5  # 简化: 50%用户需CAC
        ebitda分部 = gross_profit分部 - cac_annual * 0.3  # 摊销30%的CAC

        # 净利率
        net_margin = manual_data.get('净利率', variables.get('净利率', 0.15))
        net_profit分部 = revenue分部 * net_margin

        return {
            '分部净利润': max(0, net_profit分部),
            '分部营收': revenue分部,
            '分部毛利': gross_profit分部,
            '分部EBITDA': max(0, ebitda分部),
        }


# ========== 通用插件 (静态PE) ==========

class GenericPlugin(BaseSectorPlugin):
    """
    通用插件 (基于PE倍数法)

    适用场景:
    - 过渡期/亏损公司
    - 保险/银行 (不适用常规PE)
    - 快速估算
    """

    name = "通用PE法"
    sector_type = "generic"

    def get_required_variables(self) -> List[str]:
        return ['PE', '净利润']

    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        pe = manual_data.get('PE', variables.get('PE', 0))
        net_profit = manual_data.get('净利润', variables.get('净利润', financials.net_profit if financials else 0))

        return {
            '分部净利润': net_profit,
            '分部营收': 0,
            '分部毛利': 0,
            '分部EBITDA': net_profit,
        }


# ========== 插件注册表 ==========

PLUGIN_REGISTRY: Dict[str, type] = {
    'manufacturing': ManufacturingPlugin,
    'fabless': FablessPlugin,
    'platform': PlatformPlugin,
    'generic': GenericPlugin,
}


def get_plugin(plugin_type: str) -> BaseSectorPlugin:
    """根据类型获取插件实例"""
    plugin_class = PLUGIN_REGISTRY.get(plugin_type, GenericPlugin)
    return plugin_class()


if __name__ == '__main__':
    # 测试各插件
    print("=== 插件测试 ===\n")

    # 云南锗业半导体业务 (Fabless)
    fabless = FablessPlugin()
    result = fabless.compute(
        financials=None,
        variables={},
        manual_data={
            '订单管道': 5.0,    # 亿
            '研发成功率': 0.75,
            '终端渗透率': 0.15,
            '认证进度': 60,     # 60%
            'BOM占比': 0.35,
        }
    )
    print(f"Fabless (半导体): {result}")

    # 云南锗业锗锭业务 (Manufacturing)
    mfg = ManufacturingPlugin()
    result = mfg.compute(
        financials=None,
        variables={'商品售价': 17500, '原料成本': 8500},
        manual_data={
            '产能': 50,         # 吨/年
            '良率': 0.88,
            '稼动率': 0.85,
        }
    )
    print(f"Manufacturing (锗锭): {result}")


# ========== Phase 4: 银行/保险/房地产插件接口预置 ==========

class BankingPlugin(BaseSectorPlugin):
    """
    银行/保险插件
    
    驱动: PB × 净资产 或 内含价值
    
    适用场景:
    - 商业银行 (招商银行、工商银行)
    - 保险公司 (中国平安、中国人寿)
    
    使用方式:
        >>> plugin = BankingPlugin()
        >>> result = plugin.compute(financials, {}, {
        ...     '净资产': 1000,  # 亿元
        ...     'PB': 0.8,       # 市净率
        ... })
    """
    
    name = "银行/保险"
    sector_type = "banking"
    
    def get_required_variables(self) -> List[str]:
        return ['净资产', 'PB', '不良率', '拨备覆盖率']
    
    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 净资产
        equity = manual_data.get('净资产', variables.get('净资产', 0))
        # PB
        pb = manual_data.get('PB', variables.get('PB', 1.0))
        
        # 市值 = 净资产 × PB
        market_cap = equity * pb
        
        # 净利润 = 净资产 × ROE
        roe = manual_data.get('ROE', variables.get('ROE', 0.10))
        net_profit = equity * roe
        
        return {
            '分部净利润': net_profit,
            '分部市值': market_cap,
            '分部净资产': equity,
        }
    
    def validate_config(self, config: Dict) -> bool:
        return config.get('净资产', 0) > 0


class NAVPlugin(BaseSectorPlugin):
    """
    房地产NAV插件
    
    驱动: 土地储备 × 单价 - 负债 = NAV
    
    适用场景:
    - 房地产开发公司 (万科A、保利地产)
    
    使用方式:
        >>> plugin = NAVPlugin()
        >>> result = plugin.compute(financials, {}, {
        ...     '土地储备': 5000,  # 万平米
        ...     '单价': 20000,     # 元/平米
        ...     '负债': 800,       # 亿元
        ... })
    """
    
    name = "房地产NAV"
    sector_type = "real_estate"
    
    def get_required_variables(self) -> List[str]:
        return ['土地储备', '单价', '负债', 'NAV折扣率']
    
    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 土地储备 (万平米)
        land_reserve = manual_data.get('土地储备', variables.get('土地储备', 0))
        # 单价 (元/平米)
        unit_price = manual_data.get('单价', variables.get('单价', 0))
        # 负债 (亿元)
        debt = manual_data.get('负债', variables.get('负债', 0))
        # NAV折扣率
        discount = manual_data.get('NAV折扣率', variables.get('NAV折扣率', 0.70))
        
        # NAV = 土地储备 × 单价 × 折扣率 - 负债
        # 单位转换: 万平米 × 元/平米 = 亿元
        nav = land_reserve * unit_price * discount / 1e4 - debt
        
        return {
            '分部净利润': 0,  # 房地产用NAV不用净利
            '分部市值': max(0, nav),
            'NAV': max(0, nav),
            '土地储备': land_reserve,
        }
    
    def validate_config(self, config: Dict) -> bool:
        return config.get('土地储备', 0) > 0 and config.get('单价', 0) > 0


class TollPlugin(BaseSectorPlugin):
    """
    来料加工/委外加工插件
    
    驱动: 加工费 × 产能 - 固定成本
    
    适用场景:
    - 电池OEM (宁德时代代工)
    - 电子制造服务 (富士康)
    - 晶圆代工 (中芯国际)
    
    使用方式:
        >>> plugin = TollPlugin()
        >>> result = plugin.compute(financials, {}, {
        ...     '产能': 100,       # GWh
        ...     '加工费': 80,      # 元/Wh
        ...     '固定成本': 500,   # 亿元
        ... })
    """
    
    name = "来料加工"
    sector_type = "toll"
    
    def get_required_variables(self) -> List[str]:
        return ['产能', '加工费', '固定成本', '稼动率']
    
    def compute(
        self,
        financials,
        variables: Dict[str, float],
        manual_data: Dict[str, float],
    ) -> Dict[str, float]:
        # 产能
        capacity = manual_data.get('产能', variables.get('产能', 0))
        # 加工费
        processing_fee = manual_data.get('加工费', variables.get('加工费', 0))
        # 固定成本
        fixed_cost = manual_data.get('固定成本', variables.get('固定成本', 0))
        # 稼动率
        utilization = manual_data.get('稼动率', variables.get('稼动率', 0.80))
        
        # 营收 = 产能 × 加工费 × 稼动率
        revenue = capacity * processing_fee * utilization
        
        # 毛利 = 营收 - 固定成本 (简化，假设毛利率30%)
        gross_profit = revenue * 0.30
        
        # 净利 = 毛利 × 净利率 (加工业务净利率约10%)
        net_profit = gross_profit * 0.10
        
        return {
            '分部净利润': max(0, net_profit),
            '分部营收': revenue,
            '分部毛利': gross_profit,
        }
    
    def validate_config(self, config: Dict) -> bool:
        return config.get('产能', 0) > 0 and config.get('加工费', 0) > 0
