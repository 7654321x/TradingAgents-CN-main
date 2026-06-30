from tradingagents.sector_fund.logging_utils import mask_secret, sanitize_message


def test_mask_secret_keeps_only_safe_shape():
    assert mask_secret("sk-abcdefghijklmnopqrstuvwxyz") == "sk-****wxyz"
    assert mask_secret("abcdef") == "****"


def test_sanitize_message_masks_known_secret_names():
    text = sanitize_message("DEEPSEEK_API_KEY=sk-abcdefghijklmnopqrstuvwxyz MONGODB_CONNECTION_STRING=mongodb://user:pass@host/db")

    assert "abcdefghijklmnopqrstuvwxyz" not in text
    assert "user:pass@host" not in text
    assert "DEEPSEEK_API_KEY=sk-****wxyz" in text
