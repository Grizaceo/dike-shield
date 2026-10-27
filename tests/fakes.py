"""Injected fakes for loop tests. Never talk to Nightshift."""

from __future__ import annotations

from shield.extractor import extract_regex
from shield.llm import LLMResult

KNOWN = {
    ("161", "Código del Trabajo"): ("cl.norma.ct:art:0161", "VERIFICADA", "RESOLVED"),
    ("168", "Código del Trabajo"): ("cl.norma.ct:art:0168", "VERIFICADA", "RESOLVED"),
}


class ScriptedLLM:
    def __init__(self, scripts: dict[str, list[tuple[str, str]]]) -> None:
        self.scripts = {key: list(val) for key, val in scripts.items()}
        self.calls: list[str] = []
        self.history: list[tuple[str, list]] = []

    def chat(self, *, lane, messages, agent, max_tokens=1024, temperature=0.2, timeout=60):
        del max_tokens, temperature, timeout
        self.calls.append(agent)
        self.history.append((agent, list(messages)))
        queue = self.scripts.get(agent)
        if not queue:
            raise RuntimeError(f"no scripted reply for agent={agent}")
        text, model = queue.pop(0)
        return LLMResult(text=text, model=model, latency_ms=1, lane=lane)


def fake_verificar(texto: str) -> dict:
    detalles = []
    for cite in extract_regex(texto):
        if not cite.cuerpo:
            detalles.append(
                {
                    "cita_raw": cite.normalized,
                    "gid": None,
                    "estado": "FALLO",
                    "resolucion": "AMBIGUOUS",
                    "vigencia": None,
                }
            )
            continue
        hit = KNOWN.get((cite.numero, cite.cuerpo))
        if hit:
            gid, estado, resol = hit
            detalles.append(
                {
                    "cita_raw": cite.normalized,
                    "gid": gid,
                    "estado": estado,
                    "resolucion": resol,
                    "vigencia": "IN_FORCE",
                }
            )
        else:
            detalles.append(
                {
                    "cita_raw": cite.normalized,
                    "gid": None,
                    "estado": "FALLO",
                    "resolucion": "UNRESOLVABLE",
                    "vigencia": None,
                }
            )
    fallos = sum(1 for d in detalles if d["estado"] == "FALLO")
    return {
        "veredicto": "TODAS_VERIFICADAS" if detalles and fallos == 0 else "CON_PROBLEMAS",
        "detalles": detalles,
        "meta": {
            "pack_hash": "af1422d66d1e6eee",
            "total_citas": len(detalles),
            "citas_verificadas": len(detalles) - fallos,
            "citas_fallidas": fallos,
        },
    }


def fake_fetch(gids: list[str]) -> list[dict]:
    catalog = {
        "cl.norma.ct:art:0161": {
            "gid": "cl.norma.ct:art:0161",
            "cuerpo": "Código del Trabajo",
            "numero": "161",
            "texto": "El contrato de trabajo terminará... necesidades de la empresa...",
        },
        "cl.norma.ct:art:0168": {
            "gid": "cl.norma.ct:art:0168",
            "cuerpo": "Código del Trabajo",
            "numero": "168",
            "texto": "El trabajador podrá reclamar... ante el juzgado de letras del trabajo.",
        },
    }
    return [catalog[g] for g in gids if g in catalog]


JUDGE_PUBLICAR = (
    '{"decision":"publicar","razon":"todas verificadas","acciones":[]}',
    "fake-judge",
)
JUDGE_REPARAR = (
    '{"decision":"reparar","razon":"hay una cita fallida","acciones":[]}',
    "fake-judge",
)
