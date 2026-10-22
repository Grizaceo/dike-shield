"""6.3 — Compliance Ley 21.719: verifica un documento contra los controles.

Invoca el analizador del servidor ley21719 (registrado como MCP en
config.yaml) directamente, sin depender del transporte MCP. El servidor
vive en `_legal_repos/mcp-servers/ley21719/`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVER_DIR = (
    Path(__file__).resolve().parents[1]
    / "_legal_repos" / "mcp-servers" / "ley21719"
)


def verificar_compliance_ley21719(texto: str) -> dict:
    """Verifica un documento contra los controles de la Ley 21.719.

    Devuelve el reporte del servidor con hallazgos por artículo.
    """
    if not _SERVER_DIR.is_dir():
        raise RuntimeError(f"servidor ley21719 no encontrado en {_SERVER_DIR}")
    if str(_SERVER_DIR) not in sys.path:
        sys.path.insert(0, str(_SERVER_DIR))

    from server import tool_check_document

    reporte = tool_check_document(document_id="cli-analizar", text=texto)
    # Normalizar a hallazgos con nivel.
    hallazgos = []
    for r in reporte.get("results", []):
        nivel = {
            "OK": "bajo", "PARTIAL": "medio", "MISSING": "alto",
        }.get(r.get("status", ""), "info")
        hallazgos.append({
            "control": f"art. {r.get('article_id', '?')} ({r.get('category', '?')})",
            "nivel": nivel,
            "detalle": r.get("evidence", "")[:200],
            "status": r.get("status"),
            "score": r.get("score"),
        })
    return {
        "document_id": reporte.get("document_id"),
        "articles_checked": reporte.get("articles_checked", 0),
        "articles_ok": reporte.get("articles_ok", 0),
        "articles_partial": reporte.get("articles_partial", 0),
        "articles_missing": reporte.get("articles_missing", 0),
        "overall_risk": reporte.get("overall_risk"),
        "hallazgos": hallazgos,
    }
