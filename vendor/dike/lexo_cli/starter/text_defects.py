"""Defectos de extracción conocidos: texto atestado CITABLE que no lo es.

ARCH-002 P10 (decisión HITL «i», opción 2). Ley Chile marca el lugar de una
nota con ``<div class="n rnp"><a>NOTA:</a></div>``, a veces en mitad de una
palabra; el extractor anterior a P9 lo dejaba dentro del texto («lo
anteNOTA:⏎⏎rior», art. 162 CT) y la atestación CITABLE selló ese texto. El
hash no lo detecta: certifica fielmente los bytes corrompidos.

Dos mecanismos, ninguno fatal (el artículo se resuelve, no como CITABLE):

- **Catálogo por ``textSha256``** (``text_defects.v1.json``), calculado
  offline contra la verdad de terreno: extractor viejo vs. corregido sobre el
  caché BCN (``scripts/dike_defectos_texto.py``). Exacto para los packs
  medidos y se levanta solo al re-extraer (otro texto, otro hash).
- **Patrón de defensa** para textos fuera del catálogo: el ancla pegada al
  texto anterior en la misma línea, o una línea de ancla seguida del cuerpo
  de la nota. Medido sobre los 8.543 artículos instalados: 228 de 231
  afectados, 0 falsos positivos. El cuerpo ``np`` en su propia línea no
  coincide (decisión «h», aparte).

No se toca el corpus sellado: la marca vive en el código que lo lee.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

TEXT_DEFECT_STATUS = "NOT_CITABLE_TEXT_DEFECT"
DEFAULT_CATALOG = Path(__file__).with_name("text_defects.v1.json")
_FORMAT = "dike-text-defects-v1"

_ANCHOR = r"NOTA(?: ?\d+)?(?: ?:)?(?: ?\d+)?"
_ANCHOR_RESIDUE = re.compile(rf"(?m)[^\n]{_ANCHOR}\n|^{_ANCHOR}\n\nNOTA")

_REASONS = {
    "note_anchor": "ancla de nota de BCN dentro del texto (defecto de extracción; la re-extracción de P11 no pudo reponer este artículo con garantías)",
    # P12 (decisión 1): atestado CITABLE sin `bcnIdParte`; ningún gate pudo
    # compararlo con la fuente.
    "unverified_source": "sin identificador de parte de la BCN: el texto no se pudo verificar contra la fuente",
}


class TextDefectCatalogError(ValueError):
    """El catálogo distribuido con el CLI no se puede leer: instalación rota."""


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> dict[str, dict]:
    """``{textSha256: {eli, reason, ...}}``; ilegible o con otro formato → error."""
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TextDefectCatalogError(f"catálogo de defectos ilegible: {path}") from exc
    if not isinstance(payload, dict) or payload.get("format") != _FORMAT or not isinstance(payload.get("defects"), dict):
        raise TextDefectCatalogError(f"catálogo de defectos con formato inválido: {path}")
    return {str(sha): dict(entry) for sha, entry in payload["defects"].items() if isinstance(entry, dict)}


def has_anchor_residue(text: str) -> bool:
    return bool(_ANCHOR_RESIDUE.search(text))


def text_defect(text: str, text_sha256: str, catalog: dict[str, dict]) -> str | None:
    """Motivo legible si el texto tiene un defecto conocido; ``None`` si no."""
    entry = catalog.get(text_sha256)
    if entry is not None:
        return str(entry.get("detail") or _REASONS.get(str(entry.get("reason")), str(entry.get("reason", "defecto conocido"))))
    if has_anchor_residue(text):
        return _REASONS["note_anchor"]
    return None
