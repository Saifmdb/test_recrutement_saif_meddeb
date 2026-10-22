"""LLM client.

- Chat (with tool calling): Ollama (local) or any OpenAI-compatible API such as Groq (cloud),
  selected with LLM_PROVIDER.
- Embeddings (RAG): always Ollama (nomic-embed-text, small enough for any PC).

The agent works with Ollama's message format (tool call arguments as dicts, tool results with
"tool_name"); the OpenAI-compatible path converts to/from the OpenAI format.
"""

import json
import logging
import re
import time

import requests
from django.conf import settings

logger = logging.getLogger("admissions")

MAX_RATE_LIMIT_RETRIES = 3
MAX_RATE_LIMIT_WAIT = 30  # seconds


class LLMError(Exception):
    pass


def _retry_delay(resp: requests.Response) -> float:
    """Seconds to wait after HTTP 429 (Retry-After header, or "try again in 1.41s" in the message)."""
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = re.search(r"try again in (?:(\d+)m)?([\d.]+)s", resp.text)
    if match:
        return int(match.group(1) or 0) * 60 + float(match.group(2))
    return 5.0


def _post(url: str, body: dict, headers: dict | None = None) -> dict:
    try:
        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            resp = requests.post(url, json=body, headers=headers or {}, timeout=settings.LLM_TIMEOUT)
            if resp.status_code == 429 and attempt < MAX_RATE_LIMIT_RETRIES:
                # Free plans limit tokens per minute: wait as asked by the API, then retry
                delay = min(_retry_delay(resp) + 0.5, MAX_RATE_LIMIT_WAIT)
                logger.info("Rate limited by %s, retrying in %.1fs", url, delay)
                time.sleep(delay)
                continue
            if resp.status_code >= 400:
                logger.warning("LLM call %s -> HTTP %s: %s", url, resp.status_code, resp.text[:300])
            resp.raise_for_status()
            return resp.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("LLM call %s failed: %s", url, exc)
        raise LLMError(str(exc)) from exc
    raise LLMError("Rate limit: too many retries")


def chat(messages: list[dict], tools: list[dict] | None = None, max_tokens: int = 450) -> dict:
    """Return the assistant message: {"role": "assistant", "content": str, "tool_calls"?: [...]}"""
    if settings.LLM_PROVIDER == "openai":
        return _chat_openai(messages, tools, max_tokens)
    return _chat_ollama(messages, tools, max_tokens)


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------
def _chat_ollama(messages, tools, max_tokens) -> dict:
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
        # qwen3 "thinks" before answering by default: much slower, not needed here
        body["think"] = settings.LLM_THINK
    data = _post(f"{settings.OLLAMA_URL}/api/chat", body)
    if "message" not in data:
        raise LLMError(f"Unexpected response: {str(data)[:200]}")
    return data["message"]


# ---------------------------------------------------------------------------
# OpenAI-compatible API (Groq, OpenAI, Mistral...)
# ---------------------------------------------------------------------------
def _to_openai(messages: list[dict]) -> list[dict]:
    """Ollama-format history -> OpenAI format (tool calls need ids, arguments as JSON strings)."""
    out, pending_ids = [], []
    for i, m in enumerate(messages):
        if m["role"] == "assistant" and m.get("tool_calls"):
            calls = []
            for j, c in enumerate(m["tool_calls"]):
                call_id = c.get("id") or f"call_{i}_{j}"
                args = c["function"].get("arguments") or {}
                calls.append({"id": call_id, "type": "function", "function": {
                    "name": c["function"]["name"],
                    "arguments": args if isinstance(args, str) else json.dumps(args, ensure_ascii=False),
                }})
            pending_ids = [c["id"] for c in calls]
            out.append({"role": "assistant", "content": m.get("content") or None, "tool_calls": calls})
        elif m["role"] == "tool":
            call_id = pending_ids.pop(0) if pending_ids else f"call_{i}"
            out.append({"role": "tool", "tool_call_id": call_id, "content": m["content"]})
        else:
            out.append({"role": m["role"], "content": m.get("content") or ""})
    return out


def _chat_openai(messages, tools, max_tokens) -> dict:
    body = {
        "model": settings.LLM_CHAT_MODEL,
        "messages": _to_openai(messages),
        "temperature": 0.1,
        # Reasoning models (gpt-oss) spend part of max_tokens on hidden reasoning: leave room for the answer
        "max_tokens": max_tokens + 1500,
    }
    if tools:
        body["tools"] = tools
    if settings.LLM_REASONING_EFFORT:
        body["reasoning_effort"] = settings.LLM_REASONING_EFFORT
    data = _post(f"{settings.LLM_API_URL}/chat/completions", body,
                 headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"})
    try:
        msg = data["choices"][0]["message"]
    except (KeyError, IndexError) as exc:
        raise LLMError(f"Unexpected response: {str(data)[:200]}") from exc
    calls = []
    for c in msg.get("tool_calls") or []:
        try:
            args = json.loads(c["function"].get("arguments") or "{}")
        except json.JSONDecodeError:
            args = {}
        calls.append({"id": c.get("id"), "function": {"name": c["function"]["name"], "arguments": args}})
    result = {"role": "assistant", "content": msg.get("content") or ""}
    if calls:
        result["tool_calls"] = calls
    return result


# ---------------------------------------------------------------------------
# Embeddings (Ollama)
# ---------------------------------------------------------------------------
def embed(texts: list[str]) -> list[list[float]]:
    data = _post(f"{settings.OLLAMA_URL}/api/embed",
                 {"model": settings.LLM_EMBED_MODEL, "input": texts, "keep_alive": "30m"})
    if "embeddings" not in data:
        raise LLMError(f"Unexpected response: {str(data)[:200]}")
    return data["embeddings"]
