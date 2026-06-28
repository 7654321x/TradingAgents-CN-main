import sys


def test_main_without_args_prints_help_and_does_not_run_stock_demo(monkeypatch, capsys):
    import main

    called = {"stock_demo": False}
    monkeypatch.setattr(sys, "argv", ["main.py"])
    monkeypatch.setattr(main, "run_stock_demo", lambda: called.__setitem__("stock_demo", True))

    main.main()

    output = capsys.readouterr().out
    assert called["stock_demo"] is False
    assert "python main.py --mode sector_fund" in output
    assert "python main.py --mode stock_demo" in output


def test_main_explicit_stock_demo_runs_stock_demo(monkeypatch):
    import main

    called = {"stock_demo": False}
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "stock_demo"])
    monkeypatch.setattr(main, "run_stock_demo", lambda: called.__setitem__("stock_demo", True))

    main.main()

    assert called["stock_demo"] is True


def test_main_explicit_sector_fund_runs_sector_fund(monkeypatch):
    import main

    called = {"sector_fund": False}
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "sector_fund", "--mock", "--no-save-history"])
    monkeypatch.setattr(main, "run_sector_fund_from_args", lambda args: called.__setitem__("sector_fund", True))
    monkeypatch.setattr(main, "run_stock_demo", lambda: (_ for _ in ()).throw(AssertionError("stock demo should not run")))

    main.main()

    assert called["sector_fund"] is True


def test_main_explicit_fund_intraday_runs_data_context_mode(monkeypatch):
    import main

    called = {"fund_intraday": False}
    monkeypatch.setattr(sys, "argv", ["main.py", "--mode", "fund_intraday", "--config", "config/personal_fund_portfolio.yaml"])
    monkeypatch.setattr(main, "run_fund_intraday_from_args", lambda args: called.__setitem__("fund_intraday", True))
    monkeypatch.setattr(main, "run_stock_demo", lambda: (_ for _ in ()).throw(AssertionError("stock demo should not run")))

    main.main()

    assert called["fund_intraday"] is True
