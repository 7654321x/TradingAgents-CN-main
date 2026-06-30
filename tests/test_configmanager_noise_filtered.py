import logging


def test_configmanager_noise_filtered_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import setup_sector_fund_logging

    setup_sector_fund_logging("data_probe", quiet=True)

    assert logging.getLogger("agents").level == logging.WARNING


def test_configmanager_noise_allowed_in_verbose(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    from tradingagents.sector_fund.logging_utils import setup_sector_fund_logging

    setup_sector_fund_logging("data_probe", quiet=True, verbose=True)

    assert logging.getLogger("agents").level == logging.INFO
