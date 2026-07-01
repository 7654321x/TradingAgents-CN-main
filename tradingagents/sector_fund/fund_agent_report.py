from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable

import requests

from .fund_context_report import build_fund_context
from .fund_sql_list import SqlField, list_sql_fields, list_sql_fields_for_context, render_sql_field_report
from .holding_stock_data import refresh_holding_stock_data
from .logging_utils import get_sector_logger
from .llm_provider_resolver import first_key, resolve_provider
from .market_quote_data import refresh_market_quotes


ALLOWED_ACTIONS = ["持有观察", "谨慎加仓观察", "暂不追涨", "减仓观察", "等待确认", "数据不足，仅人工复核"]


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
    include_sql_debug: bool = False,
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
    all_fields = list_sql_fields(resolved_db_path, decision_time=decision_time, limit_per_table=1200)
    fields = list_sql_fields_for_context(resolved_db_path, decision_time=decision_time, limit_per_table=1200)
    context = build_fund_context(fields, decision_time=decision_time)
    source_run_meta = _build_source_run_meta(all_fields, context.get("data_date"), decision_time)
    context["data_sources"] = source_run_meta["data_sources"]
    context["data_source_summary"] = source_run_meta["data_source_summary"]
    context["source_run_filter"] = source_run_meta["source_run_filter"]
    context["debug_only_source_runs"] = source_run_meta["debug_only_source_runs"]
    coverage = calculate_agent_report_core_coverage(context)
    context["agent_report_core_coverage"] = coverage
    context["data_quality_summary"] = _build_quality_summary(context, coverage)
    holdings_analysis = _build_holdings_analysis(context, fields) if analyze_holdings else {}
    prompt = build_agent_prompt(
        context,
        fields,
        config_path=config_path,
        db_path=resolved_db_path,
        decision_time=decision_time,
        holdings_analysis=holdings_analysis,
    )
    llm_result = (
        call_llm(prompt, provider_override=llm_provider)
        if use_llm
        else {"status": "skipped", "content": "", "error_reason": "LLM disabled", "provider": llm_provider or ""}
    )
    if llm_result.get("status") != "success":
        logger.warning(
            "⚠️ [FundAgentReport] LLM不可用，生成fallback报告 | provider=%s reason=%s",
            llm_result.get("provider", ""),
            llm_result.get("status") or llm_result.get("error_reason"),
        )

    trade_date = _latest_trade_date(all_fields)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    run_suffix = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{run_suffix}" if unique_report_name else ""
    report_path = output_path / f"fund_agent_report_{trade_date}_{decision_time}{suffix}.md"
    context_path = output_path / f"fund_agent_context_{trade_date}_{decision_time}{suffix}.json"
    debug_report_path = output_path / f"fund_agent_debug_{trade_date}_{decision_time}_{run_suffix}.md"

    report = render_agent_report(
        context,
        fields,
        prompt,
        llm_result,
        config_path,
        resolved_db_path,
        decision_time,
        holdings_analysis=holdings_analysis,
        include_sql_debug=include_sql_debug,
    )
    report_path.write_text(report, encoding="utf-8")

    debug_report = _render_debug_report(
        context=context,
        llm_fields=fields,
        all_fields=all_fields,
        config_path=config_path,
        db_path=resolved_db_path,
        decision_time=decision_time,
        llm_result=llm_result,
        report_path=report_path,
        context_path=context_path,
    )
    debug_report_path.write_text(debug_report, encoding="utf-8")

    context_payload = {
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
        "source_run_filter": context.get("source_run_filter", {}),
        "debug_only_source_runs": context.get("debug_only_source_runs", []),
        "agent_report_core_coverage": coverage,
        "debug_report_path": str(debug_report_path),
    }
    context_path.write_text(json.dumps(context_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if view:
        print(_terminal_summary(llm_result, report_path, context))
    report_logger.info(
        "🧾 [FundAgentReport] 报告已生成 | path=%s debug=%s context=%s",
        report_path,
        debug_report_path,
        context_path,
    )
    return {
        "report_path": str(report_path),
        "debug_report_path": str(debug_report_path),
        "context_path": str(context_path),
        "llm_status": llm_result,
        "context": context,
        "market_refresh": market_refresh,
        "holding_refresh": holding_refresh,
        "holdings_analysis": holdings_analysis,
        "agent_report_core_coverage": coverage,
        "old_data_source_run_excluded": context.get("source_run_filter", {}).get("old_source_runs_excluded", 0),
        "sql_debug_included": include_sql_debug,
    }


def build_agent_prompt(
    context: Dict[str, Any],
    fields: list[SqlField],
    config_path: str,
    db_path: str,
    decision_time: str,
    holdings_analysis: Dict[str, Any] | None = None,
) -> str:
    compact_fields = [field.to_dict() for field in fields if field.include_in_llm and field.table_name != "data_source_run"][:220]
    coverage = context.get("agent_report_core_coverage") or calculate_agent_report_core_coverage(context)
    quality_note = _quality_prompt(coverage.get("agent_report_core_coverage", 0.0))
    sector_summary = _market_status_summary(context)
    return f"""你是 TradingAgents-CN 的场外基金盘中分析助手。

请基于输入数据输出“操作倾向”，不是自动交易指令。允许的操作倾向仅限：
{", ".join(ALLOWED_ACTIONS)}

约束：
- 不得编造缺失数据。
- 不得承诺收益。
- 不得输出“必须买入/必须卖出”。
- 如果数据不足，输出“等待确认”或“数据不足，仅人工复核”。
- 必须分别分析每只基金。
- 必须解释基金估算、ETF、指数、板块、持仓股、仓位约束之间是否一致。
- 板块行情今日缺失时，不得基于旧板块数据做强判断。
- Baostock 日K只能作为历史MA/趋势参考，不得把历史日K日期写成今日 ETF / 指数 / 板块盘中表现。
- 必须写明人工复核项。
- 数据质量门控：agent_report_core_coverage >= 80% 时允许弱到中等倾向；50% <= agent_report_core_coverage < 80% 时只能输出弱倾向；agent_report_core_coverage < 50% 时只能输出“数据不足，仅人工复核”。
- 今日板块结构化行情摘要：{sector_summary["sector_text"]}

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
- agent_report_core_coverage: {coverage["agent_report_core_coverage"]}
- coverage_by_group: {json.dumps(coverage.get("groups", {}), ensure_ascii=False)}
- source_run_filter: {json.dumps(context.get("source_run_filter", {}), ensure_ascii=False)}
- data_quality_prompt: {quality_note}

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
        return {
            "status": "missing_api_key",
            "content": "",
            "error_reason": f"missing {resolved['key_name']}",
            "provider": provider,
            "provider_source": resolved["provider_source"],
            "model": model,
        }
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
            status = (
                "invalid_api_key"
                if response.status_code == 401 or "invalid_api_key" in response.text or "Incorrect API key" in response.text
                else "request_failed"
            )
            logger.error("❌ [LLMCheck] LLM调用失败 | provider=%s status=%s http=%s", provider, status, response.status_code)
            return {
                "status": status,
                "content": "",
                "error_reason": f"HTTP {response.status_code}: {response.text[:500]}",
                "model": model,
                "provider": provider,
                "provider_source": resolved["provider_source"],
            }
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
    include_sql_debug: bool = False,
) -> str:
    coverage = context.get("agent_report_core_coverage") or calculate_agent_report_core_coverage(context)
    llm_result = _apply_quality_gate_to_llm_result(dict(llm_result), coverage.get("agent_report_core_coverage", 0.0))
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
        _quality_intro_section(context, coverage),
        "",
    ]
    if failed:
        lines.extend(_fallback_report(context, llm_result, holdings_analysis or {}, coverage))
    else:
        lines.append(_trim_report_heading(llm_result["content"]))
    if include_sql_debug:
        llm_fields = [field for field in fields if field.include_in_llm]
        lines.extend(["", "## SQL 输入字段列表", "", render_sql_field_report(llm_fields, config_path, db_path, decision_time)])
    return "\n".join(lines).rstrip() + "\n"


def calculate_agent_report_core_coverage(context: Dict[str, Any]) -> Dict[str, Any]:
    groups: Dict[str, Dict[str, Any]] = {
        "fund": {"ok": 0, "total": 0},
        "etf": {"ok": 0, "total": 0},
        "index": {"ok": 0, "total": 0},
        "sector": {"ok": 0, "total": 0},
        "holding_stock": {"ok": 0, "total": 0},
        "portfolio": {"ok": 0, "total": 0},
    }
    missing_core_fields: list[str] = []

    def add(group: str, field_key: str, value: Any, source_status: Any = None, source_name: Any = None) -> None:
        groups[group]["total"] += 1
        if _core_value_ok(value, source_status=source_status, source_name=source_name):
            groups[group]["ok"] += 1
        else:
            missing_core_fields.append(field_key)

    for code, item in sorted((context.get("funds") or {}).items()):
        fields = item.get("fields") or {}
        estimates = item.get("estimates") or {}
        nav = item.get("nav") or {}
        add("fund", f"fund.{code}.fund_code", code)
        add("fund", f"fund.{code}.fund_name", fields.get("fund_name"))
        add("fund", f"fund.{code}.fund_type", _first_non_empty(fields.get("fund_type"), fields.get("inferred_type")))
        add("fund", f"fund.{code}.role", _first_non_empty(fields.get("role"), fields.get("inferred_role")))
        add("fund", f"fund.{code}.position_pct", fields.get("position_pct"))
        add("fund", f"fund.{code}.estimate_nav", _first_non_empty(estimates.get("estimate_nav"), fields.get("estimate_nav")))
        add("fund", f"fund.{code}.estimate_change_pct", _first_non_empty(estimates.get("estimate_change_pct"), fields.get("estimate_change_pct")))
        add("fund", f"fund.{code}.estimate_time", _first_non_empty(estimates.get("estimate_time"), fields.get("estimate_time"), context.get("decision_time")))
        add(
            "fund",
            f"fund.{code}.estimate_reliability",
            _first_non_empty(fields.get("estimate_reliability"), estimates.get("confidence"), fields.get("confidence"), fields.get("enrich_confidence")),
        )
        add("fund", f"fund.{code}.latest_nav", _first_non_empty(nav.get("unit_nav"), fields.get("published_nav"), fields.get("latest_nav")))

    for code in _tracking_codes(context, "etfs", context.get("etfs", {}).keys()):
        item = (context.get("etfs") or {}).get(code, {})
        add("etf", f"etf.{code}.latest_price", item.get("latest_price"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("etf", f"etf.{code}.change_pct", item.get("change_pct"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("etf", f"etf.{code}.amount", item.get("amount"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("etf", f"etf.{code}.source_status", item.get("source_status"), item.get("source_status"), item.get("final_source") or item.get("source"))

    for code in _tracking_codes(context, "indices", context.get("indices", {}).keys()):
        item = (context.get("indices") or {}).get(code, {})
        add("index", f"index.{code}.latest_price", item.get("latest_price"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("index", f"index.{code}.change_pct", item.get("change_pct"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("index", f"index.{code}.amount", item.get("amount"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("index", f"index.{code}.source_status", item.get("source_status"), item.get("source_status"), item.get("final_source") or item.get("source"))

    for name in _tracking_codes(context, "sectors", context.get("sectors", {}).keys()):
        item = (context.get("sectors") or {}).get(name, {})
        add("sector", f"sector.{name}.change_pct", item.get("change_pct"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("sector", f"sector.{name}.source_status", item.get("source_status"), item.get("source_status"), item.get("final_source") or item.get("source"))

    holding_codes = []
    for fund_code, item in sorted((context.get("funds") or {}).items()):
        fund_type = _first_non_empty(item.get("fields", {}).get("fund_type"), item.get("fields", {}).get("inferred_type"))
        if fund_type == "etf_feeder":
            continue
        for holding in item.get("holdings") or []:
            code = str(holding.get("code") or "")
            if code:
                holding_codes.append((fund_code, code))
    for fund_code, code in holding_codes:
        item = (context.get("securities") or {}).get(code, {})
        add("holding_stock", f"holding_stock.{fund_code}.{code}.latest_price", item.get("latest_price"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.change_pct", item.get("change_pct"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.amount", item.get("amount"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.turnover_rate", item.get("turnover_rate"), item.get("source_status"), item.get("final_source") or item.get("source"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.ma20", item.get("ma20"), item.get("source_status"), item.get("history_source") or item.get("final_source") or item.get("source"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.trend_status", item.get("trend_status"))
        add("holding_stock", f"holding_stock.{fund_code}.{code}.source_status", item.get("source_status"), item.get("source_status"), item.get("final_source") or item.get("source"))

    portfolio = context.get("portfolio") or {}
    for field_name in ("total_position_pct", "target_position_pct", "max_position_pct", "cash_position_pct", "max_single_position_pct"):
        add("portfolio", f"portfolio.{field_name}", portfolio.get(field_name))

    total = sum(group["total"] for group in groups.values())
    ok = sum(group["ok"] for group in groups.values())
    for group in groups.values():
        group["coverage"] = round((group["ok"] / group["total"] * 100) if group["total"] else 0.0, 2)
    return {
        "agent_report_core_coverage": round((ok / total * 100) if total else 0.0, 2),
        "groups": groups,
        "missing_core_fields": missing_core_fields,
    }


def _fallback_report(context: Dict[str, Any], llm_result: Dict[str, Any], holdings_analysis: Dict[str, Any], coverage: Dict[str, Any]) -> list[str]:
    lines = [
        "## 1. 今日结论速览",
        "",
        "LLM 分析失败，未生成操作倾向。",
        "",
        "| 基金 | 操作倾向 | 置信度 | 一句话原因 |",
        "| --- | --- | --- | --- |",
    ]
    action = "数据不足，仅人工复核" if coverage.get("agent_report_core_coverage", 0.0) < 50 else "等待确认"
    for code, item in sorted((context.get("funds") or {}).items()):
        name = item.get("fields", {}).get("fund_name") or code
        lines.append(f"| {code} {name} | {action} | 低 | LLM未完成分析，仅保留结构化事实与复核提示 |")
    if len(lines) == 4:
        lines.append("| - | 数据不足，仅人工复核 | 低 | 当前未读取到基金上下文 |")
    lines.extend(
        [
            "",
            "## 2. 基金逐只分析",
            "",
        ]
    )
    for code, item in sorted((context.get("funds") or {}).items()):
        fields = item.get("fields", {})
        estimates = item.get("estimates", {})
        nav = item.get("nav", {})
        lines.extend(
            [
                f"### {code} {fields.get('fund_name') or code}",
                f"- 基金类型：{_first_non_empty(fields.get('fund_type'), fields.get('inferred_type')) or 'missing'}",
                f"- 角色：{_first_non_empty(fields.get('role'), fields.get('inferred_role')) or 'missing'}",
                f"- 仓位：{_fmt(_first_non_empty(fields.get('position_pct'), 'missing'))}",
                f"- 估算净值 / 涨跌：{_fmt(_first_non_empty(estimates.get('estimate_nav'), fields.get('estimate_nav')))} / {_fmt(_first_non_empty(estimates.get('estimate_change_pct'), fields.get('estimate_change_pct')))}",
                f"- 最新净值：{_fmt(_first_non_empty(nav.get('unit_nav'), fields.get('published_nav'), fields.get('latest_nav')))}",
                "- 持仓权重来源：AKShare fund_portfolio_hold_em / fund_enrichment_result",
                "",
            ]
        )
    lines.extend(
        [
            "## 3. 持仓股票分析摘要",
            "",
            _holding_summary_table(holdings_analysis),
            "",
            "## 4. ETF / 指数 / 板块共振",
            "",
            _market_tables_section(context),
            "",
            "## 5. 数据一致性与字段来源",
            "",
            _field_source_summary_block(context, coverage),
            "",
            "## 6. 不建议操作的情况",
            "",
            "- 当前报告未拿到足够的 LLM 结论或核心覆盖率不足，不建议依据本报告直接执行偏操作性判断。",
            "- 板块缺失、持仓股 MA 缺失、估值更新时间不明时，优先人工复核。",
            "",
            "## 7. 可以继续观察的触发条件",
            "",
            "- ETF / 指数 / 板块结构化行情在同一交易日补齐。",
            "- 持仓股 MA20、趋势状态和成交额同步刷新成功。",
            "- LLM provider 恢复可用并完成完整文本分析。",
            "",
            "## 8. 数据不足与人工复核项",
            "",
            f"- LLM状态：{llm_result.get('status')}",
            f"- 失败原因：{llm_result.get('error_reason', '') or 'LLM 未启用或未返回正文'}",
            f"- 自检命令：`python main.py --mode llm_check`",
            "- 复核重点：东方财富 / 天天基金 / AKShare 当日结构化字段是否与报告一致。",
            "",
            "## 9. 免责声明",
            "",
            "本报告仅用于个人研究和复盘，不构成投资建议，不包含自动交易或确定性收益承诺。",
        ]
    )
    return lines


def _quality_intro_section(context: Dict[str, Any], coverage: Dict[str, Any]) -> str:
    summary = context.get("data_quality_summary") or _build_quality_summary(context, coverage)
    groups = coverage.get("groups") or {}
    group_lines = []
    for name in ("fund", "etf", "index", "sector", "holding_stock", "portfolio"):
        item = groups.get(name) or {}
        group_lines.append(f"- {name}: {item.get('coverage', 0.0):.2f}% ({item.get('ok', 0)}/{item.get('total', 0)})")
    source_filter = context.get("source_run_filter") or {}
    return "\n".join(
        [
            "## 0. 数据时间与质量摘要",
            "",
            f"- 数据日期：{context.get('data_date') or '-'}",
            f"- 决策时间：{context.get('decision_time') or '-'}",
            f"- agent_report_core_coverage：{coverage.get('agent_report_core_coverage', 0.0):.2f}%",
            f"- 数据质量门控：{_quality_prompt(coverage.get('agent_report_core_coverage', 0.0))}",
            f"- ETF行情：{summary['market']['etf_success']}/{summary['market']['etf_total']}",
            f"- 指数行情：{summary['market']['index_success']}/{summary['market']['index_total']}",
            f"- 板块行情：{summary['market']['sector_success']}/{summary['market']['sector_total']}，缺失：{summary['market']['sector_missing_text']}",
            f"- 持仓股行情：{summary['holdings']['quote_success']}/{summary['holdings']['total']}",
            f"- 持仓权重来源：AKShare fund_portfolio_hold_em / fund_enrichment_result",
            f"- Firecrawl：supplementary/debug only",
            f"- old_data_source_run_excluded：{source_filter.get('old_source_runs_excluded', 0)}",
            "",
            "### coverage_by_group",
            "",
            *group_lines,
            "",
            "### 今日结构化行情摘要",
            "",
            _market_tables_section(context),
        ]
    )


def _market_tables_section(context: Dict[str, Any]) -> str:
    snapshot = context.get("market_quote_snapshot") or {}
    trade_date = snapshot.get("trade_date") or context.get("data_date") or "-"
    snapshot_time = snapshot.get("snapshot_time") or "-"
    parts = [
        f"#### ETF 今日盘中表现（{trade_date} {snapshot_time}）",
        "",
        _market_table(context.get("etfs", {}), "ETF", "最新价"),
        "",
        "#### 指数今日盘中表现",
        "",
        _market_table(context.get("indices", {}), "指数", "最新点位"),
        "",
        "#### 板块今日盘中表现",
        "",
    ]
    sector_summary = _market_status_summary(context)
    if sector_summary["sector_success"] == 0:
        parts.append(f"今日板块结构化行情缺失：{sector_summary['sector_text']}")
        parts.append("")
    parts.append(_sector_table(context.get("sectors", {})))
    return "\n".join(parts)


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


def _field_source_summary_block(context: Dict[str, Any], coverage: Dict[str, Any]) -> str:
    groups = coverage.get("groups") or {}
    market = (context.get("data_quality_summary") or {}).get("market") or {}
    source_filter = context.get("source_run_filter") or {}
    return "\n".join(
        [
            f"- fund coverage: {groups.get('fund', {}).get('coverage', 0.0):.2f}%",
            f"- etf coverage: {groups.get('etf', {}).get('coverage', 0.0):.2f}%",
            f"- index coverage: {groups.get('index', {}).get('coverage', 0.0):.2f}%",
            f"- sector coverage: {groups.get('sector', {}).get('coverage', 0.0):.2f}%",
            f"- holding_stock coverage: {groups.get('holding_stock', {}).get('coverage', 0.0):.2f}%",
            f"- portfolio coverage: {groups.get('portfolio', {}).get('coverage', 0.0):.2f}%",
            f"- 板块缺失名单：{market.get('sector_missing_text', '-')}",
            f"- 旧 data_source_run 已排除：{source_filter.get('old_source_runs_excluded', 0)}",
        ]
    )


def _build_holdings_analysis(context: Dict[str, Any], fields: list[SqlField]) -> Dict[str, Any]:
    try:
        from .analyze_holdings import analyze_holdings_from_context

        return analyze_holdings_from_context(context, fields)
    except Exception as exc:
        return {"summary": {"status": "failed", "error_reason": str(exc)}, "holdings": [], "missing_fields": []}


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


def _build_source_run_meta(all_fields: list[SqlField], data_date: str | None, decision_time: str) -> Dict[str, Any]:
    rows = _rows_from_fields(all_fields, "data_source_run")
    current_rows = []
    old_rows = []
    for row in rows:
        trade_date = str(row.get("trade_date") or "")
        row_decision_time = str(row.get("decision_time") or "")
        if data_date and trade_date and trade_date != data_date:
            old_rows.append(row)
            continue
        if row_decision_time and row_decision_time not in {"", decision_time, "data_probe"}:
            old_rows.append(row)
            continue
        current_rows.append(row)
    return {
        "data_sources": list(_data_source_summary_map(current_rows).values())[:20],
        "data_source_summary": _data_source_summary_map(current_rows),
        "source_run_filter": {
            "trade_date": data_date,
            "decision_time": decision_time,
            "old_source_runs_excluded": len(old_rows),
        },
        "debug_only_source_runs": [_sanitize_source_run_row(row) for row in old_rows[:40]],
    }


def _render_debug_report(
    context: Dict[str, Any],
    llm_fields: list[SqlField],
    all_fields: list[SqlField],
    config_path: str,
    db_path: str,
    decision_time: str,
    llm_result: Dict[str, Any],
    report_path: Path,
    context_path: Path,
) -> str:
    field_source_rows = _rows_from_fields(all_fields, "field_source")
    data_source_rows = _rows_from_fields(all_fields, "data_source_run")
    failures = [
        row
        for row in data_source_rows
        if str(row.get("fetch_status") or "").lower() not in {"success", "ok"}
        and any(token in str(row.get("source_name") or row.get("source_type") or "").lower() for token in ("firecrawl", "cninfo", "raw"))
    ]
    field_source_summary = defaultdict(int)
    for row in field_source_rows:
        key = f"{row.get('source') or 'unknown'}::{row.get('audit_status') or 'unknown'}"
        field_source_summary[key] += 1
    data_source_summary = _data_source_summary_map(data_source_rows)
    lines = [
        "# 场外基金盘中 Agent Debug 报告",
        "",
        f"- report_path: `{report_path}`",
        f"- context_json_path: `{context_path}`",
        f"- config: `{config_path}`",
        f"- db: `{db_path}`",
        f"- decision_time: {decision_time}",
        f"- llm_provider: {llm_result.get('provider') or '-'}",
        f"- llm_model: {llm_result.get('model') or '-'}",
        f"- llm_status: {llm_result.get('status') or '-'}",
        "",
        "## source_run_filter",
        "",
        "```json",
        json.dumps(context.get("source_run_filter", {}), ensure_ascii=False, indent=2),
        "```",
        "",
        "## field_source 明细摘要",
        "",
        "| source::audit | count |",
        "| --- | ---: |",
    ]
    for key, value in sorted(field_source_summary.items()):
        lines.append(f"| {_md(key)} | {value} |")
    if not field_source_summary:
        lines.append("| - | 0 |")
    lines.extend(
        [
            "",
            "## data_source_run 明细摘要",
            "",
            "```json",
            json.dumps(data_source_summary, ensure_ascii=False, indent=2),
            "```",
            "",
            "## raw fallback / Firecrawl / CNInfo 失败明细",
            "",
            "```json",
            json.dumps([_sanitize_source_run_row(row) for row in failures[:60]], ensure_ascii=False, indent=2),
            "```",
            "",
            "## debug_only_source_runs",
            "",
            "```json",
            json.dumps(context.get("debug_only_source_runs", []), ensure_ascii=False, indent=2),
            "```",
            "",
            "## SQL 输入字段列表",
            "",
            render_sql_field_report([field for field in llm_fields if field.include_in_llm], config_path, db_path, decision_time),
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _rows_from_fields(fields: Iterable[SqlField], table_name: str) -> list[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = defaultdict(dict)
    for field in fields:
        if field.table_name != table_name:
            continue
        row = rows[field.row_id]
        row[field.field_name] = field.value
        row.setdefault("row_id", field.row_id)
        row.setdefault("trade_date", field.trade_date)
        row.setdefault("decision_time", field.decision_time)
        row.setdefault("entity_code", field.entity_code)
        row.setdefault("entity_name", field.entity_name)
        row.setdefault("source_status", field.source_status)
    return list(rows.values())


def _data_source_summary_map(rows: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("source_name") or row.get("source_type") or row.get("row_id") or "unknown")
        candidate = {
            "trade_date": row.get("trade_date"),
            "decision_time": row.get("decision_time"),
            "status": row.get("fetch_status") or row.get("source_status") or "unknown",
            "matched_fields_count": row.get("matched_fields_count"),
            "missing_fields_count": row.get("missing_fields_count"),
            "source_type": row.get("source_type") or "",
        }
        current = summary.get(name)
        if current is None or _source_row_rank(candidate) >= _source_row_rank(current):
            summary[name] = candidate
    return summary


def _sanitize_source_run_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "trade_date": row.get("trade_date"),
        "decision_time": row.get("decision_time"),
        "source_name": row.get("source_name"),
        "source_type": row.get("source_type"),
        "fetch_status": row.get("fetch_status") or row.get("source_status"),
        "matched_fields_count": row.get("matched_fields_count"),
        "missing_fields_count": row.get("missing_fields_count"),
        "error_reason": row.get("error_reason"),
    }


def _build_quality_summary(context: Dict[str, Any], coverage: Dict[str, Any]) -> Dict[str, Any]:
    market = _market_status_summary(context)
    holdings = _holding_status_summary(context)
    return {
        "agent_report_core_coverage": coverage.get("agent_report_core_coverage", 0.0),
        "market": market,
        "holdings": holdings,
        "coverage_by_group": coverage.get("groups", {}),
    }


def _market_status_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    etfs = context.get("etfs") or {}
    indices = context.get("indices") or {}
    sectors = context.get("sectors") or {}
    sector_missing = [name for name, item in sorted(sectors.items()) if item.get("source_status") != "success"]
    return {
        "etf_total": len(etfs),
        "etf_success": sum(1 for item in etfs.values() if item.get("source_status") == "success"),
        "index_total": len(indices),
        "index_success": sum(1 for item in indices.values() if item.get("source_status") == "success"),
        "sector_total": len(sectors),
        "sector_success": sum(1 for item in sectors.values() if item.get("source_status") == "success"),
        "sector_missing": sector_missing,
        "sector_missing_text": "、".join(sector_missing) if sector_missing else "-",
        "sector_text": "今日板块结构化行情缺失" if len(sector_missing) == len(sectors) and sectors else ("缺失：" + "、".join(sector_missing) if sector_missing else "结构化板块行情齐全"),
    }


def _holding_status_summary(context: Dict[str, Any]) -> Dict[str, Any]:
    total = 0
    quote_success = 0
    for item in (context.get("funds") or {}).values():
        fund_type = _first_non_empty(item.get("fields", {}).get("fund_type"), item.get("fields", {}).get("inferred_type"))
        if fund_type == "etf_feeder":
            continue
        for holding in item.get("holdings") or []:
            total += 1
            security = (context.get("securities") or {}).get(str(holding.get("code") or ""), {})
            if security.get("latest_price") not in (None, "") and security.get("change_pct") not in (None, ""):
                quote_success += 1
    return {"total": total, "quote_success": quote_success}


def _tracking_codes(context: Dict[str, Any], key: str, fallback: Iterable[Any]) -> list[str]:
    values: list[str] = []
    for item in (context.get("funds") or {}).values():
        tracking = item.get("tracking") or {}
        for raw in tracking.get(key) or []:
            if isinstance(raw, dict):
                value = raw.get("code") or raw.get("name")
            else:
                value = raw
            if value:
                values.append(str(value))
    if not values:
        values = [str(item) for item in fallback]
    seen = set()
    result = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _core_value_ok(value: Any, source_status: Any = None, source_name: Any = None) -> bool:
    if value in (None, "", [], {}, "missing"):
        return False
    source_text = str(source_name or "").lower()
    if any(token in source_text for token in ("firecrawl", "cninfo", "raw", "parser_no_match", "debug")):
        return False
    if source_status is not None and str(source_status).lower() not in {"", "success", "ok"}:
        return False
    return True


def _quality_prompt(rate: float) -> str:
    if rate < 50:
        return "数据不足，仅人工复核"
    if rate < 80:
        return "只能输出弱倾向，建议持有观察 / 等待确认 / 谨慎加仓观察 / 减仓观察"
    return "可输出弱到中等倾向，但仍需人工复核"


def _apply_quality_gate_to_llm_result(llm_result: Dict[str, Any], rate: float) -> Dict[str, Any]:
    if llm_result.get("status") != "success" or not llm_result.get("content"):
        return llm_result
    content = str(llm_result.get("content") or "")
    if rate < 50:
        llm_result["status"] = "coverage_blocked"
        llm_result["error_reason"] = f"agent_report_core_coverage={rate:.2f}%"
        llm_result["content"] = ""
        return llm_result
    llm_result["content"] = _soften_action_labels(content, rate)
    return llm_result


def _soften_action_labels(text: str, rate: float) -> str:
    replacements = [("谨慎加仓", "谨慎加仓观察"), ("加仓", "加仓观察"), ("减仓", "减仓观察")]
    if rate < 80:
        replacements.extend([("强烈买入", "等待确认"), ("买入", "观察"), ("卖出", "减仓观察")])
    for old, new in replacements:
        text = re.sub(old, new, text)
    text = text.replace("加仓观察观察", "加仓观察").replace("减仓观察观察", "减仓观察")
    return text


def _trim_report_heading(content: str) -> str:
    text = content.lstrip()
    text = re.sub(r"^#\s+场外基金盘中 Agent 分析报告\s*", "", text, count=1)
    return text.lstrip()


def _terminal_summary(llm_result: Dict[str, Any], report_path: Path, context: Dict[str, Any]) -> str:
    coverage = (context.get("agent_report_core_coverage") or {}).get("agent_report_core_coverage", 0.0)
    return "\n".join(
        [
            "fund_agent_report 摘要",
            f"基金数: {len(context.get('funds', {}))}",
            f"LLM状态: {llm_result.get('status')}",
            f"核心覆盖率: {coverage:.2f}%",
            f"报告: {report_path}",
        ]
    )


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


def _first_non_empty(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def _fmt(value: Any) -> str:
    if value in (None, ""):
        return "missing"
    try:
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def _md(value: Any) -> str:
    return str(value if value is not None else "").replace("\n", " ").replace("|", "\\|")


def _source_row_rank(row: Dict[str, Any]) -> tuple:
    return (str(row.get("trade_date") or ""), str(row.get("decision_time") or ""), int(row.get("matched_fields_count") or 0))
