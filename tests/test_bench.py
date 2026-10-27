"""Bench: four runs, fake LLM, no Nightshift."""

from __future__ import annotations

from shield.bench import load_preguntas, run_bench
from shield.db import MemoryStore
from shield.engines import Memory
from shield.loop import Deps
from tests.fakes import JUDGE_PUBLICAR, ScriptedLLM, fake_fetch, fake_verificar
from tests.test_loop import BAD, GOOD

QUESTIONS = [
    {"id": "q1", "escenario": "despido", "pregunta": "¿Puedo demandar el despido?"},
    {"id": "q2", "escenario": "despido", "pregunta": "¿Cuál es el plazo para reclamar?"},
]


def test_load_thirty_preguntas() -> None:
    rows = load_preguntas()
    assert len(rows) == 30
    assert rows[0]["id"] == "q01"


def test_four_runs_shield_lowers_unproven_rate() -> None:
    drafter = [BAD, BAD, GOOD, GOOD, BAD, BAD, GOOD, GOOD]
    llm = ScriptedLLM(
        {
            "drafter": [(text, "fake-fast") for text in drafter],
            "judge": [JUDGE_PUBLICAR, JUDGE_PUBLICAR, JUDGE_PUBLICAR, JUDGE_PUBLICAR],
        }
    )
    store = MemoryStore()
    deps = Deps(
        llm=llm,
        store=store,
        memory=Memory(base_url="http://127.0.0.1:1", timeout=0.2),
        env={"SAMPLE_MODE": "false"},
        verificar=fake_verificar,
        fetch_articulos=fake_fetch,
        emitir=lambda *_a, **_k: None,
        max_iter=3,
        sample_mode=False,
    )
    ids = run_bench(
        deps=deps,
        n_preguntas=2,
        lanes=["FAST", "DEEP"],
        con_escudo=[False, True],
        questions=QUESTIONS,
    )
    assert len(ids) == 4
    assert len(store.corridas) == 4
    by_key = {(c["lane"], c["con_escudo"]): c for c in store.corridas}
    off = by_key[("FAST", False)]
    on = by_key[("FAST", True)]
    assert off["citas_no_probadas"] > 0
    assert on["citas_no_probadas"] == 0
    assert off["citas_total"] > 0
    assert on["n_preguntas"] == 2
