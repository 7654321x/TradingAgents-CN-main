from __future__ import annotations

from types import SimpleNamespace

from tradingagents.extensions.sector_fund.efunds_provider import (
    fetch_efunds_identity,
    fetch_efunds_nav_history,
)


def test_efunds_provider_extracts_identity_without_guessing_codes(monkeypatch):
    body = """
    <html><script>ignored()</script><body>
    基金名称: 易方达上证科创板芯片交易型开放式指数证券投资基金发起式联接基金
    基金简称: 易方达上证科创板芯片ETF联接发起式C
    基金代码: 020671 基金类型: ETF联接基金 成立日期: 2024-01-31
    基金经理: 李栩 基金托管人: 招商银行股份有限公司
    基金规模: 数据截至2026-06-30：4,605,470,656.89元
    基金净值日期: 2026-07-21
    标的指数名称： 上证科创板芯片指数 投资比例: 本基金投资于目标ETF的资产不低于基金资产净值的90%
    基金投资明细 序号 基金代码 基金名称 1 589130 易方达上证科创板芯片交易型开放式指数证券投资基金
    申购费率 本基金不收取申购费 赎回费率 持有时间（天） 赎回费率 0-6 1.50% 7及以上 0.00%
    管理费、托管费、销售服务费 管理费 0.50% 托管费 0.10% 销售服务费 0.30%
    </body></html>
    """
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.efunds_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text=body,
            encoding="",
            raise_for_status=lambda: None,
        ),
    )
    result = fetch_efunds_identity("020671")
    assert result.fund_code == "020671"
    assert result.fund_type == "ETF联接基金"
    assert result.benchmark_index_name == "上证科创板芯片指数"
    assert result.target_etf_ratio_min_pct == 90.0
    assert result.fund_size == 4605470656.89
    assert result.target_etf_code == "589130"
    assert result.benchmark_index_code == "000685"
    assert result.is_official is True
    assert result.purchase_fee_description == "本基金不收取申购费"
    assert result.redemption_fee_description == "0-6 1.50% 7及以上 0.00%"
    assert result.management_fee_pct == 0.5
    assert result.custody_fee_pct == 0.1
    assert result.sales_service_fee_pct == 0.3


def test_efunds_provider_rejects_unconfirmed_code(monkeypatch):
    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.efunds_provider.requests.get",
        lambda *args, **kwargs: SimpleNamespace(
            text="基金代码: 000001",
            encoding="",
            raise_for_status=lambda: None,
        ),
    )
    try:
        fetch_efunds_identity("020671")
    except ValueError as exc:
        assert "did not confirm" in str(exc)
    else:
        raise AssertionError("expected identity mismatch to fail")


def test_efunds_nav_history_parses_official_rows(monkeypatch):
    body = "基金代码：020671 2026-07-22 3.9167 -1.98% 3.9167 2026-07-21 3.9959 12.61% 3.9959"

    class Response:
        text = body
        encoding = ""

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        "tradingagents.extensions.sector_fund.efunds_provider.requests.get",
        lambda *args, **kwargs: Response(),
    )
    rows = fetch_efunds_nav_history("020671")
    assert [row.nav_date for row in rows] == ["2026-07-22", "2026-07-21"]
    assert rows[0].unit_nav == 3.9167
    assert rows[0].daily_change_pct == -1.98
