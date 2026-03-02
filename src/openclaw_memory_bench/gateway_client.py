from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
_RETRY_ATTEMPTS = int(os.environ.get("OPENCLAW_GATEWAY_INVOKE_RETRY_ATTEMPTS") or 5)
_RETRY_BASE_S = float(os.environ.get("OPENCLAW_GATEWAY_INVOKE_RETRY_BASE_S") or 2.0)
_RETRY_MAX_S = float(os.environ.get("OPENCLAW_GATEWAY_INVOKE_RETRY_MAX_S") or 30.0)
_DEFAULT_TIMEOUT_S = int(os.environ.get("OPENCLAW_GATEWAY_INVOKE_TIMEOUT_S") or 60)


def _retryable_payload(data: dict) -> bool:
    err = data.get("error")
    return isinstance(err, dict) and err.get("type") == "tool_error"


def _read_openclaw_config() -> dict:
    p = Path(os.path.expanduser("~/.openclaw/openclaw.json"))
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def resolve_gateway_config(overrides: dict | None = None) -> dict[str, str]:
    overrides = overrides or {}
    cfg = _read_openclaw_config()

    port = (
        cfg.get("gateway", {}).get("http", {}).get("port")
        or cfg.get("gateway", {}).get("port")
        or 18789
    )

    url = (
        overrides.get("gateway_url")
        or os.environ.get("OPENCLAW_GATEWAY_URL")
        or f"http://127.0.0.1:{port}"
    )
    token = (
        overrides.get("gateway_token")
        or os.environ.get("OPENCLAW_GATEWAY_TOKEN")
        or cfg.get("gateway", {}).get("auth", {}).get("token")
        or ""
    )
    agent_id = overrides.get("agent_id") or os.environ.get("OPENCLAW_AGENT_ID") or "main"

    return {
        "gateway_url": str(url).rstrip("/"),
        "gateway_token": str(token),
        "agent_id": str(agent_id),
    }


def invoke_tool(
    *, tool: str, tool_args: dict, session_key: str = "main", config: dict | None = None
) -> Any:
    resolved = resolve_gateway_config(config)
    token = resolved["gateway_token"]
    if not token:
        raise RuntimeError(
            "Gateway token is required (OPENCLAW_GATEWAY_TOKEN or ~/.openclaw/openclaw.json)"
        )

    url = resolved["gateway_url"] + "/tools/invoke"
    payload = {
        "tool": tool,
        "args": tool_args,
        "sessionKey": session_key,
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "x-openclaw-agent-id": resolved["agent_id"],
        },
        method="POST",
    )

    timeout_s = int(os.environ.get("OPENCLAW_GATEWAY_INVOKE_TIMEOUT_S") or _DEFAULT_TIMEOUT_S)

    last_exc: Exception | None = None
    for attempt in range(max(_RETRY_ATTEMPTS, 1)):
        if attempt:
            delay = min(_RETRY_BASE_S * (2 ** (attempt - 1)), _RETRY_MAX_S)
            time.sleep(delay)

        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                body = resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            exc = RuntimeError(f"Gateway error ({e.code}): {err_body}")
            if e.code in _RETRYABLE_STATUS and attempt < _RETRY_ATTEMPTS - 1:
                last_exc = exc
                continue
            raise exc from e
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as e:
            exc = RuntimeError(f"Gateway request failed: {e}")
            if attempt < _RETRY_ATTEMPTS - 1:
                last_exc = exc
                continue
            raise exc from e
        except Exception as e:
            raise RuntimeError(f"Gateway request failed: {e}") from e

        try:
            data = json.loads(body)
        except Exception as e:
            raise RuntimeError(f"Gateway response not JSON: {body[:500]}") from e

        if not isinstance(data, dict) or not data.get("ok"):
            if isinstance(data, dict) and _retryable_payload(data) and attempt < _RETRY_ATTEMPTS - 1:
                last_exc = RuntimeError(f"tools/invoke returned unexpected payload: {body[:2000]}")
                continue
            raise RuntimeError(f"tools/invoke returned unexpected payload: {body[:2000]}")

        return data.get("result")

    # Defensive: should be unreachable.
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("Gateway request failed: unknown")
