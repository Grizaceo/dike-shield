"""Adversarial bench: FAST/DEEP × with/without shield."""

from __future__ import annotations

import json
import statistics
import uuid
from pathlib import Path

from shield.env import ROOT
from shield.extractor import extract_regex
from shield.loop import Deps, run as shield_run

PREGUNTAS = ROOT / "data" / "samples" / "preguntas.jsonl"
RAW_SYSTEM = (
    "Eres un asistente jurídico chileno. Cita como artículo N del Código del Trabajo. "
    "Responde en español, 4 oraciones."
)


def load_preguntas(path: Path | None = None, n: int | None = None) -> list[dict]:
    target = path or PREGUNTAS
    rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
    if n is not None:
        rows = rows[: max(1, n)]
    return rows


def _count_citas(texto: str, detalles: list[dict] | None) -> tuple[int, int]:
    if detalles:
        total = len(detalles)
        bad = sum(1 for d in detalles if d.get("estado") == "FALLO")
        return total, bad
    extracted = extract_regex(texto)
    return len(extracted), 0


def _raw_answer(*, pregunta: str, lane: str, deps: Deps) -> tuple[str, str, int]:
    result = deps.llm.chat(
        lane=lane,  # type: ignore[arg-type]
        agent="drafter",
        max_tokens=2048,
        timeout=90,
        messages=[
            {"role": "system", "content": RAW_SYSTEM},
            {"role": "user", "content": pregunta},
        ],
    )
    return result.text, result.model, result.latency_ms


def run_bench(
    *,
    deps: Deps,
    n_preguntas: int = 30,
    lanes: list[str] | None = None,
    con_escudo: list[bool] | None = None,
    questions: list[dict] | None = None,
) -> list[str]:
    lanes = lanes or ["FAST", "DEEP"]
    flags = con_escudo if con_escudo is not None else [False, True]
    questions = questions or load_preguntas(n=n_preguntas)
    sample_mode = deps.sample_mode
    ids: list[str] = []
    for lane in lanes:
        for shielded in flags:
            cid = uuid.uuid4()
            citas_total = 0
            citas_bad = 0
            abstenciones = 0
            reparaciones = 0
            latencias: list[int] = []
            modelo = lane
            for q in questions:
                pregunta = str(q.get("pregunta") or "")
                qid = str(q.get("id") or uuid.uuid4())
                escenario = str(q.get("escenario") or "despido")
                if escenario not in {"despido", "finiquito", "libre"}:
                    escenario = "despido"
                if shielded:
                    result = shield_run(
                        entrada=pregunta,
                        escenario=escenario,
                        modo="pregunta",
                        deps=deps,
                    )
                    texto = result.get("respuesta_final") or ""
                    citas = result.get("citas") or []
                    total = len(citas)
                    bad = sum(1 for c in citas if isinstance(c, dict) and c.get("estado") == "FALLO")
                    decision = str(result.get("decision") or "escalar")
                    if decision == "abstener":
                        abstenciones += 1
                    if int(result.get("iteraciones") or 0) > 1:
                        reparaciones += 1
                    modelo = str((result.get("modelos") or {}).get("borrador") or modelo)
                    latencias.append(0)
                else:
                    texto, modelo, latency = _raw_answer(pregunta=pregunta, lane=lane, deps=deps)
                    dike = deps.verificar(texto)
                    detalles = [d for d in (dike.get("detalles") or []) if isinstance(d, dict)]
                    total, bad = _count_citas(texto, detalles)
                    decision = "medir"
                    latencias.append(latency)
                citas_total += total
                citas_bad += bad
                deps.store.save_banco_item(
                    {
                        "id": uuid.uuid4(),
                        "corrida_id": cid,
                        "pregunta_id": qid,
                        "respuesta": texto,
                        "citas_total": total,
                        "citas_no_probadas": bad,
                        "decision": decision,
                    }
                )
            p50 = int(statistics.median(latencias)) if latencias else 0
            deps.store.save_corrida(
                {
                    "id": cid,
                    "lane": lane,
                    "con_escudo": shielded,
                    "n_preguntas": len(questions),
                    "citas_total": citas_total,
                    "citas_no_probadas": citas_bad,
                    "abstenciones": abstenciones,
                    "reparaciones": reparaciones,
                    "latencia_p50_ms": p50,
                    "modelo": modelo,
                    "sample_mode": sample_mode,
                }
            )
            ids.append(str(cid))
    return ids
