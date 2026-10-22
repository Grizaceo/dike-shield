"""plan.py — NIF Plan Resolver (T4).

Deriva el plan de ejecución del pipeline desde el NIF + el Diké Circuit
Contract. Reemplaza el plan hard-codeado de preguntar/analizar: en vez de
"crear NIF → buscar index libre → juez+contradictor" siempre, el NIF decide
QUÉ capas consultar, QUÉ normas (GIDs), QUÉ gaps resolver y QUÉ gate HITL
aplicar.

La unidad interna es el plan derivado, no el chain-of-thought libre. El plan
es un artefacto portable y auditable (JSON) que el pipeline consume.

Regla de circuito (fail-closed):
  - Normas en el NIF con status vigente/derogada → capa canonical (qué dice
    la ley). Si hay norma con status derogada + señal temporal → requiere
    HITL-3.
  - Gaps abiertos de impacto alto → capa index (jurisprudencia/corpus
    adquirido) + demanda de llenado.
  - Sin hipótesis ni normas ancladas → el plan marca INSUFFICIENT_GROUNDING
    y no emite opinión final (HITL-4 bloqueado).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CIRCUIT_PATH = Path(__file__).resolve().parent.parent / "circuit" / "dike_circuit_contract.yaml"

# Capa por comando según el contrato (respaldo; el plan lee el YAML real).
_DEFAULT_LAYERS_BY_COMMAND = {
    "preguntar": ["canonical", "index"],
    "analizar": ["index", "canonical"],
    "contradecir": ["index"],
}


@dataclass(frozen=True)
class PlanStep:
    layer: str          # canonical | index | review | pichanga | vault
    action: str         # consult_norm | search_corpus | fill_gap | review_candidate
    gids: tuple[str, ...] = ()
    query: str = ""
    rationale: str = ""


@dataclass
class ExecutionPlan:
    command: str
    layers: list[str] = field(default_factory=list)
    steps: list[PlanStep] = field(default_factory=list)
    norm_gids: list[str] = field(default_factory=list)
    open_gaps: list[str] = field(default_factory=list)
    disputed_hypotheses: list[str] = field(default_factory=list)
    required_hitl: list[str] = field(default_factory=list)
    epistemic_state: str = "PLANNED"
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "command": self.command,
            "layers": self.layers,
            "steps": [s.__dict__ for s in self.steps],
            "norm_gids": self.norm_gids,
            "open_gaps": self.open_gaps,
            "disputed_hypotheses": self.disputed_hypotheses,
            "required_hitl": self.required_hitl,
            "epistemic_state": self.epistemic_state,
            "reasons": self.reasons,
        }


def _load_contract() -> dict:
    if not CIRCUIT_PATH.exists():
        return {}
    with open(CIRCUIT_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _layer_for(command: str, contract: dict) -> list[str]:
    variants = contract.get("command_variants", {})
    entry = variants.get(command)
    if entry and entry.get("layers"):
        return list(entry["layers"])
    return list(_DEFAULT_LAYERS_BY_COMMAND.get(command, ["canonical", "index"]))


def _hitl_for(command: str, contract: dict) -> list[str]:
    variants = contract.get("command_variants", {})
    entry = variants.get(command)
    if entry and entry.get("hitl"):
        return list(entry["hitl"])
    return []


def resolve_plan(
    nif: dict,
    *,
    command: str = "preguntar",
    contract: dict | None = None,
) -> ExecutionPlan:
    """Derive the execution plan from the NIF + circuit contract.

    Args:
        nif: The NormativeInteractionFrame as a dict (from board.read()).
        command: Which Diké command is running (preguntar/analizar/...).
        contract: Pre-loaded circuit contract (for tests); otherwise read live.

    Returns:
        ExecutionPlan with concrete steps the pipeline must follow.
    """
    contract = contract if contract is not None else _load_contract()
    nif = nif or {}

    plan = ExecutionPlan(command=command)
    plan.layers = _layer_for(command, contract)
    plan.required_hitl = list(_hitl_for(command, contract))

    norms = nif.get("norms") or []
    hypotheses = nif.get("hypotheses") or []
    gaps = nif.get("gaps") or []
    facts = nif.get("facts") or {}
    known = facts.get("known") or []
    question = nif.get("legal_question") or ""

    # --- 1. Normas → canonical (qué dice la ley) ------------------------
    for norm in norms:
        gid = norm.get("gid") or ""
        status = norm.get("status") or "indeterminada"
        if not gid:
            plan.reasons.append(
                f"Norma sin GID resoluble: {norm.get('label') or '<sin-etiqueta>'}"
            )
            continue
        plan.norm_gids.append(gid)
        step_layer = "canonical" if status == "vigente" else "review"
        rationale = (f"consulta norma {gid} ({status}) en {step_layer}")
        plan.steps.append(PlanStep(
            layer=step_layer, action="consult_norm",
            gids=(gid,), query=norm.get("label") or gid, rationale=rationale,
        ))
        # Cualquier estado distinto de vigente requiere resolución temporal
        # contextual y revisión humana; no se degrada a canonical por defecto.
        if status != "vigente":
            plan.required_hitl.append("HITL-3")
            plan.reasons.append(
                f"Norma con vigencia {status} {gid}: requiere HITL-3 (vigencia contextual)"
            )

    # --- 2. Gaps abiertos de alto impacto → index + fill -----------------
    for gap in gaps:
        if gap.get("status") in ("open", "in_progress"):
            desc = gap.get("description") or "gap"
            plan.open_gaps.append(desc)
            plan.steps.append(PlanStep(
                layer="index", action="fill_gap",
                query=desc, rationale=f"gap abierto: {desc}",
            ))
            if gap.get("impact") == "alto":
                plan.reasons.append(f"Gap de impacto alto abierto: {desc}")

    # --- 3. Hipótesis disputadas → replan / no opinión final ------------
    for h in hypotheses:
        if h.get("status") == "disputed":
            plan.disputed_hypotheses.append(h.get("id") or h.get("claim") or "?")
            plan.reasons.append(f"Hipótesis disputada: {h.get('claim', '?')}")
    if plan.disputed_hypotheses:
        plan.required_hitl.append("HITL-1")

    # --- 4. Grounding insuficiente → no opinión final (fail-closed) ------
    if not norms:
        plan.reasons.append("Sin normas ancladas: grounding insuficiente")
    elif not plan.norm_gids:
        plan.reasons.append("Sin GIDs normativos resolubles: grounding insuficiente")
    if not hypotheses:
        plan.reasons.append("Sin hipótesis: grounding insuficiente")
        if command == "preguntar":
            plan.epistemic_state = "INSUFFICIENT_GROUNDING"
    if not known and not question:
        plan.reasons.append("Sin hechos ni pregunta: no hay plan viable")
    if plan.reasons and not plan.norm_gids and not plan.open_gaps:
        plan.epistemic_state = "INSUFFICIENT_GROUNDING"

    # --- 5. Search steps from norms + question + known facts ------------
    if plan.norm_gids:
        plan.steps.append(PlanStep(
            layer="index", action="search_corpus",
            gids=tuple(plan.norm_gids[:5]),
            query=question or " ".join(plan.norm_gids[:3]),
            rationale="búsqueda de corpus/jurisprudencia sobre normas del NIF",
        ))

    return plan
