"""Contraste entre lo que el borrador AFIRMA y lo que sus fuentes SOSTIENEN.

Regresión de la auditoría 2026-08-14: `nif_runtime` verificaba con rigor la
procedencia de la firma (hash del borrador, hash de fuentes, binding normativo,
versión del NIF, principal autenticado) pero jamás el TEXTO. Se reprodujo, con
el corpus de producción, una opinión `HUMAN_VALIDATED` que invocaba el art. 105
del Código Civil —que el propio resolver clasifica OUT_OF_FORCE desde 2022— y
un art. 9999 inexistente. El circuito certificaba el sobre, no la carta.

El criterio es deliberadamente conservador. Con resolver canónico se exige
coincidencia exacta de cuerpo legal + artículo; sin resolver se conserva el
contrato histórico por token para compatibilidad con los llamadores existentes.
"""

from __future__ import annotations

import re

from lexo_cli.gid import a_gid_runtime

# "art. 162", "artículo 1545", "Art 105". El prefijo abre una ENUMERACIÓN:
# "artículos 161, 162 y 163" cita tres normas, no una. Sub-detectar es la
# dirección insegura —una cita que no se detecta no se verifica—, así que se
# consume la lista completa.
#
# «número(s)» es una ENTRADA del numeral, no una palabra decorativa: en
# «artículo número 9999» el artículo es el 9999. Sin este grupo la gramática
# cerraba en «artículo» + espacio, `_NUMERO` no encontraba dígito en «número»,
# y la cita entera devolvía `[]` — el gate la leía como "sin citas" y salía
# con `ok=true` y los agentes corriendo (auditoría 2026-09-27, P0).
# Se admite la palabra completa («número», «números») y las abreviaturas que el
# derecho chileno usa igual o más: «N°», «Nº», «n°», «núm.», «nro.», «nros.»,
# «num.». El grupo es opcional: «artículo 1545» sigue siendo una cita.
#
# Orden de las alternativas: las más largas primero. `n[uú]mero?s?` antes de
# `nro` para que «numero» no se lea como «nro» + «ero»; `nros?` antes de `nro`
# para que el plural no se lea como «nro» + «s».
#
# La coincidencia va ANCLADA al prefijo de artículo: «el documento n° 5» y
# «folio n° 1545» son prosa ordinaria y NO son citas normativas. Es el prefijo
# «art(ículo)» lo que abre la cita, no el símbolo de número.
_NUMERO_PALABRA = (
    r"(?:n[uú]mero?s?|n[uú]m|nros?\.?|nro|num(?:ero)?)\.?"
)
_PREFIJO = re.compile(
    r"\bart(?:[íi]culos?|s?)?\.?\s*(?:n[º°]\s*|" + _NUMERO_PALABRA + r"\s*)?",
    re.IGNORECASE,
)
# Varias normas chilenas nombran sus artículos en ordinal ("artículo primero"
# de la Ley 21.719), y sus GIDs quedan como `...:art:primero`. Si el extractor
# solo mirara dígitos, esas citas no se verificarían nunca.
_ORDINALES = (
    "primero", "segundo", "tercero", "cuarto", "quinto", "sexto", "séptimo",
    "septimo", "octavo", "noveno", "décimo", "decimo", "undécimo", "undecimo",
    "duodécimo", "duodecimo", "final",
)
# Artículo TRANSITORIO: el corpus los nombra `art_t_0005` (Ley 21.719,
# idNorma 61438, t_0001..t_0005; y 1058072 t_0001). En prosa aparecen como
# «art. t. 5» o «artículo transitorio 5». Sin una forma textual que emitiera el
# token `t-5`, `article_token` reconocía el GID pero ninguna cita podía llegar
# hasta él: todo artículo transitorio acababa en abstención permanente.
# La forma ordinal «transitorio» SIN número no individualiza un artículo y no
# debe inventar ninguno.
_TRANSITORIO_PREFIJO = r"(?:t|transitori[oa])"
_TRANSITORIO_RE = re.compile(
    _TRANSITORIO_PREFIJO + r"\.?\s*(\d+)", re.IGNORECASE,
)
# El ancho NO es un límite arbitrario: se midió sobre el snapshot de producción
# (8.544 artículos) y los 8.538 GID numéricos son de EXACTAMENTE 4 dígitos con
# zero-padding, con el artículo más alto en el 2524. No existe un artículo de 5+
# dígitos. Por eso `\d+` —y no `\d{1,4}`— es lo correcto: un numeral más largo
# se conserva ENTERO para que el verificador falle cerrado, en vez de
# truncarse a un prefijo que puede ser un artículo real y distinto. `123456`
# truncado a `1234` resolvería además un GID que existe en dos cuerpos.
#
# Los ordinales latinos (bis/ter/quáter y sus equivalentes maiores: quinquies,
# sexies, septies, octies, nonies) están en el corpus de producción. Omitirlos
# colapsaba «art. 172 octies» con el «art. 172» liso: dos normas distintas caían
# en un mismo token, y el gate aceptaba como citada una que no lo está.
_SUFIJOS = (
    "bis", "ter", "qu[aá]ter", "quater",
    "quinquies", "sexies", "septies", "octies", "nonies",
)
# El símbolo de grado va ENTRE el numeral y el sufijo: «art. 39° bis» es el
# artículo 39 bis, no el 39 liso. Sin este hueco el sufijo se perdía y las dos
# normas colapsaban en un token — la misma colisión por sufijo que el P0
# cerró para el prefijo numérico, pero por otra vía. El símbolo NO se descarta:
# en el corpus «ARTICULO 81°-» es la forma dominante de citar un artículo, y
# ahí el «°» ES el número.
_SIMBOLO_GRADO = r"[º°]?"
_NUMERO = re.compile(
    r"(\d+|" + "|".join(_ORDINALES) + r")"
    + _SIMBOLO_GRADO
    + r"(?:\s*(" + "|".join(_SUFIJOS) + r"))?",
    re.IGNORECASE,
)
_SEPARADOR = re.compile(r"\s*(?:,|;|\by\b|\be\b)\s*", re.IGNORECASE)
# Los artículos letrados ("152 quáter Ñ") son normas DISTINTAS entre sí. Sin la
# letra, los cinco artículos del capítulo de teletrabajo colapsan en un mismo
# token y el gate acepta una letra que no existe. La letra solo se busca tras un
# sufijo (bis/ter/quáter): en el derecho chileno no hay "artículo 161 G", y
# admitirla suelta haría que la "y" de "artículos 15 ter y 16" pasara por letra.
_LETRA = re.compile(r"\s*([a-zñ])(\))?", re.IGNORECASE)
# "y"/"e"/"o"/"u" son conjunciones antes que letras de artículo. Se descartan
# salvo que vengan cerradas con paréntesis ("152 quáter O)"). Una letra
# descartada degrada a token sin letra: la cita queda sin respaldo y el gate
# abstiene, que es la dirección segura.
_CONJUNCIONES = {"y", "e", "o", "u"}
_ACENTOS = str.maketrans("áéíóúÁÉÍÓÚ", "aeiouAEIOU")


def _sin_acentos(texto: str) -> str:
    return texto.translate(_ACENTOS)


def _normalize_letra(letra: str) -> str:
    """El corpus codifica la Ñ como `n` (`art_0152_quater_n` == '152 quáter Ñ')."""
    return _sin_acentos(letra.strip().lower()).replace("ñ", "n")


def _normalize_token(raw: str, sufijo: str = "", letra: str = "") -> str:
    """Token comparable entre el texto ('1545', 'primero') y el GID ('01545')."""
    base = raw.strip().lower()
    if base.isdigit():
        base = str(int(base))
    else:
        base = _sin_acentos(base)
    partes = [base]
    if sufijo:
        partes.append(_sin_acentos(sufijo.strip().lower()))
    if letra:
        partes.append(_normalize_letra(letra))
    return "-".join(partes)


def _letra_de_articulo(texto: str, pos: int) -> tuple[str, int]:
    """Letra que individualiza un artículo letrado, si la hay, y dónde termina.

    Devuelve ("", pos) cuando lo que sigue no es una letra de artículo sino el
    arranque de otra palabra ("15 ter *de* la Ley"), un enlace de enumeración
    ("15 ter *y* 16") o una conjunción sin paréntesis.
    """
    match = _LETRA.match(texto, pos)
    if not match:
        return "", pos
    resto = texto[match.end():]
    if re.match(r"[0-9A-Za-zÁÉÍÓÚáéíóúÑñ]", resto):  # "de", "del": no es letra
        return "", pos
    if re.match(r"\s*\d", resto):                    # "y 16": enumeración
        return "", pos
    cerrada = bool(match.group(2))
    if not cerrada and match.group(1).lower() in _CONJUNCIONES:
        return "", pos
    return match.group(1), match.end()


def cited_article_numbers(text: str) -> list[str]:
    """Números de artículo invocados en el texto, en orden de aparición."""
    vistos: list[str] = []
    contenido = text or ""
    for prefijo in _PREFIJO.finditer(contenido):
        pos = prefijo.end()
        # Un artículo TRANSITORIO se anuncia con su propia letra antes del
        # numeral («art. t. 5», «artículo transitorio 5»), y produce el token
        # `t-5` con el que `article_token` indexa el GID `...:art:t_0005`. Se
        # resuelve antes del ordinal para que la forma larga no se lea como el
        # ordinal suelto «transitorio» (que no individualiza ningún artículo).
        transitorio = _TRANSITORIO_RE.match(contenido, pos)
        if transitorio:
            token = "t-" + str(int(transitorio.group(1)))
            if token not in vistos:
                vistos.append(token)
            pos = transitorio.end()
            separador = _SEPARADOR.match(contenido, pos)
            if not separador:
                break
            pos = separador.end()
            continue
        while True:
            numero = _NUMERO.match(contenido, pos)
            if not numero:
                break
            fin = numero.end()
            letra = ""
            if numero.group(2):
                letra, fin = _letra_de_articulo(contenido, fin)
            token = _normalize_token(numero.group(1), numero.group(2) or "", letra)
            if token not in vistos:
                vistos.append(token)
            separador = _SEPARADOR.match(contenido, fin)
            if not separador:
                break
            pos = separador.end()
    return vistos


# `art_0152_quater_g` -> ('152', 'quater', 'g'). El `\Z` obliga a consumir el GID
# entero: sin él la letra final quedaba fuera y cinco normas distintas producían
# un solo token. Si un GID no encaja en esa forma se cae al patrón histórico,
# que ignora la letra, antes que descartar la fuente.
_GID_ARTICULO = re.compile(
    r"0*([0-9]+|[a-zá-úñ]+)(?:[-_]([a-zá-úñ]+))?(?:[-_]([a-zá-úñ]))?\Z",
    re.IGNORECASE,
)
_GID_ARTICULO_LEGADO = re.compile(
    r"0*([0-9]+|[a-zá-úñ]+)(?:[-_]([a-zá-úñ]+))?", re.IGNORECASE
)
# Artículos TRANSITORIOS: el corpus los nombra `art_t_0005` (6 casos: Ley
# 21.719 idNorma 61438 t_0001..t_0005 y 1058072 t_0001). El patrón genérico
# leía solo la `t` y devolvía el token degenerado "t", con el que cinco
# transitorios distintos —y cualquier otro artículo— colisionaban. Se resuelven
# antes del genérico y conservan su número: `t-0005`.
_GID_TRANSITORIO = re.compile(r"t[-_]0*(\d+)\Z", re.IGNORECASE)


def article_token(gid: str) -> str:
    """Token comparable de un GID: `cl.norma.ct:art:0152_quater_n` -> `152-quater-n`.

    Es la misma normalización que se aplica al texto del borrador, de modo que
    lo que la recuperación indexa es exactamente lo que el gate reconoce. Si las
    dos tokenizaciones divergieran, el sistema recuperaría una norma que después
    no sabría aceptar como citada.
    """
    gid = a_gid_runtime(gid) or gid  # la v2 se tokeniza como su equivalente runtime (F1)
    if ":art:" not in (gid or ""):
        return ""
    raw = gid.rsplit(":art:", 1)[1]
    transitorio = _GID_TRANSITORIO.match(raw)
    if transitorio:
        # Se conserva el número como aparece en el GID tras quitar solo el
        # prefijo `t`, SIN repadear a 4: el token debe comparar con lo que la
        # otra gramática produce para el mismo transitorio. `t_0005` -> `t-5`.
        return "t-" + transitorio.group(1)
    match = _GID_ARTICULO.match(raw) or _GID_ARTICULO_LEGADO.match(raw)
    if not match:
        return ""
    grupos = match.groups()
    letra = grupos[2] if len(grupos) > 2 else ""
    return _normalize_token(match.group(1), match.group(2) or "", letra or "")


def _source_tokens(sources) -> set[str]:
    """Números de artículo que las fuentes efectivamente sostienen."""
    tokens: set[str] = set()
    for item in sources or []:
        token = article_token(str((item or {}).get("gid", "")))
        if token:
            tokens.add(token)
    return tokens


def verify_draft_citations(draft: str, sources, *, resolver=None) -> dict:
    """¿Toda cita del borrador está respaldada por una fuente resuelta?

    Signature compatible con los llamadores NIF y usos legacy existentes. El
    argumento `resolver` es keyword-only y opcional.

    Comportamiento:
      * Sin `resolver`: se preserva el match por token del histórico, pero
        `not_in_force` se calcula SOLO para los tokens que el borrador citó
        (los candidatos de recuperación ya no envenenan citas ajenas).
      * Con `resolver`: se usa extracción con conocimiento de cuerpo
        (`lexo_cli.starter.norm_reference.extract_norm_references`). RESOLVED se
        soporta solo si su GID exacto está entre `sources`; un GID exacto fuera
        de vigencia => `not_in_force`; AMBIGUOUS y UNRESOLVABLE fallan cerrado
        y se reportan en `references`/`ambiguous`. El mismo número en el cuerpo
        equivocado NO soporta la cita.

    Devuelve siempre las claves de nivel superior
    ``ok, cited, supported, unsupported, not_in_force`` (tipos heredados) más
    claves estructuradas compatibles hacia atrás: ``references`` (detalle por
    cita) y ``ambiguous`` (referencias no resueltas sin cuerpo). Un borrador sin
    citas detectadas sigue siendo válido en esta capa (otros gates deciden si
    las citas son obligatorias).
    """
    if resolver is None:
        return _verify_legacy(draft, sources)

    from lexo_cli.starter.norm_reference import extract_norm_references

    references = extract_norm_references(draft, resolver)

    # GIDs de fuente exactos.
    source_gids = [
        str((item or {}).get("gid", ""))
        for item in (sources or [])
        if item and (item or {}).get("gid")
    ]
    source_gid_set = set(source_gids)

    cited: list[str] = []
    supported: list[str] = []
    unsupported: list[str] = []
    ambiguous: list[str] = []
    not_in_force: list[str] = []
    historical_text_unavailable: list[str] = []
    temporal_uncertain: list[str] = []
    reference_details: list[dict] = []

    for ref in references:
        # Token normalizado (p. ej. "2515", "0434") para mantener la semántica
        # heredada de `cited`/`supported`/`unsupported`; el detalle completo
        # (texto crudo, GID, candidatos) vive en `references`.
        token = ref.article_token or ref.raw
        cited.append(token)
        detail = {
            "raw": ref.raw,
            "status": ref.status,
            "gid": ref.gid,
            "candidates": list(ref.candidates),
            "reason": ref.reason,
            "supported": None,
        }
        reference_details.append(detail)
        if ref.status == "RESOLVED":
            if ref.gid in source_gid_set:
                supported.append(token)
                detail["supported"] = True
                # ¿La fuente citada está fuera de vigencia?
                src_item = _source_by_gid(sources, ref.gid)
                if src_item is not None and _is_out_of_force(src_item):
                    not_in_force.append(ref.gid)
                elif src_item is not None and _is_historical_text_unavailable(src_item):
                    # La cita existe, pero el texto del pack no puede probar que
                    # sea el que estaba vigente en la fecha consultada. Es una
                    # abstención histórica, no una declaración de no vigencia.
                    historical_text_unavailable.append(ref.gid)
                elif src_item is not None and _is_temporally_uncertain(src_item):
                    # Evidencia temporal incompatible: la cita no es utilizable
                    # hasta que un humano resuelva el conflicto de fuentes.
                    temporal_uncertain.append(ref.gid)
            else:
                # Mismo número en otro cuerpo (o cuerpo no provisto) => no
                # soportado. Fail-closed: sin fuente exacta, la cita cae.
                unsupported.append(token)
                detail["supported"] = False
        elif ref.status == "AMBIGUOUS":
            ambiguous.append(token)
            unsupported.append(token)
            detail["supported"] = False
        else:  # UNRESOLVABLE
            unsupported.append(token)
            detail["supported"] = False

    return {
        "ok": (
            not unsupported
            and not not_in_force
            and not historical_text_unavailable
            and not temporal_uncertain
        ),
        "cited": cited,
        "supported": supported,
        "unsupported": unsupported,
        "not_in_force": sorted(set(not_in_force)),
        "historical_text_unavailable": sorted(set(historical_text_unavailable)),
        "temporal_uncertain": sorted(set(temporal_uncertain)),
        # Claves estructuradas (compatibles hacia atrás).
        "references": reference_details,
        "ambiguous": ambiguous,
    }


def _verify_legacy(draft: str, sources) -> dict:
    """Verificación por token (sin resolver).

    `not_in_force` se limita a los tokens que el borrador REALMENTE citó: antes
    se listaba toda fuente fuera de vigencia, aunque no hubiera sido invocada.
    """
    cited_tokens = cited_article_numbers(draft)
    supported_tokens = _source_tokens(sources)

    cited_gids = [
        str((item or {}).get("gid", ""))
        for item in (sources or [])
        if item and (item or {}).get("gid")
    ]
    cited_token_set = set(cited_tokens)
    not_in_force = sorted(
        gid for gid in cited_gids
        if article_token(gid) in cited_token_set
        and _is_out_of_force(_source_by_gid(sources, gid))
    )

    historical_text_unavailable = sorted(
        gid for gid in cited_gids
        if article_token(gid) in cited_token_set
        and _is_historical_text_unavailable(_source_by_gid(sources, gid))
    )
    temporal_uncertain = sorted(
        gid for gid in cited_gids
        if article_token(gid) in cited_token_set
        and _is_temporally_uncertain(_source_by_gid(sources, gid))
    )
    unsupported = [token for token in cited_tokens if token not in supported_tokens]
    supported = [token for token in cited_tokens if token in supported_tokens]
    return {
        "ok": (
            not unsupported
            and not not_in_force
            and not historical_text_unavailable
            and not temporal_uncertain
        ),
        "cited": cited_tokens,
        "supported": supported,
        "unsupported": unsupported,
        "not_in_force": not_in_force,
        "historical_text_unavailable": historical_text_unavailable,
        "temporal_uncertain": temporal_uncertain,
        # Sin resolver no hay detalle de cuerpo; mantenemos las claves para
        # que el contrato de salida sea estable.
        "references": [
            {
                "raw": tok,
                "status": "RESOLVED" if tok in supported_tokens else "UNRESOLVABLE",
                "gid": None,
                "candidates": [],
                "reason": "",
                "supported": tok in supported_tokens,
            }
            for tok in cited_tokens
        ],
        "ambiguous": [],
    }


def _is_out_of_force(item: dict | None) -> bool:
    """True solo ante una incompatibilidad temporal positivamente acreditada.

    `UNKNOWN_BEFORE_SNAPSHOT` significa que falta texto histórico verificable;
    no permite inferir que la norma aún no existía ni que fue derogada.
    """
    if not item:
        return False
    status = item.get("temporal_status")
    return isinstance(status, str) and status in {"FUTURE", "OUT_OF_FORCE"}


def _is_historical_text_unavailable(item: dict | None) -> bool:
    """True cuando el pack no puede acreditar el texto de la fecha consultada."""
    if not item:
        return False
    return (
        item.get("temporal_status") == "UNKNOWN_BEFORE_SNAPSHOT"
        or item.get("historical_text_status") == "HISTORICAL_TEXT_UNAVAILABLE"
    )


def _is_temporally_uncertain(item: dict | None) -> bool:
    """True cuando la vigencia no está acreditada por un estado reconocido.

    Los estados FUTURE, OUT_OF_FORCE y UNKNOWN_BEFORE_SNAPSHOT tienen buckets
    propios; TEMPORAL_UNKNOWN y cualquier productor futuro/corrupto que emita
    otro valor quedan bloqueados aquí. La ausencia histórica del campo se
    conserva por compatibilidad con fuentes legacy sin metadato temporal.
    """
    if not item:
        return False
    status = item.get("temporal_status")
    if status is None or status == "":
        return False
    return not isinstance(status, str) or status not in {
        "IN_FORCE",
        "FUTURE",
        "OUT_OF_FORCE",
        "UNKNOWN_BEFORE_SNAPSHOT",
    }


def _source_by_gid(sources, gid: str) -> dict | None:
    for item in (sources or []):
        if item and str((item or {}).get("gid", "")) == gid:
            return item
    return None


def citation_failure_reasons(check: dict) -> list[str]:
    """Motivos legibles para una abstención por citas no respaldadas.

    Explica, sin duplicación, los tres casos de falla: citas sin respaldo
    (incluidas las ambiguas), referencias ambiguas (mismo número en varios
    cuerpos sin cuerpo indicado) y fuentes citadas fuera de vigencia.
    """
    reasons: list[str] = []

    unsupported = check.get("unsupported") or []
    if unsupported:
        ambiguous = set(check.get("ambiguous") or [])
        if ambiguous:
            amb = ", ".join(f"'{raw}'" for raw in sorted(ambiguous))
            reasons.append(
                f"Hay citas que no dicen de qué cuerpo legal son: {amb}. "
                "Ese número de artículo existe en más de un código, así que Diké "
                "no puede saber a cuál te refieres. Escribe el cuerpo junto al "
                "número (por ejemplo, «art. 1546 del Código Civil»)."
            )
        unsupported_unambiguous = [raw for raw in unsupported if raw not in ambiguous]
        if unsupported_unambiguous:
            listado = ", ".join(f"'{raw}'" for raw in sorted(set(unsupported_unambiguous)))
            # Distinguir: ¿el artículo existe en algún cuerpo conocido o es genuinamente inexistente?
            # Si alguna referencia tiene status UNRESOLVABLE, es probable que el artículo no exista
            # en la fuente oficial (ej. "art. 99999 del CC"). Si está RESOLVED pero no en `sources`,
            # significa que el cuerpo existe pero no está en la biblioteca del usuario.
            references = check.get("references", [])
            any_unresolvable = any(d.get("status") == "UNRESOLVABLE" for d in references if d.get("raw") in unsupported_unambiguous)
            if any_unresolvable:
                reasons.append(
                    f"El escrito cita artículos que no se pudieron verificar (posiblemente inexistentes): {listado}. "
                    "Revisa el número y el cuerpo legal antes de presentarlo."
                )
            else:
                reasons.append(
                    f"El escrito cita normas que no están en tu biblioteca: {listado}. "
                    "Diké no puede verificar su texto ni su vigencia, así que no las "
                    "da por buenas."
                )

    historical = check.get("historical_text_unavailable") or []
    if historical:
        from lexo_cli.humanize import humanize_gid

        legibles = ", ".join(humanize_gid(gid) or gid for gid in historical)
        reasons.append(
            f"Diké no dispone de texto histórico verificable para: {legibles}. "
            "No certifica el texto consolidado actual como texto vigente en la fecha consultada."
        )

    temporal_uncertain = check.get("temporal_uncertain") or []
    if temporal_uncertain:
        from lexo_cli.humanize import humanize_gid

        legibles = ", ".join(humanize_gid(gid) or gid for gid in temporal_uncertain)
        reasons.append(
            f"Diké encontró evidencia temporal incompatible para: {legibles}. "
            "Su estado es «vigencia indeterminada» y requiere revisión antes de citarla."
        )

    not_in_force = check.get("not_in_force") or []
    if not_in_force:
        # `not_in_force` viene con GIDs canónicos (`cl.norma.cc:art:1546`).
        # Mostrarlos crudos obliga al abogado a descifrar un formato interno
        # para entender qué norma de su escrito está derogada.
        from lexo_cli.humanize import humanize_gid

        legibles = ", ".join(humanize_gid(gid) or gid for gid in not_in_force)
        reasons.append(
            f"El escrito se apoya en normas que no están vigentes: {legibles}. "
            "Reemplázalas por la norma vigente equivalente."
        )

    return reasons


# Menciones de una norma SIN pinpoint de artículo: «la Ley 21.719», «el Código
# Civil». No son citas de artículo, así que no entran al gate y no pueden
# verificarse tal cual — pero tampoco pueden declararse verificadas en
# silencio. Se declaran como puntos ciegos.
_MENCION_NORMA = re.compile(
    r"\b(?:ley|dfl|d\.?l\.?|decreto|constituci[óo]n|c[óo]digo)\s*"
    r"(?:n?[º°]\s*)?([0-9]+(?:\.[0-9]+)?|org[aá]nico|provisorio)?",
    re.IGNORECASE,
)


# El orden habitual en un escrito chileno: el artículo va ANTES del nombre de
# la norma («artículo 161 del Código del Trabajo», «art. 5º de la Ley 19.799»).
_PINPOINT_ANTES = re.compile(
    r"\bart(?:[íi]culos?|s?\.)?\s*(?:n?[º°]\s*)?\d+\s*[º°]?(?:\s+(?:bis|ter|qu[áa]ter))?"
    r"\s*,?\s+(?:del|de\s+la|de\s+los|de\s+las|de)\s+\Z",
    re.IGNORECASE,
)


def _tramos_citados(texto: str, referencias: list[dict] | None) -> list[tuple[int, int]]:
    """Dónde está, en el texto, cada cita que el gate SÍ extrajo.

    `raw` es el tramo literal que la gramática reconoció. Que el gate haya
    extraído una cita no dice que la haya verificado: dice que la procesó y la
    reportó, verificada o fallida. Eso basta para que no sea un punto ciego.
    """
    tramos: list[tuple[int, int]] = []
    for ref in referencias or []:
        raw = str((ref or {}).get("raw") or "")
        if not raw:
            continue
        inicio = texto.find(raw)
        while inicio != -1:
            tramos.append((inicio, inicio + len(raw)))
            inicio = texto.find(raw, inicio + 1)
    return tramos


def _menciones_sin_verbatim(texto: str, referencias: list[dict] | None = None) -> list[str]:
    """Normas mencionadas sin pinpoint, que el gate no pudo verificar.

    Una mención acompañada de artículo («la Ley 21.719 en su art. 5») SÍ
    tiene pinpoint verificable, y el gate la cubrió: no se declara. La que
    aparece sola («el Código Civil») no lo tiene y queda como punto ciego.

    El artículo también puede ir ANTES («artículo 161 del Código del
    Trabajo»), que es como se cita en Chile. Esa mención solo se da por
    cubierta si se cumplen las dos cosas: el artículo está pegado delante, y
    la mención cae dentro de una cita que el gate extrajo (`referencias`). Con
    una sola de las dos se sigue declarando: ante la duda, se advierte de más.
    """
    texto = texto or ""
    tramos = _tramos_citados(texto, referencias)
    encontradas: list[str] = []
    for m in _MENCION_NORMA.finditer(texto):
        etiqueta = (m.group(0) or "").strip()
        if not etiqueta:
            continue
        if (
            any(inicio <= m.start() and m.end() <= fin for inicio, fin in tramos)
            and _PINPOINT_ANTES.search(texto[max(0, m.start() - 60): m.start()])
        ):
            continue
        # Solo se considera acompañada si el artículo viene INMEDIATAMENTE
        # después de la mención,permitiendo un conector corto («en su art. 5»).
        ventana = texto[m.end(): m.end() + 24]
        if re.match(
            r"\s*(?:,?\s*(?:en\s+su\s+|en\s+el\s+|,)?)\s*(?:art(?:[íi]culos?|\.)?\s*)?"
            r"(?:n?[º°]\s*)?n?[º°]?\s*\d+",
            ventana,
            re.IGNORECASE,
        ):
            continue
        if etiqueta not in encontradas:
            encontradas.append(etiqueta)
    return encontradas


def citation_disclosure(check: dict, texto: str = "") -> dict:
    """Qué acreditó Diké, qué NO, y qué no puede saber.

    Existe por una razón normativa, no estética. El Código de Ética
    Profesional del Colegio de Abogados de Chile, art. 97, prohíbe «hacer
    citas … sabiendo o debiendo saber que son inexactas». La cláusula «y
    debiendo saber» es la que obliga a que un resultado `CITATIONS_VERIFIED`
    declare su propio alcance: si el sistema calla lo que no verificó, deja al
    abogado creyendo que todo está comprobado.

    El alcance que Diké SÍ cubre es existencia, citabilidad y vigencia. NO
    cubre la pertinencia sustantiva — que la norma fundamente lo que el
    escrito dice. Bluebook R1.2 distingue la señal «no signal» (la autoridad
    enuncia directamente la proposición) de un apoyo laxo: una cita puede ser
    real, vigente y aun así no fundamentar la tesis. Diké no evalúa eso, y
    decirlo es parte del resultado.
    """
    alcance = [
        "existencia de la norma en la fuente consultada",
        "citabilidad de su texto",
        "vigencia (estado IN_FORCE) a la fecha de la consulta",
    ]
    verificadas = [str(t) for t in (check.get("supported") or [])]
    advertencias = [
        "Diké verifica que estas normas existan, sean citables y estén vigentes; "
        "NO verifica que fundamenten sustantivamente lo que el escrito afirma. "
        " Esa fundamentación es juicio del abogado."
    ]
    if not verificadas:
        advertencias.append(
            "No se acreditó ninguna cita en este resultado: no hay certificado de "
            "que la norma exista."
        )
    no_verificadas = _menciones_sin_verbatim(texto, check.get("references"))
    if no_verificadas:
        advertencias.append(
            "El texto menciona normas sin artículo pinpoint que el gate no "
            "verificó: no son citas verificables tal cual, pero existen y no "
            "deben darse por comprobadas."
        )
    return {
        "alcance": alcance,
        "verificadas": verificadas,
        "no_verificadas": no_verificadas,
        "advertencias": advertencias,
    }
