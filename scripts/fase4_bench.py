#!/usr/bin/env python3
"""Optional live bench. Fake-friendly: uses build_deps (Nightshift if up). Never prints secrets."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.bench import run_bench  # noqa: E402
from shield.env import load_env  # noqa: E402
from shield.loop import build_deps  # noqa: E402


def meterless_ok(env: dict[str, str]) -> bool:
    base = env.get("METERLESS_BASE_URL", "").rstrip("/")
    token = env.get("METERLESS_RUNTIME_TOKEN", "")
    if not base or not token or token.startswith("<"):
        return False
    req = request.Request(f"{base}/models", method="GET", headers={"Authorization": f"Bearer {token}"})
    try:
        with request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (error.URLError, error.HTTPError, TimeoutError, OSError):
        return False


def main() -> int:
    env = load_env()
    live = meterless_ok(env)
    print("nightshift_models", live)
    n = 2 if live else 2
    if not live:
        print("SKIP live bench: Nightshift /models not ok; pytest covers 4 runs with fakes")
        return 0
    deps = build_deps(env)
    ids = run_bench(deps=deps, n_preguntas=n, lanes=["FAST", "DEEP"], con_escudo=[False, True])
    print("corrida_ids", len(ids))
    latest = deps.store.latest_corridas(8)
    for row in latest:
        total = int(row.get("citas_total") or 0)
        bad = int(row.get("citas_no_probadas") or 0)
        tasa = (bad / total) if total else 0
        print(
            json.dumps(
                {
                    "lane": row.get("lane"),
                    "con_escudo": row.get("con_escudo"),
                    "n": row.get("n_preguntas"),
                    "citas_total": total,
                    "citas_no_probadas": bad,
                    "tasa": round(tasa, 4),
                },
                ensure_ascii=False,
            )
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
