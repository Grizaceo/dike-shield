"""
nif_patch.py — NIF Patch Protocol

Define los parches atómicos que los subagentes (y el usuario) aplican
al NIF compartido. Cada patch es inmutable, auditable y reversible.

El protocolo resuelve el problema de comunicación subagente ↔ subagente:
en vez de pasarse mensajes o handoffs completos, los subagentes leen
el NIF canónico, aplican patches, y el siguiente subagente ve el
NIF actualizado + el log de cambios.

Patrón basado en:
- Luke/Factory (ow1we5PzK-o): shared state + structured handoffs
- Raj/IKEA (_QAVExf_1uw): pull context, document gaps
- Zuben+Danny/Raindrop (-aM2EDTiaMs): implicit signals from shared state
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any
import uuid

from pydantic import BaseModel, ConfigDict, Field


class PatchOperation(str, Enum):
    """Operaciones atómicas sobre el NIF."""
    append = "append"       # Agregar a lista o string
    replace = "replace"     # Reemplazar valor
    delete = "delete"       # Eliminar elemento de lista o campo
    insert = "insert"       # Insertar en posición específica de lista
    merge = "merge"         # Merge profundo de dicts


class PatchTarget(str, Enum):
    """Secciones del NIF que pueden recibir patches."""
    facts_known = "facts.known"
    facts_alleged = "facts.alleged"
    facts_missing = "facts.missing"
    subjects = "subjects"
    norms = "norms"
    norm_relations = "norm_relations"
    admin_acts = "admin_acts"
    principles = "principles"
    deontic_positions = "deontic_positions"
    conflicts = "conflicts"
    hypotheses = "hypotheses"
    gaps = "gaps"
    confidence = "confidence"
    legal_question = "legal_question"
    problem_type = "problem_type"
    user_input = "extra.user_input"  # Campo especial: input del usuario


class NIFPatch(BaseModel):
    """Un parche atómico sobre el NIF.

    Cada patch registra:
    - quién lo aplicó (agent_id o "user")
    - cuándo (timestamp ISO)
    - qué campo modificó (field_path)
    - qué operación realizó (append/replace/delete/insert/merge)
    - valor anterior (para rollback)
    - valor nuevo
    - razón (para auditoría)
    """
    patch_id: str = Field(
        default_factory=lambda: (
            f"p-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            f"-{uuid.uuid4().hex[:8]}"
        ),
        description="ID único del patch, generado automáticamente con timestamp + uuid8",
    )
    agent_id: str = Field(description="'researcher' | 'case_designer' | 'contradictor' | 'juez' | 'user' | etc.")
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    field_path: str = Field(description="Path del campo NIF: 'hypotheses[0].evidence_for', 'gaps', 'facts.known', etc.")
    operation: PatchOperation
    value: Any = Field(description="Valor nuevo (o elemento a agregar/insertar)")
    previous_value: Any = Field(default=None, description="Valor anterior para rollback")
    reason: str = Field(default="", description="Por qué se aplica este patch")
    case_id: str = Field(description="Caso al que pertenece")

    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "patch_id": "p-20260510231500",
                    "agent_id": "researcher",
                    "timestamp": "2026-05-10T23:15:00Z",
                    "field_path": "norms",
                    "operation": "append",
                    "value": {
                        "gid": "cl.norma.ley_20417:art:0127",
                        "label": "Art. 127 Ley 20.417 - Sanción vertimiento riles",
                        "operator": "sancion",
                        "supuesto_de_hecho": "Vertimiento no autorizado de riles",
                        "consecuencia_juridica": "Multa de 1 a 100 UTM",
                        "destinatario": "Empresa X",
                        "status": "vigente"
                    },
                    "previous_value": None,
                    "reason": "Encontrada norma aplicable en Ley 20.417",
                    "case_id": "caso-abc123"
                },
                {
                    "patch_id": "p-20260510232000",
                    "agent_id": "user",
                    "timestamp": "2026-05-10T23:20:00Z",
                    "field_path": "hypotheses[0].evidence_for",
                    "operation": "append",
                    "value": "Sentencia Rol 1234-2023 de la Corte Suprema establece que...",
                    "previous_value": None,
                    "reason": "Usuario agregó argumento faltante vía CLI",
                    "case_id": "caso-abc123"
                }
            ]
        }
    )


class NIFPatchResult(BaseModel):
    """Resultado de aplicar un patch."""
    success: bool
    patch: NIFPatch | None = None
    error: str = ""
    nif_version: int = 0  # Versión del NIF después de aplicar (0 si falló)
    conflict: bool = False
    conflict_details: str = ""


class NIFDiff(BaseModel):
    """Diferencia entre dos versiones del NIF."""
    case_id: str
    from_version: int
    to_version: int
    from_timestamp: str
    to_timestamp: str
    patches_applied: list[NIFPatch] = Field(default_factory=list)
    fields_changed: list[str] = Field(default_factory=list)
    agents_involved: list[str] = Field(default_factory=list)
    summary: str = ""  # Resumen legible: "researcher agregó 3 normas, contradictor marcó 1 hipótesis como débil"
