"""Loop with a fake LLM: publicar, reparar, abstener, escalar."""

from __future__ import annotations

from shield.db import MemoryStore
from shield.engines import Memory
from shield.extractor import extract_regex
from shield.loop import Deps, run
from tests.fakes import (
    JUDGE_PUBLICAR,
    JUDGE_REPARAR,
    ScriptedLLM,
    fake_fetch,
    fake_verificar,
)

GOOD = (
    "El artículo 161 del Código del Trabajo regula el despido por necesidades "
    "de la empresa. El artículo 168 del Código del Trabajo permite reclamar "
    "ante el juzgado de letras del trabajo."
)
BAD = (
    "Según el artículo 9999 del Código del Trabajo el plazo es de cinco días. "
    "El artículo 168 del Código del Trabajo permite reclamar el despido."
)
FIXED = (
    "El artículo 168 del Código del Trabajo permite reclamar el despido "
    "ante el juzgado de letras del trabajo."
)


def _deps(scripts: dict, *, max_iter: int = 3) -> tuple[Deps, MemoryStore]:
    store = MemoryStore()
    deps = Deps(
        llm=ScriptedLLM(scripts),
        store=store,
        memory=Memory(base_url="http://127.0.0.1:1", timeout=0.2),
        env={"SAMPLE_MODE": "false", "SHIELD_MAX_ITER": str(max_iter)},
        verificar=fake_verificar,
        fetch_articulos=fake_fetch,
        emitir=lambda *_a, **_k: None,
        max_iter=max_iter,
        sample_mode=False,
    )
    return deps, store


def test_extractor_canonical_trabajo() -> None:
    cites = extract_regex(GOOD)
    norms = {c.normalized for c in cites}
    assert "artículo 161 del Código del Trabajo" in norms
    assert "artículo 168 del Código del Trabajo" in norms


def test_publicar() -> None:
    deps, store = _deps({"drafter": [(GOOD, "fake-fast")], "judge": [JUDGE_PUBLICAR]})
    result = run(
        entrada="Me despidieron por necesidades de la empresa, ¿puedo demandar?",
        escenario="despido",
        modo="pregunta",
        deps=deps,
    )
    assert result["decision"] == "publicar"
    assert result["iteraciones"] == 1
    assert "9999" not in (result["respuesta_final"] or "")
    assert any(c["estado"] == "VERIFICADA" for c in result["citas"])
    iid = __import__("uuid").UUID(result["intercepcion_id"])
    assert store.intercepciones[iid]["decision"] == "publicar"


def test_reparar_retira_cita_no_probada() -> None:
    deps, store = _deps(
        {
            "drafter": [(BAD, "fake-fast")],
            "judge": [JUDGE_REPARAR, JUDGE_PUBLICAR],
            "repairer": [(FIXED, "fake-deep")],
        }
    )
    result = run(
        entrada="¿Cuál es el plazo para reclamar un despido?",
        escenario="despido",
        modo="pregunta",
        deps=deps,
    )
    iid = __import__("uuid").UUID(result["intercepcion_id"])
    borrador = store.intercepciones[iid]["borrador_original"]
    final = result["respuesta_final"] or ""
    assert "9999" in borrador
    assert "9999" not in final
    assert result["decision"] == "publicar"
    assert result["iteraciones"] == 2
    assert "artículo 168 del Código del Trabajo" in final


def test_abstener_fuera_de_corpus() -> None:
    deps, _store = _deps({})
    result = run(
        entrada="¿Cuál es la multa por no pagar el permiso de circulación en la municipalidad?",
        escenario="libre",
        modo="pregunta",
        deps=deps,
    )
    assert result["decision"] == "abstener"
    assert result["iteraciones"] == 0
    assert "corpus" in (result["respuesta_final"] or "").lower()


def test_publicar_si_dike_limpio_aunque_el_juez_pida_reparar() -> None:
    deps, _store = _deps(
        {
            "drafter": [(GOOD, "fake-fast")],
            "judge": [JUDGE_REPARAR],
        }
    )
    result = run(
        entrada="¿Puedo demandar el despido?",
        escenario="despido",
        modo="pregunta",
        deps=deps,
    )
    assert result["decision"] == "publicar"
    assert result["iteraciones"] == 1


def test_escalar_si_se_agota_el_limite() -> None:
    deps, store = _deps(
        {
            "drafter": [(BAD, "fake-fast")],
            "judge": [JUDGE_REPARAR],
        },
        max_iter=1,
    )
    result = run(
        entrada="¿Puedo demandar el despido?",
        escenario="despido",
        modo="pregunta",
        deps=deps,
    )
    assert result["decision"] == "escalar"
    assert "9999" not in (result["respuesta_final"] or "")
    iid = __import__("uuid").UUID(result["intercepcion_id"])
    assert "9999" in store.intercepciones[iid]["borrador_original"]
