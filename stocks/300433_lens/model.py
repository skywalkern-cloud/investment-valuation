#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
蓝思科技(HK06613) SOTP估值模型
港股版本，基于HKD计价。

关键参数（2025年报HKD）：
- 总股本: 52.79亿股（含A股+H股）
- 已发行H股: 3.02亿股
- 营收: 744.10亿HKD（同比+6.46%）
- 归母净利: 40.18亿HKD（同比+10.87%）
- EPS: 0.79 HKD
- BPS: 10.42 HKD
- ROE: 7.75%
- 净利率: 5.43%
"""

from pathlib import Path
from typing import Dict, Any


class LensHK_SOTP:
    """蓝思科技(HK06613) SOTP估值 - 港币HKD版"""
    
    # 默认参数（HKD）
    DEFAULT_PARAMS = {
        'glass_revenue': 558.0,      # HKD亿
        'glass_net_margin': 0.055,   # 5.5%
        'glass_pe_min': 15,
        'glass_pe_max': 22,
        'glass_pe_base': 18,
        'vr_revenue': 95.0,          # HKD亿
        'vr_net_margin': 0.05,        # 5%（规模效应未兑现）
        'vr_pe_min': 20,
        'vr_pe_max': 30,
        'vr_pe_base': 25,
        'auto_revenue': 60.0,         # HKD亿
        'auto_net_margin': 0.08,     # 8%
        'auto_pe_min': 18,
        'auto_pe_max': 28,
        'auto_pe_base': 22,
        'other_revenue': 31.0,       # HKD亿
        'other_net_margin': 0.08,    # 8%
        'other_pe_min': 8,
        'other_pe_max': 15,
        'other_pe_base': 12,
        'profit_adjustment': -3.5,  # 合并抵消调整
        'shares': 52.79,             # 亿股
        'hkd_cny_rate': 0.92,        # 汇率
    }
    
    def __init__(
        self,
        glass_revenue: float = None,
        glass_net_margin: float = None,
        glass_pe_min: float = None,
        glass_pe_max: float = None,
        glass_pe_base: float = None,
        vr_revenue: float = None,
        vr_net_margin: float = None,
        vr_pe_min: float = None,
        vr_pe_max: float = None,
        vr_pe_base: float = None,
        auto_revenue: float = None,
        auto_net_margin: float = None,
        auto_pe_min: float = None,
        auto_pe_max: float = None,
        auto_pe_base: float = None,
        other_revenue: float = None,
        other_net_margin: float = None,
        other_pe_min: float = None,
        other_pe_max: float = None,
        other_pe_base: float = None,
        profit_adjustment: float = None,
        shares: float = None,
        hkd_cny_rate: float = None,
    ):
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
        self.hkd_cny_rate = hkd_cny_rate if hkd_cny_rate is not None else p['hkd_cny_rate']
    
    @classmethod
    def from_config(cls, config_path: str = None, repo_root: str = None) -> 'LensHK_SOTP':
        """从config.yaml读取参数"""
        if config_path is None:
            # 兼容云端部署：用__file__相对路径，不再用硬编码绝对路径
            if repo_root is None:
                repo_root = Path(__file__).parent.parent.parent  # 云端: /mount/src/investment-valuation
            config_path = f'{repo_root}/stocks/300433_lens/config.yaml'
        
        with open(config_path, 'r') as f:
            cfg = yaml.safe_load(f)
        
        plugins = {p['name']: p for p in cfg.get('plugins', [])}
        
        glass_cfg = plugins.get('消费电子玻璃主业', {})
        vr_cfg = plugins.get('VR/AR/可穿戴', {})
        auto_cfg = plugins.get('汽车电子', {})
        other_cfg = plugins.get('其他（陶瓷/蓝宝石/金属）', {})
        
        meta = cfg.get('meta', {})
        
        return cls(
            glass_revenue=558.0,
            glass_net_margin=0.055,
            glass_pe_min=glass_cfg.get('pe_min', 15),
            glass_pe_max=glass_cfg.get('pe_max', 22),
            glass_pe_base=glass_cfg.get('pe_base', 18),
            vr_revenue=95.0,
            vr_net_margin=0.05,
            vr_pe_min=vr_cfg.get('pe_min', 20),
            vr_pe_max=vr_cfg.get('pe_max', 30),
            vr_pe_base=vr_cfg.get('pe_base', 25),
            auto_revenue=60.0,
            auto_net_margin=0.08,
            auto_pe_min=auto_cfg.get('pe_min', 18),
            auto_pe_max=auto_cfg.get('pe_max', 28),
            auto_pe_base=auto_cfg.get('pe_base', 22),
            other_revenue=31.0,
            other_net_margin=0.08,
            other_pe_min=other_cfg.get('pe_min', 8),
            other_pe_max=other_cfg.get('pe_max', 15),
            other_pe_base=other_cfg.get('pe_base', 12),
            profit_adjustment=cls.DEFAULT_PARAMS['profit_adjustment'],
            shares=meta.get('total_shares', 52.79),
            hkd_cny_rate=meta.get('hkd_cny_rate', 0.92),
        )
    
    def calculate(self, current_price_hkd: float) -> Dict[str, Any]:
        """计算SOTP估值（HKD）"""
        
        # 各业务线净利润
        glass_nm = self.glass_revenue * self.glass_net_margin
        vr_nm = self.vr_revenue * self.vr_net_margin
        auto_nm = self.auto_revenue * self.auto_net_margin
        other_nm = self.other_revenue * self.other_net_margin
        total_nm = glass_nm + vr_nm + auto_nm + other_nm + self.profit_adjustment
        
        # 各业务线市值（HKD）
        glass_cap = glass_nm * self.glass_pe_base
        vr_cap = vr_nm * self.vr_pe_base
        auto_cap = auto_nm * self.auto_pe_base
        other_cap = other_nm * self.other_pe_base
        
        total_cap_base = glass_cap + vr_cap + auto_cap + other_cap
        total_cap_min = (self.glass_pe_min * glass_nm + self.vr_pe_min * vr_nm + 
                         self.auto_pe_min * auto_nm + self.other_pe_min * other_nm)
        total_cap_max = (self.glass_pe_max * glass_nm + self.vr_pe_max * vr_nm + 
                         self.auto_pe_max * auto_nm + self.other_pe_max * other_nm)
        
        # 目标价（HKD）
        price_base = total_cap_base / self.shares
        price_min = total_cap_min / self.shares
        price_max = total_cap_max / self.shares
        
        # 上涨空间（HKD）
        upside_base = (price_base - current_price_hkd) / current_price_hkd * 100
        upside_min = (price_min - current_price_hkd) / current_price_hkd * 100
        upside_max = (price_max - current_price_hkd) / current_price_hkd * 100
        
        # 换算CNY
        current_price_cny = current_price_hkd * self.hkd_cny_rate
        price_base_cny = price_base * self.hkd_cny_rate
        price_min_cny = price_min * self.hkd_cny_rate
        price_max_cny = price_max * self.hkd_cny_rate
        
        return {
            # 市值HKD
            'sotp_cap_min_hkd': round(total_cap_min, 1),
            'sotp_cap_max_hkd': round(total_cap_max, 1),
            'sotp_cap_base_hkd': round(total_cap_base, 1),
            # 目标价HKD
            'target_min_hkd': round(price_min, 2),
            'target_max_hkd': round(price_max, 2),
            'target_base_hkd': round(price_base, 2),
            # 目标价CNY
            'target_min_cny': round(price_min_cny, 2),
            'target_max_cny': round(price_max_cny, 2),
            'target_base_cny': round(price_base_cny, 2),
            # 上涨空间
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
            'glass_cap_hkd': round(glass_cap, 1),
            'vr_cap_hkd': round(vr_cap, 1),
            'auto_cap_hkd': round(auto_cap, 1),
            'other_cap_hkd': round(other_cap, 1),
            # 当前信息
            'current_price_hkd': current_price_hkd,
            'current_price_cny': round(current_price_cny, 2),
            'shares': self.shares,
            'current_market_cap_hkd': round(current_price_hkd * self.shares, 1),
            'hkd_cny_rate': self.hkd_cny_rate,
        }
    
    def get_sotp_detail(self) -> Dict[str, Any]:
        """返回SOTP分部分明细"""
        glass_nm = self.glass_revenue * self.glass_net_margin
        vr_nm = self.vr_revenue * self.vr_net_margin
        auto_nm = self.auto_revenue * self.auto_net_margin
        other_nm = self.other_revenue * self.other_net_margin
        total_nm = glass_nm + vr_nm + auto_nm + other_nm + self.profit_adjustment
        
        return {
            'segments': [
                {
                    'name': '消费电子玻璃主业',
                    'revenue_hkd': self.glass_revenue,
                    'net_margin': self.glass_net_margin * 100,
                    'net_profit_hkd': round(glass_nm, 2),
                    'pe_range': f'{self.glass_pe_min}-{self.glass_pe_max}x',
                    'pe_base': self.glass_pe_base,
                    'cap_hkd': round(glass_nm * self.glass_pe_base, 1),
                    'pct': f'{glass_nm/total_nm*100:.0f}%',
                },
                {
                    'name': 'VR/AR/可穿戴',
                    'revenue_hkd': self.vr_revenue,
                    'net_margin': self.vr_net_margin * 100,
                    'net_profit_hkd': round(vr_nm, 2),
                    'pe_range': f'{self.vr_pe_min}-{self.vr_pe_max}x',
                    'pe_base': self.vr_pe_base,
                    'cap_hkd': round(vr_nm * self.vr_pe_base, 1),
                    'pct': f'{vr_nm/total_nm*100:.0f}%',
                },
                {
                    'name': '汽车电子',
                    'revenue_hkd': self.auto_revenue,
                    'net_margin': self.auto_net_margin * 100,
                    'net_profit_hkd': round(auto_nm, 2),
                    'pe_range': f'{self.auto_pe_min}-{self.auto_pe_max}x',
                    'pe_base': self.auto_pe_base,
                    'cap_hkd': round(auto_nm * self.auto_pe_base, 1),
                    'pct': f'{auto_nm/total_nm*100:.0f}%',
                },
                {
                    'name': '其他（陶瓷/蓝宝石/金属）',
                    'revenue_hkd': self.other_revenue,
                    'net_margin': self.other_net_margin * 100,
                    'net_profit_hkd': round(other_nm, 2),
                    'pe_range': f'{self.other_pe_min}-{self.other_pe_max}x',
                    'pe_base': self.other_pe_base,
                    'cap_hkd': round(other_nm * self.other_pe_base, 1),
                    'pct': f'{other_nm/total_nm*100:.0f}%',
                },
            ],
            'total_revenue_hkd': self.glass_revenue + self.vr_revenue + self.auto_revenue + self.other_revenue,
            'total_net_profit_hkd': round(total_nm, 2),
            'profit_adjustment': self.profit_adjustment,
            'shares': self.shares,
            'hkd_cny_rate': self.hkd_cny_rate,
        }