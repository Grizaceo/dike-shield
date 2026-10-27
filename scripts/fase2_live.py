#!/usr/bin/env python3
"""Live phase-2 run against Nightshift. Never prints secrets."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.env import load_env, redact, secret_values  # noqa: E402
from shield.loop import build_deps, run  # noqa: E402

PREGUNTA = (
    "Me despidieron invocando necesidades de la empresa después de cuatro años "
    "en la misma pyme. ¿Puedo demandar, qué plazo tengo y qué normas aplican? "
    "Cita artículos concretos."
)
AUDITORIA = (
    "Según el artículo 9999 del Código del Trabajo el trabajador no puede demandar. "
    "El artículo 168 del Código del Trabajo permite reclamar el despido."
)


def summarize(label: str, result: dict, store, secrets: list[str]) -> None:
    iid = uuid.UUID(result["intercepcion_id"])
    row = store.get_intercepcion(iid) or {}
    draft = row.get("borrador_original") or ""
    final = result.get("respuesta_final") or ""
    trazas = store.list_trazas(iid)
    models = sorted({e.modelo for e in trazas if e.modelo})
    print(f"=== {label} ===")
    print(f"decision={result['decision']} iter={result['iteraciones']}")
    print(f"modelos_resultado={result['modelos']}")
    print(f"traza_n={len(trazas)} modelos_traza={models}")
    for e in trazas:
        print(
            f"  paso={e.paso} {e.agente}/{e.accion} lane={e.lane} "
            f"model={e.modelo} {e.latencia_ms}ms"
        )
    print(f"draft_chars={len(draft)} final_chars={len(final)}")
    print(f"draft_has_9999={'9999' in draft} final_has_9999={'9999' in final}")
    print(f"citas={[ (c.get('cita_raw'), c.get('estado'), c.get('accion')) for c in result['citas'] ]}")
    _ = secrets, redact


def main() -> int:
    env = load_env()
    secrets = secret_values(env)
    deps = build_deps(env)
    print("=== answer despido ===")
    try:
        result = run(
            entrada=PREGUNTA,
            escenario="despido",
            modo="pregunta",
            deps=deps,
        )
    except Exception as exc:
        print("FAIL answer", redact(str(exc)[:300], secrets))
        return 1
    summarize("answer", result, deps.store, secrets)

    print("=== audit texto con 9999 ===")
    try:
        audit = run(
            entrada=AUDITORIA,
            escenario="despido",
            modo="auditoria",
            deps=deps,
        )
    except Exception as exc:
        print("FAIL audit", redact(str(exc)[:300], secrets))
        return 1
    summarize("audit", audit, deps.store, secrets)
    print("PASS live phase2 completed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
