import os
from pathlib import Path
from typing import Any, Dict

from .config_loader import load_personal_semiconductor_config
from .runner import run_sector_fund_analysis
from .score_history import ScoreHistoryStore


def _exists(path: str | Path) -> bool:
    return Path(path).exists()


def _latest_score_history(path: str | Path = "data/sector_fund_score_history.json") -> Dict[str, Any]:
    rows = ScoreHistoryStore(path).load()
    return rows[-1] if rows else {}


def run_sector_fund_healthcheck(
    config_path: str = "config/personal_semiconductor.yaml",
    output_dir: str | Path = "reports/sector_fund_healthcheck",
    run_real_data: bool = True,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "config_path": config_path,
        "config_exists": _exists(config_path),
        "score_history_exists": _exists("data/sector_fund_score_history.json"),
        "price_history_exists": _exists("data/sector_fund_history.json"),
        "reports_dir_exists": _exists("reports/sector_fund"),
        "logs_dir_exists": _exists("logs"),
        "daily_script_exists": _exists("scripts/run_sector_fund_daily.ps1"),
        "firecrawl_api_key_configured": bool(os.getenv("FIRECRAWL_API_KEY")),
        "watch_stocks_ok": False,
        "funds_ok": False,
        "etfs_ok": False,
        "mock_mode_ok": False,
        "real_data_mode_ok": False if run_real_data else None,
        "latest_report_path": "",
        "latest_real_coverage_rate": None,
        "latest_data_quality_level": "",
        "errors": [],
    }

    if result["config_exists"]:
        try:
            config = load_personal_semiconductor_config(config_path)
            result["watch_stocks_ok"] = bool(config.get("watch_stocks"))
            result["funds_ok"] = bool(config.get("funds"))
            result["etfs_ok"] = bool(config.get("etfs"))
        except Exception as exc:
            result["errors"].append(f"config_load_failed: {exc}")

    try:
        mock_result = run_sector_fund_analysis(
            config_path=config_path,
            use_mock=True,
            output_dir=output_dir,
            save_history=False,
            open_report=False,
        )
        result["mock_mode_ok"] = True
        result["latest_report_path"] = str(mock_result.get("output_path", ""))
        result["latest_real_coverage_rate"] = mock_result["context"].data_quality.get("real_coverage_rate")
        result["latest_data_quality_level"] = mock_result["context"].data_quality.get("data_quality_level", "")
    except Exception as exc:
        result["errors"].append(f"mock_mode_failed: {exc}")

    if run_real_data:
        try:
            real_result = run_sector_fund_analysis(
                config_path=config_path,
                use_mock=False,
                use_firecrawl=False,
                output_dir=output_dir,
                save_history=False,
                open_report=False,
            )
            result["real_data_mode_ok"] = True
            result["latest_report_path"] = str(real_result.get("output_path", result.get("latest_report_path", "")))
            result["latest_real_coverage_rate"] = real_result["context"].data_quality.get("real_coverage_rate")
            result["latest_data_quality_level"] = real_result["context"].data_quality.get("data_quality_level", "")
        except Exception as exc:
            result["errors"].append(f"real_data_mode_failed: {exc}")

    latest = _latest_score_history()
    if latest:
        result["latest_report_path"] = latest.get("report_path") or result["latest_report_path"]
        result["latest_real_coverage_rate"] = latest.get("real_coverage_rate")
        result["latest_data_quality_level"] = latest.get("data_quality_level", "")

    return result


def format_healthcheck_report(result: Dict[str, Any]) -> str:
    labels = {
        "config_exists": "配置文件存在",
        "watch_stocks_ok": "watch_stocks读取正常",
        "funds_ok": "funds读取正常",
        "etfs_ok": "etfs读取正常",
        "score_history_exists": "评分历史文件存在",
        "price_history_exists": "价格历史文件存在",
        "reports_dir_exists": "报告目录存在",
        "logs_dir_exists": "日志目录存在",
        "daily_script_exists": "PowerShell日报脚本存在",
        "firecrawl_api_key_configured": "Firecrawl API Key已配置",
        "mock_mode_ok": "mock模式可运行",
        "real_data_mode_ok": "real-data模式可运行",
    }
    lines = ["sector_fund healthcheck"]
    for key, label in labels.items():
        value = result.get(key)
        if value is None:
            status = "SKIP"
        else:
            status = "OK" if value else "WARN"
        lines.append(f"- {label}: {status}")
    lines.append(f"- 最近一次报告路径: {result.get('latest_report_path') or '未获取到'}")
    lines.append(f"- 最近一次真实覆盖率: {result.get('latest_real_coverage_rate') if result.get('latest_real_coverage_rate') is not None else '未获取到'}")
    lines.append(f"- 最近一次数据质量等级: {result.get('latest_data_quality_level') or '未获取到'}")
    if result.get("errors"):
        lines.append("- 错误: " + " | ".join(result["errors"]))
    return "\n".join(lines)
