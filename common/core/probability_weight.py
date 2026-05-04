#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
概率加权引擎 (Probability Weight Engine)
Phase 2 P0: 将"行业洞察"转化为"算法"
"""

from __future__ import annotations

from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field


@dataclass
class ProbabilityEvent:
    """
    关键事件定义

    Attributes:
        name: 事件名称
        probability: 主观概率 (0.0 ~ 1.0)
        magnitude: 影响幅度 (1.3 = 估值×1.3)
        impact: 'positive' | 'negative'
        description: 事件描述
        source: 概率来源依据
    """
    name: str
    probability: float
    magnitude: float
    impact: str = 'positive'
    description: str = ""
    source: str = ""


class ProbabilityWeightEngine:
    """
    概率加权引擎

    将"行业洞察"（关键事件的主观概率）转化为估值调整。

    使用方式:
    >>> engine = ProbabilityWeightEngine()
    >>> engine.add_event('1.6T认证通过', probability=0.65, magnitude=1.4)
    >>> engine.add_event('良率突破85%', probability=0.55, magnitude=1.2)
    >>> weighted_value = engine.apply(base_value=30.0)
    >>> print(f"加权市值: {weighted_value:.1f}亿元")
    """

    def __init__(self):
        self.events: List[ProbabilityEvent] = []

    def add_event(
        self,
        name: str,
        probability: float,
        magnitude: float,
        impact: str = 'positive',
        description: str = "",
        source: str = "",
    ) -> 'ProbabilityWeightEngine':
        """
        添加一个关键事件

        Args:
            name: 事件名称
            probability: 主观概率 (0.0 ~ 1.0)
            magnitude: 影响幅度 (1.4 = 估值上涨40%)
            impact: 'positive' 或 'negative'
            description: 事件描述
            source: 概率来源依据

        Returns:
            self (支持链式调用)
        """
        # 校验
        if not 0 <= probability <= 1:
            raise ValueError(f"probability must be 0~1, got {probability}")
        if magnitude <= 0:
            raise ValueError(f"magnitude must be > 0, got {magnitude}")
        if impact not in ('positive', 'negative'):
            raise ValueError(f"impact must be 'positive' or 'negative', got {impact}")

        ev = ProbabilityEvent(
            name=name,
            probability=probability,
            magnitude=magnitude,
            impact=impact,
            description=description,
            source=source,
        )
        self.events.append(ev)
        return self

    def add_event_from_dict(self, config: Dict) -> 'ProbabilityWeightEngine':
        """从config字典添加事件"""
        return self.add_event(
            name=config['name'],
            probability=config['probability'],
            magnitude=config['magnitude'],
            impact=config.get('impact', 'positive'),
            description=config.get('description', ''),
            source=config.get('source', ''),
        )

    def remove_event(self, name: str) -> bool:
        """移除指定事件"""
        for i, ev in enumerate(self.events):
            if ev.name == name:
                self.events.pop(i)
                return True
        return False

    def apply(self, base_value: float, method: str = 'additive') -> float:
        """
        应用所有事件权重，计算调整后估值

        方法:
          'additive'（默认）: 加权求和（推荐）
            adjusted = base × (1 + Σ(magnitude-1)×probability)
            适用于：事件高度正相关（如同业周期），更接近真实期望值

          'multiplicative': 连乘法（兼容性保留）
            adjusted = base × ∏(1 + (magnitude-1) × probability)
            适用于：事件相互独立，连乘不会高估

        Args:
            base_value: 基础估值 (亿元市值)
            method: 'additive'（加权求和）或 'multiplicative'（连乘）

        Returns:
            调整后估值 (亿元)
        """
        if method == 'multiplicative':
            # 连乘法（兼容性保留）
            adjusted = base_value
            for ev in self.events:
                if ev.impact == 'positive':
                    adjusted *= (1 + (ev.magnitude - 1) * ev.probability)
                else:
                    adjustment = (1 - ev.magnitude) * ev.probability
                    adjusted *= (1 - adjustment)
            return adjusted

        # 默认：加权求和（避免复利偏差，更适合正相关事件）
        # 期望回报 = Σ p_i × (magnitude_i - 1)
        # 正向事件: magnitude > 1 → 回报为正
        # 负向事件: magnitude < 1 → 回报为负
        expected_return = 0.0
        for ev in self.events:
            contribution = (ev.magnitude - 1) * ev.probability
            expected_return += contribution

        adjusted = base_value * (1 + expected_return)
        return adjusted

    def adjust_valuation(
        self,
        base_value: float,
        base_target_price: float,
        shares: float = 6.53,
        include_breakdown: bool = True,
    ) -> Dict[str, Any]:
        """
        概率加权主入口 — Phase 2 P0

        将"行业洞察"（关键事件主观概率）转化为估值调整，
        返回完整的调整后结果（含目标价、上涨空间）。

        Args:
            base_value:         基础估值 (亿元市值)
            base_target_price:  基础目标价 (元)
            shares:             总股本 (亿股)
            include_breakdown:  是否包含详细拆解

        Returns:
            {
                'base_value_亿':       float,
                'adjusted_value_亿':  float,
                'upside_pct':         float,
                'adjusted_target_元': float,
                'events': [{...}, ...],
                'probability_sum':    float,
                'probability_sum_neg': float,
                'multiplier':         float,
                'warnings':           List[str],
            }
        """
        warnings: List[str] = []

        # 概率合理性校验
        pos_sum = sum(e.probability for e in self.events if e.impact == 'positive')
        neg_sum = sum(e.probability for e in self.events if e.impact == 'negative')
        if pos_sum > 1.0:
            warnings.append(f"正向概率总和({pos_sum:.2f})>1.0，可能过于乐观")
        if neg_sum > 1.0:
            warnings.append(f"负向概率总和({neg_sum:.2f})>1.0，风险可能重复计算")

        adjusted_value = self.apply(base_value)
        multiplier = adjusted_value / base_value if base_value > 0 else 1.0
        upside_pct = (multiplier - 1) * 100
        adjusted_target = adjusted_value / shares if shares > 0 else 0.0

        result = {
            'base_value_亿': round(base_value, 2),
            'adjusted_value_亿': round(adjusted_value, 2),
            'upside_pct': round(upside_pct, 1),
            'adjusted_target_元': round(adjusted_target, 2),
            'probability_sum': round(pos_sum, 2),
            'probability_sum_neg': round(neg_sum, 2),
            'multiplier': round(multiplier, 3),
            'warnings': warnings,
            'events': [],
        }

        if include_breakdown:
            bd = self.breakdown(base_value)
            result['events'] = bd['events']

        return result

    def breakdown(self, base_value: float) -> Dict[str, Any]:
        """
        返回详细拆解

        Returns:
            {
                'base_value': float,
                'adjusted_value': float,
                'total_multiplier': float,
                'events': [
                    {
                        'name': str,
                        'probability': float,
                        'magnitude': float,
                        'impact': str,
                        'contribution': float,  # 该事件贡献的比例变化
                    }, ...
                ],
            }
        """
        # 使用加权求和计算总乘数（避免连乘复利偏差）
        total_contribution = 0.0
        event_details = []

        for ev in self.events:
            # 每个事件贡献 = (magnitude - 1) × probability
            # 正向: mag>1 → 正贡献; 负向: mag<1 → 负贡献
            contrib = (ev.magnitude - 1) * ev.probability
            total_contribution += contrib

            event_details.append({
                'name': ev.name,
                'probability': ev.probability,
                'magnitude': ev.magnitude,
                'impact': ev.impact,
                'contribution': contrib,  # 各事件的绝对贡献（非复利）
                'description': ev.description,
                'source': ev.source,
            })

        total_multiplier = 1 + total_contribution

        return {
            'base_value': base_value,
            'adjusted_value': self.apply(base_value, method='additive'),
            'total_multiplier': total_multiplier,
            'upside_pct': total_contribution * 100,
            'events': event_details,
        }

    def summary(self, base_value: float) -> str:
        """生成文字摘要"""
        bd = self.breakdown(base_value)
        lines = []
        lines.append("【概率加权结果】")
        lines.append(f"基础市值: {bd['base_value']:.1f}亿元")
        lines.append(f"加权市值: {bd['adjusted_value']:.1f}亿元 ({bd['upside_pct']:+.1f}%)")
        lines.append("")
        lines.append("【事件拆解】")
        for ev in bd['events']:
            direction = "↑" if ev['impact'] == 'positive' else "↓"
            lines.append(
                f"  {ev['name']}: {ev['probability']*100:.0f}%概率 "
                f"{direction}{abs(ev['magnitude']-1)*100:.0f}% "
                f"(贡献{ev['contribution']*100:+.1f}%)"
            )
        return '\n'.join(lines)

    @classmethod
    def from_config_list(cls, events: List[Dict]) -> 'ProbabilityWeightEngine':
        """从config列表创建引擎"""
        engine = cls()
        for ev in events:
            engine.add_event_from_dict(ev)
        return engine


# ========== 测试 ==========

if __name__ == '__main__':
    print("=== ProbabilityWeightEngine 测试 ===\n")

    # 云南锗业配置
    events = [
        {'name': '1.6T认证通过', 'probability': 0.65, 'magnitude': 1.4, 'impact': 'positive'},
        {'name': '良率突破85%', 'probability': 0.55, 'magnitude': 1.2, 'impact': 'positive'},
        {'name': '锗价下跌20%', 'probability': 0.30, 'magnitude': 0.85, 'impact': 'negative'},
        {'name': '1.6T认证失败', 'probability': 0.15, 'magnitude': 0.5, 'impact': 'negative'},
    ]

    engine = ProbabilityWeightEngine.from_config_list(events)

    # 基础市值 (SOTP合计约30亿)
    base = 30.0

    print(engine.summary(base))
    print()

    # 详细拆解
    bd = engine.breakdown(base)
    print(f"总乘数: {bd['total_multiplier']:.3f}x")
    print(f"相当于目标价: {bd['adjusted_value']/6.53:.1f}元")
