"""3.4b — Aristas CONFLICTS_WITH / RESOLVED_BY (Falkor-IRAC §5.13).

Precondición 1.7 (HECHO): la autoridad de prevalencia es ÚNICA —
IndexO `/arbol/prevalece`. Toda arista de conflicto se valida contra ese
endpoint antes de proponerse; si el endpoint no responde, la arista NO se
propone (fail-closed: sin autoridad, no hay conflicto declarado).

Semántica:
- CONFLICTS_WITH: dos normas que el documento presenta como incompatibles
  (o que el extractor detecta como potencialmente conflictivas).
- RESOLVED_BY: la norma A resuelve el conflicto con B según la autoridad
  de prevalencia (resultado del árbol: A prevalece sobre B).
"""
from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# Patrones de lenguaje conflictivo en textos jurídicos.
_CONFLICT_MARKS = [
    r"\b(contradice|contradicci[oó]n|conflicto|incompatible|incompatibilidad)\b",
    r"\b(prevalece|prevalencia|primac[ií]a|preferencia)\b",
    r"\b(deroga|derogaci[oó]n|deja sin efecto|reemplaza)\b",
    r"\b(no obstante|sin perjuicio de|a pesar de)\b",
    r"\b(excepto|salvo que|excepci[oó]n)\b",
]

_ARTICLE_RE = re.compile(r"\b(?:art[ií]culos?|arts?\.?)\s+(\d+[a-z]?)(?:\s*[-,y]\s*(\d+[a-z]?))?", re.IGNORECASE)
_BODY_RE = re.compile(
    r"\b(c[oó]digo\s+(?:del\s+)?(?:trabajo|civil|penal|procesal\s+penal|comercio)|"
    r"ley\s+\d+(?:\.\d+)?|constituci[oó]n\s+pol[ií]tica)\b",
    re.IGNORECASE,
)

# Mapeo de cuerpo → alias de GID (mismo vocabulario que el resolver).
_BODY_ALIAS = {
    "codigo del trabajo": "ct",
    "codigo civil": "cc",
    "codigo penal": "cp",
    "codigo procesal penal": "cpp",
    "codigo de comercio": "ccom",
    "constitucion politica": "cpr",
}


@dataclass
class ConflictoDetectado:
    """Un conflicto potencial entre dos GIDs, con su validación de autoridad."""

    gid_a: str
    gid_b: str
    snippet: str
    validated: bool = False
    resultado: str | None = None  # "A" | "B" | "EMPATE" | None
    regla_aplicada: str | None = None
    edge_type: str = "CONFLICTS_WITH"  # se actualiza a RESOLVED_BY si hay autoridad

    def to_dict(self) -> dict:
        return {
            "gid_a": self.gid_a,
            "gid_b": self.gid_b,
            "snippet": self.snippet[:200],
            "validated": self.validated,
            "resultado": self.resultado,
            "regla_aplicada": self.regla_aplicada,
            "edge_type": self.edge_type,
        }


def _gid_for(body: str, article: str) -> str | None:
    """Construye el GID para (cuerpo, artículo) si el cuerpo es conocido."""
    key = body.strip().lower()
    # Normalizar sin acentos: el catálogo usa claves sin tilde ("codigo civil").
    key = (
        key.replace("á", "a").replace("é", "e").replace("í", "i")
        .replace("ó", "o").replace("ú", "u").replace("ñ", "n")
    )
    alias = _BODY_ALIAS.get(key)
    if alias is None:
        return None
    token = f"{int(article):04d}" if article.isdigit() else article
    return f"cl.norma.{alias}:art:{token}"


def detectar_conflictos(text: str) -> list[ConflictoDetectado]:
    """Detecta pares de normas potencialmente conflictivas en un texto.

    Heurística: dos menciones de artículos de cuerpos DISTINTOS dentro de
    una ventana (párrafo o grupo de oraciones) con lenguaje conflictivo
    (contradice, prevalece, deroga…). La ventana es necesaria: el lenguaje
    conflictivo suele estar en una oración distinta de la que menciona
    las normas.
    """
    if not text:
        return []
    conflictos: list[ConflictoDetectado] = []
    # Ventanas: párrafos (separados por doble salto de línea) o, si no hay
    # párrafos, grupos de hasta 3 oraciones.
    parrafos = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not parrafos:
        oraciones = [s.strip() for s in re.split(r"(?<=[.;])\s+", text) if s.strip()]
        parrafos = [
            " ".join(oraciones[i : i + 3])
            for i in range(0, len(oraciones), 3)
        ]
    for ventana in parrafos:
        if not any(re.search(m, ventana, re.IGNORECASE) for m in _CONFLICT_MARKS):
            continue
        bodies = _BODY_RE.findall(ventana)
        articles = _ARTICLE_RE.findall(ventana)
        if len(bodies) < 2 or len(articles) < 2:
            continue
        # Normalizar cuerpos (findall con grupos devuelve tuplas).
        norm_bodies = [b[0] if isinstance(b, tuple) else b for b in bodies]
        norm_articles = [a[0] for a in articles]
        # Primer par de cuerpos distintos con sus artículos.
        gid_a = None
        gid_b = None
        for i in range(len(norm_bodies)):
            for j in range(i + 1, len(norm_bodies)):
                if norm_bodies[i].lower() == norm_bodies[j].lower():
                    continue
                ga = _gid_for(norm_bodies[i], norm_articles[i] if i < len(norm_articles) else norm_articles[0])
                gb = _gid_for(norm_bodies[j], norm_articles[j] if j < len(norm_articles) else norm_articles[0])
                if ga and gb and ga != gb:
                    gid_a, gid_b = ga, gb
                    break
            if gid_a:
                break
        if gid_a and gid_b:
            conflictos.append(ConflictoDetectado(gid_a=gid_a, gid_b=gid_b, snippet=ventana[:300]))
    return conflictos


def validar_autoridad(conflicto: ConflictoDetectado, *, base_url: str = "http://localhost:7861") -> ConflictoDetectado:
    """Valida un conflicto contra la autoridad única de prevalencia.

    Fail-closed: si el endpoint no responde o el resultado no es A/B, la
    arista queda como CONFLICTS_WITH sin resolver (nunca se inventa la
    prevalencia). Si el árbol decide, la arista se actualiza a RESOLVED_BY
    con la regla aplicada.
    """
    url = (
        f"{base_url}/arbol/prevalece"
        f"?gid_a={urllib.parse.quote(conflicto.gid_a)}"
        f"&gid_b={urllib.parse.quote(conflicto.gid_b)}"
    )
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return conflicto  # fail-closed: sin autoridad, sin RESOLVED_BY
    resultado = data.get("resultado")
    if resultado in ("A", "B"):
        conflicto.validated = True
        conflicto.resultado = resultado
        conflicto.regla_aplicada = data.get("regla_aplicada")
        conflicto.edge_type = "RESOLVED_BY"
    return conflicto


def proponer_aristas_conflicto(
    text: str,
    *,
    base_url: str = "http://localhost:7861",
    validate: bool = True,
) -> list[ConflictoDetectado]:
    """Pipeline completo: detectar → validar contra la autoridad única."""
    conflictos = detectar_conflictos(text)
    if validate:
        conflictos = [validar_autoridad(c, base_url=base_url) for c in conflictos]
    return conflictos
