"""LLM client: Ollama, 100 % local.

- Chat (with tool calling): Gemma 4 E4B (gemma4:e4b) by default.
- Embeddings (RAG): nomic-embed-text.
"""

import logging

import requests
from django.conf import settings

logger = logging.getLogger("admissions")


class LLMError(Exception):
    pass


def _post(path: str, body: dict) -> dict:
    url = f"{settings.OLLAMA_URL}{path}"
    try:
        resp = requests.post(url, json=body, timeout=settings.LLM_TIMEOUT)
        if resp.status_code >= 400:
            logger.warning("LLM call %s -> HTTP %s: %s", url, resp.status_code, resp.text[:300])
        resp.raise_for_status()
        return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("LLM call %s failed: %s", url, exc)
        raise LLMError(str(exc)) from exc


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 450) -> dict:
    """Return the assistant message: {"role": "assistant", "content": str, "tool_calls"?: [...]}"""
    body = {
        "model": settings.LLM_CHAT_MODEL,
        "messages": messages,
        "stream": False,
        "keep_alive": "30m",
        "options": {"temperature": 0.1, "num_ctx": settings.LLM_NUM_CTX, "num_predict": max_tokens},
    }
    if tools:
        body["tools"] = tools
    if settings.LLM_THINK is not None:
        # Gemma 4 can reason before answering: much slower, not needed here
        body["think"] = settings.LLM_THINK
    data = _post("/api/chat", body)
    if "message" not in data:
        raise LLMError(f"Unexpected response: {str(data)[:200]}")
    return data["message"]


def embed(texts: list[str]) -> list[list[float]]:
    data = _post("/api/embed", {"model": settings.LLM_EMBED_MODEL, "input": texts, "keep_alive": "30m"})
    if "embeddings" not in data:
        raise LLMError(f"Unexpected response: {str(data)[:200]}")
    return data["embeddings"]
