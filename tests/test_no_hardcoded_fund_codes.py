from pathlib import Path


DATA_LAYER_FILES = [
    "tradingagents/sector_fund/db.py",
    "tradingagents/sector_fund/models.py",
    "tradingagents/sector_fund/repository.py",
    "tradingagents/sector_fund/fund_config_loader.py",
    "tradingagents/sector_fund/baostock_provider.py",
    "tradingagents/sector_fund/intraday_snapshot.py",
    "tradingagents/sector_fund/fund_context_formatter.py",
    "tradingagents/sector_fund/fund_intraday_runner.py",
]


def test_fund_intraday_data_layer_does_not_hardcode_personal_fund_codes():
    for filename in DATA_LAYER_FILES:
        text = Path(filename).read_text(encoding="utf-8")
        assert "020671" not in text, filename
        assert "025500" not in text, filename
