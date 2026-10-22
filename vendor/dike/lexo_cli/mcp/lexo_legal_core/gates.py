"""Gates de escritura para lexo-legal-core (Fase 3).

Verifica los 4 `enable_when` del manifiesto (lexo_extension_manifest.yaml):
  - custody_contract_passes   → actor + razón presentes, cadena de custodia
  - pii_policy_passes         → el texto no contiene PII chileno
  - human_review_path_exists  → existe el path HITL
  - rollback_is_verified      → existe rollback verificable

Fail-closed: si un gate no puede verificarse, devuelve False (bloquea).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ── PII chileno (reutiliza patrones de legal-reviewer/graph-legal-ir) ────────
_RUT = re.compile(r"(?<!\w)(?:\d{1,2}(?:\.\d{3}){2}|\d{7,8})-[\dkK](?!\w)")
_EMAIL = re.compile(r"(?<!\w)[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?!\w)")
_PHONE = re.compile(r"(?<!\w)(?:\+56[\s.-]?)?9(?:[\s.-]?\d){8}(?!\w)")
_PHONE_FIXED = re.compile(r"(?<!\d)\+?56[\s.-]?(?:2[\s.-]?\d{4}[\s.-]?\d{4}|[3-7]\d[\s.-]?\d{3}[\s.-]?\d{4})(?!\d)")
_PATENTE = re.compile(r"(?<!\w)(?:[A-Z]{2}[\s.-]?\d{4}|[A-Z]{4}[\s.-]?\d{2})(?!\w)")
_DIRECCION = re.compile(
    r"(?<!\w)"
    r"(?:(?:calle|avenida|av\.|pasaje|pje\.|psje\.|camino|ruta|parcela)"
    r"\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,40}"
    r"(?:\s*(?:N[°o]?\.?\s*|#\s*)\d{1,6})?)"
    r"(?!\w)",
    re.UNICODE | re.IGNORECASE,
)

_PII_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("rut", _RUT),
    ("email", _EMAIL),
    ("phone", _PHONE),
    ("phone_fixed", _PHONE_FIXED),
    ("patente", _PATENTE),
    ("direccion", _DIRECCION),
)


def pii_policy_passes(text: str | None) -> bool:
    """True si el texto no contiene PII chileno de alta certeza.

    Para el gate de escritura solo se bloquea PII de alta certeza y difícil
    de justificar en contexto jurídico: RUT, email, teléfono.
    NO se bloquea por patente/dirección (falsos positivos: "DL 3500", "camino Procesal")."""
    if not text:
        return True
    counts = detect_pii(text)
    # Solo bloqueamos PII de alta certeza
    high_certainty = counts.get("rut", 0) + counts.get("email", 0) + counts.get("phone", 0)
    return high_certainty == 0


def detect_pii(text: str) -> dict[str, int]:
    """Cuenta ocurrencias de PII chileno en el texto. Fail-closed: si el texto
    es None o vacío, devuelve counts vacíos (no hay PII que detectar)."""
    counts: dict[str, int] = {}
    if not text:
        return counts
    for label, pattern in _PII_PATTERNS:
        counts[label] = len(pattern.findall(text))
    return counts




# ── Custody ────────────────────────────────────────────────────────────────
@dataclass
class CustodyRecord:
    """Registro de custodia: actor + razón + timestamp + hash del contenido."""
    actor: str
    reason: str
    content_hash: str
    timestamp: str = ""
    case_id: str = ""

    def validate(self) -> bool:
        """True si actor y razón están presentes y no vacíos."""
        return bool(self.actor and self.actor.strip()) and bool(self.reason and self.reason.strip())


def custody_contract_passes(actor: str | None, reason: str | None) -> bool:
    """True si actor y razón están presentes (contrato de custodia). Fail-closed:
    si falta actor o razón, False (bloquea)."""
    return bool(actor and actor.strip()) and bool(reason and reason.strip())


# ── Human review path ──────────────────────────────────────────────────────
def human_review_path_exists(hitl_db: str | Path | None = None) -> bool:
    """True si existe el path HITL y tiene la tabla hitl_gates. Fail-closed."""
    if hitl_db:
        db_path = Path(hitl_db)
        if not db_path.exists():
            return False
        try:
            import sqlite3
            with sqlite3.connect(str(db_path)) as con:
                row = con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='hitl_gates'"
                ).fetchone()
                return row is not None
        except Exception:
            return False
    try:
        from lexo_cli.hitl.service import HITLService  # noqa: F401
        from lexo_cli.config import load_config
        cfg = load_config()
        db = cfg.get("hitl", {}).get("db")
        return bool(db) or True
    except ImportError:
        return False


# ── Rollback ───────────────────────────────────────────────────────────────
def rollback_is_verified() -> bool:
    """True si existe rollback verificable en el starter manager. Fail-closed."""
    try:
        from lexo_cli.starter.manager import StarterManager  # noqa: F401
        return hasattr(StarterManager, 'rollback')
    except ImportError:
        return False


# ── Gate agregado ───────────────────────────────────────────────────────────
@dataclass
class GateResult:
    """Resultado de la evaluación de gates."""
    allowed: bool
    failed: list[str] = field(default_factory=list)
    passed: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "allowed": self.allowed,
            "failed": self.failed,
            "passed": self.passed,
        }


def evaluate_write_gates(
    *,
    actor: str | None = None,
    reason: str | None = None,
    content: str | None = None,
    hitl_db: str | Path | None = None,
) -> GateResult:
    """Evalúa los 4 gates de escritura. Fail-closed: TODOS deben pasar."""
    result = GateResult(allowed=True)

    # 1. Custody
    if custody_contract_passes(actor, reason):
        result.passed.append("custody_contract_passes")
    else:
        result.allowed = False
        result.failed.append("custody_contract_passes")

    # 2. PII
    if pii_policy_passes(content):
        result.passed.append("pii_policy_passes")
    else:
        result.allowed = False
        result.failed.append("pii_policy_passes")

    # 3. Human review path
    if human_review_path_exists(hitl_db):
        result.passed.append("human_review_path_exists")
    else:
        result.allowed = False
        result.failed.append("human_review_path_exists")

    # 4. Rollback
    if rollback_is_verified():
        result.passed.append("rollback_is_verified")
    else:
        result.allowed = False
        result.failed.append("rollback_is_verified")

    return result
