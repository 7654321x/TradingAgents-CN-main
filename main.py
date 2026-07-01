import argparse
import sys


LOGGED_MODES = {
    "data_probe",
    "data_probe_view",
    "fund_enrich",
    "fund_sql_list",
    "fund_context_report",
    "fund_agent_report",
    "llm_check",
}


def run_stock_demo():
    from tradingagents.default_config import DEFAULT_CONFIG
    from tradingagents.graph.trading_graph import TradingAgentsGraph

    config = DEFAULT_CONFIG.copy()
    config["llm_provider"] = "google"
    config["backend_url"] = "https://generativelanguage.googleapis.com/v1beta"
    config["deep_think_llm"] = "gemini-2.0-flash"
    config["quick_think_llm"] = "gemini-2.0-flash"
    config["max_debate_rounds"] = 1
    config["online_tools"] = True

    ta = TradingAgentsGraph(debug=True, config=config)
    _, decision = ta.propagate("NVDA", "2024-05-10")
    print(decision)


def print_usage_examples(parser):
    parser.print_help()
    print("\n常用命令示例:")
    print("python main.py --mode data_probe --config config/personal_semiconductor.yaml")
    print("python main.py --mode sector_fund --config config/personal_semiconductor.yaml --mock --save-history")
    print("python main.py --mode sector_fund --config config/personal_semiconductor.yaml --real-data --save-history")
    print("python main.py --mode fund_intraday --config config/personal_fund_portfolio.yaml --decision-time 1445 --use-sql --refresh-data")
    print("python main.py --mode fund_sql_list --config config/personal_fund_portfolio.yaml --decision-time 1445 --view")
    print("python main.py --mode fund_context_report --config config/personal_fund_portfolio.yaml --decision-time 1445 --view")
    print("python main.py --mode fund_agent_report --config config/personal_fund_portfolio.yaml --decision-time 1445 --refresh-market-quotes --refresh-holding-quotes --analyze-holdings --top-n 5 --view --unique-report-name")
    print("python main.py --mode analyze_holdings --config config/personal_fund_portfolio.yaml --decision-time 1445 --view")
    print("python main.py --mode llm_check")
    print("python main.py --mode stock_demo")


def run_sector_fund_from_args(args):
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    result = run_sector_fund_analysis(
        config_path=args.config,
        analysis_date=args.date,
        use_mock=args.mock,
        use_firecrawl=args.firecrawl,
        output_dir=args.output_dir,
        save_history=args.save_history,
        history_days=args.history_days,
        min_real_coverage=args.min_real_coverage,
        open_report=args.open_report,
    )
    score = result["score"]
    print("个人半导体/存储板块报告已生成")
    print(f"半导体评分: {score['semiconductor_score']}")
    print(f"存储芯片评分: {score['storage_score']}")
    print(f"状态: {score['status']} / 风险: {score['risk_level']}")
    print(f"建议: {score['suggestion']}")
    print(f"报告路径: {result['output_path']}")


def run_sector_fund_healthcheck_from_args(args):
    from tradingagents.sector_fund.healthcheck import format_healthcheck_report, run_sector_fund_healthcheck

    result = run_sector_fund_healthcheck(config_path=args.config)
    print(format_healthcheck_report(result))


def run_fund_intraday_from_args(args):
    from tradingagents.sector_fund.fund_intraday_runner import run_fund_intraday

    output_dir = "reports/fund_intraday" if args.output_dir == "reports/sector_fund" else args.output_dir
    result = run_fund_intraday(
        config_path=args.config,
        decision_time=args.decision_time,
        use_sql=args.use_sql,
        db_path=args.db_path,
        refresh_data=args.refresh_data,
        baostock_only=args.baostock_only,
        no_web=args.no_web,
        save_snapshot=args.save_snapshot,
        snapshot_id=args.snapshot_id,
        output_dir=output_dir,
    )
    snapshot = result["snapshot"]
    print("基金盘中数据上下文已生成")
    print(f"决策时点: {snapshot['decision_time']}")
    print(f"数据日期: {snapshot['trade_date']}")
    print(f"核心覆盖率: {snapshot.get('core_coverage_rate', 0):.2f}%")
    print(f"SQLite: {result['db_path']}")
    print(f"报告路径: {result['output_path']}")


def run_data_probe_from_args(args):
    log_context = setup_logging_from_args(args)
    from tradingagents.sector_fund.data_probe import run_data_probe
    from tradingagents.sector_fund.logging_utils import get_sector_logger

    result = run_data_probe(
        config_path=args.config,
        output_dir=args.output_dir,
        db_path=args.db_path,
        baostock_only=args.baostock_only,
        use_akshare=args.akshare,
        no_web=args.no_web,
        view=args.view,
    )
    coverage = result["coverage"]
    get_sector_logger("summary").info(
        "📊 [Summary] 运行完成 | mode=data_probe run_id=%s core=%s%%(%s/%s) all=%s%%(%s/%s)",
        log_context.get("run_id"),
        coverage["core_coverage_rate"],
        coverage["core_matched_count"],
        coverage["core_total_count"],
        coverage["all_coverage_rate"],
        coverage["all_matched_count"],
        coverage["all_total_count"],
    )
    print_summary_block(
        "data_probe",
        log_context,
        args.config,
        coverage,
        {
            "summary": result["audit_summary_path"],
            "report": result["report_path"],
            "audit_csv": result["audit_csv_path"],
            "audit_json": result["audit_json_path"],
        },
    )


def run_data_probe_view_from_args(args):
    setup_logging_from_args(args)
    from tradingagents.sector_fund.data_audit import load_latest_audit, render_terminal_summary

    if not args.latest:
        print("请使用 --latest 查看最近一次 data_probe 审计摘要。")
        return
    payload = load_latest_audit()
    print(render_terminal_summary(payload.get("audit_rows", []), payload.get("coverage", {}), payload.get("cross_validation", [])))


def run_fund_enrich_from_args(args):
    setup_logging_from_args(args)
    from tradingagents.sector_fund.fund_enrich import run_fund_enrich

    result = run_fund_enrich(
        config_path=args.config,
        output_dir=args.output_dir,
        db_path=args.db_path,
        use_akshare=args.akshare,
        use_firecrawl=args.firecrawl,
        fund_code=args.fund_code,
        write_enriched_config=args.write_enriched_config,
        view=args.view,
    )
    if not args.view:
        print(result["terminal_summary"])
    print(f"Enriched config: {result['enriched_config_path']}")
    print(f"补全报告: {result['report_path']}")
    print(f"明细JSON: {result['records_path']}")
    print(f"SQL: {result['sql_status']}")


def run_fund_sql_list_from_args(args):
    setup_logging_from_args(args)
    from tradingagents.sector_fund.fund_sql_list import run_fund_sql_list

    output_dir = "reports/fund_intraday" if args.output_dir == "reports/sector_fund" else args.output_dir
    result = run_fund_sql_list(
        config_path=args.config,
        db_path=args.db_path,
        decision_time=args.decision_time,
        output_dir=output_dir,
        limit_per_table=args.limit_per_table,
        view=args.view,
    )
    print("SQL 全字段列表已生成")
    print(f"字段数: {result['field_count']}")
    print(f"表数量: {result['table_count']}")
    print(f"SQLite: {result['db_path']}")
    print(f"报告路径: {result['report_path']}")
    print(f"JSON路径: {result['json_path']}")


def run_fund_context_report_from_args(args):
    setup_logging_from_args(args)
    from tradingagents.sector_fund.fund_context_report import run_fund_context_report

    output_dir = "reports/fund_intraday" if args.output_dir == "reports/sector_fund" else args.output_dir
    result = run_fund_context_report(
        config_path=args.config,
        db_path=args.db_path,
        decision_time=args.decision_time,
        output_dir=output_dir,
        view=args.view,
    )
    context = result["context"]
    print("基金盘中上下文报告已生成")
    print(f"基金数: {len(context.get('funds', {}))}")
    print(f"证券数: {len(context.get('securities', {}))}")
    print(f"板块数: {len(context.get('sectors', {}))}")
    print(f"报告路径: {result['report_path']}")
    print(f"JSON路径: {result['json_path']}")


def run_fund_agent_report_from_args(args):
    log_context = setup_logging_from_args(args)
    from tradingagents.sector_fund.fund_agent_report import run_fund_agent_report
    from tradingagents.sector_fund.logging_utils import get_sector_logger

    output_dir = "reports/fund_intraday" if args.output_dir == "reports/sector_fund" else args.output_dir
    result = run_fund_agent_report(
        config_path=args.config,
        db_path=args.db_path,
        decision_time=args.decision_time,
        output_dir=output_dir,
        use_llm=args.llm,
        view=args.view,
        refresh_holding_quotes=args.refresh_holding_quotes or args.refresh_data,
        refresh_market_quotes_enabled=args.refresh_market_quotes,
        analyze_holdings=args.analyze_holdings,
        top_n=args.top_n,
        llm_provider=args.llm_provider,
        unique_report_name=args.unique_report_name,
        include_sql_debug=args.include_sql_debug,
    )
    get_sector_logger("summary").info(
        "📊 [Summary] 运行完成 | mode=fund_agent_report run_id=%s llm=%s report=%s",
        log_context.get("run_id"),
        result["llm_status"].get("status"),
        result["report_path"],
    )
    print("======== sector_fund summary ========")
    print("mode: fund_agent_report")
    print(f"run_id: {log_context.get('run_id')}")
    print(f"config: {args.config}")
    print(f"llm_status: {result['llm_status'].get('status')}")
    print(f"llm_provider: {result['llm_status'].get('provider')}")
    print(f"provider_source: {result['llm_status'].get('provider_source')}")
    quality = result.get("agent_report_core_coverage") or {}
    if quality:
        print(f"agent_report_core_coverage: {quality.get('agent_report_core_coverage', 0.0):.2f}%")
        print("coverage_by_group:")
        for name in ("fund", "etf", "index", "sector", "holding_stock", "portfolio"):
            group = (quality.get("groups") or {}).get(name) or {}
            print(f"{name}: {group.get('coverage', 0.0):.2f}%")
    print(f"old_data_source_run_excluded: {result.get('old_data_source_run_excluded', 0)}")
    print(f"sql_debug_included: {str(bool(result.get('sql_debug_included'))).lower()}")
    if result["llm_status"].get("error_reason"):
        print(f"llm_error: {result['llm_status'].get('error_reason')}")
    print("reports:")
    print(f"report: {result['report_path']}")
    print(f"debug_report: {result['debug_report_path']}")
    print(f"context: {result['context_path']}")
    if result.get("holding_refresh"):
        write_result = result["holding_refresh"].get("write_result", {})
        print(f"holding_stock_count: {result['holding_refresh'].get('stock_count', 0)}")
        print(f"security_quote_snapshot_rows: {write_result.get('security_quote_snapshot_rows', 0)}")
        print(f"field_source_rows: {write_result.get('field_source_rows', 0)}")
        print(f"data_source_run_rows: {write_result.get('data_source_run_rows', 0)}")
        summary = result["holding_refresh"].get("summary", {})
        if summary:
            print(f"holding_stock_success: {summary.get('quote_success', 0)}/{summary.get('total', result['holding_refresh'].get('stock_count', 0))}")
    if result.get("market_refresh"):
        market = result["market_refresh"]
        summary = market.get("summary", {})
        write_result = market.get("write_result", {})
        print(f"market_quote_count: {market.get('market_quote_count', 0)}")
        print(f"market_etf_success: {summary.get('etf_success', 0)}/{summary.get('etf_total', 0)}")
        print(f"market_index_success: {summary.get('index_success', 0)}/{summary.get('index_total', 0)}")
        print(f"market_sector_success: {summary.get('sector_success', 0)}/{summary.get('sector_total', 0)}")
        print(f"market_quote_snapshot_rows: {write_result.get('security_quote_snapshot_rows', 0)}")
    print("logs:")
    print(f"text: {log_context.get('log_path')}")
    print("================================================================")


def run_analyze_holdings_from_args(args):
    from tradingagents.sector_fund.analyze_holdings import run_analyze_holdings

    output_dir = "reports/fund_intraday" if args.output_dir == "reports/sector_fund" else args.output_dir
    result = run_analyze_holdings(
        config_path=args.config,
        db_path=args.db_path,
        decision_time=args.decision_time,
        output_dir=output_dir,
        view=args.view,
    )
    summary = result["analysis"]["summary"]
    print("持仓股票深度数据分析已生成")
    print(f"持仓行数: {summary.get('holding_row_count', 0)}")
    print(f"去重股票数: {summary.get('unique_stock_count', 0)}")
    print(f"缺失字段数: {summary.get('missing_field_count', 0)}")
    print(f"报告路径: {result['report_path']}")
    print(f"JSON路径: {result['json_path']}")


def run_llm_check_from_args(args):
    log_context = setup_logging_from_args(args)
    from tradingagents.sector_fund.llm_check import run_llm_check
    from tradingagents.sector_fund.logging_utils import get_sector_logger

    result = run_llm_check(view=True)
    invalid = [name for name, item in result.get("providers", {}).items() if item.get("api_status") == "invalid_api_key"]
    if invalid:
        get_sector_logger("llm").warning("⚠️ [LLMCheck] 无效key | providers=%s", ",".join(invalid))
    get_sector_logger("summary").info("📊 [Summary] 运行完成 | mode=llm_check run_id=%s", log_context.get("run_id"))
    print("======== sector_fund summary ========")
    print("mode: llm_check")
    print(f"run_id: {log_context.get('run_id')}")
    print(f"default_provider: {result.get('default_provider')}")
    print("logs:")
    print(f"text: {log_context.get('log_path')}")
    print("================================================================")


def setup_logging_from_args(args):
    if getattr(args, "mode", "") not in LOGGED_MODES:
        return {}
    import logging

    if not getattr(args, "verbose", False):
        logging.getLogger("agents").setLevel(logging.WARNING)
    from tradingagents.sector_fund.logging_utils import setup_sector_fund_logging

    return setup_sector_fund_logging(
        mode=args.mode,
        log_level=args.log_level,
        verbose=args.verbose,
        quiet=args.quiet,
        log_file=args.log_file,
    )


def print_summary_block(mode, log_context, config, coverage, reports):
    print("======== sector_fund summary ========")
    print(f"mode: {mode}")
    print(f"run_id: {log_context.get('run_id')}")
    print(f"config: {config}")
    print(f"core_coverage: {coverage['core_coverage_rate']}% ({coverage['core_matched_count']}/{coverage['core_total_count']})")
    print(f"all_coverage: {coverage['all_coverage_rate']}% ({coverage['all_matched_count']}/{coverage['all_total_count']})")
    print("reports:")
    for key, value in reports.items():
        print(f"{key}: {value}")
    print("logs:")
    print(f"text: {log_context.get('log_path')}")
    print("================================================================")


def build_parser():
    parser = argparse.ArgumentParser(description="TradingAgents-CN entry point")
    parser.add_argument(
        "--mode",
        choices=[
            "stock_demo",
            "sector_fund",
            "sector_fund_healthcheck",
            "fund_intraday",
            "data_probe",
            "data_probe_view",
            "fund_enrich",
            "fund_sql_list",
            "fund_context_report",
            "fund_agent_report",
            "analyze_holdings",
            "llm_check",
        ],
        default="stock_demo",
    )
    parser.add_argument("--config", default="config/personal_semiconductor.yaml")
    parser.add_argument("--date", default=None, help="分析日期，格式 YYYY-MM-DD")
    parser.add_argument("--output-dir", default="reports/sector_fund")
    parser.add_argument("--mock", dest="mock", action="store_true", default=True, help="使用mock数据")
    parser.add_argument("--real-data", dest="mock", action="store_false", help="尝试真实网页raw_text采集")
    parser.add_argument("--firecrawl", action="store_true", help="真实数据模式下使用可选Firecrawl")
    parser.add_argument("--no-firecrawl", dest="firecrawl", action="store_false", help="禁用Firecrawl补充")
    parser.add_argument("--save-history", dest="save_history", action="store_true", default=True, help="生成报告后保存评分历史")
    parser.add_argument("--no-save-history", dest="save_history", action="store_false", help="不保存评分历史")
    parser.add_argument("--history-days", type=int, default=5, help="报告中展示最近多少天变化")
    parser.add_argument("--min-real-coverage", type=float, default=0.4, help="真实覆盖率低于该阈值时降低建议强度；0.4 表示 40%%")
    parser.add_argument("--open-report", action="store_true", help="生成后尝试打开报告文件")
    parser.add_argument("--decision-time", choices=["1000", "1445", "night"], default="1445", help="fund_intraday 决策时点")
    parser.add_argument("--use-sql", action="store_true", help="fund_intraday 使用SQLite保存/读取快照")
    parser.add_argument("--db-path", default="data/fund_assistant.sqlite3", help="fund_intraday SQLite路径")
    parser.add_argument("--refresh-data", action="store_true", help="fund_intraday 刷新本地数据快照")
    parser.add_argument("--baostock-only", action="store_true", help="fund_intraday 仅使用Baostock数据源")
    parser.add_argument("--akshare", dest="akshare", action="store_true", default=None, help="data_probe 启用AKShare结构化补充")
    parser.add_argument("--no-akshare", dest="akshare", action="store_false", help="data_probe 禁用AKShare结构化补充")
    parser.add_argument("--no-web", action="store_true", help="fund_intraday 禁用网页/Firecrawl补充")
    parser.add_argument("--save-snapshot", action="store_true", help="fund_intraday 保存本次快照")
    parser.add_argument("--snapshot-id", type=int, default=None, help="fund_intraday 从SQLite读取指定快照")
    parser.add_argument("--view", action="store_true", help="data_probe 完成后在终端显示核心审计摘要")
    parser.add_argument("--latest", action="store_true", help="data_probe_view 查看最近一次审计结果")
    parser.add_argument("--fund-code", default=None, help="fund_enrich 只补全单只基金")
    parser.add_argument("--write-enriched-config", action="store_true", help="确认写出 generated enriched config；不会覆盖原始config")
    parser.add_argument("--limit-per-table", type=int, default=200, help="fund_sql_list 每张表最多读取多少行")
    parser.add_argument("--no-llm", dest="llm", action="store_false", default=True, help="fund_agent_report 只生成上下文，不调用LLM")
    parser.add_argument("--refresh-holding-quotes", action="store_true", help="fund_agent_report 先刷新主动基金持仓股票行情和MA")
    parser.add_argument("--refresh-market-quotes", action="store_true", help="fund_agent_report 先刷新ETF/指数/板块盘中行情")
    parser.add_argument("--analyze-holdings", action="store_true", help="fund_agent_report 在prompt和fallback报告中加入持仓股票分析摘要")
    parser.add_argument("--top-n", type=int, default=10, help="持仓股票刷新/分析最多处理前N只")
    parser.add_argument("--llm-provider", choices=["dashscope", "deepseek", "openai"], default=None, help="fund_agent_report LLM提供商，优先级高于 FUND_AGENT_REPORT_PROVIDER")
    parser.add_argument("--unique-report-name", action="store_true", help="fund_agent_report 输出带run_id时间戳的报告文件名，避免覆盖旧报告")
    parser.add_argument("--include-sql-debug", action="store_true", help="fund_agent_report 在正式报告末尾附加 SQL 输入字段列表")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="sector_fund扩展模式日志级别")
    parser.add_argument("--verbose", action="store_true", help="显示更详细日志，包括部分上游INFO")
    parser.add_argument("--quiet", action="store_true", help="不在终端输出日志，仅保留摘要/文件")
    parser.add_argument("--log-file", dest="log_file", action="store_true", default=True, help="写入统一日志文件")
    parser.add_argument("--no-log-file", dest="log_file", action="store_false", help="不写入统一日志文件")
    return parser


def main():
    parser = build_parser()
    if len(sys.argv) == 1:
        print_usage_examples(parser)
        return
    args = parser.parse_args()
    if args.mode == "sector_fund":
        run_sector_fund_from_args(args)
        return
    if args.mode == "sector_fund_healthcheck":
        run_sector_fund_healthcheck_from_args(args)
        return
    if args.mode == "fund_intraday":
        run_fund_intraday_from_args(args)
        return
    if args.mode == "data_probe":
        run_data_probe_from_args(args)
        return
    if args.mode == "data_probe_view":
        run_data_probe_view_from_args(args)
        return
    if args.mode == "fund_enrich":
        run_fund_enrich_from_args(args)
        return
    if args.mode == "fund_sql_list":
        run_fund_sql_list_from_args(args)
        return
    if args.mode == "fund_context_report":
        run_fund_context_report_from_args(args)
        return
    if args.mode == "fund_agent_report":
        run_fund_agent_report_from_args(args)
        return
    if args.mode == "analyze_holdings":
        run_analyze_holdings_from_args(args)
        return
    if args.mode == "llm_check":
        run_llm_check_from_args(args)
        return
    run_stock_demo()


if __name__ == "__main__":
    main()
