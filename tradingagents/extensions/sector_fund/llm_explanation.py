"""Opt-in LLM explanation for the deterministic 020671 report."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from tradingagents.default_config import DEFAULT_CONFIG

SYSTEM_BOUNDARY = """你是基金数据报告解读助手。只能解释给定的已验证数据。
不得修改或重新计算评分，不得编造价格、公告、概率、历史回测或数据来源。
不得输出买入、卖出、加仓、减仓等个性化交易指令；使用“观察”“情景”“风险”语言。
如果数据不足，必须明确写出数据限制。请用简洁中文输出以下固定小节：
1. 数据结论；2. 趋势依据；3. 持有与观望情景；4. 未来3日观察项；5. 数据限制。
历史回测不参与本次报告，不得引用其概率或结论。
``news_leads`` 中的 C 级媒体条目仅可标为“权威媒体报道线索”，不得当作已落地事实、不得改变评分；
``market_data_audit`` 出现未确认、冲突或历史日线缺口时，必须优先说明不能据此作收盘趋势判断：
不得引用该日的实时价格、日收益、均线、RSI、MACD、成交额、趋势分或短线分作为当日结论，
不得计算、推断或命名支撑/压力；只可列出字段、状态和下一次需核验的数据。
不得以用户成本、持仓盈亏或“已持有/未持有”为条件给出任何表述；
份额变化状态不是 AVAILABLE 时，不得输出份额变化率。"""


def _payload(report) -> dict[str, Any]:
    metrics = report.metrics
    extended = report.fund_context.get("extended_observations", {})
    market_audit = extended.get("market_data_audit", [])
    close_guard_active = any(
        isinstance(item, dict)
        and isinstance(item.get("value"), dict)
        and str(item["value"].get("status", "")).startswith("CLOSE_UNCONFIRMED")
        for item in market_audit
    )
    if close_guard_active:
        # The deterministic calculator may have constructed indicators from a
        # current MCP snapshot and an older historical cache.  Do not present
        # that hybrid series to an LLM: it could turn a multi-session gap into
        # a fictitious one-day move.  The LLM still receives the explicit audit
        # record, official NAV context, and event/news provenance.
        safe_context = {
            key: report.fund_context.get(key)
            for key in ("official_nav", "recent_events_7d", "field_health", "source_policy")
        }
        return {
            "fund_code": metrics.get("fund_code"),
            "requested_analysis_date": metrics.get("requested_analysis_date"),
            "market_date": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "current_day_analysis_status": "DATA_GUARD_BLOCKED",
            "core_trend": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "short_term": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "data_confidence": "NOT_APPLICABLE_UNTIL_CLOSE_DATA_IS_VERIFIED",
            "etf": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "sector": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "fund_context": safe_context,
            "news_leads": extended.get("news_lead", []),
            "market_data_audit": market_audit,
            "daily_observation": "EXCLUDED_CURRENT_DAY_CLOSE_UNCONFIRMED",
            "historical_backtest": "EXCLUDED_BY_REQUEST",
        }
    return {
        "fund_code": metrics.get("fund_code"),
        "requested_analysis_date": metrics.get("requested_analysis_date"),
        "market_date": metrics.get("market_date"),
        "weight_snapshot_date": metrics.get("weight_snapshot_date"),
        "core_trend": {"score": report.core_trend.score, "label": report.core_trend.label},
        "short_term": {"score": report.short_term.score, "label": report.short_term.label},
        "data_confidence": report.data_confidence.confidence_pct,
        "etf": metrics.get("etf"),
        "sector": {
            key: metrics.get("sector", {}).get(key)
            for key in (
                "expected_count", "price_available_count", "amount_available_count",
                "advancers", "decliners", "unchanged", "equal_weight_return_pct",
                "index_weighted_return_pct", "amount_vs_5d_avg", "amount_vs_20d_avg",
            )
        },
        "fund_context": report.fund_context,
        "news_leads": extended.get("news_lead", []),
        "market_data_audit": market_audit,
        "daily_observation": report.daily_observation,
        "historical_backtest": "EXCLUDED_BY_REQUEST",
    }


def generate_llm_explanation(
    report,
    *,
    provider: str | None = None,
    model: str | None = None,
    llm_factory: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Return an auditable explanation or a deterministic fallback state."""
    provider = provider or DEFAULT_CONFIG["llm_provider"]
    model = model or DEFAULT_CONFIG["deep_think_llm"]
    payload = _payload(report)
    input_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    prompt = f"{SYSTEM_BOUNDARY}\n\n已验证输入(JSON)：\n{json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)}"
    try:
        if llm_factory is None:
            from tradingagents.llm_clients.factory import create_llm_client

            llm_factory = create_llm_client
        client = llm_factory(provider=provider, model=model)
        response = client.get_llm().invoke(prompt)
        content = getattr(response, "content", response)
        content = str(content).strip()
        if not content:
            raise ValueError("LLM returned empty content")
        return {
            "status": "SUCCESS",
            "provider": provider,
            "model": model,
            "input_hash": input_hash,
            "network_call_count": 1,
            "content": content,
            "disclaimer": "LLM仅解释确定性输入，不改变评分或产生预测概率。",
        }
    except Exception as exc:
        return {
            "status": "FAILED_FALLBACK_DETERMINISTIC",
            "provider": provider,
            "model": model,
            "input_hash": input_hash,
            "network_call_count": 1,
            "content": None,
            "reason": f"{type(exc).__name__}: {exc}",
            "disclaimer": "LLM不可用；请以确定性报告为准。",
        }
