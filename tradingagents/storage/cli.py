from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tradingagents.analysis.fund_report import FundReportError, FundReportService
from tradingagents.analysis.stock_decision_report import (
    REPORT_ALREADY_EXISTS,
    StockDecisionReportError,
    StockDecisionReportService,
)
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.extensions.sector_fund import ALL_MARKET_SYMBOLS
from tradingagents.reports.fund_technical_report import save_fund_report
from tradingagents.reports.stock_decision_report import (
    save_evidence_audit_failure,
    save_stock_decision_report,
)

from .db import init_db
from .market import ingest_market
from .models import (
    FundHoldingPosition,
    FundHoldingReport,
    FundInstrumentRelation,
    Instrument,
    Universe,
    UniverseInstrument,
)
from .service import ingest_fund_holdings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tradingagents.storage.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    import_parser = sub.add_parser("import-fund-holdings")
    import_parser.add_argument("--seed")
    sub.add_parser("database-stats")
    market_parser = sub.add_parser("ingest-market")
    market_parser.add_argument("--interval", choices=["1d", "5m"], default="1d")
    market_parser.add_argument("--period", default="1mo")
    market_parser.add_argument("--symbols", nargs="*")
    sub.add_parser("update-market")
    sub.add_parser("list-universes")
    universe_parser = sub.add_parser("show-universe")
    universe_parser.add_argument("--code", required=True)

    report_parser = sub.add_parser("generate-fund-report")
    report_parser.add_argument("--fund-code", required=True)
    report_parser.add_argument("--analysis-date", required=True)
    report_parser.add_argument(
        "--mode",
        choices=["database_only", "database_first", "provider_only"],
        default="database_only",
    )
    report_parser.add_argument("--output")
    report_parser.add_argument("--overwrite", action="store_true")
    report_parser.add_argument("--format", choices=["markdown"], default="markdown")
    batch_parser = sub.add_parser("generate-fund-reports")
    batch_parser.add_argument("--fund-codes", nargs="+", required=True)
    batch_parser.add_argument("--analysis-date", required=True)
    batch_parser.add_argument(
        "--mode",
        choices=["database_only", "database_first", "provider_only"],
        default="database_only",
    )
    batch_parser.add_argument("--overwrite", action="store_true")
    stock_parser = sub.add_parser("generate-stock-decision-report")
    stock_parser.add_argument("--symbol", required=True)
    stock_parser.add_argument("--name", required=True)
    stock_parser.add_argument("--analysis-date", required=True)
    stock_parser.add_argument("--horizon", choices=["20-60d"], default="20-60d")
    stock_parser.add_argument(
        "--analysts",
        nargs="+",
        choices=["market", "fundamentals", "news"],
        default=["market", "fundamentals", "news"],
    )
    stock_parser.add_argument(
        "--mode",
        choices=["database_only", "database_first", "provider_only"],
        default="database_only",
    )
    stock_parser.add_argument("--provider", default=DEFAULT_CONFIG["llm_provider"])
    stock_parser.add_argument("--model", default=DEFAULT_CONFIG["deep_think_llm"])
    stock_parser.add_argument("--output")
    stock_parser.add_argument("--price-basis", choices=["adjusted"], default="adjusted")
    stock_parser.add_argument(
        "--audit-evidence",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    stock_parser.add_argument("--overwrite", action="store_true")
    stock_parser.add_argument("--dry-run", action="store_true")
    return parser


def _run_fund_report(engine, fund_code, analysis_date, mode, output=None, overwrite=False):
    provider = None
    if mode != "database_only":
        from tradingagents.dataflows.y_finance import _get_yfinance_daily_frame

        provider = _get_yfinance_daily_frame
    with Session(engine) as session:
        result = FundReportService(session, mode=mode, provider=provider).analyze(
            fund_code, analysis_date
        )
    json_path, markdown_path = save_fund_report(
        result, output, overwrite=overwrite
    )
    return result, json_path, markdown_path


def _generate_fund_report(args, engine) -> int:
    try:
        result, json_path, markdown_path = _run_fund_report(
            engine,
            args.fund_code,
            args.analysis_date,
            args.mode,
            args.output,
            args.overwrite,
        )
    except FundReportError as exc:
        print(str(exc))
        return 2
    print(f"基金代码：{result.fund_code}")
    print(f"基金类型：{result.fund_type}")
    print(f"报告期：{result.report_period_end}")
    print(f"分析日期：{result.analysis_date}")
    print(f"持仓数量：{result.holding_count}")
    print(f"成功数量：{result.successful_count}")
    print(f"失败数量：{result.failed_count}")
    print(f"有效分析权重：{result.analyzed_weight_pct:.2f}%")
    print(f"数据质量状态：{result.data_quality_status}")
    print(f"整体技术状态：{result.overall_technical_status}")
    print(f"Provider 调用次数：{result.provider_call_count}")
    if result.proxy_analysis is not None:
        print(f"目标 ETF：{result.proxy_analysis.symbol}")
        print(f"目标 ETF 权重：{result.proxy_analysis.weight_pct:.2f}%")
    print(f"JSON 保存路径：{json_path}")
    print(f"报告保存路径：{markdown_path}")
    return 0


def _generate_fund_reports(args, engine) -> int:
    print(
        "fund_code\tfund_type\tstatus\tholding_count\tsuccessful_count\t"
        "data_quality\treport_json\treport_markdown\terror_message"
    )
    failures = 0
    for fund_code in args.fund_codes:
        try:
            result, json_path, markdown_path = _run_fund_report(
                engine,
                fund_code,
                args.analysis_date,
                args.mode,
                overwrite=args.overwrite,
            )
            values = (
                fund_code,
                result.fund_type,
                "SUCCESS",
                str(result.holding_count),
                str(result.successful_count),
                result.data_quality_status,
                str(json_path),
                str(markdown_path),
                "",
            )
        except Exception as exc:
            failures += 1
            values = (
                fund_code,
                "unknown",
                "FAILED",
                "0",
                "0",
                "unavailable",
                "",
                "",
                f"{type(exc).__name__}: {exc}",
            )
        print("\t".join(values))
    return 1 if failures else 0


def _generate_stock_decision_report(args, engine) -> int:
    provider_fn = None
    if args.mode != "database_only":
        from tradingagents.dataflows.y_finance import _get_yfinance_daily_frame

        provider_fn = _get_yfinance_daily_frame
    try:
        output_dir = (
            Path(args.output)
            if args.output
            else Path("reports") / "stocks" / args.symbol / args.analysis_date
        )
        if not args.dry_run and (output_dir / "decision_report.md").exists() and not args.overwrite:
            raise StockDecisionReportError(
                REPORT_ALREADY_EXISTS, str((output_dir / "decision_report.md").resolve())
            )
        trader_llm = risk_llm = None
        if not args.dry_run:
            from tradingagents.llm_clients.factory import create_llm_client

            client = create_llm_client(
                args.provider,
                args.model,
                DEFAULT_CONFIG.get("backend_url"),
                temperature=DEFAULT_CONFIG.get("temperature"),
                max_retries=DEFAULT_CONFIG.get("llm_max_retries"),
                timeout=120,
            )
            trader_llm = risk_llm = client.get_llm()
        with Session(engine) as session:
            service = StockDecisionReportService(
                session,
                mode=args.mode,
                provider=provider_fn,
                trader_llm=trader_llm,
                risk_llm=risk_llm,
                llm_provider=args.provider,
                trader_model=args.model,
                risk_model=args.model,
                price_basis=args.price_basis,
                audit_evidence=args.audit_evidence,
            )
            result = service.run(
                args.symbol,
                args.name,
                args.analysis_date,
                args.analysts,
                dry_run=args.dry_run,
            )
        if args.dry_run:
            market = result["market_input"]
            trend = result["trend_result"]
            evidence = result["evidence"]
            print("状态：DRY_RUN_SUCCESS")
            print(f"股票：{args.symbol} {args.name}")
            print(f"行情来源：{market['market_data_source']}")
            print(f"数据截止：{market['data_cutoff']}")
            print(f"日线数量：{market['daily_row_count']}")
            print(f"展示价格口径：{market['display_price_basis']}")
            print(f"技术价格口径：{market['technical_price_basis']}")
            print(f"复权状态：{market['price_adjustment_status']}")
            for period in (5, 10, 20, 40, 60, 120, 200):
                print(f"{period}日收益：{market[f'return_{period}d_pct']}")
            print(f"MA5 / MA10 / MA20：{market['ma5']} / {market['ma10']} / {market['ma20']}")
            print(f"短期均线结构：{market['short_ma_structure']}")
            print(f"ADX14 / +DI14 / -DI14：{market['adx14']} / {market['plus_di14']} / {market['minus_di14']}")
            print(f"20日成交量比：{market['volume_ratio_20d']}")
            print(f"20日上涨日比例：{market['up_day_ratio_20d']}")
            print(f"20日年化历史波动率：{market['volatility_20d_pct']}")
            print(f"60日真实最大回撤：{market['max_drawdown_60d_pct']}")
            print(f"技术分：{trend['technical_score']:.6f}")
            print(f"技术风险分：{trend['technical_risk_score']:.6f}")
            print(f"确定性趋势：{trend['deterministic_trend']}")
            print(f"市场证据覆盖率：{evidence['market_evidence_coverage']:.2%}")
            print(f"跨领域证据覆盖率：{evidence['cross_domain_evidence_coverage']:.2%}")
            print(f"确定性方向倾向：{result['decision_policy']['directional_bias']}")
            print(f"确定性确认程度：{result['decision_policy']['confirmation_status']}")
            print(f"Prompt 版本：{result['trader_prompt_version']} / {result['risk_prompt_version']}")
            print(f"输入哈希：{result['input_hash']}")
            print(f"Yahoo 调用次数：{market['market_provider_call_count']}")
            print("LLM 调用次数：0")
            print("正式报告：未创建")
            return 0
        paths = save_stock_decision_report(result, args.output, overwrite=args.overwrite)
    except (StockDecisionReportError, ValueError) as exc:
        audit = getattr(exc, "audit", None)
        if audit is not None:
            failure_path = save_evidence_audit_failure(output_dir, audit)
            print(f"证据审计失败文件：{failure_path.resolve()}")
        print(str(exc))
        return 2
    market = result.market_input
    trend = result.deterministic_trend
    trader = result.trader_decision
    risk = result.risk_review
    final = result.final_decision
    print(f"股票：{result.symbol} {result.name}")
    print(f"分析日期：{result.analysis_date}")
    print(f"数据截止：{result.data_cutoff}")
    print(f"日线数量：{market['daily_row_count']}")
    print(f"技术价格口径：{market['technical_price_basis']}")
    print(f"复权状态：{market['price_adjustment_status']}")
    print(f"技术分：{trend['technical_score']:.6f}")
    print(f"技术风险分：{trend['technical_risk_score']:.6f}")
    print(f"确定性趋势：{trend['deterministic_trend']}")
    print(f"Fundamentals 状态：{result.fundamentals_analysis['status']}")
    print(f"News 状态：{result.news_analysis['status']}")
    print(f"市场证据覆盖率：{result.evidence['market_evidence_coverage']:.2%}")
    print(f"跨领域证据覆盖率：{result.evidence['cross_domain_evidence_coverage']:.2%}")
    print(f"Trader 方向倾向：{trader['directional_bias']}")
    print(f"Trader 置信度：{trader['confidence']:.2%}")
    print(f"Risk 状态：{risk['review_status']}")
    print(f"风险等级：{risk['risk_level']}")
    print(f"确认程度：{risk['confirmation_status']}")
    print(f"风险复核方向：{risk['directional_bias']}")
    print(f"调整后置信度：{risk['adjusted_confidence']:.2%}")
    print(f"最终趋势：{final['trend_direction']}")
    print(f"最终方向倾向：{final['directional_bias']}")
    print(f"无持仓动作：{final['position_scenarios']['no_position']['action']}")
    print(f"已有多头动作：{final['position_scenarios']['existing_long']['action']}")
    print(f"观察名单动作：{final['position_scenarios']['watchlist']['action']}")
    print(f"最终风险：{final['risk_level']}")
    print(f"LLM Provider：{result.llm_provider}")
    print(f"Trader Model：{result.trader_model}")
    print(f"Risk Model：{result.risk_model}")
    print(f"LLM 调用次数：{result.llm_call_count}")
    print(f"Yahoo 调用次数：{result.market_provider_call_count}")
    for filename, path in paths.items():
        print(f"{filename}：{path.resolve()}")
    return 0


def main() -> int:
    args = _build_parser().parse_args()
    engine = init_db()
    if args.command == "generate-fund-report":
        return _generate_fund_report(args, engine)
    if args.command == "generate-fund-reports":
        return _generate_fund_reports(args, engine)
    if args.command == "generate-stock-decision-report":
        return _generate_stock_decision_report(args, engine)
    if args.command == "import-fund-holdings":
        print(ingest_fund_holdings(args.seed, engine))
    elif args.command == "ingest-market":
        print(
            ingest_market(
                args.symbols or ALL_MARKET_SYMBOLS,
                args.interval,
                args.period,
                engine,
            )
        )
    elif args.command == "update-market":
        print(
            {
                "daily": ingest_market(ALL_MARKET_SYMBOLS, "1d", "1d", engine),
                "intraday_5m": ingest_market(
                    ALL_MARKET_SYMBOLS, "5m", "5d", engine
                ),
            }
        )
    elif args.command == "list-universes":
        with Session(engine) as session:
            for universe in session.scalars(select(Universe)).all():
                count = session.scalar(
                    select(func.count())
                    .select_from(UniverseInstrument)
                    .where(UniverseInstrument.universe_id == universe.id)
                )
                print(universe.code, count)
    elif args.command == "show-universe":
        with Session(engine) as session:
            universe = session.scalar(
                select(Universe).where(Universe.code == args.code)
            )
            rows = (
                session.execute(
                    select(
                        Instrument.symbol,
                        Instrument.instrument_type,
                        UniverseInstrument.membership_type,
                    )
                    .join(
                        UniverseInstrument,
                        UniverseInstrument.instrument_id == Instrument.id,
                    )
                    .where(UniverseInstrument.universe_id == universe.id)
                ).all()
                if universe
                else []
            )
            print(args.code, len(rows))
            for row in rows:
                print(*row)
    elif args.command == "database-stats":
        with Session(engine) as session:
            print(
                {
                    "instruments": session.scalar(
                        select(func.count()).select_from(Instrument)
                    ),
                    "reports": session.scalar(
                        select(func.count()).select_from(FundHoldingReport)
                    ),
                    "positions": session.scalar(
                        select(func.count()).select_from(FundHoldingPosition)
                    ),
                    "relations": session.scalar(
                        select(func.count()).select_from(FundInstrumentRelation)
                    ),
                }
            )
    else:
        print("database initialized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
