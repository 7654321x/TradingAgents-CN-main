from pathlib import Path

import yaml


def test_data_probe_respects_config_and_skips_baostock(monkeypatch, tmp_path):
    from tradingagents.sector_fund import data_probe

    config_path = tmp_path / "portfolio.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "portfolio": {"name": "test"},
                "database": {"path": str(tmp_path / "fund.sqlite3")},
                "data_sources": {
                    "use_baostock": False,
                    "use_web": False,
                    "akshare": {"enabled": True},
                    "baostock": {"enabled": False},
                },
                "funds": [{"code": "020671", "name": "基金A", "type": "etf_feeder", "tracking": {"etfs": [], "indices": [], "sectors": []}}],
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )

    calls = {"baostock": 0, "akshare": 0}

    def fail_baostock(config, raw_dir):
        calls["baostock"] += 1
        raise AssertionError("Baostock should be skipped by config")

    def fake_akshare(config, raw_dir):
        calls["akshare"] += 1
        return []

    monkeypatch.setattr(data_probe, "_probe_baostock", fail_baostock)
    monkeypatch.setattr(data_probe, "_probe_tiantian_fund", lambda *args, **kwargs: [])
    monkeypatch.setattr(data_probe, "_probe_eastmoney_structured", lambda *args, **kwargs: [])
    monkeypatch.setattr(data_probe, "_probe_akshare", fake_akshare)

    result = data_probe.run_data_probe(
        config_path=str(config_path),
        output_dir=tmp_path / "reports",
        raw_root=tmp_path / "raw",
        no_web=True,
        use_akshare=None,
    )

    assert calls["baostock"] == 0
    assert calls["akshare"] == 1
    assert Path(result["report_path"]).exists()
