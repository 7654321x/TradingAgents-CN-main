from pathlib import Path
from typing import Any, Dict

import yaml

from .models import VALID_FUND_TYPES


def load_fund_portfolio_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到基金组合配置文件: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for section in ("portfolio", "database", "data_sources", "funds"):
        if section not in data:
            raise ValueError(f"基金组合配置缺少必要字段: {section}")
    if not isinstance(data["funds"], list) or not data["funds"]:
        raise ValueError("基金组合配置至少需要一个 funds 条目")
    for fund in data["funds"]:
        fund_type = fund.get("type")
        if fund_type not in VALID_FUND_TYPES:
            raise ValueError(f"不支持的基金类型: {fund_type}")
        fund.setdefault("tracking", {})
        fund["tracking"].setdefault("etfs", [])
        fund["tracking"].setdefault("indices", [])
        fund["tracking"].setdefault("sectors", [])
        fund["tracking"].setdefault("manual_holdings", [])
    return data


def resolve_db_path(config: Dict[str, Any], override: str | None = None) -> str:
    if override:
        return override
    return config.get("database", {}).get("path", "data/fund_assistant.sqlite3")
