"""SQLite WAL persistence and fail-closed transitions for Diké HITL."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from .gates import contract_for, decision_state, validate_hitl2_evidence
from .models import (
    AuthenticatedPrincipal,
    GateState,
    GateType,
    HITLEvent,
    HITLGate,
    canonical_gate_hash,
    canonical_payload_hash,
    transition_gate,
    utc_now,
)


class HITLJournalIntegrityError(RuntimeError):
    """Materialized gate state no longer matches its append-only journal."""


class HITLService:
    def __init__(self, db_path: str | Path, *, clock: Callable[[], datetime] = utc_now):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _initialize(self) -> None:
        with self._connect() as con:
            con.execute("PRAGMA journal_mode=WAL")
            con.execute("PRAGMA foreign_keys=ON")
            con.executescript("""
                CREATE TABLE IF NOT EXISTS hitl_gates (
                    gate_id TEXT PRIMARY KEY,
                    gate_type TEXT NOT NULL,
                    ref_type TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    state TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT,
                    reopen_count INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS hitl_events (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    ts TEXT NOT NULL,
                    gate_id TEXT NOT NULL,
                    gate_type TEXT NOT NULL,
                    ref_type TEXT NOT NULL,
                    ref_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    previous_state TEXT NOT NULL,
                    new_state TEXT NOT NULL,
                    decision TEXT,
                    payload_hash TEXT NOT NULL,
                    gate_hash TEXT,
                    evidence_links_json TEXT NOT NULL,
                    notes TEXT NOT NULL,
                    corrections_json TEXT NOT NULL,
                    principal_id TEXT,
                    authentication_method TEXT,
                    session_id TEXT,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    FOREIGN KEY(gate_id) REFERENCES hitl_gates(gate_id)
                );
                CREATE TRIGGER IF NOT EXISTS hitl_events_no_update
                BEFORE UPDATE ON hitl_events BEGIN SELECT RAISE(ABORT, 'hitl_events is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS hitl_events_no_delete
                BEFORE DELETE ON hitl_events BEGIN SELECT RAISE(ABORT, 'hitl_events is append-only'); END;
            """)
            columns = {row[1] for row in con.execute("PRAGMA table_info(hitl_events)")}
            migrations = {
                "principal_id": "ALTER TABLE hitl_events ADD COLUMN principal_id TEXT",
                "authentication_method": "ALTER TABLE hitl_events ADD COLUMN authentication_method TEXT",
                "session_id": "ALTER TABLE hitl_events ADD COLUMN session_id TEXT",
                "metadata_json": "ALTER TABLE hitl_events ADD COLUMN metadata_json TEXT NOT NULL DEFAULT '{}'",
                "gate_hash": "ALTER TABLE hitl_events ADD COLUMN gate_hash TEXT",
            }
            for column, statement in migrations.items():
                if column not in columns:
                    con.execute(statement)

    def journal_mode(self) -> str:
        with self._connect() as con:
            return str(con.execute("PRAGMA journal_mode").fetchone()[0])

    def create_gate(
        self,
        gate_type: GateType | str,
        ref_type: str,
        ref_id: str,
        payload: dict,
        *,
        actor: str = "system:dike",
        expires_at: datetime | None = None,
    ) -> HITLGate:
        gate_type = GateType(gate_type)
        now = self.clock()
        if expires_at is None:
            expires_at = now + timedelta(hours=contract_for(gate_type).timeout_hours)
        state = GateState.PENDING
        if gate_type in (GateType.HITL_2, GateType.HITL_5) and not validate_hitl2_evidence(payload):
            state = GateState.INVALID
        gate = HITLGate.new(gate_type, ref_type, ref_id, payload, now=now, expires_at=expires_at, state=state)
        event = HITLEvent(
            event_id=f"evt_{gate.gate_id[2:]}", ts=now, gate_id=gate.gate_id,
            gate_type=gate.gate_type, ref_type=ref_type, ref_id=ref_id, actor=actor,
            action="INVALID" if state is GateState.INVALID else "DETECTED",
            previous_state=GateState.IDLE, new_state=state,
            payload_hash=canonical_payload_hash(payload),
            gate_hash=canonical_gate_hash(gate),
            notes="invalid evidence" if state is GateState.INVALID else "",
        )
        with self._connect() as con:
            self._insert_gate(con, gate)
            self._insert_event(con, event)
        return gate

    def _insert_gate(self, con: sqlite3.Connection, gate: HITLGate) -> None:
        con.execute(
            "INSERT INTO hitl_gates VALUES (?,?,?,?,?,?,?,?,?,?)",
            (gate.gate_id, gate.gate_type.value, gate.ref_type, gate.ref_id, gate.state.value,
             json.dumps(gate.payload, ensure_ascii=False, sort_keys=True), gate.created_at.isoformat(),
             gate.updated_at.isoformat(), gate.expires_at.isoformat() if gate.expires_at else None,
             gate.reopen_count),
        )

    def _insert_event(self, con: sqlite3.Connection, event: HITLEvent) -> None:
        con.execute(
            "INSERT INTO hitl_events (event_id,ts,gate_id,gate_type,ref_type,ref_id,actor,action,previous_state,new_state,decision,payload_hash,gate_hash,evidence_links_json,notes,corrections_json,principal_id,authentication_method,session_id,metadata_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (event.event_id, event.ts.isoformat(), event.gate_id, event.gate_type.value,
             event.ref_type, event.ref_id, event.actor, event.action, event.previous_state.value,
             event.new_state.value, event.decision, event.payload_hash, event.gate_hash,
             json.dumps(event.evidence_links, ensure_ascii=False), event.notes,
             json.dumps(event.corrections, ensure_ascii=False, sort_keys=True), event.principal_id,
             event.authentication_method, event.session_id,
             json.dumps(event.metadata, ensure_ascii=False, sort_keys=True)),
        )

    def _persist_transition(self, gate: HITLGate, event: HITLEvent, *, expected: HITLGate) -> HITLGate:
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM hitl_gates WHERE gate_id=?", (gate.gate_id,)).fetchone()
            if row is None:
                raise KeyError(gate.gate_id)
            current = self._row_gate(row)
            self._verify_gate_against_journal(current, con=con)
            if canonical_gate_hash(current) != canonical_gate_hash(expected):
                raise HITLJournalIntegrityError(f"gate {gate.gate_id} changed concurrently")
            changed = con.execute(
                "UPDATE hitl_gates SET state=?, updated_at=?, reopen_count=? WHERE gate_id=? AND state=? AND updated_at=?",
                (
                    gate.state.value, gate.updated_at.isoformat(), gate.reopen_count, gate.gate_id,
                    expected.state.value, expected.updated_at.isoformat(),
                ),
            ).rowcount
            if changed != 1:
                raise HITLJournalIntegrityError(f"gate {gate.gate_id} transition lost CAS")
            self._insert_event(con, event)
        return gate

    def get_gate(self, gate_id: str) -> HITLGate:
        with self._connect() as con:
            row = con.execute("SELECT * FROM hitl_gates WHERE gate_id=?", (gate_id,)).fetchone()
        if row is None:
            raise KeyError(gate_id)
        return self._row_gate(row)

    @staticmethod
    def _dt(value: str | None) -> datetime | None:
        return datetime.fromisoformat(value) if value else None

    def _row_gate(self, row: sqlite3.Row) -> HITLGate:
        return HITLGate(
            gate_id=row["gate_id"], gate_type=GateType(row["gate_type"]), ref_type=row["ref_type"],
            ref_id=row["ref_id"], state=GateState(row["state"]), payload=json.loads(row["payload_json"]),
            created_at=datetime.fromisoformat(row["created_at"]), updated_at=datetime.fromisoformat(row["updated_at"]),
            expires_at=self._dt(row["expires_at"]), reopen_count=int(row["reopen_count"]),
        )

    def list_gates(self, *, gate_type: GateType | str | None = None, state: GateState | str | None = None) -> list[HITLGate]:
        clauses, params = [], []
        if gate_type is not None:
            clauses.append("gate_type=?"); params.append(GateType(gate_type).value)
        if state is not None:
            clauses.append("state=?"); params.append(GateState(state).value)
        query = "SELECT * FROM hitl_gates" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY created_at, gate_id"
        with self._connect() as con:
            return [self._row_gate(row) for row in con.execute(query, params).fetchall()]

    def _transition(
        self,
        gate_id: str,
        state: GateState,
        *,
        actor: str,
        action: str,
        decision: str | None = None,
        notes: str = "",
        corrections: list[dict] | None = None,
        principal: AuthenticatedPrincipal | None = None,
        metadata: dict | None = None,
        enforce_expiry: bool = True,
    ) -> HITLGate:
        gate = self.get_gate(gate_id)
        self._verify_gate_against_journal(gate)
        if enforce_expiry and self._is_expired(gate):
            self._expire_gate(gate)
            raise PermissionError("gate expired")
        changed, event = transition_gate(
            gate, state, actor=actor, action=action, decision=decision, notes=notes,
            corrections=corrections or [], principal=principal, metadata=metadata,
            now=self.clock(), max_reopens=contract_for(gate.gate_type).max_reopens,
        )
        return self._persist_transition(changed, event, expected=gate)

    def request(self, gate_id: str) -> HITLGate:
        return self._transition(gate_id, GateState.REQUESTED, actor="system:dike", action="REQUESTED")

    def open(self, gate_id: str, *, principal: AuthenticatedPrincipal) -> HITLGate:
        principal = self._require_principal(principal)
        return self._transition(
            gate_id, GateState.IN_REVIEW, actor=principal.actor, action="OPENED", principal=principal,
        )

    def decide(self, gate_id: str, decision: str, *, principal: AuthenticatedPrincipal, notes: str = "", corrections: list[dict] | None = None) -> HITLGate:
        principal = self._require_principal(principal)
        gate = self.get_gate(gate_id)
        target = decision_state(gate.gate_type, decision)
        return self._transition(
            gate_id, target, actor=principal.actor, action="DECIDED",
            decision=decision.strip().upper(), notes=notes, corrections=corrections, principal=principal,
        )

    def reactivate(self, gate_id: str, *, principal: AuthenticatedPrincipal) -> HITLGate:
        principal = self._require_principal(principal)
        return self._transition(
            gate_id, GateState.PENDING, actor=principal.actor, action="REOPENED",
            principal=principal, enforce_expiry=False,
        )

    def cancel(self, gate_id: str, *, actor: str, notes: str) -> HITLGate:
        return self._transition(gate_id, GateState.CANCELLED, actor=actor, action="CANCELLED", notes=notes)

    def expire_due(self) -> list[str]:
        now = self.clock()
        expired: list[str] = []
        for gate in self.list_gates():
            if gate.state in {GateState.PENDING, GateState.REQUESTED, GateState.IN_REVIEW} and gate.expires_at and gate.expires_at <= now:
                self._expire_gate(gate)
                expired.append(gate.gate_id)
        return expired

    def can_proceed(self, gate_id: str, protected_effect: str) -> bool:
        gate = self.get_gate(gate_id)
        self._verify_gate_against_journal(gate)
        if self._is_expired(gate):
            self._expire_gate(gate)
            return False
        contract = contract_for(gate.gate_type)
        return contract.protected_effect == protected_effect and gate.state is GateState.DECIDED_APPROVED

    def approved_decision(self, gate_id: str, protected_effect: str) -> HITLEvent:
        """Return the authenticated decision authorizing one still-pending effect."""
        if not self.can_proceed(gate_id, protected_effect):
            raise PermissionError("gate has not approved this effect")
        decisions = [event for event in self.history(gate_id) if event.action == "DECIDED"]
        if not decisions:
            raise PermissionError("approved gate has no decision event")
        approval = decisions[-1]
        if approval.new_state is not GateState.DECIDED_APPROVED:
            raise PermissionError("gate has no approved decision event")
        if not (approval.principal_id and approval.authentication_method and approval.session_id):
            raise PermissionError("approved gate has no authenticated principal")
        return approval

    def approved_principal(self, gate_id: str, protected_effect: str) -> AuthenticatedPrincipal:
        """Recover the approving identity from the sealed DECIDED event."""
        approval = self.approved_decision(gate_id, protected_effect)
        return AuthenticatedPrincipal(
            principal_id=approval.principal_id or "",
            authentication_method=approval.authentication_method or "",
            session_id=approval.session_id or "",
        )

    @staticmethod
    def _require_principal(principal: AuthenticatedPrincipal) -> AuthenticatedPrincipal:
        if not isinstance(principal, AuthenticatedPrincipal):
            raise PermissionError("authenticated principal required")
        return principal

    def _is_expired(self, gate: HITLGate) -> bool:
        return bool(
            gate.expires_at
            and gate.expires_at <= self.clock()
            and gate.state not in {GateState.EXPIRED, GateState.CANCELLED, GateState.CONSUMED, GateState.INVALID}
        )

    def _expire_gate(self, gate: HITLGate) -> HITLGate:
        changed, event = transition_gate(
            gate, GateState.EXPIRED, actor="system:dike", action="EXPIRED",
            now=self.clock(), max_reopens=contract_for(gate.gate_type).max_reopens,
        )
        return self._persist_transition(changed, event, expected=gate)

    def _verify_gate_against_journal(self, gate: HITLGate, *, con: sqlite3.Connection | None = None) -> None:
        owns_connection = con is None
        connection = con or self._connect()
        try:
            row = connection.execute(
                "SELECT new_state,payload_hash,gate_hash,gate_type,ref_type,ref_id FROM hitl_events WHERE gate_id=? ORDER BY seq DESC LIMIT 1",
                (gate.gate_id,),
            ).fetchone()
        finally:
            if owns_connection:
                connection.close()
        if row is None:
            raise HITLJournalIntegrityError(f"gate {gate.gate_id} has no journal")
        if not row["gate_hash"]:
            raise HITLJournalIntegrityError(f"gate {gate.gate_id} predates full-snapshot sealing")
        if (
            row["new_state"] != gate.state.value
            or row["payload_hash"] != canonical_payload_hash(gate.payload)
            or row["gate_hash"] != canonical_gate_hash(gate)
            or row["gate_type"] != gate.gate_type.value
            or row["ref_type"] != gate.ref_type
            or row["ref_id"] != gate.ref_id
        ):
            raise HITLJournalIntegrityError(f"gate {gate.gate_id} diverges from append-only journal")

    def consume(
        self,
        gate_id: str,
        protected_effect: str,
        *,
        principal: AuthenticatedPrincipal,
        metadata: dict,
    ) -> HITLGate:
        principal = self._require_principal(principal)
        gate = self.get_gate(gate_id)
        self._verify_gate_against_journal(gate)
        if gate.state is GateState.CONSUMED:
            raise PermissionError("gate already consumed")
        if self._is_expired(gate):
            self._expire_gate(gate)
            raise PermissionError("gate expired")
        contract = contract_for(gate.gate_type)
        if contract.protected_effect != protected_effect or gate.state is not GateState.DECIDED_APPROVED:
            raise PermissionError("gate has not approved this effect")
        changed, event = transition_gate(
            gate, GateState.CONSUMED, actor=principal.actor, action="FINALIZED",
            principal=principal, metadata=metadata, now=self.clock(),
            max_reopens=contract.max_reopens,
        )
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT * FROM hitl_gates WHERE gate_id=?", (gate_id,)).fetchone()
            if row is None:
                raise KeyError(gate_id)
            current = self._row_gate(row)
            self._verify_gate_against_journal(current, con=con)
            if canonical_gate_hash(current) != canonical_gate_hash(gate):
                raise PermissionError("gate already consumed or changed")
            updated = con.execute(
                "UPDATE hitl_gates SET state=?,updated_at=? WHERE gate_id=? AND state=? AND updated_at=?",
                (
                    GateState.CONSUMED.value, changed.updated_at.isoformat(), gate_id,
                    GateState.DECIDED_APPROVED.value, gate.updated_at.isoformat(),
                ),
            ).rowcount
            if updated != 1:
                raise PermissionError("gate already consumed or changed")
            self._insert_event(con, event)
        return changed

    def history(self, gate_id: str | None = None) -> list[HITLEvent]:
        query = "SELECT * FROM hitl_events"
        params: tuple = ()
        if gate_id:
            query += " WHERE gate_id=?"; params = (gate_id,)
        query += " ORDER BY seq"
        with self._connect() as con:
            rows = con.execute(query, params).fetchall()
        return [HITLEvent(
            event_id=r["event_id"], ts=datetime.fromisoformat(r["ts"]), gate_id=r["gate_id"],
            gate_type=GateType(r["gate_type"]), ref_type=r["ref_type"], ref_id=r["ref_id"], actor=r["actor"],
            action=r["action"], previous_state=GateState(r["previous_state"]), new_state=GateState(r["new_state"]),
            decision=r["decision"], payload_hash=r["payload_hash"], gate_hash=r["gate_hash"] or "",
            evidence_links=tuple(json.loads(r["evidence_links_json"])),
            notes=r["notes"], corrections=tuple(json.loads(r["corrections_json"])),
            principal_id=r["principal_id"], authentication_method=r["authentication_method"],
            session_id=r["session_id"], metadata=json.loads(r["metadata_json"] or "{}"),
        ) for r in rows]


def gate_to_dict(gate: HITLGate) -> dict:
    return {
        "gate_id": gate.gate_id, "gate_type": gate.gate_type.value, "ref_type": gate.ref_type,
        "ref_id": gate.ref_id, "state": gate.state.value, "payload": gate.payload,
        "created_at": gate.created_at.isoformat(), "updated_at": gate.updated_at.isoformat(),
        "expires_at": gate.expires_at.isoformat() if gate.expires_at else None, "reopen_count": gate.reopen_count,
    }


def event_to_dict(event: HITLEvent) -> dict:
    return {
        "event_id": event.event_id, "ts": event.ts.isoformat(), "gate_id": event.gate_id,
        "gate_type": event.gate_type.value, "ref_type": event.ref_type, "ref_id": event.ref_id,
        "actor": event.actor, "action": event.action, "previous_state": event.previous_state.value,
        "new_state": event.new_state.value, "decision": event.decision, "payload_hash": event.payload_hash,
        "gate_hash": event.gate_hash,
        "evidence_links": list(event.evidence_links), "notes": event.notes, "corrections": list(event.corrections),
        "principal_id": event.principal_id, "authentication_method": event.authentication_method,
        "session_id": event.session_id, "metadata": event.metadata,
    }
