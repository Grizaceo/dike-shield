"""View-model legible: traduce datos técnicos a lenguaje de abogado.

Regla de producto: **nunca un `_`, `/` de sistema, path crudo, ni ID técnico
en la primera capa visual**. El dato técnico sigue disponible (toggle "ver
datos técnicos" o `--json`), pero el default es lenguaje humano.

| Raw actual                          | Presentación                        |
|-------------------------------------|-------------------------------------|
| path: /home/<usuario>/.../CPR_raw_backup | "Constitución (borrador)"           |
| score BM25 15,3 / coseno 0,03       | "relevancia alta en esta búsqueda"  |
| area: unknown                       | "Área: sin clasificar"              |
| backend: text                        | Oculto (o "tipo: texto")            |
| cl.norma.cpc:art:0467               | "CPC art. 467" (GID en <details>)   |
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from lexo_cli.gid import a_runtime
from lexo_cli.starter.materias import cuerpo_label

# ── Nombres legibles de documentos ─────────────────────────────────────────

# Patrones de ruido de la vault: prefijos de carpeta, sufijos de respaldo,
# marcadores de parseo. Se eliminan del nombre mostrado, no del path real.
_NOISE_PREFIXES = (
    "_sin_parsear", "_parseado", "archive", "backup", "raw", "vault",
    "Vigente", "Lexo", "docs", "documentos",
)
_NOISE_SUFFIXES = (
    "_raw_backup", "_raw", "_backup", "_original", "_copia", "_copy",
    "_sin_parsear", "_parseado", "_v1", "_v2", "_final", "_final2",
)
_EXTENSIONS = (".md", ".txt", ".pdf", ".docx", ".doc", ".html", ".json", ".yaml", ".yml")


def _strip_noise(name: str) -> str:
    stem = name
    for ext in _EXTENSIONS:
        if stem.lower().endswith(ext):
            stem = stem[: -len(ext)]
            break
    lowered = stem.lower()
    for suffix in _NOISE_SUFFIXES:
        if lowered.endswith(suffix):
            stem = stem[: -len(suffix)]
            lowered = stem.lower()
            break
    return stem.strip(" _-")


def _title_case(name: str) -> str:
    """'CPR' → 'CPR'; 'ley_21719' → 'Ley 21719'; 'codigo-civil' → 'Código Civil'."""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[_\-]+", " ", text).strip()
    words = text.split()
    if not words:
        return name
    out: list[str] = []
    for indice, word in enumerate(words):
        upper = word.upper()
        if upper in ("CPR", "CC", "CPC", "CT", "CP", "CPP", "CCOM", "CTRIB", "COT", "DL", "DFL", "Ley", "Leyes"):
            out.append(upper if upper != "Ley" else "Ley")
        elif word.isdigit():
            anterior = words[indice - 1].upper() if indice else ""
            out.append(_numero_de_norma(word) if anterior in ("LEY", "LEYES", "DL", "DFL") else word)
        else:
            out.append(word.capitalize())
    return " ".join(out)


def _numero_de_norma(digitos: str) -> str:
    """21719 → «21.719». En Chile una ley se cita con el punto de millar.

    «Ley 21719» no es la forma en que un abogado escribe ni busca esa norma, y
    era lo que salía en pantalla cada vez que el alias no estaba en el catálogo
    de cuerpos.
    """
    if len(digitos) <= 3:
        return digitos
    grupos = []
    resto = digitos
    while len(resto) > 3:
        grupos.insert(0, resto[-3:])
        resto = resto[:-3]
    grupos.insert(0, resto)
    return ".".join(grupos)


def document_title(row: dict) -> str:
    """Nombre legible de un resultado documental (nunca un path crudo)."""
    filename = row.get("filename") or ""
    path = row.get("path") or row.get("url") or ""
    raw = filename or Path(str(path)).name
    if not raw:
        return "Documento"
    cleaned = _strip_noise(raw)
    if not cleaned:
        return _title_case(raw)
    # Siglas de cuerpos conocidos → nombre completo del catálogo
    # (CPR_raw_backup.md → "Constitución Política de la República").
    alias = cleaned.lower().replace(" ", "_")
    label = cuerpo_label(alias)
    if label != alias:
        return label
    return _title_case(cleaned)


def document_area(row: dict) -> str:
    """Área legible: 'unknown'/vacío → 'sin clasificar'."""
    area = row.get("area") or row.get("materia") or ""
    if not area or str(area).lower() in ("unknown", "none", "n/a", "sin_clasificar"):
        return "sin clasificar"
    return str(area).replace("_", " ").capitalize()


def document_backend(row: dict, section_backend: str | None = None) -> str:
    """Backend legible: 'text' → 'texto', 'indexo_hybrid' → 'búsqueda semántica'."""
    backend = row.get("backend") or section_backend or ""
    return {
        "text": "texto",
        "local_rg": "texto",
        "indexo": "búsqueda semántica",
        "indexo_hybrid": "búsqueda semántica + texto",
        "starter_bm25": "ley",
    }.get(str(backend), str(backend) or "texto")


def relevancia(score: float | None, mejor: float | None = None) -> dict:
    """Cuán arriba quedó un resultado **dentro de esta búsqueda**.

    Esto se llamaba `confidence` y multiplicaba el score por cien. Los scores
    no son probabilidades: BM25 devuelve 15,3 y quedaba «Confianza 100%» en
    todas las filas —incluida la que no respondía la pregunta—, mientras
    IndexO devuelve coseno 0,03 y quedaba «Confianza 3%» en el documento más
    pertinente del expediente. Los dos números eran falsos y el primero, en
    una herramienta jurídica, afirmaba una certeza que nadie calculó.

    Lo que sí se puede afirmar es la posición relativa: este resultado puntuó
    tanto respecto del primero de la misma lista. Eso es lo que se muestra, y
    se muestra como banda («alta», «media», «baja»), no como porcentaje, para
    que no se lea como una probabilidad de acierto.
    """
    if score is None:
        return {"nivel": "sin puntuación", "proporcion": None, "etiqueta": "sin puntuación"}
    try:
        valor = float(score)
    except (TypeError, ValueError):
        return {"nivel": "sin puntuación", "proporcion": None, "etiqueta": "sin puntuación"}
    tope = float(mejor) if mejor else valor
    proporcion = 1.0 if tope <= 0 else max(0.0, min(1.0, valor / tope))
    if proporcion >= 0.75:
        nivel = "alta"
    elif proporcion >= 0.45:
        nivel = "media"
    else:
        nivel = "baja"
    return {
        "nivel": nivel,
        "proporcion": round(proporcion, 3),
        "etiqueta": f"relevancia {nivel} en esta búsqueda",
    }


_VIGENCIA_LEGIBLE = {
    "IN_FORCE": "vigente",
    "OUT_OF_FORCE": "derogado",
    "FUTURE": "aún no vigente",
    "UNKNOWN_BEFORE_SNAPSHOT": "texto histórico no verificable",
    "TEMPORAL_UNKNOWN": "vigencia indeterminada",
}


def vigencia_legible(
    status: str | None, citation_status: str | None = None, out_of_force_reason: str | None = None,
) -> str:
    """Etiqueta jurídica estable sin convertir texto no citable en vigente."""
    normalized = str(status or "")
    if normalized == "OUT_OF_FORCE" and out_of_force_reason == "SUPERSEDED_VERSION":
        # P12 (decisión 2): no es una derogación; el texto vigente no está en el corpus.
        return "versión del texto vencida (el texto vigente no está en tu biblioteca)"
    if normalized == "IN_FORCE" and citation_status == "NOT_CITABLE_TEXT_DEFECT":
        # P10 (HITL «i»): el abogado ve POR QUÉ no se puede citar.
        return "texto no citable (defecto de extracción)"
    if normalized == "IN_FORCE" and citation_status is not None and citation_status != "CITABLE":
        return "texto no citable"
    return _VIGENCIA_LEGIBLE.get(normalized, "vigencia desconocida")


def nif_vigencia_status(status: str | None, out_of_force_reason: str | None = None) -> str:
    """Proyecta evidencia temporal al enum limitado y fail-closed del NIF.

    El NIF no expresa todos los matices probatorios del resolver: toda vigencia
    que no esté positivamente acreditada queda `indeterminada` y exige revisión.
    Una versión vencida no es una derogación (P12): queda `indeterminada`.
    """
    if out_of_force_reason == "SUPERSEDED_VERSION":
        return "indeterminada"
    return {
        "IN_FORCE": "vigente",
        "OUT_OF_FORCE": "derogada",
    }.get(str(status or ""), "indeterminada")



def humanize_gid(gid: str) -> str:
    """'cl.norma.cpc:art:0467' → 'CPC art. 467' (con label del cuerpo). Lee también la v2."""
    par = a_runtime(gid)
    if par is None:
        return gid or ""
    alias, token = par
    body = cuerpo_label(alias)
    if token.isdigit():
        article = str(int(token))
    else:
        article = token.replace("_", " ")
    return f"{body} art. {article}"


def humanize_canonical_result(row: dict, mejor: float | None = None) -> dict:
    """View-model de un resultado canónico (ley).

    `mejor` es el score del primer resultado de la misma búsqueda: la
    relevancia solo tiene sentido relativa a su propia lista.
    """
    gid = row.get("gid") or ""
    score = row.get("score")
    conf = relevancia(score, mejor)
    temporal = row.get("temporal_status") or ""
    citation_status = row.get("citation_status")
    vigencia = vigencia_legible(temporal, citation_status, row.get("out_of_force_reason"))
    return {
        "titulo": humanize_gid(gid),
        "gid": gid,
        "texto": row.get("text", ""),
        "relevancia": conf,
        "vigencia": vigencia,
        "temporal_from": row.get("temporal_from"),
        "temporal_to": row.get("temporal_to"),
        # P11: por qué no es citable (HITL «i») y las notas de la BCN, que no
        # son texto de la norma (HITL «h»). Antes solo las entregaba el
        # buscador de normas del NIF, no la búsqueda principal de dike web.
        "motivo_no_citable": row.get("citation_defect"),
        "notas_bcn": list(row.get("bcn_notes") or []),
        "datos_tecnicos": {
            "eli": row.get("eli"),
            "text_sha256": row.get("text_sha256"),
            "citation_status": row.get("citation_status"),
            "channel": row.get("channel"),
            "backend": row.get("backend"),
        },
    }


def humanize_document_result(
    row: dict, section_backend: str | None = None, mejor: float | None = None
) -> dict:
    """View-model de un resultado documental (vault/IndexO)."""
    score = row.get("score")
    conf = relevancia(score, mejor)
    return {
        "titulo": document_title(row),
        "area": document_area(row),
        "tipo": document_backend(row, section_backend),
        "relevancia": conf,
        "snippet": row.get("snippet") or row.get("raw_content") or "",
        "datos_tecnicos": {
            "path": row.get("path") or row.get("url"),
            "filename": row.get("filename"),
            "backend": row.get("backend") or section_backend,
            "score": score,
        },
    }


def _mejor_score(rows: list) -> float | None:
    """El score más alto de una lista de resultados, o None si no hay."""
    valores = []
    for row in rows or []:
        try:
            valores.append(float((row or {}).get("score")))
        except (TypeError, ValueError):
            continue
    return max(valores) if valores else None


# ── H8: el veredicto de cobertura, en lenguaje de abogado ─────────────────────
# La etiqueta `relevancia` de cada artículo es relativa al mejor de la misma
# lista, así que el primero sale «alta» SIEMPRE — incluso cuando la lista no
# responde la consulta. Eso no lo arregla un umbral por artículo: lo que hace
# falta es una declaración a nivel de BÚSQUEDA, y tiene que ser legible.

_VEREDICTO_LEGIBLE = {
    "CUBIERTO": "cubierto",
    "PARCIAL": "cobertura parcial",
    # H8 (5.ª ronda): hay una cuarta vía. Sin ella, `AMBIGUA` caía en el
    # default «no verificada», que afirma que NO se verificó nada — un
    # defecto peor que el que se vino a arreglar.
    "AMBIGUA": "materia ambigua",
    "SIN_COBERTURA": "sin cobertura",
    # La evaluación no pudo correr. No es «cubierto»: no se sabe.
    "DESCONOCIDO": "cobertura no verificada",
}


def cobertura_legible(cobertura: dict | None) -> dict:
    """Veredicto de cobertura de la búsqueda, en palabras y sin adornos.

    Nunca devuelve «cubierto» por omisión: si no hay veredicto, el estado es
    «no verificada». Un default optimista sería el mismo defecto que se vino a
    arreglar — afirmar una cobertura que nadie midió.
    """
    if not cobertura:
        return {
            "estado": "no verificada",
            "detalle": "Esta búsqueda no fue evaluada contra el corpus.",
            "veredicto": None,
        }
    veredicto = cobertura.get("veredicto")
    estado = _VEREDICTO_LEGIBLE.get(str(veredicto), "no verificada")
    cuerpos_sin_cubrir = list(cobertura.get("cuerpos_esperados_sin_cubrir") or [])
    detalle = cobertura.get("mensaje") or ""
    if estado in ("cubierto", "cobertura parcial"):
        # Cuando sí hay cobertura, el detalle técnico importa menos que la cifra.
        detalle = detalle or "Mi corpus cubre los términos de esta consulta."
    if cuerpos_sin_cubrir:
        # H8 (2.ª ronda): «sin cobertura» sin cifras no le dice al abogado si le
        # falta un artículo o el cuerpo entero. La proporción va en la frase.
        from lexo_cli.starter.cobertura import CORPUS_DECLARADO
        from lexo_cli.starter.materias import cuerpo_label

        partes = []
        for alias in cuerpos_sin_cubrir:
            declarado = (CORPUS_DECLARADO.get("cuerpos") or {}).get(alias) or {}
            en_pack = declarado.get("articulos_en_pack", 0)
            total = declarado.get("articulos_totales")
            if total:
                partes.append("{} ({} de {} artículos)".format(
                    cuerpo_label(alias), en_pack, total))
            else:
                partes.append("{} ({} artículos)".format(cuerpo_label(alias), en_pack))
        sufijo = "Está instalado pero incompleto: " + ", ".join(partes) + "."
        detalle = "{} {}".format(detalle, sufijo) if detalle else sufijo
    return {
        "estado": estado,
        "detalle": detalle,
        "veredicto": veredicto,
        # Cifras, para que el detalle sea auditable y no una frase de confianza.
        "cobertura_terminos": cobertura.get("cobertura_terminos"),
        "cobertura_contenido": cobertura.get("cobertura_contenido"),
        "cuerpos_esperados": list(cobertura.get("cuerpos_esperados") or []),
        "cuerpos_sin_cubrir": cuerpos_sin_cubrir,
    }


def humanize_search_payload(payload: dict) -> dict:
    """View-model completo de una búsqueda (ley + documentos)."""
    ley = payload.get("ley") or {}
    docs = payload.get("documentos") or {}
    mejor_ley = _mejor_score(ley.get("results", []))
    mejor_doc = _mejor_score(docs.get("results", []))
    return {
        "query": payload.get("query"),
        "capa": payload.get("capa"),
        "cobertura": cobertura_legible(payload.get("cobertura")),
        "ley": {
            "resultados": [
                humanize_canonical_result(r, mejor_ley) for r in ley.get("results", [])
            ],
            "errores": ley.get("errors", []),
            "advertencias": ley.get("warnings", []),
            "corpus": ley.get("corpus", {}),
        },
        "documentos": {
            "resultados": [
                humanize_document_result(r, docs.get("backend"), mejor_doc)
                for r in docs.get("results", [])
            ],
            "errores": docs.get("errors", []),
            "advertencias": docs.get("warnings", []),
            "degradado": docs.get("degraded", False),
            "backend": docs.get("backend"),
        },
        "datos_tecnicos": {
            "backend": payload.get("backend"),
            "degraded": payload.get("degraded"),
            "errors": payload.get("errors", []),
            "filters_applied": payload.get("filters_applied", {}),
            "candidate_count": payload.get("candidate_count", 0),
            "post_filter_count": payload.get("post_filter_count", 0),
        },
    }
