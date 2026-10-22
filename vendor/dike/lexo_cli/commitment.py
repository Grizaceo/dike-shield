"""Commitment público de una constancia: prueba de integridad publicable.

DISEÑO (decidido con Cristóbal 2026-10-05, tras auditar el artefacto real):

De una constancia salen dos cosas DISTINTAS a propósito:

1. La constancia completa (lo que imprime ``dike constancia --json``). Lleva
   ``cita_raw`` (costura entre la cita legal y la prosa del cliente),
   ``documento`` (ruta absoluta) y ``origen`` (texto libre donde el --help
   sugiere escribir "demanda de Juan Pérez"). **No se publica.**

2. ``commitment.json`` — lo que construye ESTE módulo a partir de la
   constancia. Solo lo publicable: qué normas se verificaron, contra qué
   corpus (``pack_hash``) y en qué fecha. Ni una ruta, ni un nombre, ni un
   verbo del escrito. Sí revela qué normas se citaron, cuántas citas hubo y
   la hora de la constancia.

``dike constancia <escrito> --emit-commitment DIR [--sign]`` escribe el
commitment público en ``DIR/commitment.json`` y, con ``--sign``, su firma.

Por qué: un ancla pública es irreversible. Bitcoin no se borra. Anclar el
artefacto completo publicaría datos bajo reserva de una demanda. El hash es
público; el contexto que lo rodea, no.

El gate es fail-closed y en dos direcciones:
- No se emite commitment si el documento/origen traen PII de alta certeza.
- Un compromiso no puede *declarar* verificación que la constancia no tuvo:
  los conteos se derivan de las normas, no se copian.

CONTRATO V2 (2026-10-05, post-auditoría Opus 5.5):
  ``compromiso_publico()`` omite ``document_sha256`` y ``document_bytes``
  — evita confirmación por diccionario sin secretos.
  Publicar la huella exige opt-in (``escribir_commitment(publico=False)``,
  ``firmar_commitment(permitir_huella=True)``) y emite
  ``HuellaPublicadaWarning``.
  Nunca se llama "anonimización" a un SHA-256 sin secreto.

UNA SOLA PUERTA (remediación 2, 2026-10-05): ``validar_publicable``.
  La llaman el constructor, ``compromiso_publico``, ``escribir_commitment`` y
  ``firmar_commitment``. Antes la invariante vivía solo en el constructor, y
  un dict armado a mano con ``origen`` y un RUT se escribía, se firmaba y
  verificaba. La puerta es una lista BLANCA de claves (una lista negra no ve
  ``Origen`` ni ``documento_path``) y audita PII en todo lo que se publica.

  Desde la reauditoría 2 (2026-10-06, H4) la puerta también EXIGE: la lista
  blanca decía qué puede ir y no qué no puede faltar, y pasaba un commitment
  sin ``total_citas``, con un conteo negativo o con un ``pack_hash`` que decía
  ``sin-corpus``: uno firmado que no nombra contra qué corpus se verificó.
"""
from __future__ import annotations

import hashlib
import json
import re
import warnings
from pathlib import Path
from typing import Any

from lexo_cli.mcp.lexo_legal_core.gates import detect_pii

COMMITMENT_SCHEMA_VERSION = "dike-constancia-commitment-v2"

#: Campos que nunca pueden salir, ni por error de refactor. La lista blanca de
#: abajo ya los excluye; se nombran aparte para que el mensaje diga por qué.
_CAMPOS_PROHIBIDOS = frozenset({
    "documento", "origen", "cita_raw", "problemas", "detalles",
})

#: Lista BLANCA: lo único que puede llevar un commitment. Agregar un campo
#: exige agregarlo aquí, a propósito.
_CLAVES_COMMITMENT = frozenset({
    "schema_version", "pack_hash", "as_of", "fecha_constancia",
    "total_citas", "citas_verificadas", "citas_fallidas",
    "normas_verificadas", "alcance", "advertencias",
    "_aviso_huella_omitida",
})
_CLAVES_NORMA = frozenset({
    "gid", "cuerpo", "vigencia", "vigencia_legible", "texto_hash", "fuente_url", "estado",
})
#: La huella del escrito y su error de cálculo. Solo con opt-in.
_CLAVES_HUELLA = frozenset({"document_sha256", "document_bytes", "document_hash_error"})

_CONTEOS = ("total_citas", "citas_verificadas", "citas_fallidas")

#: Lo que NO puede faltar. La lista blanca dice qué puede llevar un commitment;
#: esta, qué tiene que llevar para acreditar algo.
_OBLIGATORIOS = (
    "schema_version", "pack_hash", "as_of", "fecha_constancia", *_CONTEOS,
    "normas_verificadas", "alcance", "advertencias",
)
#: De cada norma: qué norma es, contra qué texto se verificó y de dónde salió.
_OBLIGATORIOS_NORMA = ("gid", "vigencia", "texto_hash", "fuente_url", "estado")

#: 15 dígitos: lo que todo lector de JSON conserva exacto. Uno de doble
#: precisión (jq antes de 1.7) redondea los enteros más largos, y la receta
#: sin Python no verificaría un commitment legítimo.
_CONTEO_MAXIMO = 10**15 - 1

#: Formas exactas. `re.fullmatch`: con `$` un salto de línea final pasaría.
_PACK_HASH = re.compile(r"[0-9a-f]{16}")
_TEXTO_HASH = re.compile(r"[0-9a-f]{64}")
_FECHA = re.compile(r"\d{4}-\d{2}-\d{2}")
_FECHA_HORA_UTC = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")

#: Etiquetas de PII que bloquean la emisión (misma política que el write gate).
#: patente/dirección se reportan pero no bloquean: dan falsos positivos en
#: léxico jurídico ("DL 3500", "camino Procesal").
_PII_BLOQUEANTE = ("rut", "email", "phone")


class CommitmentPIIError(ValueError):
    """El commitment no se emite: riesgo de fuga (PII, campo fuera del esquema
    o huella del escrito sin opt-in)."""


class CommitmentIncoherenteError(ValueError):
    """El commitment declara algo que sus propias normas no sostienen
    (conteos que no cuadran, una norma no verificada, un tipo inesperado)."""


class HuellaPublicadaWarning(UserWarning):
    """Se va a escribir o firmar un commitment con la huella SHA-256 del escrito."""


def _hash_documento(documento_path: str | Path) -> dict[str, str]:
    """Huella SHA-256 y tamaño del documento.

    Lee el archivo completo para hashearlo; no devuelve el texto ni un
    fragmento. Un SHA-256 sin secreto NO es anonimización: quien tenga un
    escrito candidato puede confirmar si es este. Por eso la versión pública
    del commitment omite estos dos campos (``compromiso_publico``).
    """
    p = Path(documento_path)
    raw = p.read_bytes()
    return {
        "document_sha256": hashlib.sha256(raw).hexdigest(),
        "document_bytes": str(len(raw)),
    }


def auditar_pii(campos: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Devuelve las etiquetas de PII halladas por campo. Vacío = limpio.

    Reporta TODAS las etiquetas detectadas (incluidas las no bloqueantes) para
    que la auditoría sea inspeccionable; el gate decide aparte con
    ``_PII_BLOQUEANTE``.
    """
    hallazgos: dict[str, dict[str, int]] = {}
    for campo, valor in campos.items():
        if not isinstance(valor, str) or not valor:
            continue
        counts = detect_pii(valor)
        if counts:
            hallazgos[campo] = {k: v for k, v in counts.items() if v}
    return hallazgos


def _pii_bloqueante(hallazgos: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Filtra a las etiquetas que de verdad impiden emitir el commitment.

    Descarta los campos que quedan con un dict VACÍO tras el filtro: de otro
    modo un campo con solo PII no bloqueante (patente/direccion) devolvería
    ``{'documento': {}}``, que es truthy en Python y bloquearia la emision.
    """
    out: dict[str, dict[str, int]] = {}
    for campo, etiquetas in hallazgos.items():
        bloqueantes = {k: v for k, v in etiquetas.items() if k in _PII_BLOQUEANTE}
        if bloqueantes:
            out[campo] = bloqueantes
    return out


def tiene_huella(commitment: dict[str, Any]) -> bool:
    """True si el commitment lleva la huella SHA-256 del escrito."""
    return bool(commitment.get("document_sha256"))


def _cadenas(node: Any, path: str) -> dict[str, str]:
    """Todas las cadenas del commitment, por ruta: es lo que se va a publicar."""
    out: dict[str, str] = {}
    if isinstance(node, str):
        out[path] = node
    elif isinstance(node, dict):
        for k, v in node.items():
            out.update(_cadenas(v, f"{path}.{k}"))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out.update(_cadenas(v, f"{path}[{i}]"))
    return out


def _assert_claves(node: dict[str, Any], permitidas: frozenset[str], path: str) -> None:
    for k in node:
        if k in _CAMPOS_PROHIBIDOS:
            raise CommitmentPIIError(
                f"El commitment contiene el campo prohibido {k!r} en {path!r}"
            )
        if k not in permitidas:
            raise CommitmentPIIError(
                f"El commitment contiene un campo fuera del esquema, {k!r}, en {path!r}. "
                "Lo que no está en el esquema no se publica."
            )


def _es_entero(valor: Any) -> bool:
    return isinstance(valor, int) and not isinstance(valor, bool)


def validar_publicable(commitment: Any, *, permitir_huella: bool = False) -> None:
    """La única puerta: lanza si el commitment no se puede publicar ni firmar.

    Comprueba, en este orden:

    1. Solo las claves del esquema (lista blanca), también dentro de cada norma.
       La huella del escrito solo pasa con ``permitir_huella=True``.
    2. Tipos: conteos enteros, textos como cadenas. Sin números decimales
       ni el carácter de control DEL.
    3. Lo que no puede faltar, y su forma: ``schema_version`` es el de este
       módulo; ``pack_hash`` son 16 hexadecimales (un valor como
       ``sin-corpus`` no nombra ningún corpus); las fechas tienen su formato;
       los tres conteos están, no son negativos y caben en 15 dígitos; hay
       alcance y advertencias;
       cada norma dice cuál es, contra qué texto se verificó y de dónde salió.
    4. Coherencia: cada norma listada está ``VERIFICADA``,
       ``citas_verificadas == len(normas_verificadas)`` y
       ``total == verificadas + fallidas``.
    5. Ningún dato personal de alta certeza (RUT, correo, teléfono móvil) en
       ninguna cadena de lo que se publica.

    Lo que NO exige: que las normas sean distintas. Los conteos son de citas,
    y un escrito que cita dos veces el mismo artículo lo lista dos veces.

    Raises:
        CommitmentPIIError: riesgo de fuga (puntos 1 y 5). El mensaje nombra
            el campo, nunca el dato.
        CommitmentIncoherenteError: puntos 2, 3 y 4.
    """
    if not isinstance(commitment, dict):
        raise CommitmentIncoherenteError("el commitment no es un objeto")

    # ── 1. Lista blanca ──
    permitidas = _CLAVES_COMMITMENT | (_CLAVES_HUELLA if permitir_huella else frozenset())
    con_huella = sorted(k for k in commitment if k in _CLAVES_HUELLA)
    if con_huella and not permitir_huella:
        raise CommitmentPIIError(
            f"El commitment lleva la huella del escrito ({con_huella}). Un SHA-256 "
            "sin secreto no es anonimización. Usa compromiso_publico() o pide la "
            "huella a propósito (permitir_huella=True)."
        )
    _assert_claves(commitment, permitidas, "commitment")

    normas = commitment.get("normas_verificadas")
    if not isinstance(normas, list):
        raise CommitmentIncoherenteError("normas_verificadas debe ser una lista")
    for i, norma in enumerate(normas):
        if not isinstance(norma, dict):
            raise CommitmentIncoherenteError(f"normas_verificadas[{i}] no es un objeto")
        _assert_claves(norma, _CLAVES_NORMA, f"commitment.normas_verificadas[{i}]")

    # ── 2. Tipos ──
    for campo in _CONTEOS:
        if campo in commitment and commitment[campo] is not None and not _es_entero(commitment[campo]):
            raise CommitmentIncoherenteError(f"{campo} debe ser un entero")
    advertencias = commitment.get("advertencias", [])
    if advertencias is None:
        advertencias = []
    if not isinstance(advertencias, list) or not all(isinstance(a, str) for a in advertencias):
        raise CommitmentIncoherenteError("advertencias debe ser una lista de cadenas")
    for campo, valor in commitment.items():
        if campo in _CONTEOS or campo in ("normas_verificadas", "advertencias"):
            continue
        if valor is not None and not isinstance(valor, str):
            raise CommitmentIncoherenteError(f"{campo} debe ser una cadena")
    for i, norma in enumerate(normas):
        for campo, valor in norma.items():
            if valor is not None and not isinstance(valor, str):
                raise CommitmentIncoherenteError(
                    f"normas_verificadas[{i}].{campo} debe ser una cadena"
                )

    # ── 3. Lo que no puede faltar, y su forma ──
    for campo in _OBLIGATORIOS:
        if commitment.get(campo) in (None, ""):
            raise CommitmentIncoherenteError(f"falta {campo}: un commitment no se publica sin él")
    if commitment["schema_version"] != COMMITMENT_SCHEMA_VERSION:
        raise CommitmentIncoherenteError(
            f"schema_version debe ser {COMMITMENT_SCHEMA_VERSION!r}"
        )
    if not _PACK_HASH.fullmatch(commitment["pack_hash"]):
        raise CommitmentIncoherenteError(
            "pack_hash debe ser 16 hexadecimales: sin él el commitment no dice "
            "contra qué corpus se verificó"
        )
    if not _FECHA.fullmatch(commitment["as_of"]):
        raise CommitmentIncoherenteError("as_of debe ser una fecha AAAA-MM-DD")
    if not _FECHA_HORA_UTC.fullmatch(commitment["fecha_constancia"]):
        raise CommitmentIncoherenteError(
            "fecha_constancia debe ser una fecha y hora UTC (AAAA-MM-DDThh:mm:ssZ)"
        )
    for campo in _CONTEOS:
        if commitment[campo] < 0:
            raise CommitmentIncoherenteError(f"{campo} no puede ser negativo")
        if commitment[campo] > _CONTEO_MAXIMO:
            raise CommitmentIncoherenteError(f"{campo} no cabe en 15 dígitos")
    if not advertencias or not all(advertencias):
        raise CommitmentIncoherenteError(
            "advertencias no puede ir vacío: el commitment lleva lo que Diké no verificó"
        )
    for i, norma in enumerate(normas):
        for campo in _OBLIGATORIOS_NORMA:
            if norma.get(campo) in (None, ""):
                raise CommitmentIncoherenteError(f"normas_verificadas[{i}] no trae {campo}")
        if not _TEXTO_HASH.fullmatch(norma["texto_hash"]):
            raise CommitmentIncoherenteError(
                f"normas_verificadas[{i}].texto_hash debe ser un SHA-256 en hexadecimal"
            )

    # ── 4. Coherencia: no declarar más de lo que hay ──
    for i, norma in enumerate(normas):
        if norma.get("estado") != "VERIFICADA":
            raise CommitmentIncoherenteError(
                f"normas_verificadas[{i}] no está VERIFICADA: no puede ir en el commitment"
            )
    verificadas = commitment["citas_verificadas"]
    if verificadas != len(normas):
        raise CommitmentIncoherenteError(
            f"citas_verificadas={verificadas!r} no cuadra con las "
            f"{len(normas)} normas listadas"
        )
    total, fallidas = commitment["total_citas"], commitment["citas_fallidas"]
    if total != verificadas + fallidas:
        raise CommitmentIncoherenteError(
            f"total_citas={total} no es verificadas ({verificadas}) + fallidas ({fallidas})"
        )

    # El carácter DEL (U+007F) es el único que `jq` y Python serializan
    # distinto dentro de una cadena: firmarlo daría un commitment legítimo que
    # la receta sin Python no verifica.
    for ruta, cadena in _cadenas(commitment, "commitment").items():
        if "\x7f" in cadena:
            raise CommitmentIncoherenteError(f"{ruta} trae el carácter de control DEL")

    # ── 5. PII en lo que SÍ se publica ──
    bloqueantes = _pii_bloqueante(auditar_pii(_cadenas(commitment, "commitment")))
    if bloqueantes:
        raise CommitmentPIIError(
            "No se publica el commitment: hay datos personales de alta certeza "
            f"en {bloqueantes}."
        )


def commitment_de_constancia(
    result: dict[str, Any],
    *,
    documento: str | Path | None = None,
) -> dict[str, Any]:
    """Construye el commitment a partir del resultado de la constancia.

    Con ``documento`` añade la huella del escrito: es el commitment INTERNO.
    Para publicar, pasarlo por ``compromiso_publico``.

    Raises:
        CommitmentPIIError: si ``documento``/``origen`` traen PII de alta
            certeza, o si la trae algún campo que se publicaría. Fail-closed:
            preferimos no emitir antes que emitir una huella cuyo material de
            origen viaja junto en otro artefacto.
        CommitmentIncoherenteError: si los conteos que declara la constancia
            no cuadran con sus propios detalles.
    """
    meta = result.get("meta", {}) or {}
    detalles = result.get("detalles", []) or []

    # ── Gate 1: el material que NO se publica no puede traer PII ──
    hallazgos = auditar_pii({
        "documento": str(meta.get("documento") or ""),
        "documento_argumento": str(documento or ""),
        "origen": meta.get("origen") or "",
    })
    bloqueantes = _pii_bloqueante(hallazgos)
    if bloqueantes:
        raise CommitmentPIIError(
            "No se emite el commitment: el documento o su origen contienen PII "
            f"de alta certeza ({bloqueantes}). El hash puede ser público, pero "
            "el material de origen no debe viajar en un artefacto firmable."
        )

    # ── Gate 2: solo hechos que la constancia efectivamente acreditó ──
    verificadas = [d for d in detalles if d.get("estado") == "VERIFICADA"]
    normas = [
        {
            "gid": d.get("gid"),
            "cuerpo": d.get("cuerpo"),
            "vigencia": d.get("vigencia"),
            "vigencia_legible": d.get("vigencia_legible"),
            "texto_hash": d.get("texto_hash"),
            "fuente_url": d.get("fuente_url"),
            "estado": d.get("estado"),
        }
        for d in verificadas
    ]

    # Los conteos se DERIVAN de los detalles. Si la constancia declara otros,
    # no se elige entre dos números: se rechaza.
    derivados = {
        "total_citas": len(detalles),
        "citas_verificadas": len(normas),
        "citas_fallidas": len(detalles) - len(normas),
    }
    for campo, valor in derivados.items():
        declarado = meta.get(campo)
        if declarado is not None and declarado != valor:
            raise CommitmentIncoherenteError(
                f"la constancia declara {campo}={declarado!r} y sus detalles dan {valor}"
            )

    commitment: dict[str, Any] = {
        "schema_version": COMMITMENT_SCHEMA_VERSION,
        "pack_hash": meta.get("pack_hash"),
        "as_of": meta.get("as_of"),
        "fecha_constancia": meta.get("fecha_constancia"),
        **derivados,
        "normas_verificadas": normas,
        "alcance": result.get("alcance"),
        "advertencias": (result.get("citation_disclosure", {}) or {}).get("advertencias", []),
    }

    if documento is not None:
        try:
            commitment.update(_hash_documento(documento))
        except OSError as exc:
            commitment["document_sha256"] = None
            commitment["document_hash_error"] = type(exc).__name__

    # ── Gate 3: la puerta única (esquema, coherencia y PII de lo publicable) ──
    validar_publicable(commitment, permitir_huella=True)
    return commitment


def compromiso_publico(commitment: dict[str, Any]) -> dict[str, Any]:
    """Versión del commitment lista para publicar.

    OMITE ``document_sha256`` y ``document_bytes``: sin huella pública no hay
    confirmación por diccionario. Y pasa el resultado por ``validar_publicable``:
    un dict armado a mano con campos fuera del esquema o con datos personales
    no sale de aquí.

    No muta el original; devuelve un dict nuevo.
    """
    if not isinstance(commitment, dict):
        raise CommitmentIncoherenteError("el commitment no es un objeto")
    publico = dict(commitment)
    for clave in _CLAVES_HUELLA:
        publico.pop(clave, None)
    publico["_aviso_huella_omitida"] = (
        "document_sha256 y document_bytes omitidos por defecto. "
        "La huella del escrito no viaja en este compromiso."
    )
    validar_publicable(publico)
    return publico


def commitment_hash(commitment: dict[str, Any]) -> str:
    """Hash canónico del commitment. Estable: mismo contenido, mismo hash."""
    raw = json.dumps(
        commitment, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def escribir_commitment(commitment: dict[str, Any], destino: str | Path, *, publico: bool = True) -> str:
    """Escribe el commitment a disco y devuelve su hash. Fail-closed: no firma.

    Por defecto escribe la versión PÚBLICA (sin huella del escrito). Con
    ``publico=False`` escribe el commitment tal cual, huella incluida, y emite
    ``HuellaPublicadaWarning``: es un opt-in, no un descuido.

    En los dos modos valida antes de crear el archivo.
    """
    if publico:
        payload = compromiso_publico(commitment)
    else:
        validar_publicable(commitment, permitir_huella=True)
        payload = commitment
        if tiene_huella(payload):
            warnings.warn(
                "se escribe un commitment con la huella SHA-256 del escrito: "
                "quien tenga un escrito candidato puede confirmar si es este.",
                HuellaPublicadaWarning,
                stacklevel=2,
            )
    p = Path(destino)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return commitment_hash(payload)
