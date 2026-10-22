"""Typed state and append-only event contracts for Diké HITL."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class GateType(str, Enum):
    HITL_1 = "HITL-1"
    HITL_2 = "HITL-2"
    HITL_3 = "HITL-3"
    HITL_4 = "HITL-4"
    HITL_5 = "HITL-5"


class GateState(str, Enum):
    IDLE = "IDLE"
    PENDING = "PENDING"
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    DECIDED_APPROVED = "DECIDED_APPROVED"
    DECIDED_REJECTED = "DECIDED_REJECTED"
    DECIDED_CORRECTED = "DECIDED_CORRECTED"
    DECIDED_DEFERRED = "DECIDED_DEFERRED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    INVALID = "INVALID"
    CONSUMED = "CONSUMED"


TERMINAL_STATES = {
    GateState.DECIDED_APPROVED,
    GateState.DECIDED_REJECTED,
    GateState.DECIDED_CORRECTED,
    GateState.DECIDED_DEFERRED,
    GateState.CANCELLED,
    GateState.INVALID,
    GateState.CONSUMED,
}


class InvalidTransition(ValueError):
    pass


def canonical_payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def canonical_gate_hash(gate: "HITLGate") -> str:
    """Seal every authority-bearing field of a materialized gate snapshot."""
    return canonical_payload_hash({
        "gate_id": gate.gate_id,
        "gate_type": gate.gate_type.value,
        "ref_type": gate.ref_type,
        "ref_id": gate.ref_id,
        "state": gate.state.value,
        "payload": gate.payload,
        "created_at": gate.created_at.isoformat(),
        "updated_at": gate.updated_at.isoformat(),
        "expires_at": gate.expires_at.isoformat() if gate.expires_at else None,
        "reopen_count": gate.reopen_count,
    })


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class AuthenticatedPrincipal:
    """Identity asserted by a trusted local boundary, never by request payload."""

    principal_id: str
    authentication_method: str
    session_id: str

    def __post_init__(self) -> None:
        for name, value in (
            ("principal_id", self.principal_id),
            ("authentication_method", self.authentication_method),
            ("session_id", self.session_id),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")

    @property
    def actor(self) -> str:
        return f"human:{self.principal_id}"


@dataclass(frozen=True)
class HITLGate:
    gate_id: str
    gate_type: GateType
    ref_type: str
    ref_id: str
    state: GateState
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    reopen_count: int = 0

    @classmethod
    def new(
        cls,
        gate_type: GateType,
        ref_type: str,
        ref_id: str,
        payload: dict[str, Any],
        *,
        gate_id: str | None = None,
        now: datetime | None = None,
        expires_at: datetime | None = None,
        state: GateState = GateState.PENDING,
    ) -> "HITLGate":
        if not (ref_type and ref_type.strip()):
            raise ValueError("ref_type is required")
        if not (ref_id and ref_id.strip()):
            raise ValueError("ref_id is required")
        ts = now or utc_now()
        return cls(gate_id or f"g_{uuid.uuid4().hex}", gate_type, ref_type, ref_id, state, dict(payload), ts, ts, expires_at)


@dataclass(frozen=True)
class HITLEvent:
    event_id: str
    ts: datetime
    gate_id: str
    gate_type: GateType
    ref_type: str
    ref_id: str
    actor: str
    action: str
    previous_state: GateState
    new_state: GateState
    payload_hash: str
    gate_hash: str
    decision: str | None = None
    evidence_links: tuple[str, ...] = field(default_factory=tuple)
    notes: str = ""
    corrections: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    principal_id: str | None = None
    authentication_method: str | None = None
    session_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


_ALLOWED = {
    GateState.PENDING: {GateState.REQUESTED, GateState.EXPIRED, GateState.CANCELLED},
    GateState.REQUESTED: {GateState.IN_REVIEW, GateState.EXPIRED, GateState.CANCELLED},
    GateState.IN_REVIEW: {
        GateState.DECIDED_APPROVED,
        GateState.DECIDED_REJECTED,
        GateState.DECIDED_CORRECTED,
        GateState.DECIDED_DEFERRED,
        GateState.EXPIRED,
        GateState.CANCELLED,
    },
    GateState.EXPIRED: {GateState.PENDING, GateState.CANCELLED},
    GateState.DECIDED_APPROVED: {GateState.EXPIRED, GateState.CONSUMED},
}


def transition_gate(
    gate: HITLGate,
    new_state: GateState,
    *,
    actor: str,
    action: str,
    decision: str | None = None,
    evidence_links: list[str] | tuple[str, ...] = (),
    notes: str = "",
    corrections: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    principal: AuthenticatedPrincipal | None = None,
    metadata: dict[str, Any] | None = None,
    now: datetime | None = None,
    max_reopens: int = 1,
) -> tuple[HITLGate, HITLEvent]:
    if not (actor and actor.strip()):
        raise InvalidTransition("actor is required")
    human_transition = (
        new_state in {
            GateState.IN_REVIEW,
            GateState.DECIDED_APPROVED,
            GateState.DECIDED_REJECTED,
            GateState.DECIDED_CORRECTED,
            GateState.DECIDED_DEFERRED,
            GateState.CONSUMED,
        }
        or (gate.state is GateState.EXPIRED and new_state is GateState.PENDING)
    )
    if human_transition and (principal is None or actor != principal.actor):
        raise InvalidTransition("authenticated principal required for human transition")
    allowed = _ALLOWED.get(gate.state, set())
    if new_state not in allowed:
        raise InvalidTransition(f"transition {gate.state.value} -> {new_state.value} is not allowed")
    reopen_count = gate.reopen_count
    if gate.state is GateState.EXPIRED and new_state is GateState.PENDING:
        if reopen_count >= max_reopens:
            raise InvalidTransition("reactivation limit reached")
        reopen_count += 1
    ts = now or utc_now()
    changed = replace(gate, state=new_state, updated_at=ts, reopen_count=reopen_count)
    event = HITLEvent(
        event_id=f"evt_{uuid.uuid4().hex}",
        ts=ts,
        gate_id=gate.gate_id,
        gate_type=gate.gate_type,
        ref_type=gate.ref_type,
        ref_id=gate.ref_id,
        actor=actor,
        action=action,
        previous_state=gate.state,
        new_state=new_state,
        decision=decision,
        payload_hash=canonical_payload_hash(gate.payload),
        gate_hash=canonical_gate_hash(changed),
        evidence_links=tuple(evidence_links),
        notes=notes,
        corrections=tuple(corrections),
        principal_id=principal.principal_id if principal else None,
        authentication_method=principal.authentication_method if principal else None,
        session_id=principal.session_id if principal else None,
        metadata=dict(metadata or {}),
    )
    return changed, event
