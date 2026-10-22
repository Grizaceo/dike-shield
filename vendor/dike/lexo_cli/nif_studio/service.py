"""service.py — Fachada JSON sobre NIFBoard para el NIF Studio.

Traduce las operaciones del NIFBoard (versionado, patch-based) a dicts
JSON-serializables para la API. Toda escritura queda atribuida a un autor
(``agent_id``): ``user`` para humanos, el rol para agentes AI.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from shared.lib.nif_board import NIFBoard
from lexo_cli.starter.userconfig import resolve_cases_root


def _cases_root(cases_root: Optional[str]) -> str:
    # Se resuelve en cada llamada, no al importar: el usuario activo puede
    # cambiar durante la vida del proceso (y cambiaba entre `dike web` y el
    # resto del CLI, dejando los casos en dos mundos distintos).
    return str(resolve_cases_root(explicit=cases_root))


def get_board(case_id: str, cases_root: Optional[str] = None) -> NIFBoard:
    return NIFBoard(case_id, cases_root=_cases_root(cases_root))


# ---------------------------------------------------------------------------
# Lectura
# ---------------------------------------------------------------------------

def nif_snapshot(case_id: str, cases_root: Optional[str] = None) -> dict:
    """NIF completo + metadatos (versión, salud, existencia)."""
    board = get_board(case_id, cases_root)
    nif = board.read()
    if nif is None:
        return {"exists": False, "case_id": case_id, "version": 0,
                "nif": None, "health": None}
    return {
        "exists": True,
        "case_id": case_id,
        "version": board.version(),
        "nif": _normalize_nif(nif),
        "health": _safe_health(board),
    }


# Claves de lista esperadas en el NIF (el _empty_nif del board omite
# relevant_factors aunque el modelo lo define → normalizamos en lectura).
_LIST_KEYS = (
    "subjects", "norms", "norm_relations", "admin_acts", "principles",
    "deontic_positions", "conflicts", "hypotheses", "gaps", "relevant_factors",
)


def _normalize_nif(nif: dict) -> dict:
    """Garantiza que el NIF tenga todas las secciones (evita KeyError en la UI)."""
    if not isinstance(nif, dict):
        return nif
    for k in _LIST_KEYS:
        if not isinstance(nif.get(k), list):
            nif[k] = []
    facts = nif.get("facts")
    if not isinstance(facts, dict):
        nif["facts"] = {"known": [], "alleged": [], "missing": []}
    else:
        for fk in ("known", "alleged", "missing"):
            if not isinstance(facts.get(fk), list):
                facts[fk] = []
    return nif


def _safe_health(board: NIFBoard) -> dict:
    try:
        return board.health_check()
    except Exception as exc:  # nunca romper la UI por el diagnóstico
        return {"status": "unknown", "issues": [f"health_check falló: {exc}"], "warnings": []}


def patch_to_dict(p: Any) -> dict:
    op = getattr(p, "operation", None)
    return {
        "patch_id": getattr(p, "patch_id", ""),
        "version": getattr(p, "nif_version", 0),
        "agent_id": getattr(p, "agent_id", ""),
        "field_path": getattr(p, "field_path", ""),
        "operation": op.value if hasattr(op, "value") else str(op),
        "value": getattr(p, "value", None),
        "reason": getattr(p, "reason", ""),
        "timestamp": getattr(p, "timestamp", ""),
    }


def patches_since(case_id: str, since: int = 0, cases_root: Optional[str] = None) -> dict:
    # Consulta directa: NIFPatch no expone su versión, así que leemos la tabla
    # nif_patches (incluye la columna version) para que el pulso muestre la
    # versión real de cada cambio, no 0.
    board = get_board(case_id, cases_root)
    patches: list[dict] = []
    try:
        with sqlite3.connect(str(board.db_path)) as con:
            rows = con.execute(
                "SELECT patch_id, version, agent_id, field_path, operation, "
                "value_json, reason, timestamp FROM nif_patches "
                "WHERE version > ? ORDER BY version ASC",
                (since,),
            ).fetchall()
        for r in rows:
            try:
                value = json.loads(r[5]) if r[5] else None
            except (json.JSONDecodeError, TypeError):
                value = None
            patches.append({
                "patch_id": r[0], "version": r[1], "agent_id": r[2],
                "field_path": r[3], "operation": r[4], "value": value,
                "reason": r[6], "timestamp": r[7],
            })
    except sqlite3.Error:
        pass
    return {
        "case_id": case_id,
        "from_version": since,
        "to_version": board.version(),
        "patches": patches,
    }


def list_cases(cases_root: Optional[str] = None) -> list[dict]:
    """Casos con NIF poblado (al menos una versión persistida)."""
    root = Path(_cases_root(cases_root))
    out: list[dict] = []
    if not root.exists():
        return out
    for case_dir in sorted(root.iterdir()):
        db = case_dir / "nif_board.db"
        if not db.exists():
            continue
        try:
            with sqlite3.connect(str(db)) as con:
                row = con.execute(
                    "SELECT data_json, MAX(version) FROM nif_state"
                ).fetchone()
        except sqlite3.Error:
            continue
        if not row or row[0] is None:
            continue
        import json
        try:
            nif = json.loads(row[0])
        except (json.JSONDecodeError, TypeError):
            continue
        out.append({
            "case_id": case_dir.name,
            "version": row[1] or 0,
            "legal_question": nif.get("legal_question", ""),
            "confidence": nif.get("confidence", 0.0),
            "validated_by_human": nif.get("validated_by_human", False),
            "norms": len(nif.get("norms", [])),
            "hypotheses": len(nif.get("hypotheses", [])),
            "gaps": len(nif.get("gaps", [])),
        })
    return out


# ---------------------------------------------------------------------------
# Escritura (humana)
# ---------------------------------------------------------------------------

def _result_to_dict(result: Any) -> dict:
    return {
        "success": bool(getattr(result, "success", False)),
        "version": getattr(result, "nif_version", 0),
        "error": getattr(result, "error", None),
    }


def user_edit(case_id: str, field_path: str, value: Any,
              reason: str = "Edición del usuario",
              cases_root: Optional[str] = None) -> dict:
    board = get_board(case_id, cases_root)
    nif = board.read()
    if nif is None:
        return {"success": False, "error": "El caso no tiene NIF. Inicialízalo primero."}
    # Auto-sanar: si se agrega a una sección lista que aún no existe en el
    # NIF almacenado (p.ej. relevant_factors), crearla antes del append.
    if field_path in _LIST_KEYS and not isinstance(nif.get(field_path), list):
        from shared.schemas.nif_patch import NIFPatch, PatchOperation
        board.write(NIFPatch(agent_id="user", field_path=field_path,
                             operation=PatchOperation.replace, value=[],
                             reason=f"Inicializa sección {field_path}", case_id=board.case_id))
    result = board.user_edit(field_path, value, reason=reason)
    return _result_to_dict(result)


def fill_gap(case_id: str, gap_index: int, filled_by: str, filled_with: str,
             cases_root: Optional[str] = None) -> dict:
    board = get_board(case_id, cases_root)
    result = board.fill_gap(gap_index, filled_by=filled_by, filled_with=filled_with)
    return _result_to_dict(result)


def set_validated(case_id: str, validated: bool,
                  cases_root: Optional[str] = None) -> dict:
    reason = "Marco validado por humano" if validated else "Validación humana retirada"
    return user_edit(case_id, "validated_by_human", bool(validated), reason, cases_root)


def set_confidence(case_id: str, confidence: float,
                   cases_root: Optional[str] = None) -> dict:
    confidence = max(0.0, min(1.0, float(confidence)))
    return user_edit(case_id, "confidence", confidence,
                     "Confianza ajustada por humano", cases_root)


# ---------------------------------------------------------------------------
# Inicialización / seed
# ---------------------------------------------------------------------------

def init_case(case_id: str, legal_question: str, problem_type: str = "mixto",
              cases_root: Optional[str] = None) -> dict:
    board = get_board(case_id, cases_root)
    if board.read() is not None:
        return {"success": False, "error": "El caso ya tiene NIF."}
    try:
        board.init_nif(legal_question, problem_type=problem_type, source="nif_studio")
        return {"success": True, "version": board.version()}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def seed_demo(case_id: str, cases_root: Optional[str] = None) -> dict:
    """Crea un caso laboral chileno realista para demostrar el Studio."""
    board = get_board(case_id, cases_root)
    if board.read() is not None:
        return {"success": True, "version": board.version(), "note": "ya existía"}

    board.init_nif(
        "¿Procede la acción por despido injustificado y el recargo del art. 168 "
        "CT cuando el empleador invoca necesidades de la empresa (art. 161) sin "
        "acreditarlas?",
        problem_type="mixto",
        source="nif_studio",
    )
    cid = board.case_id

    def w(agent_id, field_path, value, reason, op=None):
        from shared.schemas.nif_patch import NIFPatch, PatchOperation
        operation = op or PatchOperation.append
        board.write(NIFPatch(agent_id=agent_id, field_path=field_path,
                             operation=operation, value=value, reason=reason, case_id=cid))

    from shared.schemas.nif_patch import PatchOperation

    # Hechos (researcher)
    for f in ["El trabajador prestó servicios por 4 años y 3 meses.",
              "La carta de despido invoca el art. 161 (necesidades de la empresa)."]:
        w("researcher", "facts.known", f, "Hecho establecido")
    w("researcher", "facts.alleged",
      "El empleador no acompañó antecedentes económicos que acrediten las necesidades.",
      "Hecho alegado por la defensa del trabajador")
    w("researcher", "facts.missing",
      "Liquidaciones de sueldo de los últimos 3 meses (base de cálculo).",
      "Hecho faltante")

    # Sujetos (case_designer)
    w("case_designer", "subjects",
      {"id": "s-trab", "role": "actor", "label": "Trabajador demandante"},
      "Parte demandante")
    w("case_designer", "subjects",
      {"id": "s-emp", "role": "demandado", "label": "Empresa empleadora"},
      "Parte demandada")

    # Normas (researcher) — con operadores deónticos variados
    w("researcher", "norms",
      {"gid": "cl.norma.ct:art:0168", "label": "CT art. 168 — recargo por despido injustificado",
       "operator": "obligacion", "supuesto_de_hecho": "Despido declarado injustificado",
       "consecuencia_juridica": "Recargo del 30%-100% de la indemnización por años de servicio",
       "destinatario": "Empleador", "status": "vigente"},
      "Norma central de la pretensión")
    w("researcher", "norms",
      {"gid": "cl.norma.ct:art:0161", "label": "CT art. 161 — necesidades de la empresa",
       "operator": "permiso", "supuesto_de_hecho": "Necesidades de funcionamiento de la empresa",
       "consecuencia_juridica": "Faculta el término del contrato con indemnización",
       "destinatario": "Empleador", "status": "vigente"},
      "Causal invocada por el empleador")
    w("researcher", "norms",
      {"gid": "cl.norma.ct:art:0162", "label": "CT art. 162 — formalidades y aviso",
       "operator": "obligacion", "supuesto_de_hecho": "Término de contrato",
       "consecuencia_juridica": "Deber de comunicar por escrito y pagar cotizaciones al día",
       "destinatario": "Empleador", "status": "vigente"},
      "Norma de formalidades")

    # Relación entre normas
    w("case_designer", "norm_relations",
      {"from_gid": "cl.norma.ct:art:0168", "to_gid": "cl.norma.ct:art:0161",
       "relation": "derrotabilidad",
       "notes": "El recargo del 168 se derrota si el empleador acredita la causal del 161."},
      "Interacción normativa clave")

    # Hipótesis (case_designer)
    w("case_designer", "hypotheses",
      {"id": "h-1", "type": "normativa",
       "claim": "El despido es injustificado porque la causal del art. 161 no fue acreditada, "
                "lo que activa el recargo del art. 168.",
       "evidence_for": ["Ausencia de antecedentes económicos en el proceso"],
       "evidence_against": [], "status": "open"},
      "Hipótesis principal de la demanda")

    # Factores relevantes (researcher) — para el contradictor.
    # Se usa replace para crear la clave (el _empty_nif del board la omite).
    w("researcher", "relevant_factors",
      [{"factor_id": "f-acreditacion-161", "weight": 1.0,
        "description": "Acreditación efectiva de las necesidades de la empresa (art. 161).",
        "source_evidence": ["cl.norma.ct:art:0161"]},
       {"factor_id": "f-cotizaciones", "weight": 0.5,
        "description": "Pago íntegro de cotizaciones previsionales al término (ley Bustos).",
        "source_evidence": ["cl.norma.ct:art:0162"]}],
      "Factores jurídicos identificados", op=PatchOperation.replace)

    # Conflicto (contradictor)
    w("contradictor", "conflicts",
      {"type": "probatorio",
       "description": "El empleador podría aportar prueba económica en la etapa de prueba, "
                      "revirtiendo la falta de acreditación.",
       "resolution_criteria": "Carga de la prueba del art. 161 recae en el empleador."},
      "Riesgo identificado por el contradictor")

    # Gaps (Fail -> Demand -> Fill)
    w("contradictor", "gaps",
      {"description": "Falta jurisprudencia reciente sobre el estándar de acreditación del art. 161.",
       "impact": "alto", "status": "open", "demanded_by": "contradictor", "scraper_ticket": True},
      "Gap demandado por el contradictor")
    w("researcher", "gaps",
      {"description": "Verificar si las cotizaciones estaban pagadas al mes del despido.",
       "impact": "medio", "status": "open", "demanded_by": "researcher"},
      "Gap demandado por el researcher")

    # Confianza inicial (juez)
    w("juez", "confidence", 0.42, "Evaluación inicial: hipótesis sólida pero con gaps probatorios",
      op=PatchOperation.replace)

    return {"success": True, "version": board.version()}
