from tradingagents.llm_clients.model_catalog import get_model_options
from tradingagents.llm_clients.validators import validate_model


def test_gpt_56_sol_is_selectable_and_valid() -> None:
    assert ("GPT-5.6 Sol - Flagship complex reasoning and coding", "gpt-5.6-sol") in get_model_options("openai", "deep")
    assert validate_model("openai", "gpt-5.6-sol") is True
