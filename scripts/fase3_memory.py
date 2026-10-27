#!/usr/bin/env python3
"""Demo: session A refutes a cite, session B recalls it. Fake LLM, real sidecar."""

from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path
from urllib import request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.db import MemoryStore, PostgresStore, Store  # noqa: E402
from shield.engines import Memory, engines_healthy  # noqa: E402
from shield.env import load_env  # noqa: E402
from shield.loop import Deps, run  # noqa: E402
from tests.fakes import (  # noqa: E402
    JUDGE_PUBLICAR,
    JUDGE_REPARAR,
    ScriptedLLM,
    fake_fetch,
    fake_verificar,
)
from tests.test_loop import BAD, FIXED  # noqa: E402

Q_A = "Me despidieron. Según el artículo 9999 del Código del Trabajo, ¿cuál es el plazo para reclamar?"
Q_B = "¿Cuál es el plazo para reclamar un despido según el Código del Trabajo?"


def _deps(scripts: dict, memory: Memory, store: Store) -> Deps:
    return Deps(
        llm=ScriptedLLM(scripts),
        store=store,
        memory=memory,
        env={"SAMPLE_MODE": "false", "SHIELD_MAX_ITER": "3"},
        verificar=fake_verificar,
        fetch_articulos=fake_fetch,
        emitir=lambda *_a, **_k: None,
        max_iter=3,
        sample_mode=False,
    )


def _get(url: str) -> dict:
    req = request.Request(url, method="GET")
    with request.urlopen(req, timeout=3) as resp:
        return json.loads(resp.read().decode() or "{}")


def main() -> int:
    env = load_env()
    base = env.get("ENGINES_URL", "http://127.0.0.1:8790").rstrip("/")
    hz = _get(f"{base}/healthz")
    print("sidecar_healthz", json.dumps(hz, ensure_ascii=False))
    if not (hz.get("ok") and hz.get("hmem")):
        print("FAIL sidecar hmem not ready")
        return 1
    print("engines_healthy", engines_healthy(env))

    mem = Memory(env=env)
    try:
        store: Store = PostgresStore(env)
        store.get_refutada("__probe__")
        print("store", "postgres")
    except Exception:
        store = MemoryStore()
        print("store", "memory")
    store_a = store
    a = run(
        entrada=Q_A,
        escenario="despido",
        modo="pregunta",
        deps=_deps(
            {
                "drafter": [(BAD, "fake-fast")],
                "judge": [JUDGE_REPARAR, JUDGE_PUBLICAR],
                "repairer": [(FIXED, "fake-deep")],
            },
            mem,
            store_a,
        ),
    )
    print("session_a", a["sesion_id"], "decision", a["decision"], "9999_in_final", "9999" in (a["respuesta_final"] or ""))
    print("refutadas", store_a.get_refutada("artículo 9999 del Código del Trabajo"))

    store_b = store
    b = run(
        entrada=Q_B,
        escenario="despido",
        modo="pregunta",
        deps=_deps(
            {
                "drafter": [(BAD, "fake-fast")],
                "judge": [JUDGE_REPARAR, JUDGE_PUBLICAR],
                "repairer": [(FIXED, "fake-deep")],
            },
            mem,
            store_b,
        ),
    )
    events = store_b.list_trazas(uuid.UUID(b["intercepcion_id"]))
    print("session_b", b["sesion_id"], "decision", b["decision"], "9999_in_final", "9999" in (b["respuesta_final"] or ""))
    print("traza_b")
    for ev in events:
        print(f"  paso={ev.paso} agente={ev.agente} accion={ev.accion} salida={ev.salida_resumen}")
    phrase = f"recordado de la sesión {a['sesion_id']}"
    blob = " ".join(f"{e.accion} {e.salida_resumen}" for e in events)
    if phrase not in blob:
        print("FAIL missing", phrase)
        return 1
    print("PASS", phrase)
    mirrored = store.get_refutada("artículo 9999 del Código del Trabajo")
    print("refutadas_9999_veces", None if not mirrored else mirrored["veces"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
