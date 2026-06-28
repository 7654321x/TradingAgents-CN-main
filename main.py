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
    print("python main.py --mode sector_fund --config config/personal_semiconductor.yaml --mock --save-history")
    print("python main.py --mode sector_fund --config config/personal_semiconductor.yaml --real-data --save-history")
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


def build_parser():
    parser = argparse.ArgumentParser(description="TradingAgents-CN entry point")
    parser.add_argument("--mode", choices=["stock_demo", "sector_fund", "sector_fund_healthcheck"], default="stock_demo")
    parser.add_argument("--config", default="config/personal_semiconductor.yaml")
    parser.add_argument("--date", default=None, help="分析日期，格式 YYYY-MM-DD")
    parser.add_argument("--output-dir", default="reports/sector_fund")
    parser.add_argument("--mock", dest="mock", action="store_true", default=True, help="使用mock数据")
    parser.add_argument("--real-data", dest="mock", action="store_false", help="尝试真实网页raw_text采集")
    parser.add_argument("--firecrawl", action="store_true", help="真实数据模式下使用可选Firecrawl")
    parser.add_argument("--save-history", dest="save_history", action="store_true", default=True, help="生成报告后保存评分历史")
    parser.add_argument("--no-save-history", dest="save_history", action="store_false", help="不保存评分历史")
    parser.add_argument("--history-days", type=int, default=5, help="报告中展示最近多少天变化")
    parser.add_argument("--min-real-coverage", type=float, default=0.4, help="真实覆盖率低于该阈值时降低建议强度；0.4 表示 40%%")
    parser.add_argument("--open-report", action="store_true", help="生成后尝试打开报告文件")
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
    run_stock_demo()


if __name__ == "__main__":
    main()
