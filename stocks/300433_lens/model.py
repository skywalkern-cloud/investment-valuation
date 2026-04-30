#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝思科技(300433) SOTP估值模型
支持两种初始化方式：
1. 直接传参（用于lens_cron.py）
2. 从config.yaml读取（用于dashboard.py）
"""

import numpy as np
import os
import yaml
from typing import Dict, Any, Optional, List


class LensSOTP:
    """蓝思科技SOTP估值"""
    
    # 默认参数（与config.yaml保持一致，作为后备）
    DEFAULT_PARAMS = {
        'glass_revenue': 558.0,
        'glass_net_margin': 0.055,
        'glass_pe_min': 12,
        'glass_pe_max': 18,
        'glass_pe_base': 18,        # 龙五建议：从15x调整至18x（苹果主力供应商应给溢价）
        'vr_revenue': 95.0,
        'vr_net_margin': 0.05,     # 龙五建议：从6%调整至5%（规模效应未兑现）
        'vr_pe_min': 10,
        'vr_pe_max': 20,
        'vr_pe_base': 15,          # 与config.yaml一致
        'auto_revenue': 60.0,
        'auto_net_margin': 0.08,
        'auto_pe_min': 18,
        'auto_pe_max': 28,
        'auto_pe_base': 22,
        'other_revenue': 31.0,
        'other_net_margin': 0.08,
        'other_pe_min': 8,
        'other_pe_max': 14,
        'other_pe_base': 10,       # 与config.yaml一致
        'profit_adjustment': -3.5, # 合并抵消调整：模型净利43.67亿 vs 年报归母40.18亿，差3.49亿
        'shares': 52.79,
    }
    
    def __init__(
        self,
        # 消费电子玻璃主业（手机/平板/笔记本/手表）
        glass_revenue: float = None,
        glass_net_margin: float = None,
        glass_pe_min: float = None,
        glass_pe_max: float = None,
        glass_pe_base: float = None,
        # VR/AR/可穿戴
        vr_revenue: float = None,
        vr_net_margin: float = None,
        vr_pe_min: float = None,
        vr_pe_max: float = None,
        vr_pe_base: float = None,
        # 汽车电子
        auto_revenue: float = None,
        auto_net_margin: float = None,
        auto_pe_min: float = None,
        auto_pe_max: float = None,
        auto_pe_base: float = None,
        # 其他业务
        other_revenue: float = None,
        other_net_margin: float = None,
        other_pe_min: float = None,
        other_pe_max: float = None,
        other_pe_base: float = None,
        # 合并抵消调整
        profit_adjustment: float = None,
        # 总股本
        shares: float = None,
    ):
        # 用传入值或默认值
        p = self.DEFAULT_PARAMS
        self.glass_revenue = glass_revenue if glass_revenue is not None else p['glass_revenue']
        self.glass_net_margin = glass_net_margin if glass_net_margin is not None else p['glass_net_margin']
        self.glass_pe_min = glass_pe_min if glass_pe_min is not None else p['glass_pe_min']
        self.glass_pe_max = glass_pe_max if glass_pe_max is not None else p['glass_pe_max']
        self.glass_pe_base = glass_pe_base if glass_pe_base is not None else p['glass_pe_base']
        
        self.vr_revenue = vr_revenue if vr_revenue is not None else p['vr_revenue']
        self.vr_net_margin = vr_net_margin if vr_net_margin is not None else p['vr_net_margin']
        self.vr_pe_min = vr_pe_min if vr_pe_min is not None else p['vr_pe_min']
        self.vr_pe_max = vr_pe_max if vr_pe_max is not None else p['vr_pe_max']
        self.vr_pe_base = vr_pe_base if vr_pe_base is not None else p['vr_pe_base']
        
        self.auto_revenue = auto_revenue if auto_revenue is not None else p['auto_revenue']
        self.auto_net_margin = auto_net_margin if auto_net_margin is not None else p['auto_net_margin']
        self.auto_pe_min = auto_pe_min if auto_pe_min is not None else p['auto_pe_min']
        self.auto_pe_max = auto_pe_max if auto_pe_max is not None else p['auto_pe_max']
        self.auto_pe_base = auto_pe_base if auto_pe_base is not None else p['auto_pe_base']
        
        self.other_revenue = other_revenue if other_revenue is not None else p['other_revenue']
        self.other_net_margin = other_net_margin if other_net_margin is not None else p['other_net_margin']
        self.other_pe_min = other_pe_min if other_pe_min is not None else p['other_pe_min']
        self.other_pe_max = other_pe_max if other_pe_max is not None else p['other_pe_max']
        self.other_pe_base = other_pe_base if other_pe_base is not None else p['other_pe_base']
        
        self.profit_adjustment = profit_adjustment if profit_adjustment is not None else p['profit_adjustment']
        self.shares = shares if shares is not None else p['shares']
    
    @classmethod
    def from_config(cls, config_path: str = None, repo_root: str = None) -> 'LensSOTP':
        """从config.yaml读取参数"""
        if config_path is None:
            if repo_root is None:
                repo_root = '/Users/vincentnie/.openclaw/workspace-valuation'
            config_path = f'{repo_root}/stocks/300433_lens/config.yaml'
        
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        
        plugins = {p['name']: p for p in cfg.get('plugins', [])}
        
        def get_plugin(name, key, default=None):
            p = plugins.get(name, {})
            return p.get(key, default)
        
        # 读取各业务线配置
        glass_cfg = plugins.get('消费电子玻璃主业', {})
        vr_cfg = plugins.get('VR/AR/可穿戴', {})
        auto_cfg = plugins.get('汽车电子', {})
        other_cfg = plugins.get('其他（陶瓷/蓝宝石/金属）', {})
        
        # 2025年报归母净利40.18亿，加上合并抵消调整
        base_net_profit = 40.18 + cls.DEFAULT_PARAMS['profit_adjustment']  # ≈ 36.68亿
        
        # 按收入比例分配净利
        total_rev = (
            glass_cfg.get('weight', 0.75) / 0.75 * 558 +
            vr_cfg.get('weight', 0.13) / 0.13 * 95 +
            auto_cfg.get('weight', 0.08) / 0.08 * 60 +
            other_cfg.get('weight', 0.04) / 0.04 * 31
        )
        
        return cls(
            glass_revenue=558.0,
            glass_net_margin=0.055,
            glass_pe_min=glass_cfg.get('pe_min', 12),
            glass_pe_max=glass_cfg.get('pe_max', 18),
            glass_pe_base=glass_cfg.get('pe_base', 18),
            vr_revenue=95.0,
            vr_net_margin=0.05,
            vr_pe_min=vr_cfg.get('pe_min', 10),
            vr_pe_max=vr_cfg.get('pe_max', 20),
            vr_pe_base=vr_cfg.get('pe_base', 15),
            auto_revenue=60.0,
            auto_net_margin=0.08,
            auto_pe_min=auto_cfg.get('pe_min', 18),
            auto_pe_max=auto_cfg.get('pe_max', 28),
            auto_pe_base=auto_cfg.get('pe_base', 22),
            other_revenue=31.0,
            other_net_margin=0.08,
            other_pe_min=other_cfg.get('pe_min', 8),
            other_pe_max=other_cfg.get('pe_max', 14),
            other_pe_base=other_cfg.get('pe_base', 10),
            profit_adjustment=cls.DEFAULT_PARAMS['profit_adjustment'],
            shares=cfg['meta']['total_shares'],
        )
    
    def calculate(self, current_price: float) -> Dict[str, Any]:
        """计算SOTP估值"""
        
        # 各业务线净利润
        glass_nm = self.glass_revenue * self.glass_net_margin
        vr_nm = self.vr_revenue * self.vr_net_margin
        auto_nm = self.auto_revenue * self.auto_net_margin
        other_nm = self.other_revenue * self.other_net_margin
        
        # 加上利润调整项（合并抵消等）
        total_nm = glass_nm + vr_nm + auto_nm + other_nm + self.profit_adjustment
        
        # 各业务线市值
        def cap_range(pe_min, pe_max, nm):
            return (pe_min * nm * 1e8, pe_max * nm * 1e8)
        
        glass_cap_min, glass_cap_max = cap_range(self.glass_pe_min, self.glass_pe_max, glass_nm)
        vr_cap_min, vr_cap_max = cap_range(self.vr_pe_min, self.vr_pe_max, vr_nm)
        auto_cap_min, auto_cap_max = cap_range(self.auto_pe_min, self.auto_pe_max, auto_nm)
        other_cap_min, other_cap_max = cap_range(self.other_pe_min, self.other_pe_max, other_nm)
        
        # 总市值区间
        total_cap_min = glass_cap_min + vr_cap_min + auto_cap_min + other_cap_min
        total_cap_max = glass_cap_max + vr_cap_max + auto_cap_max + other_cap_max
        total_cap_base = (
            self.glass_pe_base * glass_nm * 1e8 +
            self.vr_pe_base * vr_nm * 1e8 +
            self.auto_pe_base * auto_nm * 1e8 +
            self.other_pe_base * other_nm * 1e8
        )
        
        total_cap_min_b = total_cap_min / 1e8
        total_cap_max_b = total_cap_max / 1e8
        total_cap_base_b = total_cap_base / 1e8
        
        # 目标价区间
        price_min = total_cap_min_b / self.shares
        price_max = total_cap_max_b / self.shares
        price_base = total_cap_base_b / self.shares
        
        # 上涨空间
        upside_base = (price_base - current_price) / current_price * 100
        upside_min = (price_min - current_price) / current_price * 100
        upside_max = (price_max - current_price) / current_price * 100
        
        return {
            'sotp_cap_min': round(total_cap_min_b, 1),
            'sotp_cap_max': round(total_cap_max_b, 1),
            'sotp_cap_base': round(total_cap_base_b, 1),
            'target_min': round(price_min, 1),
            'target_max': round(price_max, 1),
            'target_base': round(price_base, 1),
            'upside_base': round(upside_base, 1),
            'upside_min': round(upside_min, 1),
            'upside_max': round(upside_max, 1),
            # 净利明细
            'glass_net_profit': round(glass_nm, 2),
            'vr_net_profit': round(vr_nm, 2),
            'auto_net_profit': round(auto_nm, 2),
            'other_net_profit': round(other_nm, 2),
            'profit_adjustment': self.profit_adjustment,
            'total_net_profit': round(total_nm, 2),
            # 市值明细
            'glass_cap': round(glass_nm * self.glass_pe_base, 1),
            'vr_cap': round(vr_nm * self.vr_pe_base, 1),
            'auto_cap': round(auto_nm * self.auto_pe_base, 1),
            'other_cap': round(other_nm * self.other_pe_base, 1),
            # 当前信息
            'current_price': current_price,
            'shares': self.shares,
            'current_market_cap': round(current_price * self.shares, 1),
        }
    
    def get_sotp_detail(self) -> Dict[str, Any]:
        """返回SOTP分部分明细（用于UI展示）"""
        glass_nm = self.glass_revenue * self.glass_net_margin
        vr_nm = self.vr_revenue * self.vr_net_margin
        auto_nm = self.auto_revenue * self.auto_net_margin
        other_nm = self.other_revenue * self.other_net_margin
        total_nm = glass_nm + vr_nm + auto_nm + other_nm + self.profit_adjustment
        
        return {
            'segments': [
                {
                    'name': '消费电子玻璃主业',
                    'revenue': self.glass_revenue,
                    'net_margin': self.glass_net_margin * 100,
                    'net_profit': round(glass_nm, 2),
                    'pe_range': f'{self.glass_pe_min}-{self.glass_pe_max}x',
                    'pe_base': self.glass_pe_base,
                    'cap': round(glass_nm * self.glass_pe_base, 1),
                    'pct': f'{glass_nm/total_nm*100:.0f}%',
                },
                {
                    'name': 'VR/AR/可穿戴',
                    'revenue': self.vr_revenue,
                    'net_margin': self.vr_net_margin * 100,
                    'net_profit': round(vr_nm, 2),
                    'pe_range': f'{self.vr_pe_min}-{self.vr_pe_max}x',
                    'pe_base': self.vr_pe_base,
                    'cap': round(vr_nm * self.vr_pe_base, 1),
                    'pct': f'{vr_nm/total_nm*100:.0f}%',
                },
                {
                    'name': '汽车电子',
                    'revenue': self.auto_revenue,
                    'net_margin': self.auto_net_margin * 100,
                    'net_profit': round(auto_nm, 2),
                    'pe_range': f'{self.auto_pe_min}-{self.auto_pe_max}x',
                    'pe_base': self.auto_pe_base,
                    'cap': round(auto_nm * self.auto_pe_base, 1),
                    'pct': f'{auto_nm/total_nm*100:.0f}%',
                },
                {
                    'name': '其他（陶瓷/蓝宝石/金属）',
                    'revenue': self.other_revenue,
                    'net_margin': self.other_net_margin * 100,
                    'net_profit': round(other_nm, 2),
                    'pe_range': f'{self.other_pe_min}-{self.other_pe_max}x',
                    'pe_base': self.other_pe_base,
                    'cap': round(other_nm * self.other_pe_base, 1),
                    'pct': f'{other_nm/total_nm*100:.0f}%',
                },
            ],
            'total_revenue': self.glass_revenue + self.vr_revenue + self.auto_revenue + self.other_revenue,
            'total_net_profit': round(total_nm, 2),
            'profit_adjustment': self.profit_adjustment,
            'shares': self.shares,
        }