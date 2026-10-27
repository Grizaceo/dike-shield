"""Load `.env` without printing secrets."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"


def load_env(path: Path | None = None) -> dict[str, str]:
    target = path or ENV_PATH
    vals: dict[str, str] = {}
    if not target.is_file():
        raise FileNotFoundError(f".env missing at {target}")
    for raw in target.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key.strip()] = value.strip().strip('"').strip("'")
    return vals


def secret_values(env: dict[str, str]) -> list[str]:
    keys = (
        "METERLESS_RUNTIME_TOKEN",
        "ZETARIS_API_KEY",
        "SHIELD_DB_PASSWORD",
        "SHIELD_DB_URL",
    )
    return [env[k] for k in keys if env.get(k)]


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out
