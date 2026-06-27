from typing import Dict

from .context import SectorFundContext


def _clamp(value: float, minimum: int = 0, maximum: int = 100) -> int:
    return int(max(minimum, min(maximum, round(value))))


def _sector_score(context: SectorFundContext, sector_name: str) -> int:
    sector = next((item for item in context.sectors if item.name == sector_name), None)
    if not sector:
        return 50

    trend = 12 + (sector.change_pct or 0) * 4 + (sector.change_5d_pct or 0) * 0.8
    flow = 10
    if sector_name == "存储芯片":
        flow += (context.fund_flow.storage_main_inflow_billion or 0) * 0.35
    elif sector_name == "半导体":
        flow += (context.fund_flow.semiconductor_main_inflow_billion or 0) * 0.28
    else:
        flow += (context.fund_flow.chip_main_inflow_billion or 0) * 0.25

    theme_stocks = [stock for stock in context.stocks if sector_name[:2] in stock.theme or stock.theme in {"存储链", "设备链"}]
    strong_count = sum(1 for stock in theme_stocks if (stock.change_pct or 0) > 3 and not stock.long_upper_shadow)
    weak_count = sum(1 for stock in theme_stocks if stock.below_ma10 or (stock.change_pct or 0) < -3)
    leaders = 10 + strong_count * 2 - weak_count * 3

    news = 5 + _announcement_score(context)
    emotion = 5 + _emotion_score(context)

    market = 5
    if (context.market.chinext_change_pct or 0) > 0 and (context.market.star50_change_pct or 0) > 0:
        market += 3
    if (context.market.declining_count or 0) > (context.market.advancing_count or 0):
        market -= 3

    return _clamp(trend + flow + leaders + news + emotion + market)


def _announcement_score(context: SectorFundContext) -> int:
    score = 0
    negative_core_count = 0
    for ann in context.announcements:
        if ann.earnings_up:
            score += 4
        if ann.major_order or ann.customer_validation:
            score += 4
        if ann.shareholder_reduce:
            score -= 4
            negative_core_count += 1
        if ann.earnings_down:
            score -= 5
            negative_core_count += 1
        if ann.risk_warning:
            score -= 3
            negative_core_count += 1
    if negative_core_count >= 2:
        score -= 3
    return score


def _emotion_score(context: SectorFundContext) -> int:
    score = 0
    institution_buy_count = sum(1 for stock in context.stocks if (stock.institution_net_buy_billion or 0) > 0)
    lhb_sell_count = sum(1 for stock in context.stocks if (stock.net_buy_amount_billion or 0) < 0)
    hot_fade_count = sum(1 for stock in context.stocks if stock.intraday_pullback and (stock.hot_money_net_buy_billion or 0) > 0)
    shadow_count = sum(1 for stock in context.stocks if stock.long_upper_shadow or stock.intraday_pullback)

    if institution_buy_count >= 1:
        score += 2
    if institution_buy_count >= 2:
        score += 3
    if hot_fade_count >= 1:
        score -= 2
    if lhb_sell_count >= 2:
        score -= 3
    if shadow_count >= 3:
        score -= 3
    return score


def score_sector_fund_context(context: SectorFundContext) -> Dict[str, object]:
    semiconductor_score = _sector_score(context, "半导体")
    storage_score = _sector_score(context, "存储芯片")
    announcement_score = _announcement_score(context)
    emotion_score = _emotion_score(context)
    average_score = (semiconductor_score + storage_score) / 2

    if average_score >= 80:
        status = "强势主线"
        risk_level = "中"
        suggestion = "已有仓位持有，可等回踩小加，但不建议追高。"
    elif average_score >= 65:
        status = "强势震荡"
        risk_level = "中高"
        suggestion = "已有仓位持有，不建议开盘追涨；回踩MA5/MA10不破可小加。"
    elif average_score >= 50:
        status = "分歧震荡"
        risk_level = "中高"
        suggestion = "观察为主，不追涨，等资金和龙头股重新共振。"
    elif average_score >= 35:
        status = "转弱"
        risk_level = "高"
        suggestion = "不补仓，可考虑降低进攻仓，等待重新站回MA10。"
    else:
        status = "风险较高"
        risk_level = "高"
        suggestion = "控制科技仓位，等板块重新站回均线并出现资金回流。"

    return {
        "semiconductor_score": semiconductor_score,
        "storage_score": storage_score,
        "announcement_score": announcement_score,
        "emotion_score": emotion_score,
        "status": status,
        "risk_level": risk_level,
        "suggestion": suggestion,
    }
