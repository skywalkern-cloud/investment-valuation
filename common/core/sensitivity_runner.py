#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
端到端敏感性分析 (Sensitivity Runner)
Phase 2 P1

同时扫描 SOTP 驱动参数（锗价、良率、认证进度等）
和 DCF 参数（WACC、Terminal Growth），
输出双维敏感性矩阵，并给出综合推荐区间。

使用方式:
    >>> from common.core.sensitivity_runner import run_sensitivity_analysis, SensitivityConfig
    >>> cfg = SensitivityConfig(sotp_params={'商品售价': [12000,17500,25000], '良率': [0.8,0.85,0.9]})
    >>> result = run_sensitivity_analysis(ff, merged, cfg, sotp, engine, fcf_projections)
    >>> print(result['recommended_range'])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple
import numpy as np

from .sotp_engine import SOTPEngine
from .discounting_engine import DiscountingEngine


# ============================================================
# 配置
# ============================================================

@dataclass
class SensitivityConfig:
    """
    敏感性分析配置

    Attributes:
        sotp_params:    SOTP参数档位字典，key=参数名，value=档位列表
        dcf_wacc_range: (min, base, max) WACC 折现率
        dcf_tg_range:   (min, mid, max) 永续增长率
        shares:         总股本 (亿股)
    """
    sotp_params: Dict[str, List[float]] = field(default_factory=dict)
    dcf_wacc_range: Tuple[float, float, float] = (0.06, 0.08, 0.10)
    dcf_tg_range: Tuple[float, float, float] = (0.02, 0.03, 0.04)
    shares: float = 6.53


@dataclass
class MatrixCell:
    """敏感性矩阵单个格子"""
    sotp_price: float
    dcf_price: float
    combined_price: float
    sotp_label: str
    dcf_label: str


# ============================================================
# 核心函数
# ============================================================

def run_sensitivity_analysis(
    financials,
    manual_data: Dict[str, Any],
    config: SensitivityConfig,
    sotp_engine: SOTPEngine,
    dcf_engine: DiscountingEngine,
    fcf_projections: List[float],
) -> Dict[str, Any]:
    """
    执行端到端敏感性分析

    对 SOTP 参数的每个档位运行 SOTP；
    对 DCF WACC × TG 的每个组合运行 DCF；
    输出双维矩阵，综合给出推荐区间。

    Args:
        financials:       FinancialFoundation 对象
        manual_data:     手动数据字典（会被深拷贝修改）
        config:          SensitivityConfig 配置
        sotp_engine:     SOTPEngine 实例（需要有分部配置）
        dcf_engine:      DiscountingEngine 实例
        fcf_projections: FCF 预测列表（用于 DCF 计算）

    Returns:
        {
            'matrix': {
                'rows': List[str],           # SOTP 参数档位标签
                'cols': List[str],           # DCF 参数标签
                'cells': List[List[MatrixCell]],
            },
            'sotp_range': (min, max),
            'dcf_range': (min, max),
            'combined_range': (min, max),
            'recommended_target': float,
            'recommended_range': (min, max),
            'all_combined_prices': List[float],
        }
    """
    sotp_labels = _build_sotp_labels(config.sotp_params)
    dcf_labels = _build_dcf_labels(config.dcf_wacc_range, config.dcf_tg_range)
    n_rows = len(sotp_labels)
    n_cols = len(dcf_labels)

    # 预先计算 DCF 基准值（不改变 SOTP 参数）
    base_manual = _deep_copy_manual(manual_data)
    base_dcf_prices = _compute_dcf_column(
        base_manual, config, dcf_engine, fcf_projections
    )

    # 构建矩阵
    cells: List[List[MatrixCell]] = []
    sotp_prices_flat: List[float] = []
    dcf_prices_flat: List[float] = []
    combined_prices_flat: List[float] = []

    param_names = list(config.sotp_params.keys())
    param_values_map = config.sotp_params

    # 构建每个 (param_name, value) 元组的行列表
    rowspecs: List[Tuple[str, float]] = []   # [(param_name, value), ...]
    for param_name, values in param_values_map.items():
        for v in values:
            rowspecs.append((param_name, v))

    # 如果没有任何 SOTP 参数，仍然要输出 DCF 敏感性（行为空标签）
    if not rowspecs:
        rowspecs = [('', 0.0)]  # 特殊占位行，表示"仅DCF"

    for row_idx, (param_name, param_val) in enumerate(rowspecs):
        row: List[MatrixCell] = []

        for col_idx in range(len(dcf_labels)):
            # 深拷贝一份 manual_data
            test_manual = _deep_copy_manual(manual_data)

            # 注入当前 SOTP 参数（仅注入非占位行）
            if param_name:
                test_manual = _inject_sotp_param(test_manual, param_name, param_val)

            # SOTP 价格（DCF参数固定为base WACC和base TG）
            sotp_result = sotp_engine.run(financials, {}, test_manual)
            sotp_price = sotp_result['目标价_中枢_元']

            # DCF 价格（用固定的 fcf_projections）
            dcf_result = dcf_engine.compute_dcf(
                fcf_projections=fcf_projections,
                terminal_fcf=fcf_projections[-1],
                wacc=config.dcf_wacc_range[1],  # base WACC
                net_debt=0.0,
                shares=config.shares,
                terminal_growth=config.dcf_tg_range[1],  # mid TG
            )
            dcf_price = dcf_result['目标价_元']

            # 综合价格
            combined = (sotp_price + dcf_price) / 2.0

            # 行标签：占位行用空字符串
            row_label = f"{param_name}={param_val}" if param_name else "(仅DCF)"

            cell = MatrixCell(
                sotp_price=round(sotp_price, 2),
                dcf_price=round(dcf_price, 2),
                combined_price=round(combined, 2),
                sotp_label=row_label,
                dcf_label=dcf_labels[col_idx],
            )
            row.append(cell)

            sotp_prices_flat.append(sotp_price)
            dcf_prices_flat.append(dcf_price)
            combined_prices_flat.append(combined)

        cells.append(row)

    sotp_min = min(sotp_prices_flat) if sotp_prices_flat else 0.0
    sotp_max = max(sotp_prices_flat) if sotp_prices_flat else 0.0
    dcf_min = min(dcf_prices_flat) if dcf_prices_flat else 0.0
    dcf_max = max(dcf_prices_flat) if dcf_prices_flat else 0.0
    comb_min = min(combined_prices_flat) if combined_prices_flat else 0.0
    comb_max = max(combined_prices_flat) if combined_prices_flat else 0.0

    # 推荐中枢 = combined 价格的中位数
    sorted_comb = sorted(combined_prices_flat)
    n = len(sorted_comb)
    if n % 2 == 0:
        recommended = (sorted_comb[n//2 - 1] + sorted_comb[n//2]) / 2.0
    else:
        recommended = sorted_comb[n//2]

    # 推荐区间: 10th~90th percentile
    p10 = float(np.percentile(combined_prices_flat, 10))
    p90 = float(np.percentile(combined_prices_flat, 90))

    matrix_dict = {
        'rows': sotp_labels,
        'cols': dcf_labels,
        'cells': [[c.__dict__ for c in row] for row in cells],
    }

    return {
        'matrix': matrix_dict,
        'sotp_range': (round(sotp_min, 2), round(sotp_max, 2)),
        'dcf_range': (round(dcf_min, 2), round(dcf_max, 2)),
        'combined_range': (round(comb_min, 2), round(comb_max, 2)),
        'recommended_target': round(recommended, 2),
        'recommended_range': (round(p10, 2), round(p90, 2)),
        'all_combined_prices': [round(p, 2) for p in combined_prices_flat],
    }


# ============================================================
# 工具函数
# ============================================================

def _build_sotp_labels(sotp_params: Dict[str, List[float]]) -> List[str]:
    """生成 SOTP 行标签"""
    labels = []
    for param_name, values in sotp_params.items():
        for v in values:
            labels.append(f"{param_name}={v}")
    return labels


def _build_dcf_labels(
    wacc_range: Tuple[float, float, float],
    tg_range: Tuple[float, float, float],
) -> List[str]:
    """生成 DCF 列标签"""
    if len(wacc_range) == 1:
        wacc_vals = list(wacc_range) * 3
    elif len(wacc_range) == 2:
        wacc_vals = [wacc_range[0], wacc_range[1], wacc_range[1]]
    else:
        wacc_vals = list(wacc_range)

    if len(tg_range) == 1:
        tg_vals = list(tg_range) * 3
    elif len(tg_range) == 2:
        tg_vals = [tg_range[0], tg_range[1], tg_range[1]]
    else:
        tg_vals = list(tg_range)

    labels = []
    for wacc in wacc_vals:
        for tg in tg_vals:
            labels.append(f"WACC={wacc*100:.0f}% TG={tg*100:.0f}%")
    return labels


def _deep_copy_manual(manual: Dict) -> Dict:
    """深拷贝 manual_data（防止污染原数据）"""
    import copy
    return copy.deepcopy(manual)


def _inject_sotp_param(manual: Dict, param_name: str, value: float) -> Dict:
    """
    将 SOTP 参数注入 manual_data

    参数名格式: '商品售价', '良率', '认证进度'
    注入路径: 找对应的分部配置字典，修改对应字段
    """
    import copy
    manual = copy.deepcopy(manual)
    # 尝试找到参数所在分部并注入
    # 通用策略: 在第一层查找含该key的值并替换
    modified = False
    for section_name, section_data in manual.items():
        if isinstance(section_data, dict) and param_name in section_data:
            manual[section_name][param_name] = value
            modified = True
            break
    if not modified:
        # 如果没找到section，直接设顶层key
        manual[param_name] = value
    return manual


def _compute_dcf_column(
    base_manual: Dict,
    config: SensitivityConfig,
    dcf_engine: DiscountingEngine,
    fcf_projections: List[float],
) -> List[float]:
    """
    计算 DCF 列（3个 WACC × 3个TG = 9个价格）
    """
    wacc_min, wacc_base, wacc_max = config.dcf_wacc_range
    tg_min, tg_mid, tg_max = config.dcf_tg_range
    prices = []
    for wacc in [wacc_min, wacc_base, wacc_max]:
        for tg in [tg_min, tg_mid, tg_max]:
            if wacc <= tg:
                prices.append(None)
                continue
            result = dcf_engine.compute_dcf(
                fcf_projections=fcf_projections,
                terminal_fcf=fcf_projections[-1],
                wacc=wacc,
                net_debt=0.0,
                shares=config.shares,
                terminal_growth=tg,
            )
            prices.append(result['目标价_元'])
    return prices


# ============================================================
# 打印辅助
# ============================================================

def print_matrix(result: Dict[str, Any]) -> None:
    """打印敏感性矩阵（控制台友好）"""
    m = result['matrix']
    rows = m['rows']
    cols = m['cols']
    cells = m['cells']

    # 找最大宽度
    col_width = max(len(c) for c in cols + ['SOTP参数\DCF参数'])

    header = "SOTP参数".ljust(col_width) + " | " + " | ".join(c.ljust(20) for c in cols)
    print(header)
    print("-" * len(header))
    for i, row_label in enumerate(rows):
        row_str = row_label.ljust(col_width) + " | "
        for j, cell_dict in enumerate(cells[i]):
            row_str += f"SOTP={cell_dict['sotp_price']:5.1f} DCF={cell_dict['dcf_price']:5.1f} C={cell_dict['combined_price']:5.1f} | "
        print(row_str)
    print()
    print(f"推荐区间: {result['recommended_range'][0]:.1f} ~ {result['recommended_range'][1]:.1f}元")
    print(f"推荐中枢: {result['recommended_target']:.1f}元")


# ============================================================
# 测试
# ============================================================

if __name__ == '__main__':
    from common.core.financial_foundation import FinancialFoundation
    from common.core.sotp_engine import SOTPEngine
    from common.core.discounting_engine import DiscountingEngine

    print("=== 端到端敏感性分析演示 ===\n")

    ff = FinancialFoundation.from_akshare('002428')

    sotp = SOTPEngine()
    sotp.add_division(
        plugin_type='manufacturing',
        name='传统锗锭业务',
        weight=0.4,
        pe_min=12,
        pe_max=25,
        pe_base=18,
    ).add_division(
        plugin_type='fabless',
        name='半导体分部',
        weight=0.6,
        pe_min=50,
        pe_max=80,
        pe_base=65,
    )

    manual = {
        '传统锗锭业务': {
            '产能': 50,
            '良率': 0.88,
            '稼动率': 0.85,
            '商品售价': 17500,
            '原料成本': 8500,
            '净利率': 0.08,
        },
        '半导体分部': {
            '订单管道': 5.0,
            '研发成功率': 0.75,
            '终端渗透率': 0.15,
            '认证进度': 60,
            'BOM占比': 0.35,
            '净利率': 0.30,
        },
    }

    engine = DiscountingEngine()
    wacc = engine.compute_wacc(risk_free_rate=0.025, beta=1.2)
    fcf_projections = [0.3, 0.5, 0.8, 1.2, 1.8]

    cfg = SensitivityConfig(
        sotp_params={
            '商品售价': [12000, 15000, 17500, 20000, 25000],
            '良率': [0.80, 0.85, 0.88, 0.90],
        },
        dcf_wacc_range=(0.06, 0.08, 0.10),
        dcf_tg_range=(0.02, 0.03, 0.04),
        shares=6.53,
    )

    result = run_sensitivity_analysis(ff, manual, cfg, sotp, engine, fcf_projections)

    print_matrix(result)
    print()
    print(f"SOTP区间: {result['sotp_range']}")
    print(f"DCF区间: {result['dcf_range']}")
    print(f"综合区间: {result['combined_range']}")
    print(f"推荐中枢: {result['recommended_target']:.1f}元")
    print(f"推荐区间: {result['recommended_range'][0]:.1f} ~ {result['recommended_range'][1]:.1f}元")
