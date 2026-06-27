from datetime import date
from typing import Dict, List

from .config_loader import load_personal_semiconductor_config
from .context import (
    Announcement,
    EtfObservation,
    FundFlow,
    FundHolding,
    MarketEnvironment,
    SectorFundContext,
    SectorPerformance,
    StockObservation,
)


def _mock_stocks(watch_stocks: Dict[str, List[Dict[str, str]]]) -> List[StockObservation]:
    theme_names = {
        "storage": "存储链",
        "equipment": "设备链",
        "manufacturing_packaging": "制造/封测",
        "material_pcb": "材料/PCB",
    }
    stock_rows: List[StockObservation] = []
    seed_changes = [8.2, 4.6, 3.1, 1.8, -1.5, -3.2]
    for theme, rows in watch_stocks.items():
        for index, row in enumerate(rows[:6]):
            change_pct = seed_changes[index % len(seed_changes)]
            stock_rows.append(
                StockObservation(
                    code=row["code"],
                    name=row["name"],
                    theme=theme_names.get(theme, theme),
                    change_pct=change_pct,
                    turnover_billion=8.5 - index * 0.4,
                    turnover_rate=9.2 - index * 0.5,
                    main_inflow_billion=1.6 - index * 0.35,
                    limit_up=change_pct >= 8,
                    intraday_pullback=index == 1,
                    long_upper_shadow=index == 1,
                    below_ma5=change_pct < -1,
                    below_ma10=change_pct < -3,
                    on_lhb=index == 0,
                    institution_net_buy_billion=0.8 if index == 0 else None,
                    hot_money_net_buy_billion=0.2 if index == 0 else None,
                    net_buy_amount_billion=1.0 if index == 0 else None,
                    lhb_reason="日涨幅偏离值达7%" if index == 0 else "",
                    sentiment_tag="机构+游资净买入" if index == 0 else "",
                )
            )
    return stock_rows


def build_mock_sector_fund_context(
    config_path: str = "config/personal_semiconductor.yaml",
    analysis_date: str | None = None,
) -> SectorFundContext:
    config = load_personal_semiconductor_config(config_path)
    analysis_date = analysis_date or date.today().isoformat()

    sectors = [
        SectorPerformance("半导体", 1.8, 820, 3.2, 92, 38, ["北方华创", "中微公司"], ["北京君正"], 4.6, 7.8, 13.2),
        SectorPerformance("存储芯片", 2.6, 460, 5.8, 35, 12, ["佰维存储", "江波龙"], ["普冉股份"], 8.9, 14.5, 24.0),
        SectorPerformance("芯片概念", 1.2, 980, 2.9, 130, 76, ["兆易创新"], ["恒烁股份"], 3.5, 6.1, 10.4),
        SectorPerformance("科创芯片", 1.5, 390, 3.6, 45, 19, ["澜起科技"], ["沪硅产业"], 3.9, 7.2, 12.8),
        SectorPerformance("半导体设备", 0.9, 310, 2.7, 24, 18, ["北方华创"], ["芯源微"], 2.1, 5.0, 8.6),
        SectorPerformance("先进封装", 1.1, 220, 3.1, 18, 10, ["长电科技"], ["华天科技"], 2.8, 5.6, 9.8),
        SectorPerformance("PCB", -0.4, 300, 4.4, 17, 26, ["沪电股份"], ["胜宏科技"], 1.2, 4.1, 11.0),
        SectorPerformance("消费电子", 0.5, 610, 2.5, 78, 61, ["深南电路"], ["香农芯创"], 1.0, 2.7, 6.3),
        SectorPerformance("AI芯片", 1.9, 280, 4.8, 22, 8, ["寒武纪", "澜起科技"], ["北京君正"], 5.0, 8.8, 16.5),
    ]

    funds = [
        FundHolding(
            code="020671",
            name="易方达科创芯片ETF联接C",
            unit_nav=1.0842,
            daily_change_pct=1.35,
            week_change_pct=4.8,
            month_change_pct=11.6,
            three_month_change_pct=18.2,
            ytd_change_pct=24.5,
            top_holdings=["科创芯片ETF", "澜起科技", "中芯国际", "寒武纪"],
            top_holdings_weight_pct=88.0,
            industry_allocation={"半导体": 82.0, "现金": 5.0},
            size_billion=18.6,
            manager="未获取到",
            role="科技底仓 / 科创芯片指数暴露",
            position_role="base",
        ),
        FundHolding(
            code="025500",
            name="东方阿尔法科技智选混合C",
            unit_nav=1.1268,
            daily_change_pct=2.15,
            week_change_pct=7.4,
            month_change_pct=16.9,
            three_month_change_pct=28.6,
            ytd_change_pct=34.2,
            top_holdings=["江波龙", "佰维存储", "德明利", "兆易创新"],
            top_holdings_weight_pct=56.0,
            industry_allocation={"存储链": 42.0, "半导体设备": 18.0, "消费电子": 12.0},
            size_billion=9.4,
            manager="未获取到",
            role="科技进攻仓 / 存储链弹性暴露",
            position_role="aggressive",
        ),
    ]

    context = SectorFundContext(
        analysis_date=analysis_date,
        profile=config["profile"],
        config=config,
        market=MarketEnvironment(0.4, 0.8, 1.1, 1.6, 0.5, 12400, 3280, 1760, 78, 4),
        sectors=sectors,
        fund_flow=FundFlow(42.5, 28.4, 55.1, 37.8, ["半导体", "存储芯片", "AI芯片"], 118.0, 206.0, 23.4, 31.6, "佰维存储", "北京君正"),
        stocks=_mock_stocks(config["watch_stocks"]),
        funds=funds,
        etfs=[
            EtfObservation("512480", "半导体ETF", 0.948, 1.4, 24.6, 6.8, 0.08, 5.4, 0.932, 0.910, 0.875, True, False),
            EtfObservation("159995", "芯片ETF", 1.126, 1.7, 18.2, 5.9, 0.12, 6.1, 1.105, 1.076, 1.028, True, False),
            EtfObservation("588200", "科创芯片ETF", 1.018, 1.9, 11.9, 7.4, 0.05, 7.2, 1.001, 0.972, 0.930, True, False),
            EtfObservation("588290", "科创芯片ETF", 1.033, 1.6, 9.8, 6.5, 0.03, 6.8, 1.018, 0.991, 0.949, True, False),
            EtfObservation("516640", "芯片龙头ETF", 0.756, 0.9, 6.4, 4.1, -0.02, 3.9, 0.752, 0.741, 0.714, True, False),
        ],
        announcements=[
            Announcement("某半导体设备公司披露重大订单进展", analysis_date, "688012", "中微公司", "重大订单", "重大订单", "利好", 4, major_order=True, summary="订单能见度改善，对设备链情绪有支撑。", impact_direction="利好", impact_strength=4),
            Announcement("某存储链公司提示短期涨幅较大风险", analysis_date, "688525", "佰维存储", "风险提示", "风险提示", "利空", 3, risk_warning=True, summary="短线波动加大，追高胜率下降。", impact_direction="利空", impact_strength=3),
            Announcement("某材料公司股东拟小比例减持", analysis_date, "688019", "安集科技", "股东减持", "股东减持", "利空", 2, shareholder_reduce=True, summary="减持比例不高，但会压制短期风险偏好。", impact_direction="利空", impact_strength=2),
        ],
        raw_text={"mock": "mock数据已启用"},
        source_status={"mock": "success"},
    )
    _mark_mock_field_sources(context)
    return context


def _mark_mock_field_sources(context: SectorFundContext) -> None:
    for field_name in (
        "semiconductor_main_inflow_billion",
        "storage_main_inflow_billion",
        "electronics_main_inflow_billion",
        "chip_main_inflow_billion",
        "five_day_inflow_billion",
        "ten_day_inflow_billion",
    ):
        context.field_sources[f"fund_flow.{field_name}"] = "mock_fallback"

    for sector in context.sectors:
        context.field_sources[f"sector.{sector.name}.change_pct"] = "mock_fallback"
        context.field_sources[f"sector.{sector.name}.turnover_billion"] = "mock_fallback"
        context.field_sources[f"sector.{sector.name}.change_5d_pct"] = "mock_fallback"

    for fund in context.funds:
        for field_name in (
            "unit_nav",
            "daily_change_pct",
            "week_change_pct",
            "month_change_pct",
            "three_month_change_pct",
            "ytd_change_pct",
            "top_holdings",
            "top_holdings_weight_pct",
            "size_billion",
            "manager",
        ):
            context.field_sources[f"fund.{fund.code}.{field_name}"] = "mock_fallback"

    for etf in context.etfs:
        for field_name in (
            "latest_price",
            "change_pct",
            "turnover_billion",
            "turnover_rate",
            "premium_rate_pct",
            "five_day_change_pct",
            "ma5",
            "ma10",
            "ma20",
            "pullback_ma5",
            "pullback_ma10",
            "below_ma10",
            "below_ma20",
        ):
            context.field_sources[f"etf.{etf.code}.{field_name}"] = "mock_fallback"

    for stock in context.stocks:
        for field_name in (
            "change_pct",
            "turnover_billion",
            "turnover_rate",
            "main_inflow_billion",
            "ma5",
            "ma10",
            "limit_up",
            "limit_down",
            "intraday_pullback",
            "long_upper_shadow",
            "below_ma5",
            "below_ma10",
            "on_lhb",
            "institution_net_buy_billion",
            "hot_money_net_buy_billion",
            "buy_top5_amount_billion",
            "sell_top5_amount_billion",
            "net_buy_amount_billion",
            "lhb_reason",
            "sentiment_tag",
        ):
            context.field_sources[f"stock.{stock.code}.{field_name}"] = "mock_fallback"

    for announcement in context.announcements:
        for field_name in (
            "title",
            "event_type",
            "sentiment",
            "importance",
            "is_earnings_increase",
            "is_earnings_loss",
            "is_shareholder_reduce",
            "is_risk_warning",
            "is_big_order",
            "is_customer_validation",
        ):
            context.field_sources[f"announcement.{announcement.stock_code}.{field_name}"] = "mock_fallback"
