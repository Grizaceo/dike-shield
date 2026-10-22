"""Contracts for private pichanga candidates and review states."""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from enum import Enum


class CandidateState(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    CORRECTED = "CORRECTED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    EXPIRED = "EXPIRED"
    INVALID = "INVALID"
    PERSONAL_APPROVED = "PERSONAL_APPROVED"


@dataclass
class Candidate:
    candidate_id: str
    batch_id: str
    graph_run_id: str
    doc_id: str
    unit_id: str
    suggested_by: str
    suggestion_confidence: float
    edge_type: str
    source_node_id: str
    target_node_id: str
    evidence_snippet: str
    start_offset: int
    end_offset: int
    source_url: str
    source_path: str
    section_hint: str
    text_hash: str
    extractor_rule: str
    state: CandidateState = CandidateState.PENDING
    priority: int = 100
    impact: float = 1.0
    parent_candidate_id: str | None = None
    gate_id: str | None = None

    def __post_init__(self) -> None:
        required = {
            "candidate_id": self.candidate_id, "batch_id": self.batch_id,
            "graph_run_id": self.graph_run_id, "doc_id": self.doc_id,
            "unit_id": self.unit_id, "suggested_by": self.suggested_by,
            "edge_type": self.edge_type, "source_node_id": self.source_node_id,
            "target_node_id": self.target_node_id, "source_path": self.source_path,
            "text_hash": self.text_hash, "extractor_rule": self.extractor_rule,
        }
        missing = [key for key, value in required.items() if not str(value).strip()]
        if missing:
            raise ValueError(f"missing candidate provenance: {', '.join(missing)}")
        if not 0 <= float(self.suggestion_confidence) <= 1:
            raise ValueError("suggestion_confidence must be in [0,1]")

    def to_dict(self) -> dict:
        value = asdict(self)
        value["state"] = self.state.value
        return value

    @classmethod
    def from_dict(cls, value: dict) -> "Candidate":
        data = dict(value)
        data["state"] = CandidateState(data.get("state", "PENDING"))
        return cls(**data)

    @classmethod
    def minimal_for_test(cls, *, text_hash: str, evidence_snippet: str, start_offset: int, end_offset: int) -> "Candidate":
        return cls(
            candidate_id=f"cand_{uuid.uuid4().hex[:12]}", batch_id="batch-test", graph_run_id="run-test",
            doc_id="doc-test", unit_id="unit-test", suggested_by="test", suggestion_confidence=0.5,
            edge_type="CITES", source_node_id="doc:test", target_node_id="cl.norma.ct:art:0168",
            evidence_snippet=evidence_snippet, start_offset=start_offset, end_offset=end_offset,
            source_url="file://test", source_path="test.txt", section_hint="", text_hash=text_hash,
            extractor_rule="test",
        )
