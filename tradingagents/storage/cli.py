from __future__ import annotations

import argparse
import json
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
from tradingagents.extensions.sector_fund import load_fund_holdings_seed
from tradingagents.extensions.sector_fund.baseline import (
    ingest_official_identity_snapshot,
    ingest_official_index_snapshot,
    ingest_index_snapshot_failure,
    ingest_official_nav_history,
    ingest_etf_status_snapshot,
    ingest_seed_identity_snapshot,
)
from tradingagents.extensions.sector_fund.csindex_provider import fetch_csindex_snapshot
from tradingagents.extensions.sector_fund.efunds_provider import (
    fetch_efunds_identity,
    fetch_efunds_nav_history,
)
from tradingagents.extensions.sector_fund.quant_metrics import SectorFundQuantService
from tradingagents.reports.fund_technical_report import save_fund_report
from tradingagents.reports.stock_decision_report import (
    save_evidence_audit_failure,
    save_stock_decision_report,
)

from .db import init_db
from .data_service import MarketDataService, SUCCESS
from .market import ingest_market
from .models import (
    FundHoldingPosition,
    FundHoldingReport,
    FundInstrumentRelation,
    FundMetadataSnapshot,
    FundNavObservation,
    Instrument,
    Universe,
    UniverseConstituentWeight,
    UniverseInstrument,
    UniverseSnapshot,
)
from .service import ingest_fund_holdings


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m tradingagents.storage.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init-db")
    import_parser = sub.add_parser("import-fund-holdings")
    import_parser.add_argument("--seed")
    sub.add_parser("database-stats")
    baseline_parser = sub.add_parser("fund-baseline-snapshot")
    baseline_parser.add_argument("--fund-code", default="020671")
    baseline_parser.add_argument("--as-of-date", required=True)
    baseline_parser.add_argument("--seed")
    baseline_parser.add_argument("--source", choices=["efunds", "seed"], default="efunds")
    nav_parser = sub.add_parser("fund-nav-snapshot")
    nav_parser.add_argument("--fund-code", default="020671")
    nav_parser.add_argument("--max-rows", type=int, default=250)
    nav_report_parser = sub.add_parser("fund-nav-report")
    nav_report_parser.add_argument("--fund-code", default="020671")
    nav_report_parser.add_argument("--analysis-date", required=True)
    nav_report_parser.add_argument("--output")
    etf_status_parser = sub.add_parser("etf-status-snapshot")
    etf_status_parser.add_argument("--etf-code", default="589130")
    event_sync_parser = sub.add_parser("sync-fund-events")
    event_sync_parser.add_argument("--fund-code", default="020671")
    event_sync_parser.add_argument("--force", action="store_true")
    event_list_parser = sub.add_parser("list-fund-events")
    event_list_parser.add_argument("--fund-code", default="020671")
    event_list_parser.add_argument("--analysis-date", required=True)
    event_list_parser.add_argument("--days", type=int, default=7)
    backtest_parser = sub.add_parser("run-sector-fund-backtest")
    backtest_parser.add_argument("--fund-code", default="020671")
    backtest_parser.add_argument("--end-date", required=True)
    backtest_parser.add_argument(
        "--market-source", choices=["database"], default="database"
    )
    backtest_parser.add_argument("--output")
    backtest_parser.add_argument("--overwrite", action="store_true")
    market_sync_parser = sub.add_parser("sync-sector-market-data")
    market_sync_parser.add_argument("--fund-code", default="020671")
    market_sync_parser.add_argument("--start-date", required=True)
    market_sync_parser.add_argument("--end-date", required=True)
    market_sync_parser.add_argument(
        "--source",
        choices=["auto", "eastmoney", "yfinance", "sina", "database"],
        default="auto",
    )
    market_sync_parser.add_argument("--output")
    quant_parser = sub.add_parser("generate-sector-fund-metrics")
    quant_parser.add_argument("--fund-code", default="020671")
    quant_parser.add_argument("--analysis-date", required=True)
    quant_parser.add_argument(
        "--market-source", choices=["database"], default="database"
    )
    quant_parser.add_argument(
        "--classification-source", choices=["database", "csindex"], default="csindex"
    )
    quant_parser.add_argument("--output")
    scored_parser = sub.add_parser("generate-sector-fund-report")
    scored_parser.add_argument("--fund-code", default="020671")
    scored_parser.add_argument("--analysis-date", required=True)
    scored_parser.add_argument(
        "--market-source", choices=["database"], default="database"
    )
    scored_parser.add_argument(
        "--classification-source", choices=["database", "csindex"], default="csindex"
    )
    scored_parser.add_argument("--output")
    scored_parser.add_argument("--overwrite", action="store_true")
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


def _fund_baseline_snapshot(args, engine) -> int:
    if args.fund_code != "020671":
        print(f"仅支持基金 020671，收到：{args.fund_code}")
        return 2
    try:
        if args.source == "efunds":
            identity = fetch_efunds_identity(args.fund_code)
            counts = ingest_official_identity_snapshot(identity, engine=engine)
            if not identity.benchmark_index_code:
                raise ValueError("official fund identity has no verified benchmark index code")
            try:
                index_snapshot = fetch_csindex_snapshot(identity.benchmark_index_code)
            except Exception as index_exc:
                ingest_index_snapshot_failure(
                    index_code=identity.benchmark_index_code,
                    index_name=identity.benchmark_index_name or identity.benchmark_index_code,
                    as_of_date=args.as_of_date,
                    error_message=f"{type(index_exc).__name__}: {index_exc}",
                    engine=engine,
                )
                raise
            counts.update(ingest_official_index_snapshot(index_snapshot, engine=engine))
        else:
            seed = load_fund_holdings_seed(args.seed)
            counts = ingest_seed_identity_snapshot(seed, as_of_date=args.as_of_date, engine=engine)
    except Exception as exc:
        print(f"基金基线快照失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"基金代码：{args.fund_code}")
    print(f"数据日期：{args.as_of_date}")
    print(f"来源状态：{'EFUNDS_OFFICIAL' if args.source == 'efunds' else 'FALLBACK_SEED（非官方动态来源）'}")
    for key, value in counts.items():
        print(f"{key}：{value}")
    if args.source == "seed":
        print("注意：当前种子未提供跟踪指数代码和动态成分权重，未填充缺失字段。")
    else:
        print("跟踪指数：000685（中证指数官方资料已核验）")
        if index_snapshot.is_complete:
            print("指数成分覆盖：FULL")
            print(f"完整权重日期：{index_snapshot.trade_date}")
            print(f"最新样本日期：{index_snapshot.membership_trade_date}")
            print(f"权重相对最新样本滞后：{index_snapshot.weight_lag_days} 天")
        else:
            print(
                "指数成分覆盖：TOP10_ONLY；官方公开接口仅返回十大权重，"
                "未将其冒充完整 50 只成分股。"
            )
    return 0


def _fund_nav_snapshot(args, engine) -> int:
    if args.fund_code != "020671":
        print(f"仅支持基金 020671，收到：{args.fund_code}")
        return 2
    try:
        observations = fetch_efunds_nav_history(args.fund_code, max_rows=args.max_rows)
        counts = ingest_official_nav_history(observations, engine=engine)
    except Exception as exc:
        print(f"基金净值快照失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"基金代码：{args.fund_code}")
    print(f"来源：EFUNDS_OFFICIAL")
    print(f"最新净值日期：{observations[0].nav_date}")
    print(f"最新单位净值：{observations[0].unit_nav:.4f}")
    print(f"净值行数：{len(observations)}")
    for key, value in counts.items():
        print(f"{key}：{value}")
    return 0


def _fund_nav_report(args, engine) -> int:
    from types import SimpleNamespace

    from tradingagents.extensions.sector_fund.nav_metrics import calculate_fund_nav_metrics

    if args.fund_code != "020671":
        print(f"仅支持基金 020671，收到：{args.fund_code}")
        return 2
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(FundNavObservation)
                .join(Instrument, Instrument.id == FundNavObservation.fund_instrument_id)
                .where(
                    Instrument.local_code == args.fund_code,
                    FundNavObservation.nav_date <= args.analysis_date,
                    FundNavObservation.status == "SUCCESS",
                )
                .order_by(FundNavObservation.nav_date)
            ).all()
            observations = [
                SimpleNamespace(
                    fund_code=args.fund_code,
                    nav_date=row.nav_date,
                    unit_nav=row.unit_nav,
                    cumulative_nav=row.cumulative_nav,
                    daily_change_pct=row.daily_change_pct,
                    source=row.source,
                )
                for row in rows
            ]
        metrics = calculate_fund_nav_metrics(observations, args.analysis_date)
        payload = metrics.to_dict()
        output = Path(args.output) if args.output else Path("reports") / "sector_fund" / (
            f"{args.fund_code}_{args.analysis_date}_nav.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"基金净值报告失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"基金代码：{metrics.fund_code}")
    print(f"净值日期：{metrics.latest_nav_date}")
    print(f"单位净值：{metrics.unit_nav:.4f}")
    print(f"1/3/5/10/20日收益：{metrics.return_1d_pct}/{metrics.return_3d_pct}/{metrics.return_5d_pct}/{metrics.return_10d_pct}/{metrics.return_20d_pct}")
    print(f"20日回撤：{metrics.drawdown_20d_pct}")
    print(f"JSON 保存路径：{output.resolve()}")
    return 0


def _etf_status_snapshot(args, engine) -> int:
    from tradingagents.extensions.sector_fund.etf_status_provider import fetch_etf_status

    if args.etf_code != "589130":
        print(f"当前仅支持目标 ETF 589130，收到：{args.etf_code}")
        return 2
    try:
        snapshot = fetch_etf_status(args.etf_code)
        counts = ingest_etf_status_snapshot(snapshot, engine=engine)
    except Exception as exc:
        print(f"ETF状态快照失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"ETF代码：{snapshot.etf_code}")
    print(f"数据日期：{snapshot.observed_date}")
    print(f"单位净值：{snapshot.unit_nav}")
    print(f"市价：{snapshot.market_price}")
    print(f"IOPV：{snapshot.iopv}")
    print(f"折价率：{snapshot.discount_rate_pct}%")
    print(f"最新份额：{snapshot.shares}")
    print(f"成交额：{snapshot.amount}")
    for key, value in counts.items():
        print(f"{key}：{value}")
    return 0


def _sync_fund_events(args, engine) -> int:
    from tradingagents.extensions.sector_fund.event_store import sync_fund_events

    try:
        result = sync_fund_events(args.fund_code, engine=engine, force=args.force)
    except Exception as exc:
        print(f"基金事件同步失败：{type(exc).__name__}: {exc}")
        return 2
    for key, value in result.items():
        print(f"{key}：{value}")
    return 0


def _list_fund_events(args, engine) -> int:
    from tradingagents.extensions.sector_fund.event_store import load_recent_fund_events

    with Session(engine) as session:
        events = load_recent_fund_events(
            session, args.fund_code, args.analysis_date, days=args.days
        )
        print(f"数据库事件数量：{len(events)}")
        print("说明：此命令只读数据库，不访问网络。")
        for event in events:
            print(
                f"{event.event_date}\t{event.event_type}\t{event.source_level}\t"
                f"{event.title}\t{event.url or ''}"
            )
    return 0


def _run_sector_fund_backtest(args, engine) -> int:
    from tradingagents.extensions.sector_fund.backtest import (
        DEFAULT_LABEL_POLICY,
        persist_backtest_result,
        run_point_in_time_backtest,
    )
    from tradingagents.storage.repository import MarketBarRepository

    if args.fund_code != "020671":
        print(f"仅支持基金 020671，收到：{args.fund_code}")
        return 2
    try:
        with Session(engine) as session:
            repository = MarketBarRepository(session)
            frame_loader = repository.get_latest_daily_bars
            result = run_point_in_time_backtest(
                session,
                fund_code=args.fund_code,
                etf_symbol="589130.SS",
                index_code="000685",
                end_date=args.end_date,
                frame_loader=frame_loader,
                label_policy=DEFAULT_LABEL_POLICY,
                minimum_probability_samples=30,
            )
            persisted = persist_backtest_result(session, result)
        output = Path(args.output) if args.output else Path("reports") / "sector_fund" / (
            f"{args.fund_code}_{args.end_date}_backtest.json"
        )
        if output.exists() and not args.overwrite:
            raise FileExistsError(f"backtest output already exists: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"基金回测失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"回测运行ID：{result.run_id}")
    print(f"样本区间：{result.sample_start_date} 至 {result.sample_end_date}")
    print(f"样本数量：{result.sample_count}")
    print(f"状态：{result.status}")
    print(f"1日概率状态：{result.horizon_1d['probability_status']}")
    print(f"3日概率状态：{result.horizon_3d['probability_status']}")
    print(f"1日Brier：{result.horizon_1d['calibration_error']}")
    print(f"3日Brier：{result.horizon_3d['calibration_error']}")
    print(f"数据库写入：{persisted}")
    print(f"JSON 保存路径：{output.resolve()}")
    return 0


def _sector_market_provider(source: str):
    from tradingagents.extensions.sector_fund.akshare_market_provider import (
        get_akshare_eastmoney_daily_frame,
        get_akshare_sina_daily_frame,
        get_auto_daily_frame,
        get_yfinance_raw_daily_frame,
    )

    return {
        "auto": get_auto_daily_frame,
        "eastmoney": get_akshare_eastmoney_daily_frame,
        "yfinance": get_yfinance_raw_daily_frame,
        "sina": get_akshare_sina_daily_frame,
    }.get(source)


def _sync_sector_market_data(args, engine) -> int:
    """Explicitly cache raw bars; never called by reports or backtests."""
    if args.fund_code != "020671":
        print(f"仅支持基金 020671，收到：{args.fund_code}")
        return 2
    try:
        with Session(engine) as session:
            metadata = session.scalar(
                select(FundMetadataSnapshot)
                .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
                .where(FundMetadataSnapshot.as_of_date <= args.end_date)
                .where(Instrument.local_code == args.fund_code)
                .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
            )
            if metadata is None or not metadata.payload_json:
                raise ValueError("no verified fund metadata snapshot at or before end date")
            identity = json.loads(metadata.payload_json)
            index_code = identity.get("benchmark_index_code")
            etf_code = identity.get("target_etf_code")
            if not index_code or not etf_code:
                raise ValueError("fund metadata lacks target ETF or benchmark index code")
            snapshot = session.scalar(
                select(UniverseSnapshot)
                .join(Universe, Universe.id == UniverseSnapshot.universe_id)
                .where(Universe.code == f"INDEX:{index_code}")
                .where(UniverseSnapshot.as_of_date <= args.end_date)
                .where(UniverseSnapshot.status == "SUCCESS")
                .order_by(UniverseSnapshot.as_of_date.desc(), UniverseSnapshot.id.desc())
            )
            if snapshot is None:
                raise ValueError("no successful universe snapshot at or before end date")
            snapshot_id = snapshot.id
            snapshot_date = str(snapshot.as_of_date)
            constituents = session.scalars(
                select(Instrument.symbol)
                .join(UniverseConstituentWeight, UniverseConstituentWeight.instrument_id == Instrument.id)
                .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
                .order_by(Instrument.symbol)
            ).all()
            symbols = [f"{etf_code}.SS", *constituents]
            provider = _sector_market_provider(args.source)
            mode = "database_only" if args.source == "database" else "database_first"
            rows = []
            for symbol in dict.fromkeys(symbols):
                result = MarketDataService(
                    session,
                    mode=mode,
                    provider=provider,
                    require_requested_start=True,
                    minimum_rows_if_start_missing=60,
                    strict_requested_end=True,
                    require_turnover_amount=True,
                ).daily(symbol, args.start_date, args.end_date)
                rows.append(
                    {
                        "symbol": symbol,
                        "status": result.status,
                        "source": result.source,
                        "provider_name": result.provider_name,
                        "refreshed": result.refreshed,
                        "provider_call_count": result.provider_call_count,
                        "row_count": len(result.data),
                        "first_bar": str(result.first_bar) if result.first_bar else None,
                        "latest_bar": str(result.latest_bar) if result.latest_bar else None,
                        "message": result.message,
                    }
                )
            session.commit()
    except Exception as exc:
        print(f"行情同步失败：{type(exc).__name__}: {exc}")
        return 2

    summary = {
        "fund_code": args.fund_code,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "requested_source": args.source,
        "universe_snapshot_id": snapshot_id,
        "universe_snapshot_date": snapshot_date,
        "symbols": rows,
        "success_count": sum(row["status"] == SUCCESS for row in rows),
        "failure_count": sum(row["status"] != SUCCESS for row in rows),
    }
    output = Path(args.output) if args.output else Path("reports") / "sector_fund" / (
        f"{args.fund_code}_{args.start_date}_{args.end_date}_market_sync.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"同步证券数：{len(rows)}")
    print(f"成功：{summary['success_count']}；失败：{summary['failure_count']}")
    print(f"JSON 保存路径：{output.resolve()}")
    return 0 if summary["failure_count"] == 0 else 2


def _run_sector_fund_metrics(args, engine):
    if args.fund_code != "020671":
        raise ValueError(f"仅支持基金 020671，收到：{args.fund_code}")
    provider = None
    mode = "database_only"
    if args.market_source == "akshare_sina":
        from tradingagents.extensions.sector_fund.akshare_market_provider import (
            get_akshare_sina_daily_frame,
        )

        provider = get_akshare_sina_daily_frame
        mode = "provider_only"
    with Session(engine) as session:
        metadata = session.scalar(
            select(FundMetadataSnapshot)
            .join(Instrument, Instrument.id == FundMetadataSnapshot.fund_instrument_id)
            .where(FundMetadataSnapshot.as_of_date <= args.analysis_date)
            .where(Instrument.local_code == args.fund_code)
            .order_by(FundMetadataSnapshot.as_of_date.desc(), FundMetadataSnapshot.id.desc())
        )
        if metadata is None or not metadata.payload_json:
            raise ValueError("no fund metadata snapshot at or before analysis date")
        identity = json.loads(metadata.payload_json)
        target_code = identity.get("target_etf_code")
        index_code = identity.get("benchmark_index_code")
        if not target_code or not index_code:
            raise ValueError("fund metadata lacks verified target ETF or benchmark index code")
        snapshot = session.scalar(
            select(UniverseSnapshot)
            .join(Universe, Universe.id == UniverseSnapshot.universe_id)
            .where(
                Universe.code == f"INDEX:{index_code}",
                UniverseSnapshot.as_of_date <= args.analysis_date,
                UniverseSnapshot.status == "SUCCESS",
            )
            .order_by(UniverseSnapshot.as_of_date.desc(), UniverseSnapshot.id.desc())
        )
        if snapshot is None:
            raise ValueError("no complete universe snapshot for classification")
        security_codes = session.scalars(
            select(Instrument.local_code)
            .join(
                UniverseConstituentWeight,
                UniverseConstituentWeight.instrument_id == Instrument.id,
            )
            .where(UniverseConstituentWeight.snapshot_id == snapshot.id)
        ).all()
    if args.classification_source == "csindex":
        from tradingagents.extensions.sector_fund.classification import (
            ingest_classification_snapshots,
        )
        from tradingagents.extensions.sector_fund.csindex_industry_provider import (
            fetch_csindex_industry_classifications,
        )

        classifications = fetch_csindex_industry_classifications(security_codes)
        ingest_classification_snapshots(classifications, engine=engine)
    with Session(engine) as session:
        result = SectorFundQuantService(session, mode=mode, provider=provider).analyze(
            fund_code=args.fund_code,
            target_etf_symbol=f"{target_code}.SS",
            index_code=str(index_code),
            analysis_date=args.analysis_date,
        )
    return result


def _generate_sector_fund_metrics(args, engine) -> int:
    try:
        result = _run_sector_fund_metrics(args, engine)
        output = Path(args.output) if args.output else Path("reports") / "sector_fund" / (
            f"{args.fund_code}_{args.analysis_date}_metrics.json"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        print(f"基金量化指标生成失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"基金代码：{result.fund_code}")
    print(f"请求分析日期：{result.requested_analysis_date}")
    print(f"实际行情日期：{result.market_date}")
    print(f"权重快照日期：{result.weight_snapshot_date}")
    print(f"目标 ETF：{result.target_etf_symbol}")
    print(f"板块价格覆盖：{result.sector.price_available_count}/{result.sector.expected_count}")
    print(f"板块成交额覆盖：{result.sector.amount_available_count}/{result.sector.expected_count}")
    print(f"中证行业分类覆盖：{result.sector.csi_classification_coverage_pct:.2f}%")
    print(f"产业链分类覆盖：{result.sector.supply_chain_classification_coverage_pct:.2f}%")
    print(f"板块状态：{result.sector.status}")
    print(f"JSON 保存路径：{output.resolve()}")
    return 0


def _generate_sector_fund_scored_report(args, engine) -> int:
    from dataclasses import replace

    from tradingagents.extensions.sector_fund.fund_context import load_fund_context
    from tradingagents.extensions.sector_fund.scoring import build_scored_report
    from tradingagents.reports.sector_fund_report import save_sector_fund_report

    try:
        metrics = _run_sector_fund_metrics(args, engine)
        with Session(engine) as session:
            context = load_fund_context(
                session,
                fund_code=metrics.fund_code,
                etf_code=metrics.target_etf_symbol.split(".")[0],
                analysis_date=metrics.requested_analysis_date,
                market_date=metrics.market_date,
            )
        report = build_scored_report(metrics, context)
        paths = save_sector_fund_report(report, args.output, overwrite=args.overwrite)
    except Exception as exc:
        print(f"基金评分报告生成失败：{type(exc).__name__}: {exc}")
        return 2
    print(f"基金代码：{metrics.fund_code}")
    print(f"实际行情日期：{metrics.market_date}")
    core_text = f"{report.core_trend.score:.2f}" if report.core_trend.score is not None else "数据不足"
    short_text = f"{report.short_term.score:.2f}" if report.short_term.score is not None else "数据不足"
    print(f"核心趋势分：{core_text}（{report.core_trend.label}）")
    print(f"短线强弱分：{short_text}（{report.short_term.label}）")
    print(f"数据质量置信度：{report.data_confidence.confidence_pct:.2f}（不代表收益预测概率）")
    print(f"冲突数量：{len(report.conflicts)}")
    print("历史概率：NOT_AVAILABLE（等待第六阶段回测）")
    for name, path in paths.items():
        print(f"{name}：{path.resolve()}")
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
    if args.command == "fund-baseline-snapshot":
        return _fund_baseline_snapshot(args, engine)
    if args.command == "fund-nav-snapshot":
        return _fund_nav_snapshot(args, engine)
    if args.command == "fund-nav-report":
        return _fund_nav_report(args, engine)
    if args.command == "etf-status-snapshot":
        return _etf_status_snapshot(args, engine)
    if args.command == "sync-fund-events":
        return _sync_fund_events(args, engine)
    if args.command == "list-fund-events":
        return _list_fund_events(args, engine)
    if args.command == "run-sector-fund-backtest":
        return _run_sector_fund_backtest(args, engine)
    if args.command == "sync-sector-market-data":
        return _sync_sector_market_data(args, engine)
    if args.command == "generate-sector-fund-metrics":
        return _generate_sector_fund_metrics(args, engine)
    if args.command == "generate-sector-fund-report":
        return _generate_sector_fund_scored_report(args, engine)
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
