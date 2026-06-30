from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict

import requests

from .fund_context_report import build_fund_context
from .fund_sql_list import SqlField, list_sql_fields_for_context, render_sql_field_report
from .holding_stock_data import refresh_holding_stock_data
from .logging_utils import get_sector_logger
from .llm_provider_resolver import first_key, resolve_provider
from .market_quote_data import refresh_market_quotes


ALLOWED_ACTIONS = ["持有观察", "谨慎加仓", "暂不买入", "减仓观察", "等待确认", "数据不足，仅人工复核"]


def run_fund_agent_report(
    config_path: str = "config/personal_fund_portfolio.yaml",
    db_path: str | None = None,
    decision_time: str = "1445",
    output_dir: str | Path = "reports/fund_intraday",
    use_llm: bool = True,
    view: bool = False,
    refresh_holding_quotes: bool = False,
    refresh_market_quotes_enabled: bool = False,
    analyze_holdings: bool = False,
    top_n: int = 10,
    llm_provider: str | None = None,
    unique_report_name: bool = False,
) -> Dict[str, Any]:
    logger = get_sector_logger("llm")
    report_logger = get_sector_logger("report")
    logger.info("🤖 [FundAgentReport] 开始生成基金Agent报告 | decision_time=%s use_llm=%s", decision_time, use_llm)
    resolved_db_path = db_path or _db_path_from_config(config_path)
    market_refresh = None
    if refresh_market_quotes_enabled:
        market_refresh = refresh_market_quotes(
            config_path=config_path,
            decision_time=decision_time,
            trade_date=None,
            use_sql=True,
        )
    holding_refresh = None
    if refresh_holding_quotes:
        holding_refresh = refresh_holding_stock_data(
            config_path=config_path,
            db_path=resolved_db_path,
            decision_time=decision_time,
            top_n=top_n,
        )
    fields = list_sql_fields_for_context(resolved_db_path, decision_time=decision_time)
    context = build_fund_context(fields, decision_time=decision_time)
    holdings_analysis = _build_holdings_analysis(context, fields) if analyze_holdings else {}
    prompt = build_agent_prompt(
        context,
        fields,
        config_path=config_path,
        db_path=resolved_db_path,
        decision_time=decision_time,
        holdings_analysis=holdings_analysis,
    )
    llm_result = call_llm(prompt, provider_override=llm_provider) if use_llm else {"status": "skipped", "content": "", "error_reason": "LLM disabled", "provider": llm_provider or ""}
    if llm_result.get("status") != "success":
        logger.warning(
            "⚠️ [FundAgentReport] LLM不可用，生成fallback报告 | provider=%s reason=%s",
            llm_result.get("provider", ""),
            llm_result.get("status") or llm_result.get("error_reason"),
        )
    report = render_agent_report(context, fields, prompt, llm_result, config_path, resolved_db_path, decision_time, holdings_analysis=holdings_analysis)
    trade_date = _latest_trade_date(fields)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    suffix = f"_{datetime.now().strftime('%Y%m%d_%H%M%S')}" if unique_report_name else ""
    report_path = output_path / f"fund_agent_report_{trade_date}_{decision_time}{suffix}.md"
    context_path = output_path / f"fund_agent_context_{trade_date}_{decision_time}{suffix}.json"
    report_path.write_text(report, encoding="utf-8")
    context_path.write_text(
        json.dumps(
            {
                "context": context,
                "fields": [field.to_dict() for field in fields if field.include_in_llm],
                "llm_status": llm_result,
                "market_refresh": market_refresh,
                "holding_refresh": holding_refresh,
                "holdings_analysis": holdings_analysis,
                "data_date": context.get("data_date"),
                "decision_time": decision_time,
                "market_quote_snapshot": context.get("market_quote_snapshot"),
                "stale_fields": context.get("stale_fields", []),
                "stale_field_count": context.get("stale_field_count", 0),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    if view:
        print(_terminal_summary(llm_result, report_path, context))
    report_logger.info("🧾 [FundAgentReport] 报告已生成 | path=%s context=%s", report_path, context_path)
    return {"report_path": str(report_path), "context_path": str(context_path), "llm_status": llm_result, "context": context, "market_refresh": market_refresh, "holding_refresh": holding_refresh, "holdings_analysis": holdings_analysis}


def build_agent_prompt(
    context: Dict[str, Any],
    fields: list[SqlField],
    config_path: str,
    db_path: str,
    decision_time: str,
    holdings_analysis: Dict[str, Any] | None = None,
) -> str:
    compact_fields = [field.to_dict() for field in fields if field.include_in_llm][:220]
    coverage = _coverage_summary(fields)
    return f"""你是 TradingAgents-CN 的场外基金盘中分析助手。

请基于输入数据输出“操作倾向”，不是自动交易指令。允许的操作倾向仅限：
{", ".join(ALLOWED_ACTIONS)}

约束：
- 不得编造缺失数据。
- 不得承诺收益。
- 不得输出“必须买入/必须卖出”。
- 如果数据不足，输出“等待确认”或“暂不操作”。
- 必须分别分析每只基金。
- 必须解释基金估算、ETF、指数、板块、持仓股、仓位约束之间是否一致。
- 如果 market_quote_snapshot 中 ETF/指数/板块 count 大于 0，必须优先使用 context.etfs/context.indices/context.sectors 的今日盘中数据，不得称“今日ETF实时数据缺失/指数数据缺失/板块数据缺失”。
- Baostock 日K只能作为历史MA/趋势参考，不得把历史日K日期写成今日 ETF / 指数 / 板块盘中表现。
- 必须写明人工复核项。
- 质量门控：core_coverage >= 80% 时允许输出操作倾向；50% <= core_coverage < 80% 时只能输出弱倾向并强制复核；core_coverage < 50% 时只能输出“数据不足，仅人工复核”。

输出 Markdown，结构如下：
# 场外基金盘中 Agent 分析报告
## 1. 今日结论速览
| 基金 | 操作倾向 | 置信度 | 一句话原因 |
## 2. 基金逐只分析
## 3. 持仓股票分析摘要
## 4. ETF / 指数 / 板块共振
## 5. 数据一致性与字段来源
## 6. 不建议操作的情况
## 7. 可以继续观察的触发条件
## 8. 数据不足与人工复核项
## 9. 免责声明

元信息：
- config: {config_path}
- db: {db_path}
- decision_time: {decision_time}
- core_coverage: {coverage["core_coverage"]}
- all_coverage: {coverage["all_coverage"]}

基金上下文 JSON：
```json
{json.dumps(context, ensure_ascii=False, indent=2)}
```

持仓股票分析 JSON：
```json
{json.dumps(holdings_analysis or {}, ensure_ascii=False, indent=2)}
```

SQL 字段列表 JSON：
```json
{json.dumps(compact_fields, ensure_ascii=False, indent=2)}
```
"""


def call_llm(prompt: str, timeout: int = 90, provider_override: str | None = None) -> Dict[str, Any]:
    logger = get_sector_logger("llm")
    resolved = resolve_provider(provider_override)
    provider = resolved["provider"]
    model = resolved["model"]
    base_url = resolved["base_url"].rstrip("/")
    logger.info(
        "🤖 [LLMCheck] 当前provider | provider=%s model=%s source=%s",
        provider,
        model,
        resolved["provider_source"],
    )
    _, api_key = first_key([resolved["key_name"]])
    if not api_key:
        logger.warning("⚠️ [LLMCheck] API key缺失 | provider=%s", provider)
        return {"status": "missing_api_key", "content": "", "error_reason": f"missing {resolved['key_name']}", "provider": provider, "provider_source": resolved["provider_source"], "model": model}
    try:
        response = requests.post(
            f"{base_url}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "你是谨慎的基金盘中分析助手，只基于输入数据输出操作倾向解释。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.2,
            },
            timeout=timeout,
        )
        if response.status_code >= 400:
            status = "invalid_api_key" if response.status_code == 401 or "invalid_api_key" in response.text or "Incorrect API key" in response.text else "request_failed"
            logger.error("❌ [LLMCheck] LLM调用失败 | provider=%s status=%s http=%s", provider, status, response.status_code)
            return {"status": status, "content": "", "error_reason": f"HTTP {response.status_code}: {response.text[:500]}", "model": model, "provider": provider, "provider_source": resolved["provider_source"]}
        payload = response.json()
        content = payload.get("choices", [{}])[0].get("message", {}).get("content", "")
        logger.info("✅ [LLMCheck] LLM调用成功 | provider=%s model=%s", provider, model)
        return {"status": "success", "content": content, "model": model, "provider": provider, "provider_source": resolved["provider_source"]}
    except Exception as exc:
        status = "timeout" if "timeout" in str(exc).lower() else "request_failed"
        logger.error("❌ [LLMCheck] LLM调用异常 | provider=%s status=%s", provider, status)
        return {"status": status, "content": "", "error_reason": str(exc), "model": model, "provider": provider, "provider_source": resolved["provider_source"]}


def render_agent_report(
    context: Dict[str, Any],
    fields: list[SqlField],
    prompt: str,
    llm_result: Dict[str, Any],
    config_path: str,
    db_path: str,
    decision_time: str,
    holdings_analysis: Dict[str, Any] | None = None,
) -> str:
    failed = llm_result.get("status") != "success" or not llm_result.get("content")
    lines = [
        "# 场外基金盘中 Agent 分析报告（LLM 分析失败）" if failed else "# 场外基金盘中 Agent 分析报告",
        "",
        f"- 配置文件：`{config_path}`",
        f"- SQLite：`{db_path}`",
        f"- 决策时间：{decision_time}",
        f"- 数据日期：{context.get('data_date') or '-'}",
        f"- LLM状态：{llm_result.get('status')}",
        f"- 生成时间：{datetime.now().isoformat(timespec='seconds')}",
        "",
    ]
    lines.extend(_market_quote_section(context))
    if llm_result.get("status") == "success" and llm_result.get("content"):
        lines.append(llm_result["content"])
    else:
        lines.extend(_fallback_report(context, llm_result, holdings_analysis or {}))
    llm_fields = [field for field in fields if field.include_in_llm]
    lines.extend(["", "## SQL 输入字段列表", "", render_sql_field_report(llm_fields, config_path, db_path, decision_time)])
    return "\n".join(lines) + "\n"


def _fallback_report(context: Dict[str, Any], llm_result: Dict[str, Any], holdings_analysis: Dict[str, Any]) -> list[str]:
    lines = [
        "## 1. 今日结论速览",
        "",
        "LLM 分析失败，未生成操作倾向。",
        "",
        f"- 失败状态：{llm_result.get('status')}",
        f"- 失败原因：{llm_result.get('error_reason', '')}",
        "- 自检命令：`python main.py --mode llm_check`",
        "",
        "## 2. 基金逐只分析",
    ]
    for code, item in context.get("funds", {}).items():
        name = item.get("fields", {}).get("fund_name") or ""
        lines.extend([f"### {code} {name}", "", "- LLM 未完成分析，本节只保留数据上下文，不输出操作倾向。"])
    lines.extend(["", "## 3. 持仓股票分析摘要", "", _holding_summary_table(holdings_analysis), "", "## 9. 免责声明", "", "本报告仅用于个人研究和复盘，不构成投资建议，不包含自动交易或确定性收益承诺。"])
    return lines


def _market_quote_section(context: Dict[str, Any]) -> list[str]:
    snapshot = context.get("market_quote_snapshot") or {}
    trade_date = snapshot.get("trade_date") or context.get("data_date") or "-"
    snapshot_time = snapshot.get("snapshot_time") or "-"
    lines = [
        "## ETF / 指数 / 板块共振（结构化行情）",
        "",
        f"### ETF 今日盘中表现（{trade_date} {snapshot_time}）",
        "",
        _market_table(context.get("etfs", {}), "ETF", "最新价"),
        "",
        "### 指数今日盘中表现",
        "",
        _market_table(context.get("indices", {}), "指数", "最新点位"),
        "",
        "### 板块今日盘中表现",
        "",
        _sector_table(context.get("sectors", {})),
        "",
    ]
    return lines


def _market_table(items: Dict[str, Dict[str, Any]], label: str, price_label: str) -> str:
    lines = [f"| {label} | 名称 | {price_label} | 今日涨跌幅 | 成交额 | 来源 | 状态 |", "| --- | --- | ---: | ---: | ---: | --- | --- |"]
    if not items:
        lines.append("| - | - | missing | missing | missing | missing | missing |")
        return "\n".join(lines)
    for code, item in sorted(items.items()):
        lines.append(
            f"| {_md(code)} | {_md(item.get('name') or '')} | {_md(_fmt(item.get('latest_price')))} | "
            f"{_md(_fmt(item.get('change_pct')))} | {_md(_fmt(item.get('amount')))} | "
            f"{_md(item.get('final_source') or item.get('source') or 'missing')} | {_md(item.get('source_status') or 'missing')} |"
        )
    return "\n".join(lines)


def _sector_table(items: Dict[str, Dict[str, Any]]) -> str:
    lines = ["| 板块 | 今日涨跌幅 | 来源 | 状态 |", "| --- | ---: | --- | --- |"]
    if not items:
        lines.append("| - | missing | missing | missing |")
        return "\n".join(lines)
    for name, item in sorted(items.items()):
        lines.append(f"| {_md(name)} | {_md(_fmt(item.get('change_pct')))} | {_md(item.get('final_source') or item.get('source') or 'missing')} | {_md(item.get('source_status') or 'missing')} |")
    return "\n".join(lines)


def _terminal_summary(llm_result: Dict[str, Any], report_path: Path, context: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "fund_agent_report 摘要",
            f"基金数: {len(context.get('funds', {}))}",
            f"LLM状态: {llm_result.get('status')}",
            f"报告: {report_path}",
        ]
    )


def _build_holdings_analysis(context: Dict[str, Any], fields: list[SqlField]) -> Dict[str, Any]:
    try:
        from .analyze_holdings import analyze_holdings_from_context

        return analyze_holdings_from_context(context, fields)
    except Exception as exc:
        return {"summary": {"status": "failed", "error_reason": str(exc)}, "holdings": [], "missing_fields": []}


def _coverage_summary(fields: list[SqlField]) -> Dict[str, Any]:
    required = ["estimate_change_pct", "latest_price", "change_pct", "ma20", "trend_status", "final_source"]
    matched = 0
    total = 0
    for field in fields:
        if field.field_name not in required:
            continue
        total += 1
        if field.value not in (None, "", "missing"):
            matched += 1
    rate = round(matched / total * 100, 2) if total else 0.0
    return {"core_coverage": rate, "all_coverage": rate, "matched": matched, "total": total}


def _holding_summary_table(holdings_analysis: Dict[str, Any]) -> str:
    lines = [
        "| 基金 | 股票 | 权重 | 最新价 | 涨跌幅 | MA20 | 趋势 | 对基金影响 |",
        "| -- | -- | -: | --: | --: | ---: | -- | ----- |",
    ]
    rows = holdings_analysis.get("holdings", []) if isinstance(holdings_analysis, dict) else []
    if not rows:
        lines.append("| - | - | - | missing | missing | missing | missing | LLM失败时仅保留上下文 |")
        return "\n".join(lines)
    for row in rows[:20]:
        lines.append(
            f"| {_md(row.get('fund_code'))} | {_md(str(row.get('stock_code') or '') + ' ' + str(row.get('stock_name') or ''))} | "
            f"{_md(_fmt(row.get('holding_weight_pct')))} | {_md(_fmt(row.get('latest_price')))} | {_md(_fmt(row.get('change_pct')))} | "
            f"{_md(_fmt(row.get('ma20')))} | {_md(row.get('trend_status') or 'missing')} | {_md(row.get('fund_impact') or '')} |"
        )
    return "\n".join(lines)


def _db_path_from_config(config_path: str) -> str:
    import yaml

    path = Path(config_path)
    if not path.exists():
        return "data/fund_assistant.sqlite3"
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return config.get("database", {}).get("path") or "data/fund_assistant.sqlite3"


def _latest_trade_date(fields: list[SqlField]) -> str:
    dates = sorted({field.trade_date for field in fields if field.trade_date}, reverse=True)
    return dates[0] if dates else date.today().isoformat()


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return "missing"
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("\n", " ").replace("|", "\\|")
