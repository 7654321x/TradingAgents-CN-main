from pathlib import Path

import pytest
import yaml

from tradingagents.sector_fund.fund_config_loader import load_fund_portfolio_config, resolve_db_path


def test_load_personal_fund_portfolio_config():
    config = load_fund_portfolio_config("config/personal_fund_portfolio.yaml")

    assert config["portfolio"]["name"]
    assert len(config["funds"]) >= 2
    assert config["database"]["path"] == "data/fund_assistant.sqlite3"
    assert all(fund["tracking"]["etfs"] for fund in config["funds"])


def test_resolve_db_path_prefers_override():
    config = load_fund_portfolio_config("config/personal_fund_portfolio.yaml")

    assert resolve_db_path(config, "tmp/custom.sqlite3") == "tmp/custom.sqlite3"


def test_invalid_fund_type_is_rejected(tmp_path):
    config_path = tmp_path / "bad.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "portfolio": {"name": "bad"},
                "funds": [{"code": "123456", "name": "bad", "type": "unknown"}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_fund_portfolio_config(config_path)


def test_missing_config_file_is_clear():
    with pytest.raises(FileNotFoundError):
        load_fund_portfolio_config(Path("config/not_exists.yaml"))
