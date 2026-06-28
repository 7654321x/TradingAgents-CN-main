import sys

import main


def test_data_probe_view_latest_cli(monkeypatch, capsys):
    monkeypatch.setattr(
        "tradingagents.sector_fund.data_audit.load_latest_audit",
        lambda: {
            "coverage": {"core_coverage_rate": 88, "all_coverage_rate": 77},
            "audit_rows": [
                {"audit_status": "ok"},
                {"audit_status": "suspect"},
                {"audit_status": "missing"},
            ],
        },
    )
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "data_probe_view", "--latest"])

    main.main()

    output = capsys.readouterr().out
    assert "data_probe view 摘要" in output
    assert "Core coverage: 88%" in output
    assert "可疑字段: 1" in output
