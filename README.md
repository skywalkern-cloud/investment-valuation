# 工业级通用动态估值系统

**版本**: v1.2
**架构师**: 龙六 🦞
**设计文档**: https://feishu.cn/docx/NgyUdw4HTodA9IxDUhic9Kn0nGc

---

## 系统架构

4层模块化架构：

```
第四层: Streamlit UI (足球场/热力图/情绪偏差)
     ↓
第三层: DCF折现 + 概率加权引擎 ✅ Phase 2 P0完成
     ↓
第二层: 行业驱动插件 ✅ Phase 1完成
     ↓
第一层: 标准化财务底座 ✅ Phase 1完成
```

## 实施进度

### ✅ Phase 1: 核心框架
- `common/core/financial_foundation.py` — 财务底座
- `common/plugins/sector_plugins.py` — 3种行业插件
- `common/core/sotp_engine.py` — SOTP分部估值
- `stocks/002428_yunnangeiyec/` — 云南锗业模型

### ✅ Phase 2 P0: 折现引擎 (2026-04-25完成)
- `common/core/discounting_engine.py` — DCF/WACC计算
- `common/core/probability_weight.py` — 概率加权引擎
- `common/data/fetcher.py` — 数据降级调度器

### ⏳ Phase 2 P1: 待完成
- terminal_growth敏感性标注
- beta过期警告机制
- 单元测试

## 快速开始

```bash
cd /Users/vincentnie/.openclaw/workspace-valuation

# 运行云南锗业模型
python3 stocks/002428_yunnangeiyec/model.py

# 敏感性分析
python3 stocks/002428_yunnangeiyec/model.py --sensitivity

# DCF测试
python3 common/core/discounting_engine.py

# 概率加权测试
python3 common/core/probability_weight.py
```

## 目录结构

```
workspace-valuation/
├── common/                     # 通用框架
│   ├── core/
│   │   ├── financial_foundation.py
│   │   ├── sotp_engine.py
│   │   ├── discounting_engine.py   # ✅ 新增
│   │   └── probability_weight.py  # ✅ 新增
│   ├── plugins/
│   │   └── sector_plugins.py
│   └── data/
│       └── fetcher.py             # ✅ 新增
├── stocks/
│   └── 002428_yunnangeiyec/
└── docs/
    └── DESIGN_v1.0_通用动态估值系统.md
```

## Phase 2 P0 测试结果

```
DiscountingEngine:
  WACC: 6.97%
  DCF目标价: 5.65元
  企业价值: 36.92亿元

TG敏感性 (WACC=7%):
  TG=2%: 4.73~4.73元
  TG=3%: 5.65元 (中枢)
  TG=4%: 7.44元

ProbabilityWeightEngine (基础市值30亿):
  1.6T认证通过: +26.0%
  良率突破85%: +11.0%
  锗价下跌20%: -4.5%
  → 加权市值: 40.1亿元 (+33.6%)

DataFetcher (云南锗业002428):
  股价: 77.12元 ✅ 同花顺
  财务摘要: ✅ 同花顺
```

## 设计文档

详见 [飞书文档 v1.2](https://feishu.cn/docx/NgyUdw4HTodA9IxDUhic9Kn0nGc)

> Dashboard auto-update: 2026-04-30 00:00:51
