def test_summary_block_output_contains_log_path(capsys):
    from main import print_summary_block

    print_summary_block(
        "data_probe",
        {"run_id": "rid", "log_path": "logs/sector_fund/2026-06-29/data_probe_rid.log"},
        "config/personal_fund_portfolio.yaml",
        {
            "core_coverage_rate": 95.45,
            "core_matched_count": 63,
            "core_total_count": 66,
            "all_coverage_rate": 87.96,
            "all_matched_count": 168,
            "all_total_count": 191,
        },
        {"summary": "reports/summary.md"},
    )
    output = capsys.readouterr().out

    assert "======== sector_fund summary ========" in output
    assert "mode: data_probe" in output
    assert "text: logs/sector_fund/2026-06-29/data_probe_rid.log" in output
