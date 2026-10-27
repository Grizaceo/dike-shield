"""H-MEM: session A refutes, session B recalls. Real sidecar on a free port."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

from shield.db import MemoryStore, PostgresStore
from shield.engines import Memory
from shield.env import load_env
from shield.loop import Deps, run
from tests.fakes import (
    JUDGE_PUBLICAR,
    JUDGE_REPARAR,
    ScriptedLLM,
    fake_fetch,
    fake_verificar,
)
from tests.test_loop import BAD, FIXED, GOOD

ROOT = Path(__file__).resolve().parents[1]
ENGINES = ROOT / "engines"
CITE = "artículo 9999 del Código del Trabajo"
Q_A = "Me despidieron. Según el artículo 9999 del Código del Trabajo, ¿cuál es el plazo para reclamar?"
Q_B = "¿Cuál es el plazo para reclamar un despido según el Código del Trabajo?"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def sidecar_url() -> str:
    port = _free_port()
    env = os.environ.copy()
    env["ENGINES_PORT"] = str(port)
    env["ENGINES_HOST"] = "127.0.0.1"
    env["ENGINES_TEST"] = "1"
    proc = subprocess.Popen(
        ["npx", "tsx", "src/main.ts"],
        cwd=ENGINES,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    url = f"http://127.0.0.1:{port}"
    deadline = time.time() + 25
    last: Exception | None = None
    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read() if proc.stdout else ""
                raise RuntimeError(f"sidecar exited {proc.returncode}: {out}")
            try:
                with urllib.request.urlopen(f"{url}/healthz", timeout=0.4) as resp:
                    payload = json.loads(resp.read().decode())
                if payload.get("ok") and payload.get("hmem") is True:
                    assert payload.get("markovian") is True
                    yield url
                    return
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                last = exc
                time.sleep(0.1)
        raise RuntimeError(f"sidecar healthz timeout: {last}")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def _deps(scripts: dict, memory: Memory, store: MemoryStore | None = None, max_iter: int = 3):
    store = store or MemoryStore()
    llm = ScriptedLLM(scripts)
    deps = Deps(
        llm=llm,
        store=store,
        memory=memory,
        env={"SAMPLE_MODE": "false", "SHIELD_MAX_ITER": str(max_iter)},
        verificar=fake_verificar,
        fetch_articulos=fake_fetch,
        emitir=lambda *_a, **_k: None,
        max_iter=max_iter,
        sample_mode=False,
    )
    return deps, store, llm


def test_fail_closed_when_sidecar_down() -> None:
    mem = Memory(base_url="http://127.0.0.1:1", timeout=0.2)
    assert mem.recall("refutadas", "despido") == []
    assert mem.remember("refutadas", CITE, {"sesion_id": "x"}) == "noop"


def test_http_remember_recall(sidecar_url: str) -> None:
    mem = Memory(base_url=sidecar_url)
    mid = mem.remember(
        "refutadas",
        CITE,
        {"sesion_id": "sess-http", "resolucion": "UNRESOLVABLE", "razon": "UNRESOLVABLE"},
    )
    assert mid != "noop"
    items = mem.recall("refutadas", Q_B, k=5)
    assert any("9999" in str(item.get("content")) for item in items)
    assert any((item.get("metadata") or {}).get("sesion_id") == "sess-http" for item in items)


def test_session_a_refutes_session_b_recalls(sidecar_url: str) -> None:
    mem = Memory(base_url=sidecar_url)
    deps_a, store_a, _llm_a = _deps(
        {
            "drafter": [(BAD, "fake-fast")],
            "judge": [JUDGE_REPARAR, JUDGE_PUBLICAR],
            "repairer": [(FIXED, "fake-deep")],
        },
        mem,
    )
    result_a = run(entrada=Q_A, escenario="despido", modo="pregunta", deps=deps_a)
    iid_a = uuid.UUID(result_a["intercepcion_id"])
    assert "9999" in (store_a.intercepciones[iid_a]["borrador_original"] or "")
    assert "9999" not in (result_a["respuesta_final"] or "")
    mirrored = store_a.get_refutada(CITE)
    assert mirrored is not None
    assert mirrored["veces"] == 1
    assert mirrored["razon"] == "UNRESOLVABLE"

    deps_b, store_b, llm_b = _deps(
        {
            "drafter": [(BAD, "fake-fast")],
            "judge": [JUDGE_REPARAR, JUDGE_PUBLICAR],
            "repairer": [(FIXED, "fake-deep")],
        },
        mem,
    )
    result_b = run(entrada=Q_B, escenario="despido", modo="pregunta", deps=deps_b)
    sid_a = result_a["sesion_id"]
    events = store_b.list_trazas(uuid.UUID(result_b["intercepcion_id"]))
    blob = " | ".join(f"{e.accion} :: {e.salida_resumen}" for e in events)
    assert f"recordado de la sesión {sid_a}" in blob
    drafter_msgs = [msgs for agent, msgs in llm_b.history if agent == "drafter"]
    assert drafter_msgs
    user = str(drafter_msgs[0][-1]["content"])
    assert "No uses" in user
    assert "9999" in user
    assert "9999" not in (result_b["respuesta_final"] or "")
    borrador_b = store_b.intercepciones[uuid.UUID(result_b["intercepcion_id"])]["borrador_original"]
    assert "9999" in (borrador_b or "")


def test_drafter_omits_recalled_cite_when_scripted_clean(sidecar_url: str) -> None:
    mem = Memory(base_url=sidecar_url)
    mem.remember(
        "refutadas",
        CITE,
        {"sesion_id": "11111111-1111-1111-1111-111111111111", "resolucion": "UNRESOLVABLE", "razon": "UNRESOLVABLE"},
    )
    deps, store, llm = _deps(
        {"drafter": [(GOOD, "fake-fast")], "judge": [JUDGE_PUBLICAR]},
        mem,
    )
    result = run(entrada=Q_B, escenario="despido", modo="pregunta", deps=deps)
    user = str([msgs for agent, msgs in llm.history if agent == "drafter"][0][-1]["content"])
    assert "No uses" in user
    iid = uuid.UUID(result["intercepcion_id"])
    assert "9999" not in (store.intercepciones[iid]["borrador_original"] or "")
    assert "9999" not in (result["respuesta_final"] or "")
    events = store.list_trazas(iid)
    blob = " | ".join(f"{e.accion} :: {e.salida_resumen}" for e in events)
    assert "recordado de la sesión 11111111-1111-1111-1111-111111111111" in blob


def test_memorystore_upsert_refutadas() -> None:
    store = MemoryStore()
    store.upsert_refutada(cita_normalizada=CITE, razon="UNRESOLVABLE")
    store.upsert_refutada(cita_normalizada=CITE, razon="still-bad")
    row = store.get_refutada(CITE)
    assert row is not None
    assert row["veces"] == 2
    assert row["razon"] == "still-bad"


def test_postgres_upsert_refutadas() -> None:
    env = load_env()
    url = env.get("SHIELD_DB_URL", "")
    if not url or "<" in url:
        pytest.skip("SHIELD_DB_URL missing")
    store = PostgresStore(env)
    key = "artículo 7777 del Código del Trabajo"
    before = store.get_refutada(key)
    store.upsert_refutada(cita_normalizada=key, razon="test-memory")
    after = store.get_refutada(key)
    assert after is not None
    assert after["razon"] == "test-memory"
    assert after["veces"] == (int(before["veces"]) + 1 if before else 1)
