from tradingagents.sector_fund.mock_data import build_mock_sector_fund_context
from tradingagents.sector_fund.data_quality import calculate_data_quality
from tradingagents.sector_fund.parsers import apply_raw_text_to_context
from tradingagents.sector_fund.report import render_sector_fund_report
from tradingagents.sector_fund.scoring import score_sector_fund_context


def test_stage4_missing_real_fields_still_generates_report(tmp_path):
    context = build_mock_sector_fund_context(analysis_date="2026-06-27")

    apply_raw_text_to_context(
        context,
        {
            "ths_lhb": "",
            "eastmoney_lhb": "",
            "cninfo": "",
            "stock_eastmoney_688012": "688012 中微公司 最新价 10.00 涨跌幅 1.00%",
        },
        source_label="real_data",
        history_store=None,
    )
    score = score_sector_fund_context(context)
    report = render_sector_fund_report(context, score)

    assert "## 5. 龙头股观察" in report
    assert "龙虎榜" in report
    assert "## 8. 公告与新闻风险" in report
    assert "【数据可信度】" in report


def test_stage4_report_shows_lhb_and_announcement_results(tmp_path):
    context = build_mock_sector_fund_context(analysis_date="2026-06-27")

    apply_raw_text_to_context(
        context,
        {
            "ths_lhb": "688525 佰维存储 龙虎榜 上榜原因 日涨幅偏离值达7% 机构净买入 1亿元 游资净买入 2000万元 净买入 1.20亿元",
            "cninfo": "2026-06-26 688525 佰维存储 股东减持公告 风险提示 股东拟减持不超过1%",
        },
        source_label="real_data",
        history_store=None,
    )
    score = score_sector_fund_context(context)
    report = render_sector_fund_report(context, score)

    assert "机构+游资净买入" in report
    assert "股东减持公告" in report
    assert "利空公告" in report


def test_stage4_lhb_and_announcement_fields_count_as_real_coverage():
    context = build_mock_sector_fund_context(analysis_date="2026-06-27")

    apply_raw_text_to_context(
        context,
        {
            "ths_lhb": "688525 佰维存储 龙虎榜 上榜原因 日涨幅偏离值达7% 机构净买入 1亿元 净买入 1亿元",
            "cninfo": "2026-06-26 688525 佰维存储 股东减持公告 风险提示 股东拟减持不超过1%",
        },
        source_label="real_data",
        history_store=None,
    )
    quality = calculate_data_quality(context.field_sources)

    assert context.field_sources["stock.688525.on_lhb"] == "real_data"
    assert context.field_sources["announcement.688525.sentiment"] == "real_data"
    assert quality["real_field_count"] >= 2
