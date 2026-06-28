import argparse
import sys


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
    from tradingagents.sector_fund.data_probe import run_data_probe

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
    print("data_probe 数据链路诊断已完成")
    print(f"Core coverage: {coverage['core_coverage_rate']}% ({coverage['core_matched_count']}/{coverage['core_total_count']})")
    print(f"All coverage: {coverage['all_coverage_rate']}% ({coverage['all_matched_count']}/{coverage['all_total_count']})")
    print(f"Debug raw目录: {result['raw_dir']}")
    print(f"明细JSON: {result['summary_path']}")
    print(f"诊断报告: {result['report_path']}")
    print(f"数据摘要: {result['audit_summary_path']}")
    print(f"审计CSV: {result['audit_csv_path']}")
    print(f"审计JSON: {result['audit_json_path']}")


def run_data_probe_view_from_args(args):
    from tradingagents.sector_fund.data_audit import load_latest_audit, render_terminal_summary

    if not args.latest:
        print("请使用 --latest 查看最近一次 data_probe 审计摘要。")
        return
    payload = load_latest_audit()
    print(render_terminal_summary(payload.get("audit_rows", []), payload.get("coverage", {}), payload.get("cross_validation", [])))


def run_fund_enrich_from_args(args):
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


def build_parser():
    parser = argparse.ArgumentParser(description="TradingAgents-CN entry point")
    parser.add_argument(
        "--mode",
        choices=["stock_demo", "sector_fund", "sector_fund_healthcheck", "fund_intraday", "data_probe", "data_probe_view", "fund_enrich"],
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
    run_stock_demo()


if __name__ == "__main__":
    main()
