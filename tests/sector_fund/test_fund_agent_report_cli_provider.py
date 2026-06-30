import main


def test_fund_agent_report_accepts_llm_provider_cli_arg():
    parser = main.build_parser()

    args = parser.parse_args(["--mode", "fund_agent_report", "--llm-provider", "deepseek"])

    assert args.mode == "fund_agent_report"
    assert args.llm_provider == "deepseek"
