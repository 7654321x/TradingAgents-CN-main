from __future__ import annotations

from typing import Any, Iterable, Mapping

from .logging_utils import get_sector_logger, sanitize_url


class DataFetchLogger:
    """Compatibility wrapper around unified sector_fund logging."""

    def __init__(self, log_dir: str = "logs", echo: bool = True):
        self.echo = echo
        self.log_dir = log_dir
        self.log_path = ""

    def info(self, message: str) -> None:
        get_sector_logger("data_probe").info("🔍 [DataProbe] %s", message)

    def fetch_result(
        self,
        source_name: str,
        url: str,
        status: str,
        raw_text_length: int = 0,
        fields: Iterable[str] | None = None,
        error_reason: str = "",
    ) -> None:
        fields_list = list(fields or [])
        fields_count = len(fields_list)
        logger_name, component, action, entity_key, entity_value = _source_meta(source_name)
        logger = get_sector_logger(logger_name)
        success = status.startswith("success/") or status == "success"
        no_match = "no_match" in status or fields_count == 0
        if no_match:
            action = "持仓解析未命中" if "持仓" in action else "读取成功但解析未命中"
        level = logger.info if success and not no_match else logger.warning
        icon = "✅" if success and not no_match else "⚠️"
        reason = _reason(error_reason, no_match)
        extra = f" {entity_key}={entity_value}" if entity_key and entity_value else ""
        msg = (
            f"{icon} [{component}] {action} |{extra} status={status} "
            f"fields={fields_count} raw={raw_text_length}B"
        )
        if url:
            msg += f" source={sanitize_url(url)}"
        if reason:
            msg += f" reason={reason}"
        level(msg)

    def parsed_fields(self, source_name: str, fields: Iterable[str], entity: str = "") -> None:
        field_list = list(fields)
        if not field_list:
            return
        logger_name, component, action, _, _ = _source_meta(source_name)
        get_sector_logger(logger_name).info(
            "✅ [%s] 字段解析成功 | entity=%s fields=%s names=%s",
            component,
            entity or source_name,
            len(field_list),
            ",".join(field_list[:12]),
        )

    def source_summary(self, source_status: Mapping[str, str], field_sources: Mapping[str, str]) -> None:
        success_count = sum(1 for status in source_status.values() if status == "success")
        failed_count = sum(1 for status in source_status.values() if status != "success")
        source_counts: dict[str, int] = {}
        for source in field_sources.values():
            source_counts[source] = source_counts.get(source, 0) + 1
        source_text = ",".join(f"{key}:{value}" for key, value in sorted(source_counts.items())) or "-"
        get_sector_logger("summary").info(
            "📊 [Summary] 字段来源汇总 | web_success=%s web_failed=%s sources=%s",
            success_count,
            failed_count,
            source_text,
        )

    def quote_summary(self, source_name: str, quotes: Mapping[str, Mapping[str, Any]]) -> None:
        logger = get_sector_logger("holding")
        for code, item in quotes.items():
            status = item.get("source_status") or item.get("audit_status") or item.get("final_source") or "unknown"
            fields = [
                field
                for field in ("latest_price", "change_pct", "amount", "turnover_rate", "ma5", "ma10", "ma20", "below_ma20")
                if item.get(field) is not None
            ]
            icon = "✅" if fields and status != "missing" else "⚠️"
            logger.info(
                "%s [HoldingStock] 字段读取结果 | source=%s stock=%s status=%s fields=%s",
                icon,
                source_name,
                code,
                status,
                len(fields),
            )


def _source_meta(source_name: str) -> tuple[str, str, str, str, str]:
    lower = source_name.lower()
    code = source_name.rsplit("_", 1)[-1] if "_" in source_name else ""
    if "akshare" in lower:
        action = "基金持仓读取成功" if "holding" in lower else "结构化字段读取成功"
        return "akshare", "AKShare", action, "code", code
    if "tiantian" in lower or "fund_" in lower:
        action = "估算读取成功" if "estimate" in lower else "持仓读取成功" if "holding" in lower else "基金字段读取成功"
        return "tiantianfund", "TianTianFund", action, "fund", code
    if "eastmoney" in lower:
        return "eastmoney", "EastMoney", "行情读取成功", "code", code
    if "baostock" in lower:
        return "baostock", "Baostock", "日K/MA读取成功", "code", code
    if "firecrawl" in lower:
        return "firecrawl", "Firecrawl", "raw_text读取成功", "", ""
    return "data_probe", "DataProbe", "字段读取成功", "", ""


def _reason(error_reason: str, no_match: bool) -> str:
    if error_reason:
        if "parser matched no expected fields" in error_reason:
            return "parser_no_match"
        return error_reason[:160]
    return "parser_no_match" if no_match else ""
