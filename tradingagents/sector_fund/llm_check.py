from __future__ import annotations

import os
from typing import Any, Dict

import requests

from .logging_utils import get_sector_logger
from .llm_provider_resolver import PROVIDERS, first_key, load_env, resolve_provider


def run_llm_check(view: bool = False, timeout: int = 20) -> Dict[str, Any]:
    logger = get_sector_logger("llm")
    load_env()
    resolved = resolve_provider()
    configured = os.environ.get("FUND_AGENT_REPORT_PROVIDER", "").strip().lower()
    logger.info(
        "🤖 [LLMCheck] 当前provider | provider=%s model=%s source=%s",
        resolved["provider"],
        resolved["model"],
        resolved["provider_source"],
    )
    result = {
        "configured_provider": configured or "",
        "default_provider": resolved["provider"],
        "provider_source": resolved["provider_source"],
        "model": resolved["model"],
        "providers": {name: check_provider(name, timeout=timeout) for name in PROVIDERS},
    }
    if view:
        print(render_llm_check(result))
    for name, item in result.get("providers", {}).items():
        status = item.get("api_status")
        model = item.get("model")
        if status == "valid":
            logger.info("✅ [LLMCheck] key有效 | provider=%s model=%s", name, model)
        elif status == "invalid_api_key":
            logger.error("❌ [LLMCheck] key无效 | provider=%s status=invalid_api_key", name)
        elif status == "missing":
            logger.warning("⚠️ [LLMCheck] key缺失 | provider=%s", name)
        else:
            logger.warning("⚠️ [LLMCheck] provider检查未通过 | provider=%s status=%s", name, status)
    return result


def check_provider(provider: str, timeout: int = 20) -> Dict[str, Any]:
    meta = PROVIDERS[provider]
    key_name, key = first_key(meta["keys"])
    model = os.environ.get("FUND_AGENT_REPORT_MODEL") or os.environ.get(f"{provider.upper()}_MODEL") or meta["model"]
    base_url = os.environ.get(f"{provider.upper()}_BASE_URL") or meta["base_url"]
    if not key:
        return {"key_status": "missing", "api_status": "missing", "key_name": meta["keys"][0], "model": model, "base_url": base_url}
    try:
        response = requests.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": 0,
                "max_tokens": 4,
            },
            timeout=timeout,
        )
        if response.status_code in {401, 403}:
            return {"key_status": "present", "api_status": "invalid_api_key", "key_name": key_name, "model": model, "base_url": base_url}
        if response.status_code >= 400:
            status = "invalid_api_key" if "invalid_api_key" in response.text or "Incorrect API key" in response.text else "request_failed"
            return {"key_status": "present", "api_status": status, "key_name": key_name, "model": model, "base_url": base_url, "status_code": response.status_code}
        return {"key_status": "present", "api_status": "valid", "key_name": key_name, "model": model, "base_url": base_url}
    except Exception:
        return {"key_status": "present", "api_status": "request_failed", "key_name": key_name, "model": model, "base_url": base_url}


def render_llm_check(result: Dict[str, Any]) -> str:
    lines = [
        "llm_check 摘要",
        f"FUND_AGENT_REPORT_PROVIDER: {result.get('configured_provider') or '(未设置)'}",
        f"当前默认 provider: {result.get('default_provider')}",
        "| Provider | Key | API | Key变量 | Model |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, item in result.get("providers", {}).items():
        lines.append(
            f"| {name} | {item.get('key_status')} | {item.get('api_status')} | {item.get('key_name')} | {item.get('model')} |"
        )
    lines.append("提示：不会打印完整 key；invalid_api_key 请更新 .env 后重试。")
    return "\n".join(lines)
