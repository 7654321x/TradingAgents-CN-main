from tradingagents.sector_fund.logging_utils import sanitize_url


def test_sanitize_url_masks_sensitive_query_params():
    url = sanitize_url("https://example.com/api?token=abc123&rt=999&code=512480&api_key=secret")

    assert "token=%2A%2A%2A%2A" in url
    assert "rt=%2A%2A%2A%2A" in url
    assert "api_key=%2A%2A%2A%2A" in url
    assert "code=512480" in url
    assert "abc123" not in url
    assert "secret" not in url
