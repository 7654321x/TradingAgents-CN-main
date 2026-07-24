"""2026 Q1 fund holdings derived from the JSON seed."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

DEFAULT_SEED_PATH = Path(__file__).resolve().parents[3] / "data" / "seeds" / "fund_holdings_seed_2026q1.json"


def load_fund_holdings_seed(seed_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(seed_path) if seed_path else DEFAULT_SEED_PATH
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    validate_fund_holdings_seed(data)
    return data


def validate_fund_holdings_seed(data: dict[str, Any]) -> None:
    required = {"schema_version", "holding_report_period_end", "holding_report_published_date", "funds"}
    if not required <= set(data):
        raise ValueError("invalid fund holdings seed header")
    funds = data["funds"]
    expected_codes = {"020671", "017811", "025500"}
    if len(funds) != 3 or {str(item.get("fund_code")) for item in funds} != expected_codes:
        raise ValueError("expected three known funds")
    for fund in funds:
        if len(fund.get("holdings", [])) != 10:
            raise ValueError(f"fund {fund.get('fund_code')} must have ten holdings")
        for holding in fund["holdings"]:
            if not str(holding.get("symbol", "")).endswith((".SS", ".SZ")):
                raise ValueError(f"invalid A-share symbol: {holding.get('symbol')}")


def build_stock_universe(seed: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    instruments: dict[str, dict[str, Any]] = {}
    for fund in seed["funds"]:
        for holding in fund["holdings"]:
            symbol = holding["symbol"]
            item = instruments.setdefault(
                symbol,
                {
                    "symbol": symbol,
                    "local_code": holding["local_code"],
                    "name": holding["name"],
                    "instrument_type": "stock",
                    "fund_membership": [],
                },
            )
            item["fund_membership"].append(
                {"fund_code": fund["fund_code"], "rank": holding["rank"], "weight_pct": holding["weight_pct"]}
            )
    return tuple(instruments[s] for s in sorted(instruments))


def build_proxy_universe(seed: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    result = []
    for fund in seed["funds"]:
        if fund.get("proxy_instrument"):
            result.append({**fund["proxy_instrument"], "fund_code": fund["fund_code"]})
    return tuple(sorted(result, key=lambda item: item["symbol"]))

FUND_HOLDINGS_SEED = load_fund_holdings_seed()
FUND_CODES = tuple(f["fund_code"] for f in FUND_HOLDINGS_SEED["funds"])
UNIQUE_STOCKS = build_stock_universe(FUND_HOLDINGS_SEED)
PROXY_INSTRUMENTS = build_proxy_universe(FUND_HOLDINGS_SEED)
STOCK_SYMBOLS = tuple(x["symbol"] for x in UNIQUE_STOCKS)
PROXY_SYMBOLS = tuple(x["symbol"] for x in PROXY_INSTRUMENTS)
ALL_MARKET_SYMBOLS = STOCK_SYMBOLS + PROXY_SYMBOLS
