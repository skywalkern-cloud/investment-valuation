# 股票估值模型创建指南

## 标准流程

### 1. 创建目录结构
```
stocks/XXXXXX_stockname/
├── __init__.py         # 导出SOTP类
├── config.yaml         # 配置（分部/事件/财务数据）
├── model.py            # SOTP估值模型
└── manual_data.yaml    # 手动输入数据（可选）
```

### 2. 注册到仪表盘
编辑 `common/ui/dashboard.py` 中的 `STOCK_REGISTRY`

**必须包含的字段：**
- `name`, `code`, `market`, `currency`, `currency_symbol`
- `symbol_tencent`: 腾讯行情代码（如 `sh603993`）
- `shares`: 总股本（亿股）
- `config_path`: 配置路径
- `fcf_proj`: 【必须】5期FCF预测列表（亿元），否则DCF热力图会IndexError

**可选字段：**
- `manual_path`: 手动数据YAML路径
- `model_path`: 自定义模型路径（默认用SOTP）
- `sotp_price_fixed`: 固定SOTP目标价
- `hkd_cny_rate`: 港股汇率

### 3. 价格函数（如腾讯行情不支持）
添加 `get_price_XXXXXX()` → 注册到 `get_current_price()` 的 elif 分支

### 4. 估值函数
添加 `run_stockname_valuation()` 函数，**必须返回以下key：**
- `target_price` / `target_low` / `target_high`
- `current_price`, `upside`
- `segments`: 列表，每个分部包含 `name`, `net_profit`, `pe_base`, `pe_range`, `cap_base`, `cap_min`, `cap_max`
- `sotp_cap_base`: SOTP总市值
- `dcf_price`: DCF估值（用 `DiscountingEngine` 算）
- `weighted_price`: 概率加权估值（用 `ProbabilityWeightEngine` 算）
- `pw_detail`: 概率加权详情（用 `pw.breakdown()` 获取）
- `fcf_proj`: 5期FCF列表

### 5. 仪表盘显示
- `elif selected == "XXXXXX":` — 调用估值函数 + 提取结果
- 结论区: 添加SOTP分部表、情景分析、概率加权说明

## 常见错误

### ❌ 忘记配 `fcf_proj`
**症状**: IndexError: list index out of range at render_heatmap
**原因**: render_heatmap访问 fcf_proj[-1] 时空列表
**修复**: STOCK_REGISTRY加 `"fcf_proj": [值1, 值2, ...]`

### ❌ Key名不匹配（最频繁）
**症状**: KeyError
**原因**: model.py 和 dashboard.py 用了不同的key名
**常见冲突**:
| model.py用 | dashboard.py用 | ✓ 统一用 |
|---|---|---|
| `net_profit` | `net_profit_cny` | `net_profit` |
| `target_price` | `sotp_price` | 看清楚哪个在返回dict里 |
| `total_cap` | `sotp_cap_base` | `total_market_cap` 或 `sotp_cap_base` |

**修复**: 模型返回后，用 `result.get("key", default)` 而不是 `result["key"]`

### ❌ 函数定义位置不对
**症状**: NameError: run_xxx_valuation is not defined
**原因**: 函数插入的位置不对，main()调用时还没定义
**修复**: 函数必须定义在 `def main():` 之前

### ❌ 忘记概率加权
**症状**: weighted_price 为 None，页面上不显示
**原因**: 只调了 `pw.apply()` 没加 `pw_detail`
**修复**: 
```python
pw = ProbabilityWeightEngine.from_config_list(events)
weighted_cap = pw.apply(base_value)
pw_detail = pw.breakdown(base_value)  # 用于显示
```

### ❌ 直接部署不做本地测试
**症状**: 上线就崩
**原因**: 没走 review → test → deploy 流程
**修复**: 写代码 → 龙五/扣钉评审 → 泰斯特测试 → 再部署

## 代码评审检查清单

### 模型类
- [ ] __init__.py 正确导出 SOTP 类?
- [ ] config.yaml segments 有 net_profit_cny、pe_min/base/max、weight?
- [ ] model.py calculate() 返回 target_price/lows/highs、segments、upside?
- [ ] model.py scenario_analysis() 有3种以上情景?

### 仪表盘
- [ ] STOCK_REGISTRY 有 shares 和 fcf_proj?
- [ ] get_price_XXX() 注册了?
- [ ] get_current_price() 有 elif 分支?
- [ ] run_xxx_valuation() 返回 target_price/lows/highs/dcf/weighted/pw_detail?
- [ ] main() 中的 elif 分支正确提取所有值?
- [ ] 显示区有 SOTP分部表、情景分析、概率加权说明?

### 测试
- [ ] `python3 model.py` 跑得通?
- [ ] Model返回key和Dashboard使用key一致?
- [ ] `python3 -c "import py_compile; py_compile.compile('common/ui/dashboard.py')"` OK?
