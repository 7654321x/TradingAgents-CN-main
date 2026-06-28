import yaml

from tradingagents.sector_fund.fund_config_loader import load_fund_portfolio_config
from tradingagents.sector_fund.intraday_snapshot import build_intraday_snapshot


def test_multi_fund_config_is_data_driven(tmp_path):
    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "portfolio": {"name": "multi", "total_position_pct": 10},
                "database": {"path": str(tmp_path / "fund.sqlite3")},
                "data_sources": {"use_baostock": False, "use_web": False, "use_firecrawl": False},
                "funds": [
                    {
                        "code": "111111",
                        "name": "基金A",
                        "type": "core",
                        "tracking": {"etfs": ["512480"], "indices": ["科创50"], "sectors": ["半导体"], "manual_holdings": []},
                    },
                    {
                        "code": "222222",
                        "name": "基金B",
                        "type": "offensive",
                        "tracking": {"etfs": ["159995"], "indices": ["创业板指"], "sectors": ["芯片"], "manual_holdings": []},
                    },
                    {
                        "code": "333333",
                        "name": "基金C",
                        "type": "satellite",
                        "tracking": {"etfs": ["588200"], "indices": ["沪深300"], "sectors": ["算力"], "manual_holdings": []},
                    },
                ],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    config = load_fund_portfolio_config(config_path)
    snapshot = build_intraday_snapshot(config, decision_time="1000", refresh_data=False, db_path=tmp_path / "fund.sqlite3")

    assert [fund["code"] for fund in snapshot["snapshot"]["funds"]] == ["111111", "222222", "333333"]
    assert snapshot["snapshot"]["tracking"]["etfs"] == ["159995", "512480", "588200"]
