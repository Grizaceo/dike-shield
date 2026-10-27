#!/usr/bin/env python3
"""Phase-0 eligibility smoke. Prints PASS/FAIL only; never prints secrets."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
DIKE_HOME = ROOT / ".local" / "dike-home"
DIKE_USERS = DIKE_HOME / "users"
DIKE_PACK = DIKE_HOME / "pack-src" / "chile-base"
CORPUS_TAR = ROOT / "vendor" / "dike" / "corpus" / "chile-base-af1422d66d1e6eee.tar.gz"
VENDOR_DIKE = ROOT / "vendor" / "dike"
KNOWN_CITE = "artículo 168 del Código del Trabajo"
FAST_PROMPT = "Reply with the single word pong."


def load_env(path: Path) -> dict[str, str]:
    vals: dict[str, str] = {}
    if not path.is_file():
        raise SystemExit("FAIL: .env missing")
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        vals[key] = value.strip().strip('"').strip("'")
    return vals


def redact(text: str, secrets: list[str]) -> str:
    out = text
    for secret in secrets:
        if secret:
            out = out.replace(secret, "***")
    return out


def http_json(
    url: str,
    *,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: dict | None = None,
    timeout: int = 30,
) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            parsed: object
            try:
                parsed = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"_text": raw[:400]}
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode()[:400]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"_text": raw}
        return exc.code, parsed


def check_zetaris_web() -> str:
    code, _ = http_json("http://127.0.0.1:3000/", timeout=8)
    if code >= 200 and code < 500:
        return f"PASS zetaris_web HTTP {code}"
    return f"FAIL zetaris_web HTTP {code}"


def check_zetaris_sql(env: dict[str, str], secrets: list[str]) -> str:
    base = env.get("ZETARIS_REST_URL", "").rstrip("/")
    key = env.get("ZETARIS_API_KEY", "")
    org = env.get("ZETARIS_ORG_ID", "1")
    if not base or not key or key.startswith("<"):
        return "FAIL zetaris_sql missing ZETARIS_REST_URL or ZETARIS_API_KEY"
    url = f"{base}/sql-editor/sqls/run"
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Org-ID": str(org),
        "X-Request-ID": str(uuid.uuid4()),
    }
    body = {
        "queryId": str(uuid.uuid4()),
        "sql": "SELECT 1",
        "source": "SqlEditor",
        "limit": 10,
    }
    code, payload = http_json(url, method="POST", headers=headers, body=body, timeout=20)
    data = payload.get("data") if isinstance(payload, dict) else None
    if code == 200 and data == [["1"]]:
        return "PASS zetaris_sql SELECT 1 -> [['1']]"
    summary = redact(str(payload)[:180], secrets)
    return f"FAIL zetaris_sql HTTP {code} {summary}"


def check_meterless_models(env: dict[str, str], secrets: list[str]) -> str:
    base = env.get("METERLESS_BASE_URL", "").rstrip("/")
    token = env.get("METERLESS_RUNTIME_TOKEN", "")
    fast = env.get("METERLESS_MODEL_FAST", "")
    deep = env.get("METERLESS_MODEL_DEEP", "")
    if not base or not token or token.startswith("<"):
        return "FAIL meterless_models missing URL or token"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "meterless-app": env.get("METERLESS_APP", "dike-shield"),
    }
    code, payload = http_json(f"{base}/models", headers=headers, timeout=12)
    models = payload.get("data") if isinstance(payload, dict) else None
    if code != 200 or not isinstance(models, list):
        return f"FAIL meterless_models HTTP {code} {redact(str(payload)[:180], secrets)}"
    ids = [m.get("id") for m in models if isinstance(m, dict)]
    nemotron = [i for i in ids if isinstance(i, str) and "nemotron" in i.lower()]
    missing = [name for name in (fast, deep) if name and name not in ids]
    if "nvidia/" in fast and fast in ids and not missing:
        return (
            f"PASS meterless_models HTTP 200 n={len(ids)} "
            f"nemotron={len(nemotron)} FAST={fast} DEEP={deep}"
        )
    if missing:
        return f"FAIL meterless_models missing {missing} (nemotron listed={len(nemotron)})"
    return f"FAIL meterless_models FAST not nvidia Nemotron ({fast!r})"


def check_meterless_chat_fast(env: dict[str, str], secrets: list[str]) -> str:
    base = env.get("METERLESS_BASE_URL", "").rstrip("/")
    token = env.get("METERLESS_RUNTIME_TOKEN", "")
    fast = env.get("METERLESS_MODEL_FAST", "")
    if not all([base, token, fast]) or token.startswith("<") or fast.startswith("<"):
        return "FAIL meterless_chat_fast missing URL, token or FAST model"
    headers = {
        "Authorization": f"Bearer {token}",
        "meterless-app": env.get("METERLESS_APP", "dike-shield"),
        "meterless-scope": "user",
    }
    body = {
        "model": fast,
        "messages": [{"role": "user", "content": FAST_PROMPT}],
        "max_tokens": 256,
        "temperature": 0,
    }
    t0 = time.monotonic()
    code, payload = http_json(
        f"{base}/chat/completions",
        method="POST",
        headers=headers,
        body=body,
        timeout=180,
    )
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    if not isinstance(payload, dict):
        return f"FAIL meterless_chat_fast HTTP {code} {elapsed_ms}ms"
    model_used = payload.get("model") or fast
    choices = payload.get("choices") or []
    text = ""
    if choices and isinstance(choices[0], dict):
        msg = choices[0].get("message") or {}
        text = str(msg.get("content") or "")
    if code == 200 and text.strip():
        return (
            f"PASS meterless_chat_fast HTTP 200 model={model_used} "
            f"chars={len(text)} {elapsed_ms}ms"
        )
    err = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    hint = err.get("code") or err.get("message") or str(payload)[:160]
    return f"FAIL meterless_chat_fast HTTP {code} {elapsed_ms}ms {redact(str(hint), secrets)}"


def dike_env() -> dict[str, str]:
    home = str(DIKE_HOME)
    return {
        **os.environ,
        "HOME": home,
        "LEXO_CONFIG": str(DIKE_HOME / "config.yaml"),
        "DIKE_USER": "shield",
        "DIKE_USERS_ROOT": str(DIKE_USERS),
        "DIKE_HOME_DIR": home,
        "LEXO_CASES_ROOT": str(DIKE_HOME / "cases"),
        "DIKE_BINDING_CACHE_DIR": str(DIKE_HOME / "cache" / "binding"),
        "DIKE_ROOTS_CACHE_DIR": str(DIKE_HOME / "cache" / "roots"),
        "LEXO_BCN_CACHE_DIR": str(DIKE_HOME / "cache" / "bcn"),
    }


def ensure_dike_cli() -> list[str]:
    DIKE_HOME.mkdir(parents=True, exist_ok=True)
    cmd = ["uv", "run", "--directory", str(VENDOR_DIKE), "dike"]
    probe = subprocess.run(
        cmd + ["--help"],
        capture_output=True,
        text=True,
        env=dike_env(),
        timeout=180,
    )
    if probe.returncode != 0:
        sync = subprocess.run(
            ["uv", "sync"],
            cwd=VENDOR_DIKE,
            capture_output=True,
            text=True,
            timeout=300,
        )
        if sync.returncode != 0:
            raise RuntimeError(f"uv sync vendor/dike failed: {sync.stderr[-400:]}")
    return cmd


def ensure_corpus(dike_cmd: list[str]) -> None:
    marker = DIKE_USERS / "shield" / "starter" / "chile-base"
    if (marker / "STATE.json").is_file() or any(marker.glob("**/MANIFEST.json")):
        return
    DIKE_PACK.parent.mkdir(parents=True, exist_ok=True)
    if not DIKE_PACK.is_dir():
        with tarfile.open(CORPUS_TAR) as tar:
            tar.extractall(DIKE_PACK.parent)
    install = subprocess.run(
        dike_cmd
        + [
            "starter",
            "install",
            str(DIKE_PACK),
            "--name",
            "chile-base",
            "--user",
            "shield",
            "--users-root",
            str(DIKE_USERS),
            "--json",
        ],
        capture_output=True,
        text=True,
        env=dike_env(),
        timeout=180,
    )
    if install.returncode != 0:
        raise RuntimeError(
            f"dike starter install failed rc={install.returncode} "
            f"stderr={install.stderr[-400:]} stdout={install.stdout[-400:]}"
        )


def check_dike_citation() -> str:
    lexo_before = None
    lexo = Path.home() / ".lexo"
    if lexo.exists():
        lexo_before = lexo.stat().st_mtime
    try:
        dike_cmd = ensure_dike_cli()
        ensure_corpus(dike_cmd)
    except Exception as exc:
        return f"FAIL dike_citation setup {exc}"
    sample = DIKE_HOME / "smoke-cita.md"
    sample.write_text(
        f"Escrito sintético de prueba. Según el {KNOWN_CITE}, "
        "el trabajador puede reclamar el despido ante el tribunal competente.\n",
        encoding="utf-8",
    )
    run = subprocess.run(
        dike_cmd
        + [
            "constancia",
            str(sample),
            "--json",
            "--user",
            "shield",
            "--users-root",
            str(DIKE_USERS),
        ],
        capture_output=True,
        text=True,
        env=dike_env(),
        timeout=120,
    )
    if lexo.exists() and lexo_before is not None and lexo.stat().st_mtime != lexo_before:
        return "FAIL dike_citation touched ~/.lexo"
    try:
        result = json.loads(run.stdout)
    except json.JSONDecodeError:
        return (
            f"FAIL dike_citation rc={run.returncode} "
            f"stdout={run.stdout[:200]!r} stderr={run.stderr[-200:]!r}"
        )
    detalles = result.get("detalles") or []
    estados = [d.get("estado") for d in detalles if isinstance(d, dict)]
    if "VERIFICADA" in estados:
        return (
            f"PASS dike_citation veredicto={result.get('veredicto')} "
            f"estados={estados} rc={run.returncode}"
        )
    return f"FAIL dike_citation veredicto={result.get('veredicto')} estados={estados}"


def main() -> int:
    env = load_env(ENV_PATH)
    secrets = [
        env.get("METERLESS_RUNTIME_TOKEN", ""),
        env.get("ZETARIS_API_KEY", ""),
        env.get("SHIELD_DB_PASSWORD", ""),
    ]
    checks = [
        check_zetaris_web,
        lambda: check_zetaris_sql(env, secrets),
        lambda: check_meterless_models(env, secrets),
        lambda: check_meterless_chat_fast(env, secrets),
        check_dike_citation,
    ]
    results = []
    for check in checks:
        try:
            results.append(check())
        except Exception as exc:
            results.append(f"FAIL {check.__name__ if hasattr(check, '__name__') else 'check'} {exc}")
        print(results[-1])
    passed = sum(1 for line in results if line.startswith("PASS"))
    print(f"{passed}/5 PASS")
    return 0 if passed == 5 else 1


if __name__ == "__main__":
    sys.exit(main())
