import inspect
from pathlib import Path

from tradingagents.sector_fund import data_probe


def test_data_probe_does_not_call_agent_or_graph_logic():
    source = inspect.getsource(data_probe)

    assert "from tradingagents.graph" not in source
    assert "TradingAgentsGraph(" not in source
    assert "propagate(" not in source
    assert "create_trader" not in source
    assert "create_risk_manager" not in source
    assert "create_bull_researcher" not in source
    assert "create_bear_researcher" not in source


def test_graph_core_does_not_import_data_probe():
    graph_path = Path("tradingagents/graph/trading_graph.py")
    source = graph_path.read_text(encoding="utf-8")

    assert "data_probe" not in source
    assert "sector_fund.data_probe" not in source
