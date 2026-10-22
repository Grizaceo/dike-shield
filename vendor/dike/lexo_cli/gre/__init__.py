"""Grafo de Relaciones Evidenciadas (GRE), privado y revisable.

This is the public Diké boundary for personal evidence relations.  The
``lexo_cli.pichanga`` package remains a compatibility namespace for existing
installations; its persisted data format is unchanged and no data is moved.
"""

from lexo_cli.pichanga.evidence import validate_evidence
from lexo_cli.pichanga.isolation import UserWorkspace
from lexo_cli.pichanga.models import Candidate, CandidateState
from lexo_cli.pichanga.pipeline import PersonalPichangaPipeline
from lexo_cli.pichanga.selection import rank_candidates

PersonalGREPipeline = PersonalPichangaPipeline
PersonalEvidenceRelationsPipeline = PersonalPichangaPipeline

__all__ = [
    "Candidate",
    "CandidateState",
    "PersonalEvidenceRelationsPipeline",
    "PersonalGREPipeline",
    "UserWorkspace",
    "rank_candidates",
    "validate_evidence",
]
