"""
nif.py — Normative Interaction Frame (NIF)

Pydantic models for the structured legal reasoning artifact that flows between
subagents in the LexO Mission Harness.

The NIF captures every element of a legal problem:
- facts (known, alleged, missing)
- subjects (parties, tribunal, third parties)
- norms (with deontic logic, exceptions, status)
- norm relations (hierarchy, conflict, subclass)
- administrative acts
- principles
- deontic positions (subject ↔ norm)
- conflicts
- hypotheses (competing legal interpretations)
- gaps (missing knowledge)

Each NIF carries a coverage score and evidence references, making it the
primary reusable artifact from researcher through evaluator.

Designed to coexist with:
- ValidationContract.nif_requirement → defines what NIF fields are mandatory
- StructuredHandoff.nif_output → carries the NIF between workers
- LexRAGEvaluator → measures nif_coverage_score
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------------------
#  Enums
# ---------------------------------------------------------------------------


class ProblemType(str, Enum):
    normativo = "normativo"
    jurisprudencial = "jurisprudencial"
    procedimental = "procedimental"
    administrativo = "administrativo"
    doctrinal = "doctrinal"
    mixto = "mixto"


class DeonticOperator(str, Enum):
    obligacion = "obligacion"
    prohibicion = "prohibicion"
    permiso = "permiso"
    potestad = "potestad"
    sancion = "sancion"
    excepcion = "excepcion"
    # El texto no siempre sostiene un operador deóntico: casi la mitad del
    # corpus chileno es constitutivo o definitorio ("Se llama acción
    # redhibitoria la que..."). Forzar `obligacion` por defecto sería afirmar
    # una fuerza normativa que el artículo no declara.
    indeterminado = "indeterminado"


class NormStatus(str, Enum):
    vigente = "vigente"
    derogada = "derogada"
    modificada = "modificada"
    indeterminada = "indeterminada"


class NormRelationType(str, Enum):
    jerarquia = "jerarquia"
    especialidad = "especialidad"
    temporalidad = "temporalidad"
    remision = "remision"
    compatibilidad = "compatibilidad"
    conflicto = "conflicto"
    derogacion = "derogacion"
    prevalencia = "prevalencia"
    laguna = "laguna"
    derrotabilidad = "derrotabilidad"


class HypothesisType(str, Enum):
    normativa = "normativa"
    jurisprudencial = "jurisprudencial"
    administrativa = "administrativa"
    procedimental = "procedimental"
    doctrinal = "doctrinal"


class HypothesisStatus(str, Enum):
    open = "open"
    supported = "supported"
    disputed = "disputed"
    rejected = "rejected"
    needs_more_evidence = "needs_more_evidence"


class GapImpact(str, Enum):
    alto = "alto"
    medio = "medio"
    bajo = "bajo"


class SubjectRole(str, Enum):
    actor = "actor"
    demandado = "demandado"
    organismo = "organismo"
    tribunal = "tribunal"
    tercero = "tercero"
    querellante = "querellante"
    # El esquema nació para litigio; un contrato tiene partes, no actor y
    # demandado. Sin este valor, revisar una compraventa obliga a inventar un
    # rol procesal que no existe.
    parte = "parte"


class DeonticPosition(str, Enum):
    obligado = "obligado"
    titular_derecho = "titular_derecho"
    titular_potestad = "titular_potestad"
    sancionado = "sancionado"
    exceptuado = "exceptuado"


# ---------------------------------------------------------------------------
#  Sub-models
# ---------------------------------------------------------------------------


class Facts(BaseModel):
    known: list[str] = Field(default_factory=list, description="Hechos establecidos con respaldo")
    alleged: list[str] = Field(default_factory=list, description="Hechos alegados sin confirmar")
    missing: list[str] = Field(default_factory=list, description="Hechos necesarios que aún no se conocen")


class Subject(BaseModel):
    id: str = Field(min_length=1)
    role: SubjectRole
    label: str


class Norm(BaseModel):
    gid: str = Field(default="", description="GID del grafo: cl.norma.ley_20417:art:0127")
    label: str = ""
    operator: DeonticOperator = DeonticOperator.obligacion
    supuesto_de_hecho: str = ""
    consecuencia_juridica: str = ""
    destinatario: str = ""
    condicion_aplicacion: str = ""
    exceptions: list[str] = Field(default_factory=list)
    status: NormStatus = NormStatus.vigente


class NormRelation(BaseModel):
    from_gid: str
    to_gid: str
    relation: NormRelationType
    notes: str = ""


class AdminAct(BaseModel):
    id: str
    type: str = "otro"
    label: str = ""
    date: str = ""


class DeonticPositionItem(BaseModel):
    subject_id: str
    norm_gid: str
    position: DeonticPosition


class ConflictItem(BaseModel):
    type: str = ""
    description: str = ""
    resolution_criteria: str = ""


class Hypothesis(BaseModel):
    id: str
    type: HypothesisType = HypothesisType.normativa
    claim: str
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    status: HypothesisStatus = HypothesisStatus.open


class GapStatus(str, Enum):
    open = "open"
    in_progress = "in_progress"
    filled = "filled"
    wont_fix = "wont_fix"


class GapItem(BaseModel):
    description: str
    impact: GapImpact = GapImpact.medio
    scraper_ticket: bool = False
    status: GapStatus = GapStatus.open
    demanded_by: str = ""   # agent_id que detectó el gap
    filled_by: str = ""     # agent_id o "user" que lo resolvió
    filled_with: str = ""   # descripción de cómo se resolvió


class Factor(BaseModel):
    """Un factor jurídico relevante que el Contradictor debe atacar — L000.

    Los factores son los elementos de hecho o derecho que determinan el resultado
    del caso. El Researcher los identifica desde el NIF; el Contradictor reporta
    cuántos atacó efectivamente (coverage_score = attacked / total).
    """

    factor_id: str = Field(min_length=1, description="Identificador único, ej: 'f-01-causas-despido'")
    description: str = Field(description="Descripción del factor (qué debe probarse o refutarse)")
    source_evidence: list[str] = Field(
        default_factory=list,
        description="GIDs o source_ids que respaldan este factor",
    )
    weight: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Peso relativo del factor (1.0 = crítico, 0.5 = relevante, 0.1 = marginal)",
    )
    examined_by: str = Field(
        default="",
        description="agent_id que EXAMINÓ este factor (lo procesó con grounding), "
                    "lo haya hallado vulnerable o robusto. Distinto de attacked_by.",
    )
    attacked_by: str = Field(
        default="",
        description="agent_id que halló un ángulo de ataque FUNDADO contra este factor "
                    "(vacío = no atacado: o no examinado, o examinado y hallado robusto)",
    )
    attack_summary: str = Field(
        default="",
        description="Resumen del argumento con el que se atacó el factor",
    )
    examination_note: str = Field(
        default="",
        description="Nota de la examinación cuando el factor se halló robusto (no atacable de forma fundada)",
    )


# ---------------------------------------------------------------------------
#  Main NIF model
# ---------------------------------------------------------------------------


class NormativeInteractionFrame(BaseModel):
    """Structured representation of a legal problem for agent consumption.

    Every worker (researcher, case_designer, procurador, etc.) can produce
    a NIF.  Validators (juez, contradictor) can consume a NIF to verify
    completeness against a ValidationContract.nif_requirement.
    """

    frame_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    source: str = "unknown"
    legal_question: str
    problem_type: ProblemType = ProblemType.mixto

    facts: Facts = Field(default_factory=Facts)
    subjects: list[Subject] = Field(default_factory=list)
    norms: list[Norm] = Field(default_factory=list)
    norm_relations: list[NormRelation] = Field(default_factory=list)
    admin_acts: list[AdminAct] = Field(default_factory=list)
    principles: list[str] = Field(default_factory=list)
    deontic_positions: list[DeonticPositionItem] = Field(default_factory=list)
    conflicts: list[ConflictItem] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    gaps: list[GapItem] = Field(default_factory=list)
    relevant_factors: list[Factor] = Field(
        default_factory=list,
        description="Factores jurídicos que el Contradictor debe atacar — L000/L002",
    )

    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    validated_by_human: bool = False

    # 5.6 — Evidencia del validador deóntico (P16). Sin esto, deontic_validated no puede ser True.
    deontic_validation_evidence: dict[str, Any] = Field(default_factory=dict)

    # 5.6 — Lógica deóntica defeasible (arXiv:2506.08899): hasta que exista
    # un validador deóntico, el NIF marca deontic_validated: false — no se
    # declara validado lo que no lo está.
    deontic_validated: bool = False

    @model_validator(mode="after")
    def _enforce_deontic_validation_evidence(self) -> "NormativeInteractionFrame":
        # P16: no se puede declarar deontic_validated=True sin evidencia de validador.
        if self.deontic_validated and not self.deontic_validation_evidence:
            raise ValueError(
                "deontic_validated=True sin deontic_validation_evidence: "
                "no se puede declarar validado lo que no lo está (P16)"
            )
        return self

    extra: dict[str, Any] = Field(default_factory=dict)

    # ------------------------------------------------------------------
    #  Factor coverage — L002
    # ------------------------------------------------------------------

    def factor_coverage_score(self) -> float:
        """Ratio de factores con un ataque FUNDADO (vulnerabilidad hallada).

        Mide SUSTANCIA: cuántos factores el Contradictor halló efectivamente
        vulnerables, leyendo el documento/evidencia/norma. Un escrito robusto
        tendrá score bajo (pocos factores atacables) — eso NO es un defecto del
        análisis, por eso el gate de abstención del juez usa
        factor_examination_score(), no este. Este alimenta el rating.

        Returns 0.0 si no hay factores definidos (NIF subpoblado).
        """
        if not self.relevant_factors:
            return 0.0
        attacked = sum(1 for f in self.relevant_factors if f.attacked_by)
        return round(attacked / len(self.relevant_factors), 4)

    def factor_examination_score(self) -> float:
        """Ratio de factores EXAMINADOS por el Contradictor (engagement).

        Mide PROCESO: ¿el Contradictor corrió sobre los factores? Un factor
        atacado también cuenta como examinado (backward-compat con NIFs que solo
        traen attacked_by). Este es el signal correcto para el gate de
        abstención del juez: si es bajo, el Contradictor no se ejecutó.

        Returns 0.0 si no hay factores definidos.
        """
        if not self.relevant_factors:
            return 0.0
        examined = sum(1 for f in self.relevant_factors if f.examined_by or f.attacked_by)
        return round(examined / len(self.relevant_factors), 4)

    def unatacked_factors(self) -> list[Factor]:
        """Return factors not yet attacked."""
        return [f for f in self.relevant_factors if not f.attacked_by]

    def unexamined_factors(self) -> list[Factor]:
        """Return factors the Contradictor has not examined yet."""
        return [f for f in self.relevant_factors if not (f.examined_by or f.attacked_by)]

    # ------------------------------------------------------------------
    #  Coverage: compute how many required NIF fields are populated
    # ------------------------------------------------------------------

    def coverage_against(self, requirement: NIFRequirement | None = None) -> NIFCoverageResult:
        """Measure what fraction of required fields are populated."""
        from shared.schemas.validation_contracts import NIFRequirement as Req

        req = requirement or Req()

        total_fields = 0
        populated_fields = 0

        def _has_content(val: Any) -> bool:
            if isinstance(val, list):
                return len(val) > 0
            if isinstance(val, str):
                return len(val.strip()) > 0
            if isinstance(val, BaseModel):
                return True
            return val is not None

        if req.require_facts:
            total_fields += 3
            if self.facts.known:
                populated_fields += 1
            if self.facts.alleged:
                populated_fields += 1
            if self.facts.missing:
                populated_fields += 1

        if req.require_subjects:
            total_fields += 1
            if self.subjects:
                populated_fields += 1

        if req.require_norms:
            total_fields += 1
            if self.norms:
                populated_fields += 1

        if req.require_deontic_positions:
            total_fields += 1
            if self.deontic_positions:
                populated_fields += 1

        if req.require_conflicts:
            total_fields += 1
            if self.conflicts:
                populated_fields += 1

        if req.require_gaps:
            total_fields += 1
            if self.gaps:
                populated_fields += 1

        if req.require_evidence_for_and_against:
            total_fields += 2
            for h in self.hypotheses:
                if h.evidence_for:
                    populated_fields += 1
                    break
            for h in self.hypotheses:
                if h.evidence_against:
                    populated_fields += 1
                    break

        score = populated_fields / max(total_fields, 1)
        factors_total = len(self.relevant_factors)
        factors_attacked = sum(1 for f in self.relevant_factors if f.attacked_by)
        factors_examined = sum(
            1 for f in self.relevant_factors if f.examined_by or f.attacked_by
        )
        return NIFCoverageResult(
            score=round(score, 4),
            populated=populated_fields,
            required=total_fields,
            missing_fields=list(self._find_missing(req)),
            factor_coverage=self.factor_coverage_score(),
            factor_examination=self.factor_examination_score(),
            factors_total=factors_total,
            factors_attacked=factors_attacked,
            factors_examined=factors_examined,
        )

    def _find_missing(self, req: NIFRequirement) -> list[str]:
        missing = []
        if req.require_facts:
            if not self.facts.known:
                missing.append("facts.known")
            if not self.facts.alleged:
                missing.append("facts.alleged")
            if not self.facts.missing:
                missing.append("facts.missing")
        if req.require_subjects and not self.subjects:
            missing.append("subjects")
        if req.require_norms and not self.norms:
            missing.append("norms")
        if req.require_deontic_positions and not self.deontic_positions:
            missing.append("deontic_positions")
        if req.require_conflicts and not self.conflicts:
            missing.append("conflicts")
        if req.require_gaps and not self.gaps:
            missing.append("gaps")
        if req.require_evidence_for_and_against:
            if not any(h.evidence_for for h in self.hypotheses):
                missing.append("evidence_for")
            if not any(h.evidence_against for h in self.hypotheses):
                missing.append("evidence_against")
        return missing


class NIFCoverageResult(BaseModel):
    """Result of measuring NIF coverage against a contract requirement."""

    score: float = 0.0
    populated: int = 0
    required: int = 0
    missing_fields: list[str] = Field(default_factory=list)
    factor_coverage: float = 0.0       # vulnerabilidad hallada (sustancia → rating)
    factor_examination: float = 0.0    # engagement (proceso → gate de abstención)
    factors_total: int = 0
    factors_attacked: int = 0
    factors_examined: int = 0


# Avoid circular import at runtime; used only for type hint convenience


class NIFRequirement(BaseModel):
    """Minimum NIF fields that must be populated before a legal conclusion.

    A ValidationContract uses this to define what NIF coverage is expected
    before a subagent passes validation.

    Each field maps to sections of NormativeInteractionFrame.
    """

    require_facts: bool = True
    require_subjects: bool = True
    require_norms: bool = True
    require_deontic_positions: bool = True
    require_conflicts: bool = True
    require_gaps: bool = True
    require_evidence_for_and_against: bool = True
