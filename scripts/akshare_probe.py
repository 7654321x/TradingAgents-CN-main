# scripts/akshare_fund_estimate_probe.py
# -*- coding: utf-8 -*-
"""
AKShare 基金净值估算测试脚本

用途：
1. 测试 AKShare 是否能读取基金估算涨幅。
2. 重点检查 020671 / 025500 是否在估值列表中。
3. 不接入 Agent / Graph / LLM / 交易逻辑。
"""

from __future__ import annotations

import json
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd


FUND_CODES = ["020671", "025500"]

# 为了提高命中率，全部类型都试一遍
ESTIMATE_SYMBOLS = [
    "全部",
    "股票型",
    "混合型",
    "指数型",
    "ETF联接",
    "LOF",
    "QDII",
    "债券型",
    "场内交易基金",
]


def ensure_akshare():
    try:
        import akshare as ak

        print(f"✅ AKShare 导入成功，版本：{getattr(ak, '__version__', 'unknown')}")
        return ak
    except Exception as exc:
        print("❌ AKShare 导入失败，请先安装：")
        print(r".\.venv\Scripts\pip.exe install akshare -U")
        raise exc


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df


def zfill_code(value) -> str:
    return str(value).strip().replace(".0", "").zfill(6)


def pick_columns(df: pd.DataFrame) -> pd.DataFrame:
    preferred = [
        "基金代码",
        "基金名称",
        "交易日-估算数据-估算值",
        "交易日-估算数据-估算增长率",
        "交易日-公布数据-单位净值",
        "交易日-公布数据-日增长率",
        "估算偏差",
    ]

    # AKShare 有些字段名会带具体日期，比如 “2026-06-26-估算值”
    # 所以这里做模糊兜底
    selected = []
    for col in df.columns:
        col_str = str(col)
        if col_str in preferred:
            selected.append(col)
        elif "基金代码" in col_str:
            selected.append(col)
        elif "基金名称" in col_str:
            selected.append(col)
        elif "估算" in col_str:
            selected.append(col)
        elif "增长率" in col_str:
            selected.append(col)
        elif "单位净值" in col_str:
            selected.append(col)
        elif "偏差" in col_str:
            selected.append(col)

    # 去重保持顺序
    seen = set()
    selected_unique = []
    for col in selected:
        if col not in seen:
            selected_unique.append(col)
            seen.add(col)

    return df[selected_unique] if selected_unique else df


def main() -> int:
    ak = ensure_akshare()

    out_dir = Path("data/akshare_probe") / f"fund_estimate_{datetime.now().strftime('%Y-%m-%d_%H%M%S')}"
    out_dir.mkdir(parents=True, exist_ok=True)

    all_hits = []
    summary = []

    for symbol in ESTIMATE_SYMBOLS:
        print(f"\n====== 查询 AKShare 基金估算：{symbol} ======")

        item = {
            "symbol": symbol,
            "status": "failed",
            "rows": 0,
            "hit_rows": 0,
            "error": None,
            "columns": [],
        }

        try:
            df = ak.fund_value_estimation_em(symbol=symbol)
            df = normalize_columns(df)

            item["status"] = "success" if len(df) > 0 else "empty"
            item["rows"] = len(df)
            item["columns"] = list(df.columns)

            print(f"状态: {item['status']}")
            print(f"总行数: {len(df)}")
            print(f"列名: {list(df.columns)}")

            if "基金代码" not in df.columns:
                print("⚠️ 未找到 基金代码 列")
                summary.append(item)
                continue

            df["基金代码"] = df["基金代码"].map(zfill_code)

            hit = df[df["基金代码"].isin(FUND_CODES)].copy()
            item["hit_rows"] = len(hit)

            if len(hit) > 0:
                hit.insert(0, "查询类型", symbol)
                hit = pick_columns(hit)
                all_hits.append(hit)

                print("✅ 命中目标基金:")
                print(hit.to_string(index=False))
            else:
                print("未命中 020671 / 025500")

        except Exception as exc:
            item["error"] = repr(exc)
            print("❌ 查询失败:")
            print(repr(exc))
            traceback.print_exc()

        summary.append(item)

    if all_hits:
        result_df = pd.concat(all_hits, ignore_index=True)

        # 按基金代码去重：同一基金可能在 “全部” 和分类里重复出现
        if "基金代码" in result_df.columns:
            result_df = result_df.drop_duplicates(subset=["基金代码"], keep="first")

        csv_path = out_dir / "fund_estimate_hits.csv"
        json_path = out_dir / "fund_estimate_hits.json"

        result_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        result_df.to_json(json_path, orient="records", force_ascii=False, indent=2)

        print("\n====== 最终命中结果 ======")
        print(result_df.to_string(index=False))
        print(f"\nCSV : {csv_path}")
        print(f"JSON: {json_path}")
    else:
        print("\n⚠️ 没有命中目标基金")
        print("可能原因：")
        print("1. 当前时点 AKShare / 东方财富估值表没有这两只基金。")
        print("2. 基金类型没有覆盖到。")
        print("3. 接口当时返回为空。")
        print("4. 该基金不提供盘中估算。")

    summary_path = out_dir / "fund_estimate_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n摘要: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())