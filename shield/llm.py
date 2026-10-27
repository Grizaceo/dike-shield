"""Meterless Nightshift client. FAST and DEEP are explicit NVIDIA model ids."""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal
from urllib import error, request

from shield.env import ROOT, load_env, redact, secret_values

Lane = Literal["FAST", "DEEP"]

CACHE_DIR = ROOT / "data" / "cache"
LLM_CACHE_DIR = CACHE_DIR / "llm"
MANIFEST_PATH = CACHE_DIR / "manifest.json"


class LLMError(RuntimeError):
    pass


@dataclass
class LLMResult:
    text: str
    model: str
    latency_ms: int
    lane: Lane


def _post(url: str, headers: dict[str, str], body: dict, timeout: int) -> tuple[int, object]:
    data = json.dumps(body).encode()
    req = request.Request(url, data=data, method="POST", headers=headers)
    req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                parsed: object = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"_text": raw[:400]}
            return resp.status, parsed
    except error.HTTPError as exc:
        raw = exc.read().decode()[:800]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"_text": raw}
        return exc.code, parsed
    except error.URLError as exc:
        raise LLMError(f"network {exc.reason}") from exc


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"1", "true", "yes", "on"}


def sample_manifest() -> dict:
    if not MANIFEST_PATH.is_file():
        return {}
    try:
        data = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def sample_recorded_at() -> str:
    return str(sample_manifest().get("recorded_at") or "")


def _user_text(messages: list[dict[str, str]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") == "user":
            return str(msg.get("content") or "")
    return ""


def _cache_file(agent: str, lane: Lane, messages: list[dict[str, str]]) -> Path | None:
    user = _user_text(messages)
    if agent == "judge":
        blob = user.upper()
        if any(tag in blob for tag in ("CON_PROBLEMAS", "FALLO", "UNRESOLVABLE", "AMBIGUOUS")):
            name = "judge_reparar.json"
        else:
            name = "judge_publicar.json"
        path = LLM_CACHE_DIR / name
        return path if path.is_file() else None
    digest = hashlib.sha256(f"{agent}|{lane}|{user.strip()[:800]}".encode()).hexdigest()[:20]
    hashed = LLM_CACHE_DIR / f"{agent}_{lane}_{digest}.json"
    if hashed.is_file():
        return hashed
    for candidate in (
        LLM_CACHE_DIR / f"{agent}_{lane}.json",
        LLM_CACHE_DIR / f"{agent}.json",
    ):
        if candidate.is_file():
            return candidate
    return None


def _result_from_cache(path: Path, lane: Lane) -> LLMResult | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    text = str(payload.get("text") or "")
    model = str(payload.get("model") or "")
    if not text.strip() or not model:
        return None
    latency = int(payload.get("latency_ms") or 0)
    used_lane = payload.get("lane") or lane
    if used_lane not in {"FAST", "DEEP"}:
        used_lane = lane
    return LLMResult(text=text, model=model, latency_ms=latency, lane=used_lane)


def _write_cache(agent: str, lane: Lane, messages: list[dict[str, str]], result: LLMResult) -> None:
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    user = _user_text(messages)
    digest = hashlib.sha256(f"{agent}|{lane}|{user.strip()[:800]}".encode()).hexdigest()[:20]
    path = LLM_CACHE_DIR / f"{agent}_{lane}_{digest}.json"
    payload = {
        "text": result.text,
        "model": result.model,
        "lane": result.lane,
        "latency_ms": result.latency_ms,
        "agent": agent,
        "recorded_at": sample_recorded_at() or time.strftime("%Y-%m-%d"),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class LLMClient:
    def __init__(self, env: dict[str, str] | None = None) -> None:
        self.env = env or load_env()
        self.secrets = secret_values(self.env)

    def _sample_mode(self) -> bool:
        return _truthy(self.env.get("SAMPLE_MODE"))

    def _cached(self, agent: str, lane: Lane, messages: list[dict[str, str]]) -> LLMResult | None:
        path = _cache_file(agent, lane, messages)
        if path is None:
            return None
        return _result_from_cache(path, lane)

    def _model(self, lane: Lane) -> str:
        key = "METERLESS_MODEL_FAST" if lane == "FAST" else "METERLESS_MODEL_DEEP"
        model = self.env.get(key, "")
        if not model or model.startswith("<") or model.startswith("meterless/auto"):
            raise LLMError(f"invalid {key}")
        if model in {"meterless/auto", "meterless/fast", "meterless/deep"}:
            raise LLMError("meterless/* routes are forbidden on the prize path")
        return model

    def chat(
        self,
        *,
        lane: Lane,
        messages: list[dict[str, str]],
        agent: str,
        max_tokens: int = 2048,
        temperature: float = 0.2,
        timeout: int = 90,
    ) -> LLMResult:
        if self._sample_mode():
            cached = self._cached(agent, lane, messages)
            if cached is not None:
                return cached
        base = self.env.get("METERLESS_BASE_URL", "").rstrip("/")
        token = self.env.get("METERLESS_RUNTIME_TOKEN", "")
        if not base or not token or token.startswith("<"):
            if self._sample_mode():
                raise LLMError("SAMPLE_MODE no tiene caché para esta pregunta.")
            raise LLMError("missing Meterless URL or token")
        model = self._model(lane)
        headers = {
            "Authorization": f"Bearer {token}",
            "meterless-app": self.env.get("METERLESS_APP", "dike-shield"),
            "meterless-scope": "user",
        }
        url = f"{base}/chat/completions"
        tokens = max(256, max_tokens)
        last_err = "unknown"
        for attempt in range(2):
            body = {
                "model": model,
                "messages": messages,
                "max_tokens": tokens,
                "temperature": temperature,
            }
            t0 = time.monotonic()
            try:
                code, payload = _post(url, headers, body, timeout)
            except LLMError as exc:
                last_err = redact(str(exc), self.secrets)
                if attempt == 0:
                    continue
                if self._sample_mode():
                    cached = self._cached(agent, lane, messages)
                    if cached is not None:
                        return cached
                raise LLMError(last_err) from exc
            latency = int((time.monotonic() - t0) * 1000)
            err_code = ""
            if isinstance(payload, dict):
                err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
                err_code = str(err.get("code") or err.get("message") or "")
            if code >= 500 or code == 408:
                last_err = f"HTTP {code} {redact(err_code, self.secrets)}"
                if attempt == 0:
                    if "empty_response" in err_code:
                        tokens = min(4096, max(tokens * 2, 2048))
                    continue
                raise LLMError(last_err)
            if code != 200 or not isinstance(payload, dict):
                raise LLMError(redact(f"HTTP {code} {payload!r}"[:240], self.secrets))
            choices = payload.get("choices") or []
            text = ""
            if choices and isinstance(choices[0], dict):
                msg = choices[0].get("message") or {}
                text = str(msg.get("content") or "")
            if not text.strip():
                last_err = "empty_response"
                if attempt == 0:
                    tokens = min(4096, max(tokens * 2, 2048))
                    continue
                raise LLMError(last_err)
            used = str(payload.get("model") or model)
            result = LLMResult(text=text, model=used, latency_ms=latency, lane=lane)
            try:
                _write_cache(agent, lane, messages, result)
            except OSError:
                pass
            return result
        if self._sample_mode():
            cached = self._cached(agent, lane, messages)
            if cached is not None:
                return cached
        raise LLMError(last_err)
