"""HTTP client for the engines sidecar (DESIGN.md /hmem/* and /markovian/*). Fail closed."""

from __future__ import annotations

import json
from urllib import error, request

from shield.env import load_env


def _base_url(env: dict[str, str] | None, override: str | None) -> str:
    if override:
        return override.rstrip("/")
    try:
        cfg = env or load_env()
    except FileNotFoundError:
        cfg = {}
    return (cfg.get("ENGINES_URL") or "http://127.0.0.1:8790").rstrip("/")


class _Http:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        env: dict[str, str] | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.base_url = _base_url(env, base_url)
        self.timeout = timeout

    def _post(self, path: str, payload: dict) -> dict | None:
        raw = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=raw,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode() or "{}")
        except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
            return None


class Memory(_Http):
    def recall(self, namespace: str, query: str, k: int = 5) -> list[dict]:
        body = self._post("/hmem/recall", {"namespace": namespace, "query": query, "k": k})
        if not body:
            return []
        items = body.get("items")
        return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []

    def remember(self, namespace: str, content: str, metadata: dict | None = None) -> str:
        if not content:
            return "noop"
        body = self._post(
            "/hmem/remember",
            {"namespace": namespace, "content": content, "metadata": metadata or {}},
        )
        if not body:
            return "noop"
        return str(body.get("id") or "noop")


class Markovian(_Http):
    def start(self, task: str, max_steps: int) -> dict | None:
        return self._post("/markovian/start", {"task": task, "max_steps": max_steps})

    def step(self, run_id: str, observation: dict) -> dict | None:
        return self._post("/markovian/step", {"run_id": run_id, "observation": observation})


def engines_healthy(env: dict[str, str] | None = None) -> bool:
    cfg = env or load_env()
    base = cfg.get("ENGINES_URL", "http://127.0.0.1:8790").rstrip("/")
    req = request.Request(f"{base}/healthz", method="GET")
    try:
        with request.urlopen(req, timeout=2) as resp:
            payload = json.loads(resp.read().decode() or "{}")
        return bool(payload.get("ok")) and bool(payload.get("hmem"))
    except (error.URLError, error.HTTPError, TimeoutError, json.JSONDecodeError, OSError):
        return False
