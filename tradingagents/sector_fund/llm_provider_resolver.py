from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Tuple


PROVIDERS = {
    "dashscope": {
        "keys": ["DASHSCOPE_API_KEY", "DASH_SCOPE_API_KEY", "QWEN_API_KEY"],
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
    },
    "deepseek": {
        "keys": ["DEEPSEEK_API_KEY"],
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
    },
    "openai": {
        "keys": ["OPENAI_API_KEY"],
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
    },
}


def load_env(path: str | Path = ".env") -> None:
    env_path = Path(path)
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    normalize_provider_env()


def normalize_provider_env() -> None:
    aliases = {
        "DASHSCOPE_API_KEY": ["DASH_SCOPE_API_KEY", "QWEN_API_KEY"],
    }
    for canonical, names in aliases.items():
        if os.environ.get(canonical):
            continue
        for name in names:
            if os.environ.get(name):
                os.environ[canonical] = os.environ[name]
                break


def resolve_provider(cli_provider: str | None = None) -> Dict[str, str]:
    load_env()
    cli = (cli_provider or "").strip().lower()
    env_provider = os.environ.get("FUND_AGENT_REPORT_PROVIDER", "").strip().lower()
    if cli in PROVIDERS:
        provider = cli
        source = "cli"
    elif env_provider in PROVIDERS:
        provider = env_provider
        source = "env"
    else:
        provider = default_provider()
        source = "default"
    meta = PROVIDERS[provider]
    model = os.environ.get("FUND_AGENT_REPORT_MODEL") or os.environ.get(f"{provider.upper()}_MODEL") or meta["model"]
    base_url = os.environ.get(f"{provider.upper()}_BASE_URL") or meta["base_url"]
    key_name, _ = first_key(meta["keys"])
    return {
        "provider": provider,
        "provider_source": source,
        "model": model,
        "base_url": base_url,
        "key_name": key_name,
    }


def default_provider() -> str:
    if first_key(PROVIDERS["dashscope"]["keys"])[1]:
        return "dashscope"
    if first_key(PROVIDERS["deepseek"]["keys"])[1]:
        return "deepseek"
    return "openai"


def first_key(names: list[str]) -> Tuple[str, str]:
    for name in names:
        value = os.environ.get(name)
        if value:
            return name, value
    return names[0], ""
