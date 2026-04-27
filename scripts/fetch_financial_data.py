#!/usr/bin/env python3
"""
财务数据自动获取脚本 - 东方财富/新浪财经
自动更新云南锗业(002428)和阿里巴巴(09988)的财务数据

用法:
    python3 scripts/fetch_financial_data.py           # 更新所有
    python3 scripts/fetch_financial_data.py 002428   # 只更新指定股票
"""
import os, sys, warnings, json
from pathlib import Path

warnings.filterwarnings('ignore')

# ── 股票代码映射 ──────────────────────────────────────
STOCKS = {
    "002428": {
        "name": "云南锗业",
        "sina_code": "sz002428",
        "manual_path": "stocks/002428_yunnangeiyec/manual_data.yaml",
        "annual_fields": {
            "revenue": "营业总收入",      # 亿元
            "net_profit": "净利润",         # 亿元
            "net_profit_attr": "归属于母公司所有者的净利润",  # 亿元
            "eps": "基本每股收益",
            "gross_margin": None,           # 从计算得出
            "roe": None,                    # 从计算得出
        }
    },
    "09988": {
        "name": "阿里巴巴",
        "sina_code": "hk09988",
        "manual_path": "stocks/09988_alibaba/manual_data.yaml",
        "annual_fields": {
            "revenue": "营业总收入",
            "net_profit": "净利润",
            "net_profit_attr": "归属于母公司所有者的净利润",
            "eps": "基本每股收益",
        }
    }
}

def fetch_income_statement_akshare(sina_code: str) -> dict:
    """用akshare获取利润表，返回最新一期关键指标"""
    import akshare as ak
    import pandas as pd

    df = ak.stock_financial_report_sina(stock=sina_code, symbol="利润表")
    if df.empty:
        return {}

    # 取最新一期（非合并期末/最新季报）
    # 优先取年报（12-31），其次最新季报
    df = df.copy()
    df['报告日'] = df['报告日'].astype(str)
    
    # 取最新的年报（12-31结尾）
    annual = df[df['报告日'].str.endswith('1231')]
    if not annual.empty:
        row = annual.iloc[0]
    else:
        row = df.iloc[0]  # fallback to most recent

    def safe(val, scale=1e8):
        """安全转换为数值"""
        if val is None: return 0
        try:
            v = float(val)
            if v != v: return 0  # NaN check
            return v / scale
        except: return 0

    rev = safe(row.get("营业总收入") or row.get("营业收入"))
    ni = safe(row.get("净利润"))
    ni_attr = safe(row.get("归属于母公司所有者的净利润"))
    gross_profit = safe(row.get("毛利") or row.get("营业成本"))  # 毛利润
    eps = safe(row.get("基本每股收益"), scale=1)

    return {
        "报告日": str(row.get("报告日", "")),
        "营业总收入": rev,
        "营业收入": safe(row.get("营业收入")),
        "净利润": ni,
        "归属母公司净利润": ni_attr,
        "基本每股收益": eps,
        "毛利": gross_profit,
    }

def update_manual_yaml(stock_code: str, financial_data: dict):
    """更新对应股票的 manual_data.yaml"""
    import yaml

    if not financial_data:
        print(f"  ⚠️ {stock_code} 无财务数据可更新")
        return False

    repo_root = Path(__file__).parent.parent
    manual_path = repo_root / STOCKS[stock_code]["manual_path"]

    if not manual_path.exists():
        print(f"  ⚠️ {manual_path} 不存在，跳过")
        return False

    with open(manual_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        data = {}

    # 初始化 financials section
    if "financials" not in data:
        data["financials"] = {}

    fin = data["financials"]
    fin["date"] = financial_data.get("报告日", "")
    fin["revenue"] = round(financial_data.get("营业总收入", 0), 2)
    fin["net_profit"] = round(financial_data.get("净利润", 0), 2)
    fin["net_profit_attr"] = round(financial_data.get("归属母公司净利润", 0), 2)
    fin["eps"] = round(financial_data.get("基本每股收益", 0), 3)
    
    # 计算毛利率 = (营收 - 营业成本) / 营收
    rev = financial_data.get("营业总收入", 0)
    cost = financial_data.get("毛利", 0)
    if rev > 0 and cost > 0:
        fin["gross_margin"] = round((rev - cost) / rev, 4)
    elif rev > 0:
        fin["gross_margin"] = 0.0

    fin.pop("roa", None)  # 移除无效字段

    data["date"] = financial_data.get("报告日", "")[:10]

    with open(manual_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False, indent=2)

    print(f"  ✅ {stock_code} manual_data.yaml 已更新: 营收={fin['revenue']}亿 净利={fin['net_profit']}亿")
    return True

def fetch_and_update(stock_code: str) -> bool:
    """获取并更新单个股票财务数据"""
    info = STOCKS.get(stock_code)
    if not info:
        print(f"❌ 未知股票: {stock_code}")
        return False

    print(f"\n📊 抓取 {info['name']}({stock_code}) 财务数据...")
    try:
        data = fetch_income_statement_akshare(info["sina_code"])
        if not data:
            print(f"  ⚠️ 无数据返回")
            return False
        print(f"  最新财报: {data.get('报告日')} | 营收={data.get('营业总收入'):.2f}亿 | 净利={data.get('净利润'):.2f}亿")
        update_manual_yaml(stock_code, data)
        return True
    except Exception as e:
        print(f"  ❌ 失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    target = sys.argv[1] if len(sys.argv) > 1 else None

    if target:
        ok = fetch_and_update(target)
        print(f"\n完成! 结果: {'✅ 成功' if ok else '❌ 失败'}")
    else:
        print("=" * 50)
        print("财务数据自动更新")
        print("=" * 50)
        results = []
        for code in STOCKS:
            ok = fetch_and_update(code)
            results.append(ok)
        print(f"\n完成! 更新成功: {sum(results)}/{len(results)}")

if __name__ == "__main__":
    main()
