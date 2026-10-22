from __future__ import annotations

import hashlib
import json
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    statute = "statute"
    regulation = "regulation"
    jurisprudence = "jurisprudence"
    doctrine = "doctrine"
    transcript = "transcript"
    paper = "paper"
    internal_doc = "internal_doc"


class EvidenceRef(BaseModel):
    """A single evidence reference backing a legal claim."""

    source_id: str = Field(min_length=1)
    path_or_url: str
    line_start: int | None = None
    line_end: int | None = None
    source_type: SourceType
    sha256: str | None = None
    claim_supported: str


# Avoid circular import: NIFRequirement lives in nif.py
# Re-exported from shared.schemas.nif for convenience
from shared.schemas.nif import NIFRequirement  # noqa: E402, F811


class ValidationContract(BaseModel):
    """Contract defining what a subagent must satisfy to pass validation."""

    contract_id: str
    mission_id: str
    agent_role: str
    objective: str
    nif_requirement: NIFRequirement = Field(default_factory=NIFRequirement)
    required_sources: list[SourceType] = Field(default_factory=list)
    min_evidence_refs: int = 1
    max_uncited_legal_claims: int = 0
    privacy_check_required: bool = True
    no_hallucinated_jurisprudence: bool = True
    acceptance_tests: list[str] = Field(default_factory=list)


class ModelFingerprint(BaseModel):
    """Acta de modelo — SEC-002.

    Registra el modelo, hash del prompt y hash del NIF que produjeron un handoff,
    garantizando reproducibilidad jurídica auditada en el tiempo.
    """

    model_version: str = Field(description="Modelo LLM usado (ej: claude-sonnet-4-6)")
    prompt_hash: str = Field(description="SHA-256 hex de los primeros 8KB del prompt enviado al subagente")
    nif_hash: str = Field(description="SHA-256 hex del NIF JSON serializado en el momento del handoff, o 'none' si no hay NIF")
    recorded_at: str = Field(description="ISO timestamp del momento de registro")

    @staticmethod
    def compute(model_version: str, prompt_text: str, nif_dict: dict | None) -> "ModelFingerprint":
        from datetime import datetime, timezone

        prompt_bytes = prompt_text[:8192].encode("utf-8")
        prompt_hash = hashlib.sha256(prompt_bytes).hexdigest()

        if nif_dict:
            nif_bytes = json.dumps(nif_dict, sort_keys=True, ensure_ascii=False).encode("utf-8")
            nif_hash = hashlib.sha256(nif_bytes).hexdigest()
        else:
            nif_hash = "none"

        return ModelFingerprint(
            model_version=model_version,
            prompt_hash=prompt_hash,
            nif_hash=nif_hash,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )


class StructuredHandoff(BaseModel):
    """Structured handoff between subagents, replacing loose text NCB handoffs.

    Optionally carries a NormativeInteractionFrame (nif_output) so the next
    worker receives structured legal reasoning context, not just evidence refs.
    """

    handoff_id: str
    mission_id: str
    from_agent: str
    to_agent: str
    completed: list[str]
    left_undone: list[str]
    commands_run: list[dict] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    context_blocks_used: list[str] = Field(default_factory=list)
    gaps_reported: list[str] = Field(default_factory=list)
    issues_discovered: list[str] = Field(default_factory=list)
    procedures_followed: bool
    privacy_risk: str = "none"
    nif_output: dict[str, Any] | None = Field(
        default=None,
        description="NormativeInteractionFrame as dict (produzido por researcher/case_designer, consumido por juez/contradictor)",
    )
    model_fingerprint: ModelFingerprint | None = Field(
        default=None,
        description="Acta de modelo SEC-002: model_version + prompt_hash + nif_hash para reproducibilidad jurídica auditada",
    )


class MissionSpec(BaseModel):
    """Full specification of a legal mission."""

    mission_id: str
    user_goal: str
    legal_area: str | None = None
    output_type: str
    workflow: list[str]
    contracts: list[ValidationContract]
    status: str = "planned"
