"""Hash and exact-offset evidence validation."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .models import Candidate


@dataclass(frozen=True)
class EvidenceValidation:
    ok: bool
    errors: tuple[str, ...]


def validate_evidence(candidate: Candidate, full_text: str) -> EvidenceValidation:
    errors: list[str] = []
    digest = hashlib.sha256(full_text.encode("utf-8")).hexdigest()
    if digest != candidate.text_hash:
        errors.append("hash")
    if candidate.start_offset < 0 or candidate.end_offset <= candidate.start_offset or candidate.end_offset > len(full_text):
        errors.append("offsets")
    elif full_text[candidate.start_offset:candidate.end_offset] != candidate.evidence_snippet:
        errors.append("snippet")
    return EvidenceValidation(not errors, tuple(errors))
