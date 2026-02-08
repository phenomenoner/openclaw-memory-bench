from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


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


def invoke_tool(*, tool: str, tool_args: dict, session_key: str = "main", config: dict | None = None) -> Any:
    resolved = resolve_gateway_config(config)
    token = resolved["gateway_token"]
    if not token:
        raise RuntimeError("Gateway token is required (OPENCLAW_GATEWAY_TOKEN or ~/.openclaw/openclaw.json)")

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

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Gateway error ({e.code}): {err_body}") from e
    except Exception as e:
        raise RuntimeError(f"Gateway request failed: {e}") from e

    data = json.loads(body)
    if not isinstance(data, dict) or not data.get("ok"):
        raise RuntimeError(f"tools/invoke returned unexpected payload: {body[:2000]}")
    return data.get("result")
