from __future__ import annotations

import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


LOG_FORMAT = "%(asctime)s | %(name)-22s | %(levelname)-7s | %(message)s"
SECRET_NAMES = (
    "DASHSCOPE_API_KEY",
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "FIRECRAWL_API_KEY",
    "WENCAI_COOKIE",
    "MONGODB_CONNECTION_STRING",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "COOKIE",
)
SECRET_QUERY_KEYS = {"key", "token", "cookie", "sign", "rt", "apikey", "api_key"}

_CURRENT_RUN: dict[str, str] = {}


class SanitizingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        return sanitize_message(rendered)


def setup_sector_fund_logging(
    mode: str,
    run_id: str | None = None,
    log_level: str = "INFO",
    verbose: bool = False,
    quiet: bool = False,
    log_file: bool = True,
) -> dict[str, str]:
    run_id = run_id or datetime.now().strftime("%Y%m%d_%H%M%S")
    level = getattr(logging, str(log_level or "INFO").upper(), logging.INFO)
    log_date = datetime.now().date().isoformat()
    log_path = Path("logs") / "sector_fund" / log_date / f"{mode}_{run_id}.log"

    formatter = SanitizingFormatter(LOG_FORMAT)
    root = logging.getLogger("sector_fund")
    root.setLevel(logging.DEBUG)
    root.propagate = False
    root.handlers.clear()

    if not quiet:
        console = logging.StreamHandler(sys.stdout)
        console.setLevel(level)
        console.setFormatter(formatter)
        root.addHandler(console)

    if log_file:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    set_noisy_loggers(verbose=verbose)
    _CURRENT_RUN.clear()
    _CURRENT_RUN.update({"mode": mode, "run_id": run_id, "log_path": str(log_path) if log_file else ""})
    return dict(_CURRENT_RUN)


def get_sector_logger(name: str) -> logging.Logger:
    normalized = name if name.startswith("sector_fund") else f"sector_fund.{name}"
    logger = logging.getLogger(normalized)
    logger.propagate = True
    return logger


def current_log_context() -> dict[str, str]:
    return dict(_CURRENT_RUN)


def mask_secret(value: str) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 8:
        return "****"
    prefix = text[:3] if text.startswith("sk-") else text[:2]
    return f"{prefix}****{text[-4:]}"


def sanitize_url(url: str) -> str:
    text = str(url or "")
    try:
        parts = urlsplit(text)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            query.append((key, "****" if key.lower() in SECRET_QUERY_KEYS else value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))
    except Exception:
        return text


def sanitize_message(message: Any) -> str:
    text = str(message)
    for name in SECRET_NAMES:
        text = re.sub(rf"({re.escape(name)}\s*[=:]\s*)([^\s|,;]+)", lambda m: m.group(1) + mask_secret(m.group(2)), text, flags=re.IGNORECASE)
    text = re.sub(r"(mongodb(?:\+srv)?://)([^\s|]+)", r"\1****", text, flags=re.IGNORECASE)
    text = re.sub(r"(Bearer\s+)([A-Za-z0-9._\-]+)", lambda m: m.group(1) + mask_secret(m.group(2)), text, flags=re.IGNORECASE)
    text = re.sub(r"(sk-[A-Za-z0-9_\-]{8,})", lambda m: mask_secret(m.group(1)), text)

    def replace_url(match: re.Match[str]) -> str:
        return sanitize_url(match.group(0))

    return re.sub(r"https?://[^\s|]+", replace_url, text)


def set_noisy_loggers(verbose: bool = False) -> None:
    level = logging.INFO if verbose else logging.WARNING
    for name in ("agents", "tradingagents", "pymongo", "urllib3", "requests"):
        logging.getLogger(name).setLevel(level)
