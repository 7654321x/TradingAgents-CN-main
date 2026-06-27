from pathlib import Path


def test_personal_semiconductor_config_loads():
    from tradingagents.sector_fund.config_loader import load_personal_semiconductor_config

    config = load_personal_semiconductor_config("config/personal_semiconductor.yaml")

    assert config["profile"]["name"] == "personal_semiconductor_storage"
    assert config["profile"]["current_tech_position"] == 0.20
    assert {fund["code"] for fund in config["funds"]} == {"020671", "025500"}


def test_mock_data_builds_sector_fund_context():
    from tradingagents.sector_fund.context import SectorFundContext
    from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context

    context = build_mock_sector_fund_context("config/personal_semiconductor.yaml")

    assert isinstance(context, SectorFundContext)
    assert context.profile["current_tech_position"] == 0.20
    assert {fund.code for fund in context.funds} == {"020671", "025500"}
    assert any(sector.name == "半导体" for sector in context.sectors)
    assert context.raw_text["mock"] == "mock数据已启用"


def test_sector_fund_score_stays_between_zero_and_one_hundred():
    from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
    from tradingagents.sector_fund.scoring import score_sector_fund_context

    context = build_mock_sector_fund_context("config/personal_semiconductor.yaml")
    score = score_sector_fund_context(context)

    assert 0 <= score["semiconductor_score"] <= 100
    assert 0 <= score["storage_score"] <= 100
    assert score["status"]
    assert "建议" not in score["suggestion"] or "必" not in score["suggestion"]


def test_sector_fund_report_renders_chinese_markdown(tmp_path):
    from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
    from tradingagents.sector_fund.report import render_sector_fund_report, save_sector_fund_report
    from tradingagents.sector_fund.scoring import score_sector_fund_context

    context = build_mock_sector_fund_context("config/personal_semiconductor.yaml")
    score = score_sector_fund_context(context)
    report = render_sector_fund_report(context, score)
    output = save_sector_fund_report(report, output_dir=tmp_path, analysis_date="2026-06-27")

    assert "【A股半导体/存储板块与个人基金持仓趋势报告】" in report
    assert "020671" in report
    assert "025500" in report
    assert "免责声明" in report
    assert output.exists()
    assert output.read_text(encoding="utf-8") == report


def test_existing_cli_analyze_command_remains_available():
    import pytest

    pytest.importorskip("typer")
    from cli.main import app

    command_names = {command.name for command in app.registered_commands}

    assert "analyze" in command_names
    assert "analyze-sector-fund" in command_names
