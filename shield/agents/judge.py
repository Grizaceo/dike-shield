"""DEEP judge. Code still forbids publishing a FALLO citation."""

from __future__ import annotations

from dataclasses import dataclass, field

from shield.jsonutil import parse_object
from shield.llm import LLMClient, LLMError, LLMResult

DECISIONS = ("publicar", "reparar", "abstener", "escalar")
ACCIONES = ("mantener", "reparar", "retirar")


@dataclass
class AccionCita:
    cita_raw: str
    accion: str
    reemplazo_gid: str | None
    razon: str


@dataclass
class Juicio:
    decision: str
    razon: str
    acciones: list[AccionCita] = field(default_factory=list)
    llm: LLMResult | None = None


_SYSTEM = """Eres el juez de Diké Shield. Recibes veredictos de Diké (no los reinterpretas).
Decide una de: publicar, reparar, abstener, escalar.
Reglas duras:
- publicar SOLO si todas las citas del texto vigente tienen estado VERIFICADA (o no hay citas).
- reparar si hay FALLO y aún se puede reescribir.
- abstener si el fondo queda fuera del corpus.
- escalar si no se puede reparar con lo verificado.
Responde SOLO JSON:
{"decision":"...","razon":"...","acciones":[{"cita_raw":"...","accion":"mantener|reparar|retirar","reemplazo_gid":null,"razon":"..."}]}
Las opiniones de fondo son del modelo, no verificadas.
"""


def _default_acciones(detalles: list[dict]) -> list[AccionCita]:
    out: list[AccionCita] = []
    for d in detalles:
        estado = d.get("estado")
        resol = d.get("resolucion") or ""
        raw = str(d.get("cita_raw") or "")
        if estado == "VERIFICADA":
            out.append(AccionCita(raw, "mantener", None, "verificada por Diké"))
        elif resol == "UNRESOLVABLE":
            out.append(AccionCita(raw, "retirar", None, "Diké: UNRESOLVABLE"))
        else:
            out.append(AccionCita(raw, "reparar", None, f"Diké: {resol}"))
    return out


def coerce_decision(decision: str, detalles: list[dict], *, iteracion: int, max_iter: int) -> str:
    if decision not in DECISIONS:
        decision = "reparar"
    fallos = [d for d in detalles if d.get("estado") == "FALLO"]
    if not fallos:
        # Diké already cleared every citation. Looping on "reparar" burns the cap.
        return "publicar" if decision != "abstener" else "abstener"
    if decision == "publicar":
        decision = "reparar"
    if decision == "reparar" and iteracion >= max_iter:
        decision = "escalar"
    return decision


def decide(
    *,
    texto: str,
    detalles: list[dict],
    articulos: list[dict],
    iteracion: int,
    max_iter: int,
    llm: LLMClient,
) -> Juicio:
    fallback = _default_acciones(detalles)
    fallos = [d for d in detalles if d.get("estado") == "FALLO"]
    default_decision = "publicar" if not fallos else ("reparar" if iteracion < max_iter else "escalar")
    user = (
        f"iteracion={iteracion}/{max_iter}\n"
        f"texto:\n{texto[:4000]}\n\n"
        f"veredictos_dike:\n{detalles}\n\n"
        f"articulos_verificados:\n{articulos}"
    )
    result: LLMResult | None = None
    decision = default_decision
    razon = "regla: " + ("todas VERIFICADA" if not fallos else f"{len(fallos)} FALLO")
    acciones = fallback
    try:
        result = llm.chat(
            lane="DEEP",
            agent="judge",
            temperature=0,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        payload = parse_object(result.text)
        decision = str(payload.get("decision") or default_decision)
        razon = str(payload.get("razon") or razon)
        raw_acc = payload.get("acciones") or []
        parsed: list[AccionCita] = []
        if isinstance(raw_acc, list):
            for item in raw_acc:
                if not isinstance(item, dict):
                    continue
                acc = str(item.get("accion") or "retirar")
                if acc not in ACCIONES:
                    acc = "retirar"
                parsed.append(
                    AccionCita(
                        cita_raw=str(item.get("cita_raw") or ""),
                        accion=acc,
                        reemplazo_gid=item.get("reemplazo_gid"),
                        razon=str(item.get("razon") or ""),
                    )
                )
        if parsed:
            acciones = parsed
    except (LLMError, ValueError):
        pass
    decision = coerce_decision(decision, detalles, iteracion=iteracion, max_iter=max_iter)
    by_raw = {a.cita_raw: a for a in acciones}
    merged: list[AccionCita] = []
    for d in detalles:
        raw = str(d.get("cita_raw") or "")
        if raw in by_raw:
            acc = by_raw[raw]
            if d.get("estado") == "VERIFICADA":
                acc = AccionCita(raw, "mantener", acc.reemplazo_gid, acc.razon or "verificada")
            elif decision == "escalar":
                acc = AccionCita(raw, "retirar", None, acc.razon or "escalar: se retira lo no probado")
            merged.append(acc)
        else:
            merged.extend(_default_acciones([d]))
    if decision == "publicar" and fallos:
        decision = coerce_decision("reparar", detalles, iteracion=iteracion, max_iter=max_iter)
    return Juicio(decision=decision, razon=razon, acciones=merged, llm=result)
