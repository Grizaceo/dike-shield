"""UI labels and static routes. No Nightshift."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from shield.api import WEB, create_app
from shield.db import MemoryStore
from shield.engines import Memory
from shield.loop import Deps
from tests.fakes import JUDGE_PUBLICAR, ScriptedLLM, fake_fetch, fake_verificar
from tests.test_loop import GOOD


def test_mandatory_labels_in_ui_files() -> None:
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "app.js").read_text(encoding="utf-8")
    blob = html + js
    assert "Probado por Diké: existe, tiene texto citable y estaba vigente al" in blob
    assert "Diké no evalúa si la norma respalda el argumento; eso es juicio del abogado" in blob
    assert "Opinión del modelo" in blob
    assert "Cifras medidas sobre" in blob
    assert "no son una estimación de la tasa en producción" in blob
    assert "Modo muestra: respuestas grabadas de una corrida real del" in blob


def test_ui_and_bench_endpoints() -> None:
    store = MemoryStore()
    deps = Deps(
        llm=ScriptedLLM(
            {
                "drafter": [(GOOD, "fake-fast"), (GOOD, "fake-fast")],
                "judge": [JUDGE_PUBLICAR, JUDGE_PUBLICAR],
            }
        ),
        store=store,
        memory=Memory(base_url="http://127.0.0.1:1", timeout=0.2),
        env={"SAMPLE_MODE": "false"},
        verificar=fake_verificar,
        fetch_articulos=fake_fetch,
        emitir=lambda *_a, **_k: None,
        sample_mode=False,
    )
    client = TestClient(create_app(deps))
    home = client.get("/")
    assert home.status_code == 200
    assert "Diké Shield" in home.text
    css = client.get("/web/styles.css")
    assert css.status_code == 200
    sample = client.get("/samples/despido_01.md")
    assert sample.status_code == 200
    assert "artículo 161" in sample.text
    fin = client.get("/samples/finiquito_01.md")
    assert fin.status_code == 200
    ran = client.post(
        "/v1/bench/run",
        json={"n_preguntas": 1, "lanes": ["FAST"], "con_escudo": [True]},
    )
    assert ran.status_code == 200
    assert ran.json()["corrida_ids"]
    latest = client.get("/v1/bench/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert "Cifras medidas sobre" in body["etiqueta"]
    missing = client.get("/v1/commitments/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404


def test_samples_exist() -> None:
    root = Path(__file__).resolve().parents[1] / "data" / "samples"
    trampas = [line for line in (root / "trampas.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(trampas) == 20
    assert (root / "despido_01.md").is_file()
    assert (root / "finiquito_01.md").is_file()
