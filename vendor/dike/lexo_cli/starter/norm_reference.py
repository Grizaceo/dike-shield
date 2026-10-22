"""Body-aware normalization of norm references for the Diké NIF pipeline.

Adapter over ``StarterCorpusResolver`` (see ``starter/resolver.py``). It turns
free-text norm citations -- ``CC art. 2515``, ``artículo 2515 del Código
Civil``, ``CPC art. 434 N° 4`` -- into canonical GIDs *or* a fail-closed
resolution.

Root cause addressed (audit 2026-08-20): ``--normas "CC art. 2515"`` created a
synthetic ``sin-gid:0`` because only canonical GIDs were accepted, and citation
verification could accept ``CPC art. 434`` merely because some other body had an
art. 434. This module resolves against the actual resolver contents and refuses
to invent GIDs.

Contract (consumed in wave 2 by rhetoric_writer):
  - ``NormReferenceResolution`` (immutable dataclass)
  - ``resolve_norm_reference(raw, resolver) -> NormReferenceResolution``
  - ``extract_norm_references(text, resolver) -> list[NormReferenceResolution]``
  - status vocabulary: ``RESOLVED`` | ``AMBIGUOUS`` | ``UNRESOLVABLE``

It does NOT edit the alias catalog or the resolver; it only reads
``resolver._aliases`` (code -> alias) and calls ``resolver.resolve(gid)``.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from lexo_cli.gid import a_runtime
from lexo_cli.starter.resolver import NormativeResolutionError


# ---------------------------------------------------------------------------
# Normalization primitives (deterministic, accent/punctuation/zero-pad aware)
# ---------------------------------------------------------------------------

_ACENTS = str.maketrans("áéíóúñÁÉÍÓÚÑ", "aeiounAEIOUN")

# Common official code names / abbreviations -> resolver code or alias.
# Mirrors the leychileCodeToAlias catalog without duplicating it; these are the
# natural-language spellings that prose may use. Values are either a leychile
# *code* (resolved via resolver._aliases) or a resolver *alias* resolved
# dynamically against resolver._aliases.values(). Generic bodies (Comercio,
# Tributario, Penal, ...) are resolver-driven: if the derived alias is absent
# from the catalog the citation stays UNRESOLVABLE (body retained), never
# falling back to a body-less survey.
_BODY_NAMES: dict[str, str] = {
    # leychile codes (resolved via resolver._aliases)
    "codigo civil": "172986",
    "código civil": "172986",
    "cc": "172986",
    "codigo de procedimiento civil": "22740",
    "código de procedimiento civil": "22740",
    "cpc": "22740",
    "codigo del trabajo": "207436",
    "código del trabajo": "207436",
    "ct": "207436",
    "ley 21719": "1209272",
    "ley 21.719": "1209272",
    "ley n° 21.719": "1209272",
    "ley n° 21719": "1209272",
    # generic bodies -> resolver alias (resolved dynamically; if absent => UNRESOLVABLE)
    "codigo de comercio": "ccom",
    "código de comercio": "ccom",
    "codigo comercial": "ccom",
    "codigo tributario": "ctrib",
    "código tributario": "ctrib",
    "codigo penal": "cp",
    "código penal": "cp",
    "codigo procesal penal": "cpp",
    "código procesal penal": "cpp",
    "codigo organico de tribunales": "cot",
    "código orgánico de tribunales": "cot",
    "codigo de aguas": "dfl_1122",
    "código de aguas": "dfl_1122",
    "caguas": "dfl_1122",
    "dfl 1122": "dfl_1122",
    "dfl1122": "dfl_1122",
    "codigo sanitario": "csanit",
    "código sanitario": "csanit",
    "constitucion": "cpr",
    "constitución": "cpr",
    "constitucion politica": "cpr",
    "constitución política": "cpr",
}

# Generic Chilean body phrase (resolver-driven). Any explicit body beginning
# with Código/Ley/Decreto/DFL/DL/Constitución is retained and resolved
# dynamically; if the derived alias is not in the catalog the citation stays
# UNRESOLVABLE (body retained) -- it must never fall back to a body-less survey.
# The body tail rejects "art"/"artículo" AND Spanish connectives (la/el/los/
# las/y/e/o/que/se) so following prose or the next citation is never swallowed
# into the body phrase (P0-4 #3).
_BODY_PHRASE = (
    r"(?:c[oó]digo\s+(?:de\s+)?[a-záéíóúñ]+"
    r"(?:\s+(?!art(?:[íi]culo)?s?\b|la\b|el\b|los\b|las\b|y\b|e\b|o\b|que\b|se\b)"
    r"[a-záéíóúñ]+){0,3}(?!\s*art)"
    r"|constituci[oó]n(?:\s+pol[ií]tica)?(?!\s*art)"
    r"|ley\s+n?[º°]?\s*\d+(?:\.\d+)?"
    r"|decreto\s+(?:[a-záéíóúñ]+\s+)?n?[º°]?\s*\d+(?:\.\d+)?"
    r"|dfl\s+n?[º°]?\s*\d+(?:\.\d+)?"
    r"|dl\s+n?[º°]?\s*\d+(?:\.\d+)?"
    r"|c[oó]digo\s+civil|c[oó]digo\s+del\s+trabajo|c[oó]digo\s+de\s+procedimiento\s+civil"
    r"|\b(?:cc|ct|cpc|ccom|ctrib|cpp|cot|cpr|caguas|csanit)\b)"
)
_GENERIC_BODY_CAPTURE = re.compile(_BODY_PHRASE, re.IGNORECASE)

# Any explicit body keyword: an unrecognized explicit body must NOT be treated
# as body-less (fail-closed => UNRESOLVABLE).
_GENERIC_BODY_TOKEN = re.compile(
    r"\b(c[oó]digo|ley|decreto|dfl|dl|constituci[oó]n)\b", re.IGNORECASE
)


def _derive_alias_from_phrase(phrase: str) -> str | None:
    """Derive a resolver alias from a (possibly generic) body phrase.

    Static map first (code or alias), then dynamic forms: ley_N, decreto_N,
    dfl_N, dl_N. Returns None when nothing resolvable is recognized -- the
    caller then fails closed (UNRESOLVABLE) rather than guessing a body.
    """
    key = _sin_acentos((phrase or "").strip().lower())
    if key in _BODY_NAMES:
        return _BODY_NAMES[key]
    m = re.match(r"ley\s+n?[º°]?\s*(\d+)\.?(\d+)?", key)
    if m:
        return f"ley_{m.group(1)}{m.group(2) or ''}"
    m = re.match(r"decreto\s+(?:[a-záéíóúñ]+\s+)?n?[º°]?\s*(\d+)\.?(\d+)?", key)
    if m:
        return f"decreto_{m.group(1)}{m.group(2) or ''}"
    m = re.match(r"dfl\s+n?[º°]?\s*(\d+)\.?(\d+)?", key)
    if m:
        return f"dfl_{m.group(1)}{m.group(2) or ''}"
    m = re.match(r"dl\s+n?[º°]?\s*(\d+)\.?(\d+)?", key)
    if m:
        return f"dl_{m.group(1)}{m.group(2) or ''}"
    return None

_ORDINALS = {
    "primero": "primero", "segundo": "segundo", "tercero": "tercero",
    "cuarto": "cuarto", "quinto": "quinto", "sexto": "sexto",
    "septimo": "septimo", "séptimo": "septimo", "octavo": "octavo",
    "noveno": "noveno", "decimo": "decimo", "décimo": "decimo",
    "undecimo": "undecimo", "undécimo": "undecimo",
    "duodecimo": "duodecimo", "duodécimo": "duodecimo",
    "final": "final", "transitorio": "transitorio", "unico": "unico", "único": "unico",
}

# Sufijos de artículo admitidos por el corpus chileno, en una sola definición
# que comparten `_TOKEN` (parseo del token) y `_PROSE`/`_PROSE_ENUM` (detección
# en prosa). Antes vivían en dos lugares y divergían: `_PROSE` conocía
# quinquies/sexies/septies/octies/nonies (están en el pack) y `_TOKEN` no, de
# modo que «art. 172 octies» se detectaba y luego se parseaba como el `172`
# liso — dos normas distintas cayendo en un mismo token.
_SUFIJOS_ART = (
    "bis", "ter", "qu[aá]ter", "quater",
    "quinquies", "sexies", "septies", "octies", "nonies",
)
_SUFIJO_ART_RE = r"(?:" + "|".join(_SUFIJOS_ART) + r")"

# Formas de escribir «número» que abren el numeral de un artículo. Compartida por
# `_PROSE` y `_PROSE_ENUM` para que la detección en prosa y el parseo del token
# no puedan divergir: cuando divergieron, la preliminar veía «art. N° 5» y la
# body-aware no emitía ninguna referencia, que es el P0 (cita no detectada ->
# NO_CITATIONS con ok=true y agentes corriendo).
#
# Orden de alternativas: las largas antes que las cortas, o «numero» se leería
# como «nro» + «ero» y «nros.» como «nro» + «s».
_NUM_ART_RE = (
    r"(?:n[uú]mero?s?|n[uú]m|nros?\.?|nro|num(?:ero)?)\.?"
)
# «N°» / «Nº» llevan un punto después en vez de una letra, y no se confunden
# con «nro».
_SIMBOLO_NUM_RE = r"n[º°]"

# El grupo completo que se inserta entre el prefijo «art(ículo)» y el numeral.
_NUMERO_ENTRADA_RE = r"(?:" + _SIMBOLO_NUM_RE + r"|" + _NUM_ART_RE + r")\s*"

# Artículo TRANSITORIO en prosa: «art. t. 5» / «artículo transitorio 5». Sus
# GID son `...:art:t_0005`, y la pre-extracción emite el token `t-5`. El token
# propio va en un grupo con nombre para que `_parse_token` pueda distinguirlo
# del numeral ordinario y no zero-padear «t» como si fuera un artículo más.
_TRANSITORIO_TEXTO_RE = r"(?P<transitorio>t|transitori[oa])\.?\s*(?P<numero>\d+)"
# La misma forma, ya compilada, para el parseo del token.
_TOKEN_TRANSITORIO = re.compile(
    r"\b(?:t|transitori[oa])\.?\s*(\d+)", re.IGNORECASE,
)

# Absorption of a trailing paragraph/sub-number ("N° 4", "núm. 3", "Nº 2").
# These are NOT part of the article token: "CPC art. 434 N° 4" -> art 0434.
_SUBNUMBER = re.compile(
    r"\b(?:n[º°]|nro|num|numero|nu?mero)\.?\s*\d+", re.IGNORECASE
)
# El sub-número solo es un sub-número si va DETRÁS de un numeral de artículo.
# Sin la lookbehind, el patrón también matcheaba la entrada «art. N° 5» y
# `_strip_subnumber` devolvía «art.»: la cita quedaba sin token y el
# verificador no veía nada. La lookbehind exige un dígito o un cierre de
# paréntesis justo antes del «N°».
_SUBNUMBER_TRAILING = re.compile(
    r"(?<=[\d)])\s*\b(?:n[º°]|nros?\.?|nro|num(?:ero)?\.?|nu?mero)\.?\s*\d+",
    re.IGNORECASE,
)

# Conjunctions that must not be read as a lettered article.
_CONJUNCIONES = {"y", "e", "o", "u"}

# One article token: digits (zero-padded to 4), ordinal word, plus an optional
# bis/ter/quáter suffix and -- ONLY when that suffix is present -- an optional
# lettered article (152 quáter G). Under the Chilean contract a standalone
# letter is never valid on its own (plain "art. 434 N" must NOT become a
# lettered norm), so the letter group is nested inside the suffix group.
#
# The degree symbol sits BETWEEN the numeral and the suffix: "art. 39° bis" is
# article 39 bis, not plain 39. Without that gap the suffix was dropped and the
# two norms collapsed into one token. The symbol is not discarded: in the
# corpus "ARTICULO 81°-" is the dominant way to cite an article.
_TOKEN = re.compile(
    r"(\d+|" + "|".join(_ORDINALS) + r")"
    r"[º°]?"
    r"(?:\s*(" + _SUFIJO_ART_RE + r")(?:\s*([a-zñ]))?)?",
    re.IGNORECASE,
)


def _letter_is_article(text: str, end: int) -> bool:
    """True if the single letter at `end` individualizes the article.

    Rejects the case where the letter is the start of the next word
    (e.g. "del", "de"), a conjunction, runs into a digit (enumeration), or is
    the paragraph sub-number separator ("N° 4" / "Nº 4" -- the "N" must never
    be read as a lettered article).
    """
    rest = text[end:end + 1]
    after = text[end + 1:end + 2]
    if rest.isalpha() and rest.lower() in _CONJUNCIONES and not after.strip():
        return False
    if re.match(r"[a-záéíóúñ]", after, re.IGNORECASE):
        return False   # start of another word ("del")
    if re.match(r"\s*\d", text[end:]):
        return False    # enumeration ("y 16")
    if re.match(r"\s*[º°]", text[end:]):
        return False    # paragraph sub-number separator ("N° 4")
    return True

# Public body must follow the token when the order is "art X <Body>"; when the
# order is "<Body> art X" the body precedes and is captured by _BODY_BEFORE.
_BODY_AFTER = re.compile(
    r"\b(?:del?|de la|la)?\s*(?:codigo|código|ley|cod|ct|cc|cpc|"
    r"c[oó]digo\s+(?:civil|del\s+trabajo|de\s+procedimiento\s+civil))\b"
    r"|c[oó]digo\s+civil|c[oó]digo\s+del\s+trabajo"
    r"|c[oó]digo\s+de\s+procedimiento\s+civil"
    r"|ley\s+n?[º°]?\s*21\.?719",
    re.IGNORECASE,
)


def _sin_acentos(texto: str) -> str:
    return texto.translate(_ACENTS)


def _normalize_token(raw: str, suffix: str = "", letter: str = "") -> str:
    """Token comparable to the resolver's GID article token.

    Mirrors StarterCorpusResolver._article_token: digits are zero-padded to 4
    places (2515 -> "2515", 432 -> "0432"), ordinals stay as words, and
    suffix/letter are appended with underscores so '152 quáter G' ->
    '0152_quater_g'.
    """
    base = _sin_acentos(raw.strip().lower())
    if base.isdigit():
        base = f"{int(base):04d}"
    parts = [base]
    if suffix:
        parts.append(_sin_acentos(suffix.strip().lower()))
    if letter:
        parts.append(_sin_acentos(letter.strip().lower()).replace("ñ", "n"))
    return "_".join(parts)


def _strip_subnumber(text: str) -> str:
    """Quita el sub-número de párrafo, que solo vale DESPUÉS de un numeral.

    «N°» significa dos cosas según dónde esté: en la entrada
    («art. N° 5») abre el número de artículo; después de un numeral
    («art. 434 N° 4») es el párrafo 4. Un `sub()` global no distingue los dos
    casos y se comía el numeral de entrada — «art. N° 5» quedaba como «art.» y
    la referencia salía con token nulo, es decir, invisible para el verificador.

    La condición es la que ya usa el resto del módulo: el sub-número sólo
    aparece si hay un dígito delante. Se aplica repetidamente para que
    «art. 434 N° 4 y N° 5» pierda los dos.
    """
    anterior = None
    texto = text
    while texto != anterior:
        anterior = texto
        texto = _SUBNUMBER_TRAILING.sub("", texto).strip()
    return texto


# ---------------------------------------------------------------------------
# Resolution result
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NormReferenceResolution:
    raw: str
    status: str           # RESOLVED | AMBIGUOUS | UNRESOLVABLE
    gid: str | None
    candidates: list[str]
    reason: str
    alias: str | None
    article_token: str | None
    # 3.7 — distinguir laguna de alucinación (Gaps or Hallucinations? 2024):
    #   NOT_FOUND_IN_CORPUS            — el cuerpo existe, el artículo no
    #   NONEXISTENT_CONFIRMED          — el cuerpo legal no existe en el catálogo
    #   RESOLVED_WITH_METADATA_MISMATCH— resuelto pero con metadata inconsistente
    #   None                           — RESOLVED / AMBIGUOUS / sin clasificar
    failure_kind: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Resolution core
# ---------------------------------------------------------------------------

def _alias_for_code(resolver, code: str) -> str | None:
    """Resolve a body code/alias to a resolver alias.

    ``code`` may be a leychile code (lookup in resolver._aliases) or already a
    resolver alias (present in resolver._aliases.values()). Returns None when
    the corpus does not contain it -- the caller fails closed (UNRESOLVABLE),
    it must NOT fall back to a body-less survey.
    """
    if code in resolver._aliases:
        return resolver._aliases[code]
    if code and code in set(resolver._aliases.values()):
        return code
    return None


def _body_to_code(body: str | None) -> str | None:
    """Map a natural-language body fragment to a leychile *code* or alias.

    Static map first, then dynamic derivation (ley_N / decreto_N / dfl_N / dl_N
    and generic Código/Ley phrases). Returns None when unrecognized.
    """
    if not body:
        return None
    key = _sin_acentos(body.strip().lower())
    if key in _BODY_NAMES:
        return _BODY_NAMES[key]
    return _derive_alias_from_phrase(body)


def _gid_article_part(token: str) -> str:
    """Parte `:art:` de un GID a partir de un token de comparación.

    El token que emite la pre-extracción (`t-5`, `1545`, `152-quater-n`) no es
    la parte del GID (`t_0005`, `01545`, `0152_quater_n`). Para los artículos
    numerales la conversión es el zero-padding a 4 que ya hace
    `_normalize_token`; para los TRANSITORIOS hace falta además convertir el
    guion del token en el subguion que usa el corpus: sin esto se pedía
    `cl.norma.X:art:t-5` y ningún artículo transitorio resolvía nunca.
    """
    base = (token or "").strip().lower()
    if not base:
        return base
    if re.match(r"^t-\d+$", base):
        numero = base.split("-", 1)[1]
        return "t_" + str(int(numero)).zfill(4)
    return base


def _try_resolve(resolver, alias: str, token: str) -> str | None:
    gid = f"cl.norma.{alias}:art:{_gid_article_part(token)}"
    try:
        resolver.resolve(gid)
        return gid
    except NormativeResolutionError:
        return None


def _candidate_gids(resolver, alias: str, token: str) -> list[str]:
    """Every GID that resolves for (alias, token) under the actual corpus."""
    gid = _try_resolve(resolver, alias, token)
    return [gid] if gid else []


def resolve_norm_reference(raw: str, resolver) -> NormReferenceResolution:
    """Resolve one norm reference string against the live resolver.

    Never invents a GID. Returns AMBIGUOUS (with candidates) when the same
    article number exists in several bodies and no body was supplied, and
    UNRESOLVABLE when the alias/article pair does not exist in the corpus.
    """
    raw = (raw or "").strip()
    if not raw:
        return NormReferenceResolution(
            raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
            reason="cadena vacía", alias=None, article_token=None,
        )

    # 1) Canonical GID. Normalize the article token (zero-pad digits, etc.) so
    #    e.g. cl.norma.cpc:art:434 resolves to the corpus token 0434 instead of
    #    failing open as UNRESOLVABLE.
    par = a_runtime(raw)  # runtime o v2 (ARCH-003 F1)
    if par:
        alias = par[0]
        token = _normalize_token(par[1])
        gid = _try_resolve(resolver, alias, token)
        if gid:
            return NormReferenceResolution(
                raw=raw, status="RESOLVED", gid=gid, candidates=[gid],
                reason="", alias=alias,
                article_token=token,
            )
        return NormReferenceResolution(
            raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
            reason="GID no resuelve en el corpus", alias=None, article_token=None,
            failure_kind="NOT_FOUND_IN_CORPUS",
        )

    # 2) Free-text: detect body first, then extract token from the remainder.
    text = _strip_subnumber(raw)
    body = _parse_body(text, raw)
    code = _body_to_code(body)
    if _known_body_token(raw) and code is None:
        # An explicit body keyword was named (e.g. "Código Imaginario") but it
        # did not map to a catalog code: do NOT fall back to a body-less survey
        # (that would silently treat it as body-less and possibly return
        # AMBIGUOUS). Fail closed as UNRESOLVABLE.
        token, _suffix, _letter = _parse_token(_strip_body(text, raw))
        norm_token = _normalize_token(token, _suffix or "", _letter or "") if token else None
        return NormReferenceResolution(
            raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
            reason="cuerpo legal desconocido", alias=None,
            article_token=norm_token,
            failure_kind="NONEXISTENT_CONFIRMED",
        )
    remainder = _strip_body(text, raw) if body else text
    token, suffix, letter = _parse_token(remainder)
    if not token:
        return NormReferenceResolution(
            raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
            reason="no se reconoce número de artículo", alias=None,
            article_token=None,
        )
    norm_token = _normalize_token(token, suffix or "", letter or "")

    if code:
        alias = _alias_for_code(resolver, code)
        if alias is None:
            return NormReferenceResolution(
                raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
                reason=f"cuerpo legal desconocido: {code}", alias=None,
                article_token=norm_token,
                failure_kind="NONEXISTENT_CONFIRMED",
            )
        gids = _candidate_gids(resolver, alias, norm_token)
        if gids:
            return NormReferenceResolution(
                raw=raw, status="RESOLVED", gid=gids[0], candidates=gids,
                reason="", alias=alias, article_token=norm_token,
            )
        return NormReferenceResolution(
            raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
            reason=f"artículo {norm_token} no existe en {alias}",
            alias=alias, article_token=norm_token,
            failure_kind="NOT_FOUND_IN_CORPUS",
        )

    # 3) Body-less: enumerate every alias present in the corpus catalog.
    candidates: list[str] = []
    for code, alias in resolver._aliases.items():
        gids = _candidate_gids(resolver, alias, norm_token)
        candidates.extend(gids)
    if len(candidates) == 1:
        return NormReferenceResolution(
            raw=raw, status="RESOLVED", gid=candidates[0],
            candidates=candidates, reason="",
            alias=candidates[0].split(":")[0].split(".")[-1]
            if ":art:" in candidates[0] else None,
            article_token=norm_token,
        )
    if len(candidates) > 1:
        return NormReferenceResolution(
            raw=raw, status="AMBIGUOUS", gid=None, candidates=sorted(candidates),
            reason="mismo número de artículo en varios cuerpos sin cuerpo indicado",
            alias=None, article_token=norm_token,
        )
    return NormReferenceResolution(
        raw=raw, status="UNRESOLVABLE", gid=None, candidates=[],
        reason=f"artículo {norm_token} no existe en ningún cuerpo del corpus",
        alias=None, article_token=norm_token,
        failure_kind="NOT_FOUND_IN_CORPUS",
    )


def _parse_token(text: str) -> tuple[str | None, str | None, str | None]:
    """Extract (number/ordinal, suffix, letter) from cleaned text.

    A standalone letter after the number is NOT a lettered article (the letter
    group lives inside the suffix group in ``_TOKEN``). Uses the article-letter
    guard so a body fragment like "del Código" is not swallowed as the
    article's trailing letter, and rejects the separator of a paragraph
    sub-number ("N° 4") so it is never consumed as a letter.
    """
    cleaned = _sin_acentos(text)
    m = _TOKEN.search(cleaned)
    if not m:
        return None, None, None
    # Artículo transitorio: «t. 5» / «transitorio 5». El numeral NO se
    # zero-padea a 4 como un artículo corriente; su token es `t-5`, la forma en
    # que el GID `...:art:t_0005` queda indexado y con la que lo compara la
    # pre-extracción.
    transitorio = _TOKEN_TRANSITORIO.search(cleaned)
    if transitorio:
        return "t-" + str(int(transitorio.group(1))), None, None
    raw_letter = m.group(3) or ""
    letter = raw_letter.strip() or None
    # The letter group may capture a leading space; use the actual letter
    # position for the individualization guard.
    letter_pos = m.end(3) - 1 if letter else None
    # The letter group only individualizes the article when a bis/ter/quáter
    # suffix preceded it (Chilean contract): a bare "art. 434 N" is NOT a
    # lettered norm.
    if not m.group(2):
        letter = None
    if letter and letter_pos is not None and not _letter_is_article(cleaned, letter_pos):
        letter = None
    return m.group(1), m.group(2), letter


def _known_body_token(raw: str) -> bool:
    """True if the string names a recognizable body keyword, even if no code
    maps to it (e.g. 'Código Imaginario'). Used to distinguish an *explicit but
    unknown* body (UNRESOLVABLE) from *no body named* (body-less survey).

    Includes any explicit Chilean body opener (Código/Ley/Decreto/DFL/DL/
    Constitución), so an unmapped explicit body fails closed instead of being
    treated as body-less.
    """
    hay = _sin_acentos(raw.lower())
    if _GENERIC_BODY_TOKEN.search(hay):
        return True
    for name in _BODY_NAMES:
        if name in hay:
            return True
    return False


def _normalize_generic_body(phrase: str) -> str:
    """Trim a captured generic body phrase to its longest known-body prefix.

    The generic capture regex may swallow trailing prose (e.g. "Código del
    Trabajo es aplicable"). We trim trailing words until the phrase maps to a
    recognized body (via ``_body_to_code``); if even the full phrase maps, it is
    returned unchanged. This keeps the body precise without enumerating every
    Spanish connective.
    """
    words = (phrase or "").split()
    for i in range(len(words), 0, -1):
        cand = " ".join(words[:i])
        if _body_to_code(cand) is not None:
            return cand
    return phrase


def _parse_body(text: str, raw: str) -> str | None:
    """Detect a body name anywhere in the string, choosing the LONGEST
    boundary-aware match.

    This prevents short aliases (``cc``/``ct``/``cpc``) from winning over an
    explicit long body, and stops them matching *inside* other words
    (``cc`` inside ``acción``, ``ct`` inside ``acto``). A leading/trailing
    letter boundary is enforced so only standalone aliases are recognized.
    Generic Chilean body phrases (Código de Comercio, Ley 20.720, ...) are
    also captured and returned verbatim (trimmed to a known-body prefix) so the
    alias can be derived later.
    """
    hay = _sin_acentos(raw.lower())
    best: tuple[int, str] | None = None  # (match_length, body_key)
    for name in _BODY_NAMES:
        pattern = re.compile(
            rf"(?<![a-záéíóúñ])(?:{re.escape(_sin_acentos(name))})(?![a-záéíóúñ])"
        )
        m = pattern.search(hay)
        if m:
            length = m.end() - m.start()
            if best is None or length > best[0]:
                best = (length, name)
    for gm in _GENERIC_BODY_CAPTURE.finditer(raw):
        phrase = _normalize_generic_body(gm.group(0))
        length = len(phrase)
        if best is None or length > best[0]:
            best = (length, phrase)
    return best[1] if best else None


def _strip_body(text: str, raw: str) -> str:
    """Remove the detected body phrase so the token parser is unambiguous.

    Body matching is accent- and case-insensitive, so "Código del Trabajo"
    is stripped even though the catalog key is stored without accents.
    """
    body = _parse_body(text, raw)
    if not body:
        return text
    # Operate on the accented original; match accent-insensitively.
    pattern = re.compile(re.escape(_sin_acentos(body.lower())), re.IGNORECASE)
    # Build a sub that removes the corresponding span in the original text.
    cleaned = text
    for m in list(pattern.finditer(_sin_acentos(text.lower())))[::-1]:
        span = m.span()
        cleaned = cleaned[:span[0]] + " " + cleaned[span[1]:]
    return cleaned


# ---------------------------------------------------------------------------
# Prose extraction
# ---------------------------------------------------------------------------

# Matches "art[ículo(s)] <token>..." and the flipped "<Body> art[ículo] <token>".
# A leading body (CC / CPC / CT / Código de Comercio / Ley 20.720 / ...) before
# "art" is captured so a citation like "CC art. 2515" keeps its body in the
# resolved snippet and resolves exactly to that body (not ambiguously across all
# bodies). A trailing paragraph sub-number ("N° 4", "núm. 3") is consumed so the
# "N" is never read as a lettered article.
#
# ANCHO DEL NUMERAL (`\d+`, no `\d{1,5}`): medido sobre el snapshot de producción,
# los 8.538 GID numéricos son de EXACTAMENTE 4 dígitos y el artículo más alto es
# el 2524 — no existe un artículo de 5+ dígitos. Con `\d{1,5}` la cadena
# `123456` se consumía como `12345` y el resolver buscaba una norma que el
# escrito nunca invocó (y `1234` sí existe, en dos cuerpos). `\d+` conserva la
# cadena íntegra: el GID buscado no existe y la referencia queda
# UNRESOLVABLE, que es el veredicto fail-closed correcto.
#
# SUFIJOS: el corpus contiene los ordinales latinos mayores además de
# bis/ter/quáter (quinquies, sexies, septies, octies, nonies: 13+7+3+3+2
# artículos). Omitirlos hacía que «art. 172 octies» se resolviera como el
# `0172` liso.
#
# «número(s)» ANTES del numeral: es la entrada del número de artículo
# («artículo número 9999»), no un sub-número de párrafo. Por eso va en el
# prefijo y no en el grupo de sub-número, que sigue reservado para «N° 4» /
# «núm. 3» — que sí son párrafos y NO individualizan un artículo.
_SUFIJO_ART = _SUFIJO_ART_RE
# El símbolo de grado va inmediatamente DESPUÉS del numeral, para que el
# sufijo pueda seguir: «art. 39° bis» = artículo 39 bis, no el 39 liso. Va
# dentro de _NUM_ART y no como parche aparte, para que _PROSE, _ENUM_ITEM y
# _CONTINUATION compartan la regla y no puedan divergir entre sí.
_SIMBOLO_GRADO_ART = r"[º°]?"
_NUM_ART = r"(?:\d+|" + "|".join(_ORDINALS) + r")" + _SIMBOLO_GRADO_ART
_SUBNUM_ART = r"(?:\s*(?:n[º°]|nro|num|numero|nu?mero)\.?\s*\d+)?"
_LETRA_ART = r"(?:\s*[a-zñ])?"

_PROSE = re.compile(
    r"(?:"
    + _BODY_PHRASE + r"\s+"
    r")?"
    r"art(?:[íi]culos?|s?)?\.?\s*"
    + r"(?:" + _NUMERO_ENTRADA_RE + r")?"  # "artículo número 9999", "art. N° 5"
    + r"(?:" + _TRANSITORIO_TEXTO_RE + r"|" + _NUM_ART + r")"
    r"(?:\s*" + _SUFIJO_ART + _LETRA_ART + r")?"
    + _SUBNUM_ART                          # paragraph sub-number
    ,
    re.IGNORECASE,
)

# Recognized body phrase that may precede "art" in prose (for backward span).
_BODY_BEFORE = re.compile(r"(?:" + _BODY_PHRASE + r")\s*$", re.IGNORECASE)

# Enumeration of article numbers: "artículos 434, 9999 y 105 del CPC" or
# "CPC arts. 434 y 9999". The number list requires at least two items so a
# single citation is handled by _PROSE instead.
_ENUM_BODY_LEAD = r"(?:" + _BODY_PHRASE + r"\s+)"
_ENUM_BODY_TRAIL = r"(?:\s+(?:del?\s+)?(?:" + _BODY_PHRASE + r"))?"
_ENUM_ITEM = (
    _NUM_ART
    + r"(?:\s*" + _SUFIJO_ART + _LETRA_ART + r")?"
    + _SUBNUM_ART
)
_PROSE_ENUM = re.compile(
    r"(?:" + _ENUM_BODY_LEAD + r")?"
    r"art(?:[íi]culos?|s?)\.?\s*"
    + r"(?:" + _NUMERO_ENTRADA_RE + r")?"  # "artículos números 1545 y 1546", "arts. N° 3 y 4"
    r"(" + _ENUM_ITEM + r"(?:\s*(?:,|;|\by\b|\be\b)\s*" + _ENUM_ITEM + r")+)"
    + _ENUM_BODY_TRAIL,
    re.IGNORECASE,
)

# Implied continuation (P1-4): "art. 434 del CPC y 9999 del CC" -- a number
# followed by an explicit body after a conjunction, even when "art" is omitted.
# Captures the number and the body so a second reference is emitted. Stops at
# punctuation/connectives; never absorbs the next citation's own "art".
_CONTINUATION = re.compile(
    r"(?:,|;|\by\b|\be\b)\s+(?:al?\s+)?"
    # `\d+` y no `\d{1,5}`: con el límite, «y 123456 del CC» hacía fallar el
    # match ENTERO (el \d{1,5} comía 12345, luego exigía \s+ y encontraba «6»)
    # y la referencia desaparecía sin dejar rastro. Desaparecer es peor que
    # no verificarse: una cita que el escrito invoca debe aparecer en el resultado,
    # exista o no en el corpus. El mismo razonamiento que en `_PROSE`.
    r"(\d+" + r"(?:\s*" + _SUFIJO_ART_RE + r"(?:\s*[a-zñ])?)?)"
    r"\s+(?:del?\s+|de la\s+)?"
    r"(?P<body>" + _BODY_PHRASE + r")",
    re.IGNORECASE,
)

# Split a token-list fragment into individual article references.
_ENUM_SEP = re.compile(r"\s*(?:,|;|\by\b|\be\b)\s*", re.IGNORECASE)


def _split_enum_numbers(numlist: str) -> list[str]:
    return [p for p in _ENUM_SEP.split(numlist.strip()) if p.strip()]


def _spans_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] < b[1] and b[0] < a[1]


def _extend_tail(text: str, end: int, has_body_before: bool) -> int:
    """Compute the end of a citation span for tail-body extension.

    If the citation already carries a body-before, it must NOT absorb the next
    citation's body (P0-3). Otherwise the tail is cut at the next "art"/"artículo"
    prefix so a trailing body is only associated with THIS citation -- but if that
    trailing body is itself immediately followed by "art" (e.g. "... y el CPC
    art. 2515"), it belongs to the next citation and must not be attached.
    Generic body phrases are recognized so "del Código de Comercio" is attached
    to its own citation and never swallowed into the next.
    """
    if has_body_before:
        return end
    nxt = text.lower().find("art", end)
    limit = nxt if nxt != -1 else min(end + 60, len(text))
    tail = text[end:limit]
    body_m = re.search(r"\b(?:del?|de la)?\s*(?:" + _BODY_PHRASE + r")", tail, re.IGNORECASE)
    if body_m:
        # If the matched trailing body is itself immediately followed by another
        # "art" (e.g. "... y el CPC art. 2515"), it introduces a new citation and
        # must not be attached to this span. Only attach when real words sit
        # between the body and the next "art".
        body_abs_end = end + body_m.end()
        if nxt != -1 and not text[body_abs_end:nxt].strip():
            return end
        return end + body_m.end()
    return end


def extract_norm_references(text: str, resolver) -> list[NormReferenceResolution]:
    """Find every norm citation embedded in prose and resolve it.

    Returns one resolution per detected citation, in order of appearance. Each
    enumeration ("artículos 434, 9999 y 105 del CPC") emits one resolution per
    article, inheriting the explicit body for every item (P0-1). An implied
    continuation ("art. 434 del CPC y 9999 del CC") emits a second reference for
    the number that follows a conjunction and an explicit body even without a
    repeated "art" (P1-4). The detected span is extended backward to include a
    recognized body that precedes ``art`` (e.g. "CC art. 432"), and forward over
    a trailing body phrase ("... del Código Civil") -- but never across the next
    citation (P0-3). Generic Chilean bodies (Comercio, Ley 20.720, ...) are
    recognized wherever they appear (P0-4).
    """
    results: list[NormReferenceResolution] = []
    seen_spans: set[tuple[int, int]] = set()

    # --- Enumeration pass (P0-1) ---
    for m in _PROSE_ENUM.finditer(text or ""):
        start, end = m.span()
        if (start, end) in seen_spans:
            continue
        snippet = text[start:end].strip()
        body = _parse_body(snippet, snippet)
        nums = _split_enum_numbers(m.group(1))
        seen_spans.add((start, end))
        for num in nums:
            sub = f"{body} art. {num}" if body else f"art. {num}"
            results.append(resolve_norm_reference(sub, resolver))
        # Mark any single-number spans fully inside this enumeration as seen.
        for sm in _PROSE.finditer(text or ""):
            ss, se = sm.span()
            if start <= ss and se <= end:
                seen_spans.add((ss, se))

    # --- Single-citation pass ---
    for m in _PROSE.finditer(text or ""):
        start, end = m.span()
        if (start, end) in seen_spans:
            continue
        # Extend backward over a recognized body that immediately precedes.
        prefix = text[:start].rstrip()
        bm = _BODY_BEFORE.search(prefix)
        has_body_before = bm is not None
        if has_body_before:
            start = bm.start()
        seen_spans.add((start, end))
        snippet = text[start:end].strip()
        snippet = _strip_subnumber(snippet)
        end = _extend_tail(text, end, has_body_before)
        snippet = text[start:end].strip()
        results.append(resolve_norm_reference(snippet, resolver))

    # --- Implied continuation pass (P1-4) ---
    # Run after ordinary citations so output order follows the prose.
    for m in _CONTINUATION.finditer(text or ""):
        start, end = m.span()
        if any(_spans_overlap((start, end), s) for s in seen_spans):
            continue
        num = m.group(1)
        body = m.group("body")
        seen_spans.add((start, end))
        sub = f"{body} art. {num}" if body else f"art. {num}"
        results.append(resolve_norm_reference(sub, resolver))
    return results
