from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..upstream import dashboard_request

router = APIRouter()


# Static catalog of API-key LLM providers hermes supports (non-OAuth).
# Each entry groups the env vars hermes exposes via /api/env into a
# single user-facing provider. Keep in sync with hermes HERMES_OVERLAYS
# and provider-category env entries.
_PROVIDERS: list[dict[str, Any]] = [
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "api_key_env": "OPENROUTER_API_KEY",
        "base_url_env": "OPENROUTER_BASE_URL",
        "docs_url": "https://openrouter.ai/keys",
    },
    {
        "id": "google",
        "name": "Google AI Studio (Gemini)",
        "api_key_env": "GOOGLE_API_KEY",
        "api_key_env_aliases": ["GEMINI_API_KEY"],
        "base_url_env": "GEMINI_BASE_URL",
        "docs_url": "https://aistudio.google.com/app/apikey",
    },
    {
        "id": "xai",
        "name": "xAI (Grok)",
        "api_key_env": "XAI_API_KEY",
        "base_url_env": "XAI_BASE_URL",
        "docs_url": "https://console.x.ai/",
    },
    {
        "id": "zai",
        "name": "Z.AI (GLM)",
        "api_key_env": "GLM_API_KEY",
        "api_key_env_aliases": ["ZAI_API_KEY", "Z_AI_API_KEY"],
        "base_url_env": "GLM_BASE_URL",
        "docs_url": "https://open.bigmodel.cn/",
    },
    {
        "id": "kimi",
        "name": "Kimi / Moonshot",
        "api_key_env": "KIMI_API_KEY",
        "api_key_env_aliases": ["KIMI_CN_API_KEY"],
        "base_url_env": "KIMI_BASE_URL",
        "docs_url": "https://platform.moonshot.cn/",
    },
    {
        "id": "arcee",
        "name": "Arcee AI",
        "api_key_env": "ARCEEAI_API_KEY",
        "base_url_env": "ARCEE_BASE_URL",
        "docs_url": "https://arcee.ai/",
    },
    {
        "id": "minimax",
        "name": "MiniMax",
        "api_key_env": "MINIMAX_API_KEY",
        "api_key_env_aliases": ["MINIMAX_CN_API_KEY"],
        "base_url_env": "MINIMAX_BASE_URL",
        "docs_url": "https://www.minimax.io/",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "api_key_env": "DEEPSEEK_API_KEY",
        "base_url_env": "DEEPSEEK_BASE_URL",
        "docs_url": "https://platform.deepseek.com/",
    },
    {
        "id": "dashscope",
        "name": "Alibaba DashScope (Qwen)",
        "api_key_env": "DASHSCOPE_API_KEY",
        "base_url_env": "DASHSCOPE_BASE_URL",
        "docs_url": "https://dashscope.console.aliyun.com/",
    },
    {
        "id": "opencode-zen",
        "name": "OpenCode Zen",
        "api_key_env": "OPENCODE_ZEN_API_KEY",
        "base_url_env": "OPENCODE_ZEN_BASE_URL",
        "docs_url": "https://opencode.ai/zen",
    },
    {
        "id": "opencode-go",
        "name": "OpenCode Go",
        "api_key_env": "OPENCODE_GO_API_KEY",
        "base_url_env": "OPENCODE_GO_BASE_URL",
        "docs_url": "https://opencode.ai/go",
    },
    {
        "id": "huggingface",
        "name": "Hugging Face",
        "api_key_env": "HF_TOKEN",
        "base_url_env": "HF_BASE_URL",
        "docs_url": "https://huggingface.co/settings/tokens",
    },
    {
        "id": "ollama",
        "name": "Ollama Cloud",
        "api_key_env": "OLLAMA_API_KEY",
        "base_url_env": "OLLAMA_BASE_URL",
        "docs_url": "https://ollama.com/",
    },
    {
        "id": "xiaomi",
        "name": "Xiaomi MiMo",
        "api_key_env": "XIAOMI_API_KEY",
        "base_url_env": "XIAOMI_BASE_URL",
        "docs_url": "https://api.xiaomimimo.com/",
    },
]


def _env_entry(env: dict[str, Any], key: str) -> dict[str, Any] | None:
    e = env.get(key)
    if not isinstance(e, dict):
        return None
    return {
        "key": key,
        "is_set": bool(e.get("is_set")),
        "redacted_value": e.get("redacted_value"),
        "is_password": bool(e.get("is_password")),
        "description": e.get("description") or "",
        "url": e.get("url"),
    }


@router.get("/api/providers/llm")
async def list_llm_providers(request: Request) -> JSONResponse:
    """Return the catalog of API-key LLM providers with connection status.

    Source of truth: hermes /api/env (category=='provider'). This endpoint
    groups the raw env entries into user-facing providers for mobile clients.
    """
    resp = await dashboard_request(request, "GET", "/api/env")
    if resp.status_code >= 400:
        return JSONResponse(
            {"detail": "upstream /api/env failed", "status": resp.status_code},
            status_code=502,
        )
    env: dict[str, Any] = resp.json() or {}

    out: list[dict[str, Any]] = []
    for p in _PROVIDERS:
        api_key = _env_entry(env, p["api_key_env"])
        aliases = [
            _env_entry(env, k)
            for k in p.get("api_key_env_aliases", [])
        ]
        aliases = [a for a in aliases if a is not None]
        base_url = (
            _env_entry(env, p["base_url_env"]) if p.get("base_url_env") else None
        )
        connected = bool(api_key and api_key["is_set"]) or any(
            a["is_set"] for a in aliases
        )
        out.append(
            {
                "id": p["id"],
                "name": p["name"],
                "docs_url": p.get("docs_url"),
                "connected": connected,
                "api_key": api_key,
                "api_key_aliases": aliases,
                "base_url": base_url,
            }
        )

    return JSONResponse({"providers": out})
