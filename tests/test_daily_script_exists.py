from pathlib import Path


def test_daily_powershell_script_exists_and_uses_history_flags():
    script = Path("scripts/run_sector_fund_daily.ps1")

    assert script.exists()
    text = script.read_text(encoding="utf-8")
    assert "--real-data" in text
    assert "--mock" in text
    assert "--save-history" in text
    assert "sector_fund_daily_$Date.log" in text
