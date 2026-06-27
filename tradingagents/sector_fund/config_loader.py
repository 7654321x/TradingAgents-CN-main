from pathlib import Path
from typing import Any, Dict

import yaml


def load_personal_semiconductor_config(config_path: str | Path) -> Dict[str, Any]:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"未找到配置文件: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}

    required_sections = ("profile", "funds", "sectors", "etfs", "watch_stocks", "rules")
    missing = [section for section in required_sections if section not in data]
    if missing:
        raise ValueError(f"配置文件缺少必要字段: {', '.join(missing)}")

    return data

