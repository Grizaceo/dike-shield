"""Zero-network private pichanga vertical slice."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from lexo_cli.hitl.models import GateState, GateType
from lexo_cli.hitl.models import AuthenticatedPrincipal
from lexo_cli.hitl.receipts import build_effect_receipt
from lexo_cli.hitl.service import HITLService
from lexo_cli.starter.resolver import StarterCorpusResolver

from .evidence import validate_evidence
from .isolation import UserWorkspace
from .models import Candidate, CandidateState


_ARTICLE_RE = re.compile(r"art(?:í|i)culo\s+(\d+)", re.IGNORECASE)
_LAW_ARTICLE_RE = re.compile(
    r"art(?:í|i)culo\s+([a-záéíóúñ]+|\d+)\s+de\s+la\s+ley\s+(?:n[°ºo]\s*)?([\d.]+)",
    re.IGNORECASE,
)

_INGEST_IGNORE_DIRS = {
    "node_modules", ".venv", "venv", "__pycache__", ".git", ".hg", ".svn",
    ".pytest_cache", ".mypy_cache", ".snapshots", "dist", "build",
}
_INGEST_IGNORE_SUFFIXES = {".pyc", ".pyo", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".ico"}


class PersonalPichangaPipeline:
    def __init__(self, workspace: UserWorkspace, *, corpus_roots: list[str | Path] | tuple[str | Path, ...] = ()):
        self.workspace = workspace.ensure()
        self.db_path = self.workspace.resolve("graph/personal.db")
        self.hitl = HITLService(self.workspace.resolve("events.db"))
        self.corpus = StarterCorpusResolver(corpus_roots)
        self._initialize_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    def _initialize_db(self) -> None:
        with self._connect() as con:
            con.executescript("""
                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    state TEXT NOT NULL,
                    priority INTEGER NOT NULL,
                    parent_candidate_id TEXT,
                    gate_id TEXT
                );
                CREATE TABLE IF NOT EXISTS personal_edges (
                    candidate_id TEXT PRIMARY KEY,
                    source_node_id TEXT NOT NULL,
                    target_node_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status='PERSONAL_APPROVED'),
                    source_path TEXT NOT NULL,
                    text_hash TEXT NOT NULL,
                    start_offset INTEGER NOT NULL,
                    end_offset INTEGER NOT NULL,
                    evidence_snippet TEXT NOT NULL,
                    source_version TEXT NOT NULL,
                    temporal_scope TEXT NOT NULL,
                    reviewer TEXT NOT NULL,
                    reviewed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS promotion_receipts (
                    candidate_id TEXT PRIMARY KEY,
                    gate_id TEXT NOT NULL UNIQUE,
                    receipt_json TEXT NOT NULL
                );
            """)

    def ingest(self, vault_path: str | Path) -> list[dict]:
        source_root = Path(vault_path).expanduser().resolve()
        if not source_root.is_dir():
            raise ValueError("vault path must be a directory")
        docs: list[dict] = []
        for source in sorted(source_root.rglob("*")):
            if not source.is_file() or source.suffix.lower() not in {".txt", ".md"}:
                continue
            # Excluye directorios de sistema/venv/node y binarios para que un
            # abogado pueda apuntar la web a su carpeta de caso sin arrastrar
            # basura técnica ni colgar el pipeline con miles de archivos.
            rel_parts = source.relative_to(source_root).parts
            if any(part in _INGEST_IGNORE_DIRS for part in rel_parts):
                continue
            if source.suffix.lower() in _INGEST_IGNORE_SUFFIXES:
                continue
            text = source.read_text(encoding="utf-8")
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
            doc_id = f"doc_{digest[:16]}"
            target = self.workspace.resolve(f"vault/{doc_id}{source.suffix.lower()}")
            target.write_text(text, encoding="utf-8")
            docs.append({"doc_id": doc_id, "source_name": source.name, "path": str(target), "sha256": digest, "bytes": len(text.encode('utf-8'))})
        manifest = {"schemaVersion": "dike-private-manifest-v1", "user_id": self.workspace.user_id, "documents": docs}
        self.workspace.resolve("manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        return docs

    def parse_umj(self, docs: list[dict]) -> list[dict]:
        units: list[dict] = []
        for doc in docs:
            text = Path(doc["path"]).read_text(encoding="utf-8")
            cursor = 0
            for index, paragraph in enumerate(re.split(r"\n\s*\n", text)):
                if not paragraph:
                    continue
                start = text.find(paragraph, cursor)
                end = start + len(paragraph)
                cursor = end
                unit = {
                    "doc_id": doc["doc_id"], "unit_id": f"{doc['doc_id']}:u:{index+1}",
                    "text": paragraph, "text_hash": doc["sha256"], "start_offset": start,
                    "end_offset": end, "tipo": "paragraph", "materia": "laboral",
                    "source_path": doc["path"],
                }
                units.append(unit)
                out = self.workspace.resolve(f"umj/{doc['doc_id']}.jsonl")
                with out.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(unit, ensure_ascii=False, sort_keys=True) + "\n")
        return units

    def propose(self, units: list[dict], *, graph_run_id: str | None = None) -> list[Candidate]:
        run_id = graph_run_id or f"run_{uuid.uuid4().hex[:12]}"
        batch_id = f"batch_{uuid.uuid4().hex[:12]}"
        candidates: list[Candidate] = []
        for unit in units:
            matches: list[tuple[re.Match[str], str]] = []
            if "código del trabajo" in unit["text"].lower():
                matches.extend(
                    (match, f"cl.norma.ct:art:{int(match.group(1)):04d}")
                    for match in _ARTICLE_RE.finditer(unit["text"])
                )
            for match in _LAW_ARTICLE_RE.finditer(unit["text"]):
                article_token = match.group(1).lower()
                if article_token.isdigit():
                    article_token = f"{int(article_token):04d}"
                law_number = match.group(2).replace(".", "")
                matches.append((match, f"cl.norma.ley_{law_number}:art:{article_token}"))
            for match, target_gid in matches:
                start = unit["start_offset"] + match.start()
                end = unit["start_offset"] + match.end()
                candidates.append(Candidate(
                    candidate_id=f"cand_{uuid.uuid4().hex[:12]}", batch_id=batch_id, graph_run_id=run_id,
                    doc_id=unit["doc_id"], unit_id=unit["unit_id"], suggested_by="regex:cites:v1",
                    suggestion_confidence=0.92, edge_type="CITES", source_node_id=f"private.doc:{unit['doc_id']}",
                    target_node_id=target_gid, evidence_snippet=match.group(0),
                    start_offset=start, end_offset=end, source_url=Path(unit["source_path"]).as_uri(),
                    source_path=unit["source_path"], section_hint=unit["unit_id"], text_hash=unit["text_hash"],
                    extractor_rule="ct_article_v1", impact=1.0,
                ))
            # 3.4b — aristas de conflicto: CONFLICTS_WITH / RESOLVED_BY,
            # validadas contra la autoridad única de prevalencia (1.7).
            from lexo_cli.pichanga.conflictos import proponer_aristas_conflicto

            for conflicto in proponer_aristas_conflicto(unit["text"]):
                candidates.append(Candidate(
                    candidate_id=f"cand_{uuid.uuid4().hex[:12]}", batch_id=batch_id, graph_run_id=run_id,
                    doc_id=unit["doc_id"], unit_id=unit["unit_id"],
                    suggested_by="regex:conflictos:v1",
                    suggestion_confidence=0.7 if conflicto.validated else 0.4,
                    edge_type=conflicto.edge_type,
                    source_node_id=conflicto.gid_a,
                    target_node_id=conflicto.gid_b,
                    evidence_snippet=conflicto.snippet,
                    start_offset=unit["start_offset"], end_offset=unit["end_offset"],
                    source_url=Path(unit["source_path"]).as_uri(),
                    source_path=unit["source_path"], section_hint=unit["unit_id"],
                    text_hash=unit["text_hash"],
                    extractor_rule="conflictos_v1",
                    impact=0.8 if conflicto.validated else 0.5,
                ))
        return candidates

    def enqueue(self, candidate: Candidate) -> Candidate:
        text = Path(candidate.source_path).read_text(encoding="utf-8")
        validation = validate_evidence(candidate, text)
        if not validation.ok:
            candidate.state = CandidateState.INVALID
            self._save_candidate(candidate)
            return candidate
        try:
            normative = self.corpus.resolve(candidate.target_node_id)
        except ValueError:
            candidate.state = CandidateState.INVALID
            self._save_candidate(candidate)
            return candidate
        gate = self.hitl.create_gate(GateType.HITL_2, "item", candidate.candidate_id, {
            "source_path": candidate.source_path, "start_offset": candidate.start_offset,
            "end_offset": candidate.end_offset, "text_hash": candidate.text_hash,
            "evidence_snippet": candidate.evidence_snippet,
            "target_gid": normative.gid,
            "target_eli": normative.eli,
            "target_text_sha256": normative.text_sha256,
        })
        self.hitl.request(gate.gate_id)
        candidate.gate_id = gate.gate_id
        candidate.state = CandidateState.PENDING
        self._save_candidate(candidate)
        return candidate

    def _save_candidate(self, candidate: Candidate) -> None:
        payload = candidate.to_dict()
        with self._connect() as con:
            con.execute(
                "INSERT INTO candidates VALUES (?,?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET payload_json=excluded.payload_json,state=excluded.state,priority=excluded.priority,parent_candidate_id=excluded.parent_candidate_id,gate_id=excluded.gate_id",
                (candidate.candidate_id, json.dumps(payload, ensure_ascii=False, sort_keys=True), candidate.state.value,
                 candidate.priority, candidate.parent_candidate_id, candidate.gate_id),
            )
        self.workspace.resolve(f"candidates/{candidate.candidate_id}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def get_candidate(self, candidate_id: str) -> Candidate:
        with self._connect() as con:
            row = con.execute("SELECT payload_json FROM candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
        if row is None:
            raise KeyError(candidate_id)
        return Candidate.from_dict(json.loads(row[0]))

    def list_candidates(self) -> list[Candidate]:
        with self._connect() as con:
            rows = con.execute("SELECT payload_json FROM candidates ORDER BY priority DESC,candidate_id").fetchall()
        return [Candidate.from_dict(json.loads(row[0])) for row in rows]

    def review(self, candidate_id: str, decision: str, *, principal: AuthenticatedPrincipal, corrections: dict | None = None) -> dict:
        candidate = self.get_candidate(candidate_id)
        if candidate.state is CandidateState.PERSONAL_APPROVED:
            raise PermissionError("HITL-2 gate already consumed for this personal promotion")
        text = Path(candidate.source_path).read_text(encoding="utf-8")
        validation = validate_evidence(candidate, text)
        if not validation.ok:
            candidate.state = CandidateState.INVALID
            self._save_candidate(candidate)
            return {"candidate_id": candidate_id, "status": "INVALID", "errors": list(validation.errors)}
        if not candidate.gate_id:
            raise ValueError("candidate has no HITL-2 gate")
        gate = self.hitl.get_gate(candidate.gate_id)
        self._verify_candidate_against_sealed_gate(candidate, gate)
        if gate.state is GateState.REQUESTED:
            self.hitl.open(gate.gate_id, principal=principal)
        normalized = decision.strip().upper()
        decided = self.hitl.decide(
            gate.gate_id, normalized, principal=principal,
            corrections=[corrections] if corrections else None,
        )
        if normalized == "ACEPTAR":
            if not self.hitl.can_proceed(gate.gate_id, "personal_promotion"):
                raise PermissionError("HITL-2 has not authorized personal promotion")
            approval = self.hitl.approved_decision(gate.gate_id, "personal_promotion")
            approver = self.hitl.approved_principal(gate.gate_id, "personal_promotion")
            receipt = self._promote_with_receipt(candidate, gate, approval, approver)
            try:
                self.hitl.consume(
                    gate.gate_id,
                    "personal_promotion",
                    principal=approver,
                    metadata={"receipt": receipt},
                )
            except PermissionError:
                # The personal effect is already durable.  Do not retry or
                # infer consumption: make the cross-DB reconciliation visible.
                return {
                    "candidate_id": candidate_id,
                    "status": "PERSONAL_APPROVED_RECONCILIATION_REQUIRED",
                    "reconciliation": self.promotion_reconciliation(candidate_id),
                }
            return {"candidate_id": candidate_id, "status": "PERSONAL_APPROVED", "receipt": receipt}
        if normalized == "CORREGIR":
            candidate.state = CandidateState.CORRECTED
            self._save_candidate(candidate)
            data = candidate.to_dict()
            data.update(corrections or {})
            data.update({
                "candidate_id": f"cand_{uuid.uuid4().hex[:12]}", "state": "PENDING", "priority": candidate.priority + 100,
                "parent_candidate_id": candidate.candidate_id, "gate_id": None,
            })
            corrected = self.enqueue(Candidate.from_dict(data))
            return corrected.to_dict()
        candidate.state = CandidateState.REJECTED if normalized == "RECHAZAR" else CandidateState.DEFERRED
        self._save_candidate(candidate)
        return {"candidate_id": candidate_id, "status": candidate.state.value}

    def _verify_candidate_against_sealed_gate(self, candidate: Candidate, gate) -> None:
        """The reviewed candidate must still be exactly the one HITL-2 sealed."""
        payload = gate.payload
        sealed_fields = {
            "source_path": candidate.source_path,
            "start_offset": candidate.start_offset,
            "end_offset": candidate.end_offset,
            "text_hash": candidate.text_hash,
            "evidence_snippet": candidate.evidence_snippet,
            "target_gid": candidate.target_node_id,
        }
        if gate.ref_id != candidate.candidate_id or any(payload.get(name) != value for name, value in sealed_fields.items()):
            raise PermissionError("candidate differs from sealed HITL-2 authorization")
        try:
            normative = self.corpus.resolve(candidate.target_node_id)
        except ValueError as exc:
            raise PermissionError("candidate target no longer resolves against sealed HITL-2 authorization") from exc
        if normative.eli != payload.get("target_eli") or normative.text_sha256 != payload.get("target_text_sha256"):
            raise PermissionError("candidate target differs from sealed HITL-2 authorization")

    def _edge_values(self, candidate: Candidate, reviewer: str, reviewed_at: str) -> tuple:
        return (
            candidate.candidate_id, candidate.source_node_id, candidate.target_node_id, candidate.edge_type,
            "PERSONAL_APPROVED", candidate.source_path, candidate.text_hash, candidate.start_offset,
            candidate.end_offset, candidate.evidence_snippet, candidate.text_hash, "private-user-scope",
            reviewer, reviewed_at,
        )

    def _promote_with_receipt(self, candidate: Candidate, gate, approval, approver: AuthenticatedPrincipal) -> dict:
        candidate_input = candidate.to_dict()
        reviewed_at = datetime.now(UTC).isoformat()
        candidate.state = CandidateState.PERSONAL_APPROVED
        edge_values = self._edge_values(candidate, approver.actor, reviewed_at)
        edge_payload = {
            "candidate_id": candidate.candidate_id,
            "source_node_id": candidate.source_node_id,
            "target_node_id": candidate.target_node_id,
            "edge_type": candidate.edge_type,
            "status": "PERSONAL_APPROVED",
            "text_hash": candidate.text_hash,
            "start_offset": candidate.start_offset,
            "end_offset": candidate.end_offset,
            "temporal_scope": "private-user-scope",
            "reviewer": approver.actor,
            "reviewed_at": reviewed_at,
        }
        receipt = build_effect_receipt(
            gate=gate,
            approval=approval,
            effect_id=f"personal-promotion:{candidate.candidate_id}",
            effect_type="personal_promotion",
            input_payload={"candidate": candidate_input, "gate_payload": gate.payload},
            output_payload={"edge": edge_payload},
            binding={"target_gid": candidate.target_node_id, "text_hash": candidate.text_hash},
        )
        with self._connect() as con:
            con.execute("BEGIN IMMEDIATE")
            current = con.execute("SELECT state FROM candidates WHERE candidate_id=?", (candidate.candidate_id,)).fetchone()
            if current is None or current["state"] != CandidateState.PENDING.value:
                raise PermissionError("candidate is not pending personal promotion")
            if con.execute("SELECT 1 FROM personal_edges WHERE candidate_id=?", (candidate.candidate_id,)).fetchone():
                raise PermissionError("candidate already has a personal edge")
            con.execute(
                "UPDATE candidates SET payload_json=?,state=? WHERE candidate_id=?",
                (json.dumps(candidate.to_dict(), ensure_ascii=False, sort_keys=True), candidate.state.value, candidate.candidate_id),
            )
            con.execute(
                "INSERT INTO personal_edges VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                edge_values,
            )
            con.execute(
                "INSERT INTO promotion_receipts VALUES (?,?,?)",
                (candidate.candidate_id, gate.gate_id, json.dumps(receipt, ensure_ascii=False, sort_keys=True)),
            )
        self.workspace.resolve(f"candidates/{candidate.candidate_id}.json").write_text(
            json.dumps(candidate.to_dict(), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        return receipt

    def promotion_reconciliation(self, candidate_id: str) -> dict:
        with self._connect() as con:
            row = con.execute(
                "SELECT gate_id,receipt_json FROM promotion_receipts WHERE candidate_id=?", (candidate_id,)
            ).fetchone()
        if row is None:
            return {"status": "NO_PROMOTION_RECEIPT", "candidate_id": candidate_id}
        receipt = json.loads(row["receipt_json"])
        gate = self.hitl.get_gate(row["gate_id"])
        if gate.state is GateState.CONSUMED:
            final = self.hitl.history(gate.gate_id)[-1]
            if final.metadata.get("receipt", {}).get("receipt_hash") == receipt.get("receipt_hash"):
                return {"status": "CONSUMED", "candidate_id": candidate_id, "receipt": receipt}
            return {"status": "REVIEW_REQUIRED_RECEIPT_MISMATCH", "candidate_id": candidate_id, "receipt": receipt}
        if gate.state is GateState.DECIDED_APPROVED:
            return {"status": "EFFECT_PERSISTED_PENDING_CONSUMPTION", "candidate_id": candidate_id, "receipt": receipt}
        return {"status": "REVIEW_REQUIRED_GATE_STATE", "candidate_id": candidate_id, "gate_state": gate.state.value, "receipt": receipt}

    def graph_edges(self) -> list[dict]:
        with self._connect() as con:
            rows = con.execute("SELECT * FROM personal_edges ORDER BY candidate_id").fetchall()
        return [dict(row) for row in rows]

    def tamper_candidate_for_test(self, candidate_id: str, **changes) -> None:
        candidate = self.get_candidate(candidate_id)
        for key, value in changes.items():
            setattr(candidate, key, value)
        self._save_candidate(candidate)

    def run(self, vault_path: str | Path) -> dict:
        docs = self.ingest(vault_path)
        units = self.parse_umj(docs)
        candidates = [self.enqueue(candidate) for candidate in self.propose(units)]
        return {
            "documents": len(docs), "units": len(units),
            "candidates": sum(c.state is CandidateState.PENDING for c in candidates),
            "invalid": sum(c.state is CandidateState.INVALID for c in candidates),
            "risk_assessment": "NO_EVALUADO",
            "network_used": False,
        }
