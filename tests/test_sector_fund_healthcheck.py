from tradingagents.sector_fund.healthcheck import run_sector_fund_healthcheck, format_healthcheck_report


def test_sector_fund_healthcheck_runs_with_mock_only(tmp_path):
    result = run_sector_fund_healthcheck(
        config_path="config/personal_semiconductor.yaml",
        output_dir=tmp_path / "healthcheck_reports",
        run_real_data=False,
    )
    report = format_healthcheck_report(result)

    assert result["config_exists"] is True
    assert result["watch_stocks_ok"] is True
    assert result["funds_ok"] is True
    assert result["etfs_ok"] is True
    assert result["mock_mode_ok"] is True
    assert "sector_fund healthcheck" in report
