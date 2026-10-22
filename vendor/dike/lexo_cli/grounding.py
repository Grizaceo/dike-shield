"""Grounding jurídico — acceso determinista a la vault canónica.

Conecta Diké con la vault real (`Vault/Lexo/Vigente`) por path, sin depender
de que IndexO esté corriendo. Entrega los artículos REALES del código
aplicable para que juez, contradictor y LLM citen números exactos — nunca
inventados.

Receta validada en lexo-bench (2026-08-12): la precisión de la keyword es
todo. Keyword vaga cae en el artículo equivocado (ej. "evicción" → 1345/1346);
keyword precisa aterriza en el correcto ("evicción de la cosa comprada" → 1838).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

# Vault canónica. La ruta NO se codifica: un path absoluto al home del autor
# hacía que en cualquier otra máquina `gather_grounding` devolviera "" sin
# avisar, y el comando siguiera adelante sin fuentes como si todo estuviera
# bien. Orden: parámetro explícito > DIKE_VAULT_ROOT > config > default.
DEFAULT_VAULT_ROOT = Path.home() / ".hermes/workspaces/lexo/Vault/Lexo/Vigente"


def resolve_vault_root(cfg: dict | None = None, vault_root: str | Path | None = None) -> Path:
    if vault_root:
        return Path(vault_root).expanduser()
    env = os.environ.get("DIKE_VAULT_ROOT")
    if env:
        return Path(env).expanduser()
    configured = ((cfg or {}).get("vault") or {}).get("path")
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_VAULT_ROOT


# Compatibilidad con llamadores antiguos que importaban la constante.
VAULT_ROOT = resolve_vault_root()

# Mapa de códigos -> subdirectorio de artículos.
#
# Las rutas no pueden llevar el nombre del directorio tal como lo escribió quien
# redactó el mapa: en la Vault la 19.628 y la 20.066 están en MAYÚSCULAS
# (`LEY_19628`, `LEY_20066`) y el nombre canónico del Código Civil es
# `Codigo_Civil`. Como el sistema de archivos distingue mayúsculas, una
# discrepancia de una letra hacía que `gather_grounding` devolviera "" sin
# avisar y el análisis siguiera adelante sin fuentes (hallazgo de P13, 2026-09-27:
# `grounding.py:52` buscaba `Ley_19628` donde la Vault tiene `LEY_19628`).
#
# Por eso el mapa guarda el NOMBRE REAL (el que devuelve `listdir`) y
# `_resolver_dir_articles` lo confirma contra el disco. Si un día cambia el
# nombre en la Vault, el código sigue la ruta en vez de devolver vacío.
CODIGO_DIRS = {
    "CODIGO_CIVIL": "Codigo_Civil",
    "CODIGO_TRABAJO": "Codigo_Trabajo",
    "CODIGO_COMERCIO": "Codigo_Comercio",
    "CODIGO_PENAL": "Codigo_Penal",
    "CODIGO_TRIBUTARIO": "Codigo_Tributario",
    "L21719": "Ley_21719",
    "LEY_19628": "LEY_19628",
    "LEY_20066": "LEY_20066",
}

_LEY_GENERAL = "Ley_General"


def _resolver_dir_articles(codigo: str, vault_root: str | Path) -> Path | None:
    """Ruta real de los artículos de `codigo`, o None si no está en la Vault.

    Se resuelve por el contenido del disco, no por la constante: el disco es la
    única fuente que no puede desincronizarse del mapa.
    """
    nombre = CODIGO_DIRS.get(codigo)
    if not nombre:
        return None
    raiz = Path(vault_root).expanduser() / _LEY_GENERAL
    if not raiz.is_dir():
        return None
    # 1) ruta tal cual (el caso normal, y el rápido)
    directo = raiz / nombre / "articulos"
    if directo.is_dir():
        return directo
    # 2) mismo nombre ignorando mayúsculas/minúsculas
    for hijo in sorted(raiz.iterdir()):
        if hijo.is_dir() and hijo.name.casefold() == nombre.casefold():
            return hijo / "articulos"
    return None

# Tema -> keyword precisa de búsqueda en el texto del artículo.
# Incluir TODOS los temas del código (no filtrar por las instrucciones):
# un task de review no lista los temas, y filtrar deja al agente sin fuente
# real y lo induce a alucinar números (verificado 2026-08-12).
GROUNDING_MAP = {
    "CODIGO_CIVIL": [
        ("intereses moratorios", "intereses legales"),
        ("evicción", "evicción de la cosa comprada"),
        ("vicios ocultos", "vicios ocultos"),
        ("arras / cláusula penal", "cláusula penal"),
        ("tradición / inscripción", "tradición del dominio de los bienes raíces"),
        ("reajuste / inflación", "interés convencional"),
        ("contrato como ley", "ley para los contratantes"),
    ],
    "CODIGO_TRABAJO": [
        ("necesidades de la empresa", "necesidades de la empresa"),
        ("aviso previo", "aviso previo"),
        ("indemnización por años de servicio", "indemnización por años de servicio"),
        ("finiquito", "finiquito"),
        ("recurrir al juzgado", "recurrir al juzgado"),
        ("causales de despido", "causales"),
    ],
    "L21719": [
        ("consentimiento datos sensibles", "datos sensibles"),
        ("protección desde el diseño", "protección desde el diseño"),
        ("evaluación de impacto", "evaluación de impacto"),
        ("reportar vulneraciones", "reportar a la Agencia"),
        ("derechos del titular", "derechos de los titulares"),
    ],
    "CODIGO_PENAL": [
        ("hurto / robo", "comete robo"),
        ("pena según valor", "valor de la cosa hurtada"),
        ("ánimo de lucro", "ánimo de lucrarse"),
    ],
    "CODIGO_COMERCIO": [
        ("actos de comercio", "actos de comercio"),
        ("supletoriedad", "aplicarán las disposiciones del Código Civil"),
        ("ánimo de reventa", "ánimo de venderlas"),
        ("letras de cambio / cheques", "letras de cambio"),
    ],
}

# Áreas del CLI -> código de la vault
_AREA_TO_CODIGO = {
    "civil": "CODIGO_CIVIL",
    "laboral": "CODIGO_TRABAJO",
    "comercial": "CODIGO_COMERCIO",
    "penal": "CODIGO_PENAL",
    "datos": "L21719",
    "privacidad": "L21719",
}

# Detección por keywords en el texto del documento (fallback cuando el área
# no está en el mapa o es genérica)
_DOC_KEYWORDS = [
    (re.compile(r"código del trabajo|codigo del trabajo", re.I), "CODIGO_TRABAJO"),
    (re.compile(r"ley\s*21\.?\s*719", re.I), "L21719"),
    (re.compile(r"código penal|codigo penal|hurto|robo", re.I), "CODIGO_PENAL"),
    (re.compile(r"código de comercio|codigo de comercio", re.I), "CODIGO_COMERCIO"),
    (re.compile(r"código civil|codigo civil", re.I), "CODIGO_CIVIL"),
]


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Devuelve (frontmatter, cuerpo). El frontmatter se descartaba entero, y
    con él la vigencia: por eso se inyectaban artículos derogados rotulados
    como "artículos reales del código chileno"."""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[3:end], text[end + 4:].lstrip("\n")
    return "", text


def _strip_frontmatter(text: str) -> str:
    return _split_frontmatter(text)[1]


_FM_KEY = re.compile(r'^([a-z_]+):\s*"?([^"\n]*)"?\s*$', re.MULTILINE)

# El texto que corta antes de cerrar la frase no acredita completitud. Mismo
# criterio que `StarterCorpusResolver.is_truncated`.
_TERMINAL_PUNCTUATION = (".", "!", "?", ":", ";", '"', "”", ")")


def _is_truncated(body: str) -> bool:
    return not body.strip().endswith(_TERMINAL_PUNCTUATION)


def _fecha(valor: str) -> date | None:
    try:
        return date.fromisoformat(valor)
    except ValueError:
        return None


@dataclass
class _Article:
    numero: str
    texto: str
    vigencia_estado: str
    truncado: bool
    vigencia_desde: str = ""
    vigencia_hasta: str = ""

    def estado_al(self, as_of: date | None = None) -> str:
        """Vigencia a la fecha de la consulta, no a la de la extracción.

        P12 (decisión 2): `vigencia_estado` se sella al extraer. Medido el
        2026-09-26: 186 artículos del DL 3.500 seguían «VIGENTE» con
        `vigencia_hasta: 2026-08-31`. La ventana `[desde, hasta)` manda; la
        derogación sellada nunca se «desderoga» y sin estado no se inventa uno.
        """
        sellado = self.vigencia_estado
        if sellado in ("", "DEROGADA"):
            return sellado
        hoy = as_of or date.today()
        desde, hasta = _fecha(self.vigencia_desde), _fecha(self.vigencia_hasta)
        if hasta is not None and hoy >= hasta:
            return "VERSION_VENCIDA"
        if desde is not None and hoy < desde:
            return "NO_VIGENTE_AUN"
        if sellado == "NO_VIGENTE_AUN" and desde is not None:
            return "VIGENTE"
        return sellado

    def citable_al(self, as_of: date | None = None) -> bool:
        """Solo lo VIGENTE y completo puede presentarse como derecho aplicable.

        Un artículo sin `vigencia_estado` no se descarta: la vault tiene 546
        artículos sin re-extracción verificada, y excluirlos dejaría al LLM sin
        fuentes en áreas enteras. Se marca como no verificado y se rotula.
        """
        return self.estado_al(as_of) in ("", "VIGENTE") and not self.truncado

    @property
    def citable(self) -> bool:
        return self.citable_al()

    @property
    def verificado(self) -> bool:
        return self.estado_al() == "VIGENTE"


@lru_cache(maxsize=None)
def _load_articles_detailed(codigo: str, vault_root: str) -> dict[str, _Article] | None:
    """Carga los artículos de un código con su estado de vigencia.

    Caché de proceso: la lectura de ~2.500 archivos se hace una sola vez.
    """
    dir_rel = CODIGO_DIRS.get(codigo)
    if not dir_rel:
        return None
    art_dir = _resolver_dir_articles(codigo, vault_root)
    if art_dir is None or not art_dir.is_dir():
        return None
    arts: dict[str, _Article] = {}
    for f in art_dir.glob("art_*.md"):
        try:
            raw = f.read_text(encoding="utf-8")
        except OSError:
            continue
        frontmatter, body = _split_frontmatter(raw)
        meta = dict(_FM_KEY.findall(frontmatter))
        numero = f.stem.removeprefix("art_")
        arts[numero] = _Article(
            numero=numero,
            texto=body,
            vigencia_estado=(meta.get("vigencia_estado") or "").strip().upper(),
            truncado=_is_truncated(body),
            vigencia_desde=(meta.get("vigencia_desde") or "").strip(),
            vigencia_hasta=(meta.get("vigencia_hasta") or "").strip(),
        )
    return arts


def _load_articles(codigo: str, vault_root: str | Path | None = None) -> dict[str, str] | None:
    detailed = _load_articles_detailed(
        codigo, str(vault_root or resolve_vault_root())
    )
    if detailed is None:
        return None
    return {numero: art.texto for numero, art in detailed.items()}


def get_articulo(codigo: str, numero: int | str) -> str | None:
    """Obtiene el texto de un artículo de la vault por código y número."""
    arts = _load_articles(codigo)
    if arts is None:
        return None
    num = str(numero).lower()
    if num in arts:
        return arts[num]
    if str(numero).isdigit():
        padded = f"{int(numero):04d}"
        if padded in arts:
            return arts[padded]
    return None


def search_articulos(codigo: str, query: str, limit: int = 5) -> list[dict]:
    """Busca artículos de un código por coincidencia de texto (keyword)."""
    arts = _load_articles(codigo)
    if arts is None:
        return []
    q = query.lower()
    results = []
    for numero in sorted(arts):
        if q in arts[numero].lower():
            results.append({"numero": numero, "texto": arts[numero]})
            if len(results) >= limit:
                break
    return results


def _detect_codigo(area: str = "", doc_text: str = "") -> str | None:
    """Detecta el código aplicable: primero por área del CLI, luego por el
    texto del documento. Devuelve None si no hay código identificable."""
    key = (area or "").strip().lower()
    if key in _AREA_TO_CODIGO:
        return _AREA_TO_CODIGO[key]
    for pattern, codigo in _DOC_KEYWORDS:
        if pattern.search(doc_text or ""):
            return codigo
    return None


@dataclass
class GroundingResult:
    """Fuentes de apoyo más el motivo cuando no las hay.

    Antes esto era un `str`: cuando la vault no estaba donde el código creía,
    `gather_grounding` devolvía "" y el análisis continuaba sin fuentes sin que
    nadie lo notara. Un grounding ausente tiene que ser audible.
    """

    text: str = ""
    codigo: str | None = None
    warnings: list[str] = field(default_factory=list)
    excluidos: dict[str, int] = field(default_factory=dict)
    articulos: list[dict] = field(default_factory=list)

    def __bool__(self) -> bool:
        return bool(self.text)

    def __len__(self) -> int:  # compatibilidad con `len(fuentes)`
        return len(self.text)


def gather_grounding_detailed(
    doc_text: str,
    area: str = "",
    cfg: dict | None = None,
    vault_root: str | Path | None = None,
    as_of: date | None = None,
) -> GroundingResult:
    """Construye el bloque de fuentes con SOLO derecho vigente y completo."""
    root = resolve_vault_root(cfg, vault_root)
    codigo = _detect_codigo(area, doc_text)
    if not codigo:
        return GroundingResult(warnings=[
            f"no se identificó un código aplicable (área={area or 'sin área'})"
        ])
    if not root.is_dir():
        return GroundingResult(codigo=codigo, warnings=[
            f"la vault no existe en {root}: el análisis continúa SIN fuentes. "
            "Define vault.path en la configuración o DIKE_VAULT_ROOT."
        ])
    arts = _load_articles_detailed(codigo, str(root))
    if arts is None:
        return GroundingResult(codigo=codigo, warnings=[
            f"la vault no tiene artículos para {codigo} en {root}"
        ])

    sections: list[str] = []
    seleccionados: list[dict] = []
    excluidos: dict[str, int] = {}
    for tema, keyword in GROUNDING_MAP.get(codigo, []):
        q = keyword.lower()
        encontrados = 0
        for numero in sorted(arts):
            if encontrados >= 2:
                break
            art = arts[numero]
            if q not in art.texto.lower():
                continue
            if not art.citable_al(as_of):
                # Un artículo derogado o truncado NUNCA se presenta como
                # derecho aplicable: es exactamente lo que los gates del
                # resolver existen para impedir.
                estado = art.estado_al(as_of)
                motivo = ("truncado" if art.truncado
                          else "versión vencida" if estado == "VERSION_VENCIDA"
                          else estado.lower())
                excluidos[motivo] = excluidos.get(motivo, 0) + 1
                continue
            encontrados += 1
            estado_actual = art.estado_al(as_of)
            marca = "" if estado_actual == "VIGENTE" else " [vigencia no verificada]"
            sections.append(
                f"### {tema} → Art. {art.numero} ({codigo}){marca}\n{art.texto}"
            )
            seleccionados.append({
                "numero": art.numero,
                "codigo": codigo,
                "vigencia_estado": estado_actual or "SIN_VERIFICAR",
            })

    warnings: list[str] = []
    if excluidos:
        detalle = ", ".join(f"{n} {motivo}" for motivo, n in sorted(excluidos.items()))
        warnings.append(f"excluidos del grounding: {detalle}")
    if not sections:
        warnings.append(
            f"ningún artículo vigente y completo de {codigo} coincidió con los temas"
        )
        return GroundingResult(codigo=codigo, warnings=warnings, excluidos=excluidos)

    header = (
        "FUENTES DE LA VAULT (artículos vigentes del código chileno)\n"
        "Para citar, usa SOLO los números de artículo que aparecen en estas "
        "fuentes. No inventes números de artículo."
    )
    return GroundingResult(
        text=header + "\n\n" + "\n\n".join(sections),
        codigo=codigo,
        warnings=warnings,
        excluidos=excluidos,
        articulos=seleccionados,
    )


def gather_grounding(doc_text: str, area: str = "", cfg: dict | None = None) -> str:
    """Compatibilidad: solo el texto. Prefiere `gather_grounding_detailed`,
    que además informa por qué no hay fuentes."""
    return gather_grounding_detailed(doc_text, area=area, cfg=cfg).text
