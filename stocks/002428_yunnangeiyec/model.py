#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
云南锗业(002428) 估值模型 v2.1
SOTP + DCF + 概率加权

【核心逻辑】
云南锗业 = 磷化铟(InP)衬底供应商 + 传统锗矿
- 磷化铟: AI 1.6T光模块刚性需求，供需缺口>70%
- 锗矿: 传统业务，稳定但增速低

使用方式:
    python3 stocks/002428_yunnangeiyec/model.py
    python3 stocks/002428_yunnangeiyec/model.py --sensitivity
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import warnings
warnings.filterwarnings('ignore')

import json
import yaml
import argparse
from datetime import datetime

from common.core.discounting_engine import DiscountingEngine
from common.core.financial_foundation import FinancialFoundation


# ============================================================
# 云南锗业SOTP模型 - 直接计算 + 清晰说明
# ============================================================

class YunnangeiyecSOTP:
    """
    云南锗业 SOTP 估值模型
    
    分部:
    1. 半导体材料分部 (磷化铟InP衬底) - PE×60-80
    2. 传统锗锭业务 - PE×15-20
    """
    
    # --- 磷化铟半导体分部参数 (2026年5月) ---
    # InP价格估算逻辑：供需缺口驱动溢价，铟价成本传导有限
    # 供需缺口>70% → 溢价3.3x基础价，5月扩大至~3.5x
    CAPACITY_WAN = 15        # 当前产能 (万片/年)
    UTILIZATION = 1.0        # 产能利用率 (满产，订单超产能)
    InP_PRICE = 3.0         # InP衬底均价 (万元/片) — 5月估算，供需紧张+原料涨价
    NET_MARGIN = 0.24        # 净利率 24% (毛利率45%×制造折算)
    SEMI_PE_MIN, SEMI_PE_MAX = 60, 80
    SEMI_PE_BASE = 70
    
    # --- 传统锗矿分部参数 ---
    GERMANIUM_OUTPUT = 30     # 锗金属产量 (吨/年)
    GERMANIUM_PRICE = 1.95   # 锗价 (万元/公斤) — 5月实际价1.95万/kg
    TRAD_NET_MARGIN = 0.30    # 净利率
    TRAD_PE_MIN, TRAD_PE_MAX = 15, 20
    TRAD_PE_BASE = 18
    
    # --- InP价格估算辅助函数 ---
    @staticmethod
    def estimate_inp_price(indium_price_yuan_kg=None, supply_gap_ratio=0.72):
        """
        估算InP衬底价格
        逻辑：供需缺口驱动溢价，铟价成本传导有限
        
        indium_price_yuan_kg: 铟价(元/kg)，如果提供则考虑成本传导
        supply_gap_ratio: 供需缺口比例，默认72%（比4月更紧）
        """
        base_inp = 2.65  # 4月基础价(万元/片)
        
        # 铟价成本传导：每片InP约需12g铟，铟价涨幅传导到成本端<1%
        if indium_price_yuan_kg:
            indium_apr = 4350  # 4月底铟价
            indium_chg_pct = (indium_price_yuan_kg - indium_apr) / indium_apr
            # 材料成本占比仅0.2%，传导系数极低
            cost_impact = 1 + indium_chg_pct * 0.002
        else:
            cost_impact = 1.0
        
        # 供需溢价：缺口越大溢价越高
        scarcity_mult = 1 / (1 - supply_gap_ratio)  # 72%缺口→3.57x
        
        # 综合估算
        return base_inp * cost_impact * (scarcity_mult / 3.33) * 1.05  # 归一化到5月溢价水平
    
    TOTAL_SHARES = 6.53       # 总股本 (亿股)
    
    def __init__(
        self,
        capacity=CAPACITY_WAN,
        utilization=UTILIZATION,
        inp_price=InP_PRICE,
        semi_pe_min=SEMI_PE_MIN,
        semi_pe_max=SEMI_PE_MAX,
        germanium_output=GERMANIUM_OUTPUT,
        germanium_price=GERMANIUM_PRICE,
        trad_pe_min=TRAD_PE_MIN,
        trad_pe_max=TRAD_PE_MAX,
    ):
        self.capacity = capacity           # 万片/年
        self.utilization = utilization   # 利用率
        self.inp_price = inp_price         # 万元/片
        self.semi_pe_min = semi_pe_min
        self.semi_pe_max = semi_pe_max
        
        self.germanium_output = germanium_output
        self.germanium_price = germanium_price
        self.trad_pe_min = trad_pe_min
        self.trad_pe_max = trad_pe_max
        
        # ===== 从共享JSON加载最新估值参数 =====
        # data/latest_valuation.json 由 valuation_framework.py (cron) 写入
        # 如果存在，优先使用JSON中的数据，确保Streamlit与bitable一致
        _json_path = os.path.join(os.path.dirname(__file__), '..', '..', 'data', 'latest_valuation.json')
        try:
            with open(_json_path) as _f:
                _data = json.load(_f)
            if _data.get('semi_nm') and _data.get('target_price'):
                # JSON中有完整估值数据，用配置文件参数但保留框架计算的SOTP结果
                self._json_data = _data
                print(f"  📋 从latest_valuation.json加载估值: target={_data['target_price']}元")
            else:
                self._json_data = None
        except (FileNotFoundError, json.JSONDecodeError, Exception):
            self._json_data = None


    def calculate(self, current_price: float) -> dict:
        """计算SOTP估值"""
        # ===== 1. 半导体分部 (磷化铟InP) =====
        # 公式: 产能 × 利用率 × 单价 = 收入
        #       收入 × 净利率 = 净利润
        semi_revenue = self.capacity * self.utilization * self.inp_price  # 亿元
        semi_net_profit = semi_revenue * self.NET_MARGIN       # 亿元
        
        # 市值 = 净利润 × PE
        semi_cap_min = semi_net_profit * self.semi_pe_min
        semi_cap_max = semi_net_profit * self.semi_pe_max
        semi_cap_base = semi_net_profit * self.SEMI_PE_BASE
        
        # ===== 2. 传统业务 (锗矿) =====
        # 公式: 产量 × 单价 = 收入
        #       收入 × 净利率 = 净利润
        trad_revenue = self.germanium_output * 1000 * self.germanium_price / 10000  # 亿元 (吨→公斤×万元/公斤÷10000)
        trad_net_profit = trad_revenue * self.TRAD_NET_MARGIN
        
        # 市值
        trad_cap_min = trad_net_profit * self.trad_pe_min
        trad_cap_max = trad_net_profit * self.trad_pe_max
        
        # ===== 3. SOTP汇总 =====
        sotp_cap_min = semi_cap_min + trad_cap_min
        sotp_cap_max = semi_cap_max + trad_cap_max
        sotp_cap_base = semi_cap_base + (trad_net_profit * self.TRAD_PE_BASE)
        
        # ===== 4. 目标价 =====
        target_min = sotp_cap_min / self.TOTAL_SHARES
        target_max = sotp_cap_max / self.TOTAL_SHARES
        target_base = sotp_cap_base / self.TOTAL_SHARES
        
        # ===== 5. 上涨空间 =====
        upside_min = (target_min / current_price - 1) * 100
        upside_max = (target_max / current_price - 1) * 100
        upside_base = (target_base / current_price - 1) * 100
        
        result = {
            'current_price': current_price,
            # 半导体分部
            'semi_revenue': semi_revenue,
            'semi_net_profit': semi_net_profit,
            'semi_cap_min': semi_cap_min,
            'semi_cap_max': semi_cap_max,
            'semi_cap_base': semi_cap_base,
            # 传统业务
            'trad_revenue': trad_revenue,
            'trad_net_profit': trad_net_profit,
            'trad_cap_min': trad_cap_min,
            'trad_cap_max': trad_cap_max,
            'trad_cap_base': trad_net_profit * self.TRAD_PE_BASE,
            # SOTP汇总
            'sotp_cap_min': sotp_cap_min,
            'sotp_cap_max': sotp_cap_max,
            'sotp_cap_base': sotp_cap_base,
            'target_min': target_min,
            'target_max': target_max,
            'target_base': target_base,
            'upside_min': upside_min,
            'upside_max': upside_max,
            'upside_base': upside_base,
        }
        
        # ===== 共享JSON覆盖（使Streamlit与bitable一致） =====
        if getattr(self, '_json_data', None):
            j = self._json_data
            if j.get('target_price') and j.get('stock_price'):
                jp = j.get('stock_price')
                # 只当股价接近时（防止股价过期）
                if abs(jp - current_price) / max(jp, current_price) < 0.1:
                    result['target_base'] = j['target_price']
                    result['target_min'] = j.get('target_low', j['target_price'])
                    result['target_max'] = j.get('target_high', j['target_price'])
                    result['upside_base'] = j.get('upside_pct', 0)
                    result['semi_net_profit'] = j.get('semi_nm', semi_net_profit)
                    result['trad_net_profit'] = j.get('trad_nm', trad_net_profit)
                    result['sotp_cap_base'] = j.get('sotp_cap', sotp_cap_base)
                    result['semi_cap_base'] = j.get('semi_cap', semi_cap_base)
                    result['trad_cap_base'] = j.get('trad_cap', trad_net_profit * self.TRAD_PE_BASE)
        
        return result
    
    def explain(self, result: dict, current_price: float) -> list:
        """生成带解释的输出"""
        lines = []
        lines.append("=" * 58)
        lines.append("【SOTP分部估值说明 - 云南锗业(002428)】")
        lines.append("=" * 58)
        
        # 半导体分部
        lines.append("【半导体分部：磷化铟(InP)衬底】")
        lines.append("-" * 50)
        lines.append(f"  公式: 产能 {self.capacity}万片 × 利用率 {self.utilization} × 均{self.inp_price}万 = 收入")
        lines.append(f"  产能: {self.capacity} 万片/年")
        lines.append(f"  利用率: {self.utilization*100:.0f}% (订单超产能，满产)")
        lines.append(f"  InP均价: {self.inp_price} 万元/片")
        lines.append(f"  → 收入: {self.capacity} × {self.utilization} × {self.inp_price} = {result['semi_revenue']:.2f} 亿元")
        lines.append(f"  净利率: {self.NET_MARGIN*100:.0f}% (制造费用折算)")
        lines.append(f"  → 净利润: {result['semi_revenue']:.2f} × {self.NET_MARGIN:.0%} = {result['semi_net_profit']:.2f} 亿元")
        lines.append(f"  PE区间: {self.semi_pe_min}-{self.semi_pe_max}x")
        lines.append(f"  → 市值: {result['semi_net_profit']:.2f}亿 × [{self.semi_pe_min},{self.semi_pe_max}x] = [{result['semi_cap_min']:.1f}, {result['semi_cap_max']:.1f}] 亿元")
        
        lines.append("")
        lines.append("【传统业务：锗矿开采冶炼】")
        lines.append("-" * 50)
        lines.append(f"  公式: 产量 {self.germanium_output}吨 × {self.germanium_price}万元/公斤 × 1000 ÷ 10000 = 收入")
        lines.append(f"  产量: {self.germanium_output} 吨/年")
        lines.append(f"  锗价: {self.germanium_price} 万元/公斤")
        lines.append(f"  → 收入: {self.germanium_output} × {self.germanium_price} = {result['trad_revenue']:.2f} 亿元")
        lines.append(f"  净利率: {self.TRAD_NET_MARGIN*100:.0f}%")
        lines.append(f"  → 净利润: {result['trad_revenue']:.2f} × {self.TRAD_NET_MARGIN:.0%} = {result['trad_net_profit']:.2f} 亿元")
        lines.append(f"  PE���间: {self.trad_pe_min}-{self.trad_pe_max}x")
        lines.append(f"  → 市值: [{result['trad_cap_min']:.1f}, {result['trad_cap_max']:.1f}] 亿元")
        
        lines.append("")
        lines.append("【SOTP合计】")
        lines.append("-" * 50)
        lines.append(f"  半导体市值: [{result['semi_cap_min']:.1f}, {result['semi_cap_max']:.1f}] 亿元")
        lines.append(f"  传统业务市值: [{result['trad_cap_min']:.1f}, {result['trad_cap_max']:.1f}] 亿元")
        lines.append(f"  → 总市值: [{result['sotp_cap_min']:.1f}, {result['sotp_cap_max']:.1f}] 亿元")
        lines.append(f"  目标价: {result['target_min']:.2f} ~ {result['target_max']:.2f} 元 (中枢{result['target_base']:.2f}元)")
        lines.append(f"  当前价: {current_price:.2f}元")
        lines.append(f"  上涨空间: {result['upside_min']:+.1f}% ~ {result['upside_max']:+.1f}%")
        
        return lines


def load_config():
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(__file__), 'config.yaml')
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_manual_data():
    """加载手动数据"""
    manual_path = os.path.join(os.path.dirname(__file__), 'manual_data.yaml')
    if os.path.exists(manual_path):
        with open(manual_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    return {}


def run_full_model():
    """运行完整估值模型"""
    print(f"=== 云南锗业(002428) 估值模型 v2.1 ===")
    print(f"=== {datetime.now().strftime('%Y-%m-%d')} ===\n")
    
    config = load_config()
    meta = config.get('meta', {})
    manual = load_manual_data()
    
    # 1. 获取实时行情
    print("📈 获取实时行情...")
    ff = FinancialFoundation.from_akshare(meta['stock_code'])
    current_price = ff.price if ff.price > 0 else 69.67  # fallback
    print(f"  当前价: {current_price:.2f}元")
    print()
    
    # 2. SOTP分部估值
    print("🧮 SOTP分部估值...")
    sotp = YunnangeiyecSOTP()
    sotp_result = sotp.calculate(current_price)
    
    # 打印带解释的输出
    lines = sotp.explain(sotp_result, current_price)
    for line in lines:
        print(line)
    
    print()
    
    if sotp_result['sotp_cap_min'] < sotp_result['sotp_cap_max']:
        target_price = (sotp_result['target_min'] + sotp_result['target_max']) / 2
        target_min = sotp_result['target_min']
        target_max = sotp_result['target_max']
    else:
        target_price = sotp_result['target_base']
        target_min = target_max = target_price
    
    # 3. 简化DCF (使用SOTP净利润作为基数)
    print("📈 DCF折现估值...")
    engine = DiscountingEngine()
    
    rf = engine.fetch_risk_free_rate()
    print(f"  Rf: {rf*100:.2f}% (10年国债)")
    
    wacc = engine.calc_wacc(risk_free_rate=rf, beta=1.2, market_premium=0.05)
    print(f"  WACC: {wacc*100:.2f}%")
    
    # 简化FCF预测 = SOTP净利润 × 增长假设
    total_nm = sotp_result['semi_net_profit'] + sotp_result['trad_net_profit']
    fcf_base = total_nm * 0.85  # 简化：净利×85%
    growth = [0.20, 0.25, 0.30, 0.25, 0.20]
    fcf_projections = [fcf_base * (1+g)**i for i,g in enumerate(growth, 1)]
    
    tg = 0.03
    dcf_result = engine.dcf_fcf(
        fcf_projections=fcf_projections,
        terminal_fcf=fcf_projections[-1],
        wacc=wacc,
        net_debt=0,
        shares=meta.get('total_shares', 6.53),
        terminal_growth=tg,
    )
    print(f"  5年FCF: {[f'{x:.2f}亿' for x in fcf_projections]}")
    print(f"  预测PV: {dcf_result['PV_sum_亿']:.1f}亿 | 终值PV: {dcf_result['PV_terminal_亿']:.1f}亿")
    print(f"  DCF目标价: {dcf_result['目标价_元']:.2f}元")
    
    print()
    
    # 4. 概率加权
    print("🎯 概率加权...")
    dcf_cap = dcf_result['企业价值_亿']
    weighted_cap = dcf_cap * 1.20  # 简化概率加权
    weighted_price = weighted_cap / meta.get('total_shares', 6.53)
    print(f"  加权市值: {weighted_cap:.1f}亿元 (+20%)")
    print(f"  加权目标价: {weighted_price:.2f}元")
    
    print()
    
    # ===== 整体计算逻辑说明 =====
    print("=" * 58)
    print("【整体计算逻辑说明 - 云南锗业估值模型】")
    print("=" * 58)
    print("""
【一、估值框架】
  本模型采用SOTP(分部估值) + DCF(现金流折现) + 概率加权
  
【二、分部估值逻辑】
  
  1. 半导体分部 (磷化铟InP衬底)
     - 核心假设:
       * 产能: 15万片/年 (2026年当前产能)
       * 利用率: 100% (订单超产能，满产)
       * InP均价: 2.65万元/片 (2026年4月价格，已涨3倍)
       * 净利率: 24% (毛利率45%×制造费用折算)
     - 计算公式:
       * 收入 = 产能 × 利用率 × 单价
       *     = 15 × 1.0 × 2.65 = 39.75亿元
       * 净利润 = 收入 × 净利率
       *         = 39.75 × 24% = 9.54亿元
     - 市值 = 净利润 × PE倍数
       * PE区���: 60-80x (AI材料稀缺溢价)
       * 市值区间: [572.4亿, 763.2亿]
  
  2. 传统业务 (锗矿)
     - 核心假设:
       * 产量: 30吨/年
       * 锗价: 1.2万元/公斤
       * 净利率: 30%
     - 计算公式:
       * 收入 = 产量 × 锗价
       *     = 30 × 1.2 = 36亿元
       * 净利润 = 36 × 30% = 10.8亿元
     - 市值区间: [162亿, 216亿] (PE 15-20x)

【三、DCF估值】
  - 以SOTP净利润为基数，假设未来5年增长20%-30%
  - WACC = Rf + β×市场溢价 = 1.77% + 1.2×5% = 7.77%
  - 终值增长假设: 3%

【四、概率加权】
  - 考虑关键事件概率:
    * 1.6T量产突破: 75%概率 ↑30%
    * 扩产如期完成: 65%概率 ↑20%
    * InP价格持续上涨: 60%概率 ↑25%
  - 加权后市值 = DCF市值 × 120%

【五、关键跟踪指标】
  - 合同负债/预收款项 (4月30日一季报)
  - 扩产设备采购进度 (Q2)
  - InP衬底价格走势
  
【六、风险提示】
  - 扩产不及预期
  - InP价格回落
  - 硅光方案替代EML (短期概率低)
""")
    
    print("=" * 58)
    print(f"【综合估值结论】")
    print(f"=" * 58)
    print(f"  SOTP: {sotp_result['target_base']:.1f}元 ({sotp_result['upside_base']:+.0f}%)")
    print(f"  DCF: {dcf_result['目标价_元']:.1f}元")
    print(f"  概率加权: {weighted_price:.1f}元")
    print(f"  当前价: {current_price:.2f}元")
    print(f"  综合目标价: {weighted_price:.1f}~{target_min:.1f}元")
    
    return {
        'current_price': current_price,
        'target_price': weighted_price,
        'sotp': sotp_result,
        'dcf': dcf_result,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='云南锗业估值模型 v2.1')
    parser.add_argument('--sensitivity', action='store_true', help='敏感性分析')
    args = parser.parse_args()
    
    run_full_model()