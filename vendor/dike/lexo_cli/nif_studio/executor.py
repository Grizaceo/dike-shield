"""Executable, fail-closed NIF plans with explicit backend provenance."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Protocol

from .plan import ExecutionPlan, PlanStep


@dataclass(frozen=True)
class SearchOutcome:
    results: list[dict]
    backend: str
    degraded: bool
    errors: list[str]


@dataclass(frozen=True)
class StepExecution:
    step_index: int
    step: dict[str, Any]
    status: str
    backend: str | None = None
    degraded: bool = False
    evidence: list[dict] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PlanExecution:
    status: str
    plan: dict[str, Any]
    steps: list[StepExecution]
    evidence: list[dict]
    reasons: list[str]
    pending_hitl: list[str] = field(default_factory=list)
    finalization_allowed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "plan": self.plan,
            "steps": [step.to_dict() for step in self.steps],
            "evidence": self.evidence,
            "reasons": self.reasons,
            "pending_hitl": self.pending_hitl,
            "finalization_allowed": self.finalization_allowed,
        }


class CanonicalResolver(Protocol):
    def resolve_many(self, gids): ...


IndexSearch = Callable[[str, tuple[str, ...], str], SearchOutcome]


def _step_dict(step: PlanStep) -> dict[str, Any]:
    return {
        "layer": step.layer,
        "action": step.action,
        "gids": list(step.gids),
        "query": step.query,
        "rationale": step.rationale,
    }


def execute_plan(
    plan: ExecutionPlan,
    *,
    area: str,
    index_search: IndexSearch,
    canonical_resolver: CanonicalResolver | None = None,
    canonical_unavailable_reason: str = "",
) -> PlanExecution:
    """Execute every declared step or abstain; no step is silently ignored."""
    plan_payload = plan.to_dict()
    pending_hitl = list(dict.fromkeys(plan.required_hitl))
    blocking_hitl = [gate for gate in pending_hitl if gate in {"HITL-1", "HITL-3"}]
    finalization_allowed = "HITL-4" not in pending_hitl
    if plan.epistemic_state == "INSUFFICIENT_GROUNDING":
        reasons = list(plan.reasons) or ["Grounding insuficiente"]
        return PlanExecution(
            "abstain", plan_payload, [], [], reasons,
            pending_hitl, False,
        )
    if blocking_hitl:
        reasons = [f"{gate} pendiente: ejecución bloqueada" for gate in blocking_hitl]
        return PlanExecution(
            "abstain", plan_payload, [], [], reasons,
            pending_hitl, False,
        )

    steps: list[StepExecution] = []
    evidence: list[dict] = []
    reasons: list[str] = []

    for index, step in enumerate(plan.steps):
        step_payload = _step_dict(step)
        if step.layer == "canonical" and step.action == "consult_norm":
            if canonical_resolver is None:
                reason = "Resolver canónico no disponible"
                if canonical_unavailable_reason:
                    reason = f"{reason}: {canonical_unavailable_reason}"
                steps.append(StepExecution(index, step_payload, "blocked", error=reason))
                reasons.append(reason)
                continue
            try:
                resolved = canonical_resolver.resolve_many(step.gids)
                items = [item.to_dict() if hasattr(item, "to_dict") else dict(item) for item in resolved]
            except Exception as exc:
                reason = f"Consulta canónica falló: {exc}"
                steps.append(StepExecution(index, step_payload, "failed", backend="starter", error=reason))
                reasons.append(reason)
                continue
            if not step.gids or [item.get("gid") for item in items] != list(step.gids):
                reason = "Consulta canónica incompleta o GID no coincidente"
                steps.append(StepExecution(
                    index, step_payload, "blocked", backend="starter",
                    evidence=items, error=reason,
                ))
                reasons.append(reason)
                continue
            unsafe = [
                item for item in items
                if item.get("citation_status") != "CITABLE"
                or item.get("temporal_status") != "IN_FORCE"
            ]
            if unsafe:
                states = ", ".join(
                    f"{item.get('gid', '?')}="
                    f"{item.get('citation_status', 'UNKNOWN')}/"
                    f"{item.get('temporal_status', 'UNKNOWN')}"
                    for item in unsafe
                )
                reason = f"Evidencia canónica no utilizable: {states}"
                steps.append(StepExecution(
                    index, step_payload, "blocked", backend="starter",
                    evidence=items, error=reason,
                ))
                reasons.append(reason)
                continue
            evidence.extend(items)
            steps.append(StepExecution(index, step_payload, "completed", backend="starter", evidence=items))
            continue

        if step.layer == "review" and step.action == "consult_norm":
            reason = "HITL-3 requerido para norma en revisión temporal"
            steps.append(StepExecution(index, step_payload, "blocked", error=reason))
            reasons.append(reason)
            continue

        if step.layer == "index" and step.action in {"search_corpus", "fill_gap"}:
            try:
                outcome = index_search(step.query, step.gids, area)
                if not isinstance(outcome, SearchOutcome):
                    raise TypeError("adaptador index debe devolver SearchOutcome")
            except Exception as exc:
                reason = f"Backend index falló: {exc}"
                steps.append(StepExecution(index, step_payload, "failed", backend="index", error=reason))
                reasons.append(reason)
                continue
            if outcome.errors and not outcome.results:
                reason = "; ".join(outcome.errors)
                steps.append(StepExecution(
                    index, step_payload, "failed", backend=outcome.backend,
                    degraded=outcome.degraded, error=reason,
                ))
                reasons.append(reason)
                continue
            if not outcome.results:
                reason = f"Búsqueda sin evidencia para {step.action}: {step.query}"
                steps.append(StepExecution(
                    index, step_payload, "searched_unresolved", backend=outcome.backend,
                    degraded=outcome.degraded, error=reason,
                ))
                reasons.append(reason)
                continue
            if outcome.degraded or outcome.errors:
                reason = "; ".join(outcome.errors) or f"Backend degradado: {outcome.backend}"
                steps.append(StepExecution(
                    index, step_payload, "blocked", backend=outcome.backend,
                    degraded=outcome.degraded, evidence=[dict(item) for item in outcome.results],
                    error=reason,
                ))
                reasons.append(reason)
                continue
            status = "searched_unresolved" if step.action == "fill_gap" else "completed"
            items = [dict(item) for item in outcome.results]
            evidence.extend(items)
            steps.append(StepExecution(
                index, step_payload, status, backend=outcome.backend,
                degraded=outcome.degraded, evidence=items,
                error="; ".join(outcome.errors) if outcome.errors else None,
            ))
            continue

        reason = f"Paso no soportado: {step.layer}/{step.action}"
        steps.append(StepExecution(index, step_payload, "blocked", error=reason))
        reasons.append(reason)

    blocked = any(
        step.status in {"blocked", "failed"}
        or (step.status == "searched_unresolved" and not step.evidence)
        for step in steps
    )
    return PlanExecution(
        "abstain" if blocked else "completed",
        plan_payload,
        steps,
        evidence,
        reasons,
        pending_hitl,
        finalization_allowed and not blocked,
    )
