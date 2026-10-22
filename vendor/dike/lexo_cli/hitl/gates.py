"""Fail-closed contracts for the four Diké human gates."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .models import GateState, GateType


@dataclass(frozen=True)
class GateContract:
    gate_type: GateType
    protected_effect: str
    timeout_hours: int
    decisions: dict[str, GateState]
    max_reopens: int = 1


_CONTRACTS = {
    GateType.HITL_1: GateContract(GateType.HITL_1, "autonomous_cycle", 72, {
        "APROBAR_CICLO": GateState.DECIDED_APPROVED,
        "AJUSTAR": GateState.DECIDED_CORRECTED,
        "RECHAZAR": GateState.DECIDED_REJECTED,
    }),
    GateType.HITL_2: GateContract(GateType.HITL_2, "personal_promotion", 720, {
        "ACEPTAR": GateState.DECIDED_APPROVED,
        "CORREGIR": GateState.DECIDED_CORRECTED,
        "RECHAZAR": GateState.DECIDED_REJECTED,
        "NO_SÉ": GateState.DECIDED_DEFERRED,
        "NO_SE": GateState.DECIDED_DEFERRED,
        "POSPONER": GateState.DECIDED_DEFERRED,
    }),
    GateType.HITL_3: GateContract(GateType.HITL_3, "temporal_export", 168, {
        "USO_LEGITIMO": GateState.DECIDED_APPROVED,
        "NO_USAR": GateState.DECIDED_REJECTED,
        "REVISAR_DESPUES": GateState.DECIDED_DEFERRED,
    }),
    GateType.HITL_4: GateContract(GateType.HITL_4, "final_opinion", 168, {
        "APROBAR_NIF": GateState.DECIDED_APPROVED,
        "CORREGIR_NIF": GateState.DECIDED_CORRECTED,
        "NO_CONCLUIR": GateState.DECIDED_REJECTED,
        "POSPONER": GateState.DECIDED_DEFERRED,
    }),
    GateType.HITL_5: GateContract(GateType.HITL_5, "nif_patch", 168, {
        "ACEPTAR": GateState.DECIDED_APPROVED,
        "CORREGIR": GateState.DECIDED_CORRECTED,
        "RECHAZAR": GateState.DECIDED_REJECTED,
        "POSPONER": GateState.DECIDED_DEFERRED,
    }),
}


def contract_for(gate_type: GateType | str) -> GateContract:
    return _CONTRACTS[GateType(gate_type)]


def decision_state(gate_type: GateType | str, decision: str) -> GateState:
    contract = contract_for(gate_type)
    normalized = decision.strip().upper()
    try:
        return contract.decisions[normalized]
    except KeyError as exc:
        valid = ", ".join(sorted(contract.decisions))
        raise ValueError(f"invalid decision for {contract.gate_type.value}: {decision}; valid: {valid}") from exc


def validate_hitl2_evidence(payload: dict) -> bool:
    required = ("source_path", "start_offset", "end_offset", "text_hash")
    if any(key not in payload for key in required):
        return False
    if not str(payload.get("source_path") or "").strip():
        return False
    start, end = payload.get("start_offset"), payload.get("end_offset")
    if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end <= start:
        return False
    return bool(re.fullmatch(r"[0-9a-fA-F]{64}", str(payload.get("text_hash") or "")))
