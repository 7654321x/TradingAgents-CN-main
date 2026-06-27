import argparse


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


def run_sector_fund_from_args(args):
    from tradingagents.sector_fund.runner import run_sector_fund_analysis

    result = run_sector_fund_analysis(
        config_path=args.config,
        analysis_date=args.date,
        use_mock=args.mock,
        use_firecrawl=args.firecrawl,
        output_dir=args.output_dir,
    )
    score = result["score"]
    print("个人半导体/存储板块报告已生成")
    print(f"半导体评分: {score['semiconductor_score']}")
    print(f"存储芯片评分: {score['storage_score']}")
    print(f"状态: {score['status']} / 风险: {score['risk_level']}")
    print(f"建议: {score['suggestion']}")
    print(f"报告路径: {result['output_path']}")


def build_parser():
    parser = argparse.ArgumentParser(description="TradingAgents-CN entry point")
    parser.add_argument("--mode", choices=["stock_demo", "sector_fund"], default="stock_demo")
    parser.add_argument("--config", default="config/personal_semiconductor.yaml")
    parser.add_argument("--date", default=None, help="分析日期，格式 YYYY-MM-DD")
    parser.add_argument("--output-dir", default="reports/sector_fund")
    parser.add_argument("--mock", dest="mock", action="store_true", default=True, help="使用mock数据")
    parser.add_argument("--real-data", dest="mock", action="store_false", help="尝试真实网页raw_text采集")
    parser.add_argument("--firecrawl", action="store_true", help="真实数据模式下使用可选Firecrawl")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if args.mode == "sector_fund":
        run_sector_fund_from_args(args)
        return
    run_stock_demo()


if __name__ == "__main__":
    main()
