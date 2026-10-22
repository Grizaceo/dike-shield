"""Versioned, content-addressed receipts for effects approved through Diké HITL."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .models import HITLEvent, HITLGate, canonical_payload_hash


RECEIPT_SCHEMA_VERSION = "dike-effect-receipt-v1"


def build_effect_receipt(
    *,
    gate: HITLGate,
    approval: HITLEvent,
    effect_id: str,
    effect_type: str,
    input_payload: dict[str, Any],
    output_payload: dict[str, Any],
    binding: dict[str, Any] | None = None,
    recorded_at: datetime | None = None,
) -> dict[str, Any]:
    """Build an immutable receipt tying one output to one human decision.

    The receipt carries hashes rather than mutable runtime objects. Its caller
    persists it in the protected effect's own store, then includes this exact
    dict in the append-only HITL ``FINALIZED`` event through ``consume()``.
    """
    if not isinstance(effect_id, str) or not effect_id.strip():
        raise ValueError("effect_id is required")
    if not isinstance(effect_type, str) or not effect_type.strip():
        raise ValueError("effect_type is required")
    if approval.gate_id != gate.gate_id or approval.action != "DECIDED":
        raise ValueError("approval event does not belong to gate")
    if not (approval.principal_id and approval.authentication_method and approval.session_id):
        raise PermissionError("approved gate has no authenticated principal")
    ts = (recorded_at or datetime.now(UTC)).isoformat()
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "effect_id": effect_id,
        "effect_type": effect_type,
        "gate_id": gate.gate_id,
        "gate_type": gate.gate_type.value,
        "gate_payload_hash": canonical_payload_hash(gate.payload),
        "approval_event_id": approval.event_id,
        "approval_gate_hash": approval.gate_hash,
        "approved_principal": {
            "principal_id": approval.principal_id,
            "authentication_method": approval.authentication_method,
            "session_id": approval.session_id,
        },
        "input_hash": canonical_payload_hash(input_payload),
        "output_hash": canonical_payload_hash(output_payload),
        "binding_hash": canonical_payload_hash(binding or {}),
        "recorded_at": ts,
    }
    receipt["receipt_hash"] = canonical_payload_hash(receipt)
    return receipt
