"""Tests del commitment publicable de la constancia.

REGLA (H12): todo test negativo requiere un control positivo y un detector de
excepciones. Un `try/except` ancho puede tragarse el fallo; por eso se verifica
explícitamente que la excepción ES la esperada y que el control positivo NO lanza.

Cada test negativo de fuga tiene un gemelo positivo:
  - el commitment se emite (sin PII)
  - el commitment NO se emite (con PII) y el motivo es el correcto

RECONSTRUIDO 2026-10-05: el .py de este archivo desapareció del árbol de trabajo
(patrón ya documentado en el pendiente [079] — un proceso externo borra archivos
no commiteados) mientras el .pyc sobrevivía. Verificado de nuevo en commit.
"""

from __future__ import annotations

import copy
import hashlib
import json
import warnings
from pathlib import Path

import pytest

from lexo_cli.commitment import (
    CommitmentIncoherenteError,
    CommitmentPIIError,
    HuellaPublicadaWarning,
    _pii_bloqueante,
    auditar_pii,
    commitment_de_constancia,
    commitment_hash,
    compromiso_publico,
    escribir_commitment,
    validar_publicable,
)


def _constancia_falsa() -> dict:
    """Constancia sintética con la FORMA real del artefacto (no el dato)."""
    return {
        "veredicto": "TODAS_VERIFICADAS",
        "alcance": "La constancia acredita identidad de la referencia, integridad del texto fuente.",
        "problemas": [],
        "detalles": [
            {
                "cita_raw": "artículo 161 del Código del Trabajo",
                "gid": "cl.norma.ct:art:0161",
                "cuerpo": "Código del Trabajo art. 161",
                "estado": "VERIFICADA",
                "resolucion": "RESOLVED",
                "texto_hash": "a" * 64,
                "vigencia": "IN_FORCE",
                "vigencia_legible": "vigente",
                "fuente_url": "https://ejemplo/1",
            },
            {
                "cita_raw": "artículo 39 del Código del Trabajo impone",
                "gid": "cl.norma.ct:art:0039",
                "cuerpo": "Código del Trabajo art. 39",
                "estado": "VERIFICADA",
                "resolucion": "RESOLVED",
                "texto_hash": "b" * 64,
                "vigencia": "IN_FORCE",
                "vigencia_legible": "vigente",
                "fuente_url": "https://ejemplo/2",
            },
            {
                "cita_raw": "artículo 999 del Código del Trabajo",
                "gid": "cl.norma.ct:art:0999",
                "cuerpo": "Código del Trabajo art. 999",
                "estado": "FALLO",
                "resolucion": "UNRESOLVED",
                "texto_hash": None,
                "vigencia": None,
                "vigencia_legible": None,
                "fuente_url": None,
            },
        ],
        "citation_disclosure": {
            "alcance": ["existencia de la norma en la fuente consultada"],
            "verificadas": ["0161", "0039"],
            "no_verificadas": [],
            "advertencias": ["Diké NO verifica que fundamente sustantivamente."],
        },
        "meta": {
            "documento": "/home/usuario/caso/secreto/demanda_juan_perez.md",
            "origen": "demanda de Juan Pérez",
            "as_of": "2026-10-05",
            "fecha_constancia": "2026-10-05T09:17:55Z",
            "pack_hash": "ea28fa1c0f9af6c1",
            "total_citas": 3,
            "citas_verificadas": 2,
            "citas_fallidas": 1,
        },
    }


def _doc_limpio(tmp_path: Path, nombre: str = "sin_pii.md") -> str:
    """Archivo local sin PII, para hashear."""
    p = tmp_path / nombre
    p.write_text("texto sin datos personales", encoding="utf-8")
    return str(p)


# ── CONTROL POSITIVO: sin PII se emite ───────────────────────────────

def test_control_positivo_emite_commitment(tmp_path):
    """Control positivo: material limpio → commitment emitido."""
    c = commitment_de_constancia(_constancia_falsa(), documento=_doc_limpio(tmp_path))
    assert c["schema_version"] == "dike-constancia-commitment-v2"
    assert c["pack_hash"] == "ea28fa1c0f9af6c1"
    assert c["citas_verificadas"] == 2


# ── NO FUGA: ningún campo prohibido sale ──────────────────────────────

def test_no_fuga_cita_raw(tmp_path):
    """La prosa del cliente ('impone') no puede aparecer en el commitment."""
    c = commitment_de_constancia(_constancia_falsa(), documento=_doc_limpio(tmp_path))
    blob = json.dumps(c, ensure_ascii=False)
    assert "impone" not in blob, "fuga: cita_raw (prosa del cliente) llegó al commitment"
    assert "cita_raw" not in blob


def test_no_fuga_documento_ni_origen(tmp_path):
    """Ruta absoluta y nombre del cliente no pueden aparecer."""
    c = commitment_de_constancia(_constancia_falsa(), documento=_doc_limpio(tmp_path))
    blob = json.dumps(c, ensure_ascii=False)
    assert "juan_perez" not in blob.lower(), "fuga: nombre en la ruta del documento"
    assert "Juan Pérez" not in blob, "fuga: nombre del cliente en origen"
    assert "/home/usuario" not in blob, "fuga: ruta absoluta"


def test_commitment_solo_incluye_normas_verificadas(tmp_path):
    """Un fallo no se disfraza de verificado."""
    c = commitment_de_constancia(_constancia_falsa(), documento=_doc_limpio(tmp_path))
    gids = [n["gid"] for n in c["normas_verificadas"]]
    assert gids == ["cl.norma.ct:art:0161", "cl.norma.ct:art:0039"]
    assert "cl.norma.ct:art:0999" not in gids


# ── GATE PII: fail-closed con PII + control positivo ─────────────────

def test_gate_pii_bloquea_rut_en_origen(tmp_path):
    """Con RUT en el origen NO se emite. Gemelo positivo arriba."""
    c = _constancia_falsa()
    c["meta"]["origen"] = "demanda de Juan Pérez, RUT 12.345.678-5"

    with pytest.raises(CommitmentPIIError) as exc:
        commitment_de_constancia(c, documento=_doc_limpio(tmp_path))
    # Detector de excepción: el motivo debe ser el nuestro, no cualquier error.
    assert "PII" in str(exc.value)
    assert "origen" in str(exc.value) or "documento" in str(exc.value)


def test_gate_pii_bloquea_email(tmp_path):
    """El path de meta['documento'] con email bloquea.

    El argumento `documento=` es el archivo local a hashear y sobreescribiría
    ese campo — por eso el caso va en meta (bug real detectado por este test).
    """
    c = _constancia_falsa()
    c["meta"]["documento"] = "/tmp/contacto/juan@example.com/demanda.md"

    with pytest.raises(CommitmentPIIError):
        commitment_de_constancia(c, documento=_doc_limpio(tmp_path))


def test_gate_pii_audita_argumento_tambien(tmp_path):
    """El argumento documento= también se audita, no solo meta['documento']."""
    c = _constancia_falsa()
    c["meta"]["documento"] = "/tmp/demanda.md"
    ruta_pii = tmp_path / "contacto-juan@example.com.md"
    ruta_pii.write_text("texto", encoding="utf-8")

    with pytest.raises(CommitmentPIIError):
        commitment_de_constancia(c, documento=str(ruta_pii))


def test_auditar_pii_detecta_y_no_crea_falsos_positivos_juridicos():
    """Control: 'DL 3500' y 'camino Procesal' se REPORTAN pero NO bloquean.

    El write gate los tolera a propósito (falsos positivos en léxico jurídico).
    El commitment se comporta igual: la auditoría los muestra, el gate los
    deja pasar.
    """
    texto = "art. 161 del DL 3500 y el camino Procesal"
    auditoría = auditar_pii({"documento": texto})
    # Se reporta (visible para auditoría)...
    assert auditoría.get("documento"), f"la auditoría debe mostrar: {auditoría}"
    # ...pero NO bloquea, porque no es PII de alta certeza.
    assert not _pii_bloqueante(auditoría), "DL 3500 / camino Procesal no deben bloquear"

    sucio = auditar_pii({"origen": "RUT 12.345.678-5"})
    assert sucio["origen"].get("rut", 0) >= 1
    assert _pii_bloqueante(sucio)["origen"].get("rut", 0) >= 1


def test_hash_estable():
    c1 = {"a": 1, "b": 2}
    c2 = {"b": 2, "a": 1}
    assert commitment_hash(c1) == commitment_hash(c2)


def test_escribir_commitment_devuelve_hash(tmp_path):
    c = commitment_de_constancia(_constancia_falsa())
    destino = tmp_path / "sub" / "commitment.json"
    h = escribir_commitment(c, destino)
    escrito = json.loads(destino.read_text(encoding="utf-8"))
    assert escrito["pack_hash"] == "ea28fa1c0f9af6c1"
    assert len(h) == 64
    assert h == commitment_hash(escrito), "el hash devuelto no es el del archivo escrito"


# ═════════════════════════════════════════════════════════════════════════
# REMEDIACIÓN 2 (2026-10-05) — P2, P3, P4 y los mutantes M09 y M10
# ═════════════════════════════════════════════════════════════════════════


def _escrito(tmp_path: Path) -> tuple[str, str]:
    """Un escrito en disco y su SHA-256 real."""
    p = tmp_path / "escrito.md"
    p.write_text("PRIMERO.- texto del escrito, sin datos personales.", encoding="utf-8")
    return str(p), hashlib.sha256(p.read_bytes()).hexdigest()


# ── M09: la versión pública omite la huella y no toca el original ──

def test_compromiso_publico_omite_la_huella_y_no_muta(tmp_path):
    ruta, sha = _escrito(tmp_path)
    c = commitment_de_constancia(_constancia_falsa(), documento=ruta)
    assert c["document_sha256"] == sha, "control: el commitment interno sí trae la huella"
    antes = copy.deepcopy(c)

    pub = compromiso_publico(c)

    assert "document_sha256" not in pub and "document_bytes" not in pub
    assert sha not in json.dumps(pub, ensure_ascii=False)
    assert c == antes, "compromiso_publico mutó el original"
    assert pub["normas_verificadas"] == c["normas_verificadas"]


# ── M10, P2: escribir sin argumentos NO publica la huella ──

def test_escribir_por_defecto_no_publica_la_huella(tmp_path):
    ruta, sha = _escrito(tmp_path)
    c = commitment_de_constancia(_constancia_falsa(), documento=ruta)
    destino = tmp_path / "commitment.json"

    with warnings.catch_warnings():
        warnings.simplefilter("error")  # el modo público no advierte nada
        escribir_commitment(c, destino)

    assert sha not in destino.read_text(encoding="utf-8")
    assert "document_sha256" not in json.loads(destino.read_text(encoding="utf-8"))


def test_escribir_con_publico_true_no_publica_la_huella(tmp_path):
    ruta, sha = _escrito(tmp_path)
    c = commitment_de_constancia(_constancia_falsa(), documento=ruta)
    destino = tmp_path / "commitment.json"
    escribir_commitment(c, destino, publico=True)
    assert sha not in destino.read_text(encoding="utf-8")


def test_escribir_la_huella_exige_opt_in_y_advierte(tmp_path):
    ruta, sha = _escrito(tmp_path)
    c = commitment_de_constancia(_constancia_falsa(), documento=ruta)
    destino = tmp_path / "interno.json"
    with pytest.warns(HuellaPublicadaWarning):
        escribir_commitment(c, destino, publico=False)
    assert sha in destino.read_text(encoding="utf-8"), "control: con opt-in la huella sí se escribe"


# ── P3: un dict armado a mano no elude la invariante ──

def _publico_limpio() -> dict:
    return compromiso_publico(commitment_de_constancia(_constancia_falsa()))


def test_control_positivo_el_compromiso_del_constructor_es_publicable():
    validar_publicable(_publico_limpio())


@pytest.mark.parametrize("clave", [
    "documento", "origen", "cita_raw", "problemas", "detalles",
    # Variantes que una lista negra no ve (reauditoría, q5-f):
    "Origen", "origen ", "documento_path", "cualquier_campo_nuevo",
])
def test_compromiso_publico_rechaza_campos_fuera_del_esquema(clave):
    manual = dict(_publico_limpio(), **{clave: "demanda de Juan Pérez"})
    with pytest.raises(CommitmentPIIError):
        compromiso_publico(manual)
    with pytest.raises(CommitmentPIIError):
        validar_publicable(manual)


def test_compromiso_publico_rechaza_campo_extra_dentro_de_una_norma():
    manual = _publico_limpio()
    manual["normas_verificadas"] = [dict(manual["normas_verificadas"][0], cita_raw="artículo 161 impone")] + manual["normas_verificadas"][1:]
    with pytest.raises(CommitmentPIIError):
        compromiso_publico(manual)


def test_escribir_rechaza_dict_manual_y_no_deja_archivo(tmp_path):
    manual = dict(_publico_limpio(), origen="demanda de Juan Pérez")
    destino = tmp_path / "commitment.json"
    with pytest.raises(CommitmentPIIError):
        escribir_commitment(manual, destino)
    assert not destino.exists()


# ── P4: lo que SÍ se publica también pasa por el gate de PII ──

@pytest.mark.parametrize("donde", ["alcance", "advertencias", "cuerpo"])
def test_pii_en_un_campo_publicado_bloquea(donde):
    r = _constancia_falsa()
    if donde == "alcance":
        r["alcance"] = "Acredita la demanda de RUT 12.345.678-5."
    elif donde == "advertencias":
        r["citation_disclosure"]["advertencias"] = ["escribir a juan@example.com"]
    else:
        r["detalles"][0]["cuerpo"] = "Código del Trabajo art. 161, contacto +56 9 1234 5678"
    with pytest.raises(CommitmentPIIError) as exc:
        commitment_de_constancia(r)
    # El mensaje nombra el campo, nunca el dato.
    assert "12.345.678" not in str(exc.value) and "juan@" not in str(exc.value)


def test_lexico_juridico_en_un_campo_publicado_no_bloquea():
    r = _constancia_falsa()
    r["alcance"] = "art. 161 del DL 3500 y el camino Procesal"
    assert commitment_de_constancia(r)["alcance"].startswith("art. 161")


def test_hashes_urls_y_fechas_no_dan_falsos_positivos():
    """Medición pedida antes de volver bloqueante el gate: los campos
    estructurados (hex de 64, URL de BCN, fechas ISO, gid) no parecen PII."""
    base = _publico_limpio()
    norma = base["normas_verificadas"][0]
    for i in range(3000):
        h = hashlib.sha256(str(i).encode()).hexdigest()
        candidato = dict(
            base,
            pack_hash=h[:16],
            fecha_constancia=f"2026-10-{1 + i % 28:02d}T09:{i % 60:02d}:5{i % 10}Z",
            normas_verificadas=[dict(
                norma, texto_hash=h, gid=f"cl.norma.ct:art:{i:04d}",
                fuente_url=f"https://nuevo.leychile.cl/servicios/Navegar/get_norma_json?idNorma={200000 + i}",
            )],
            citas_verificadas=1, total_citas=1, citas_fallidas=0,
        )
        validar_publicable(candidato)  # no lanza


# ── Conteos derivados, no copiados ──

def test_constructor_rechaza_conteos_que_no_cuadran():
    r = _constancia_falsa()
    r["meta"]["citas_verificadas"] = 99
    with pytest.raises(CommitmentIncoherenteError):
        commitment_de_constancia(r)


def test_constructor_cuadra_los_conteos_con_las_normas():
    c = commitment_de_constancia(_constancia_falsa())
    assert c["citas_verificadas"] == len(c["normas_verificadas"]) == 2
    assert c["total_citas"] == 3 and c["citas_fallidas"] == 1


def test_validar_rechaza_conteo_declarado_sin_normas():
    manual = dict(_publico_limpio(), citas_verificadas=99)
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(manual)


def test_validar_rechaza_norma_que_no_esta_verificada():
    manual = _publico_limpio()
    manual["normas_verificadas"] = [dict(manual["normas_verificadas"][0], estado="FALLO")] + manual["normas_verificadas"][1:]
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(manual)


def test_validar_rechaza_el_caracter_del():
    """DEL (U+007F) es lo único que jq y Python serializan distinto dentro de
    una cadena. Firmarlo daría un commitment legítimo que la receta sin Python
    no verifica."""
    validar_publicable(dict(_publico_limpio(), alcance="texto con salto\ny tab\t, sin DEL"))
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), alcance="texto con DEL \x7f"))
    manual = _publico_limpio()
    manual["normas_verificadas"] = [dict(manual["normas_verificadas"][0], cuerpo="art. 161\x7f")] + manual["normas_verificadas"][1:]
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(manual)


@pytest.mark.parametrize("campo,valor", [
    ("citas_verificadas", 2.0), ("total_citas", "3"), ("citas_fallidas", True),
    ("alcance", 1.5), ("advertencias", "una sola cadena"),
])
def test_validar_rechaza_tipos_inesperados(campo, valor):
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), **{campo: valor}))


# ═════════════════════════════════════════════════════════════════════════
# Reauditoría 2 (2026-10-06)
# ═════════════════════════════════════════════════════════════════════════

# ── H4: la puerta también exige. Antes acotaba (lista blanca) pero dejaba
# pasar un commitment al que le faltaba lo que lo hace decir algo. ──

def _norma(**cambios) -> dict:
    manual = _publico_limpio()
    manual["normas_verificadas"] = (
        [dict(manual["normas_verificadas"][0], **cambios)] + manual["normas_verificadas"][1:]
    )
    return manual


def _sin(campo: str) -> dict:
    manual = _publico_limpio()
    del manual[campo]
    return manual


@pytest.mark.parametrize("campo", [
    "schema_version", "pack_hash", "as_of", "fecha_constancia",
    "total_citas", "citas_verificadas", "citas_fallidas",
    "normas_verificadas", "alcance", "advertencias",
])
def test_validar_exige_cada_campo_obligatorio(campo):
    """Ausente, nulo o vacío: en los tres casos el commitment no dice lo que
    tendría que decir, y no se publica ni se firma."""
    validar_publicable(_publico_limpio())  # control
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(_sin(campo))
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), **{campo: None}))
    if campo not in ("total_citas", "citas_verificadas", "citas_fallidas", "normas_verificadas"):
        vacio = [] if campo == "advertencias" else ""
        with pytest.raises(CommitmentIncoherenteError):
            validar_publicable(dict(_publico_limpio(), **{campo: vacio}))


@pytest.mark.parametrize("valor", [
    "sin-corpus", "sin-manifest", "varios-corpus",       # las etiquetas de reserva del CLI
    "EA28FA1C0F9AF6C1", "ea28fa1c0f9af6c", "ea28fa1c0f9af6c12", "ea28fa1c0f9af6c1\n", "zzzzzzzzzzzzzzzz",
])
def test_validar_exige_pack_hash_de_16_hexadecimales(valor):
    """Un commitment con `pack_hash: sin-corpus` no dice contra qué corpus se
    verificó. El CLI llegaba a firmarlo."""
    assert _publico_limpio()["pack_hash"] == "ea28fa1c0f9af6c1", "control: el bueno son 16 hex"
    with pytest.raises(CommitmentIncoherenteError) as exc:
        validar_publicable(dict(_publico_limpio(), pack_hash=valor))
    assert "pack_hash" in str(exc.value)


def test_validar_exige_el_schema_version_de_este_modulo():
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), schema_version="cualquier-cosa"))
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), schema_version="dike-constancia-commitment-v1"))


@pytest.mark.parametrize("campo,valor", [
    ("as_of", "05-10-2026"), ("as_of", "2026-10-05T00:00:00Z"), ("as_of", "hoy"),
    ("fecha_constancia", "2026-10-05"), ("fecha_constancia", "2026-10-05T09:17:55"),
    ("fecha_constancia", "2026-10-05T09:17:55+00:00"), ("fecha_constancia", "2026-10-05T09:17:55Z\n"),
])
def test_validar_exige_el_formato_de_las_fechas(campo, valor):
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), **{campo: valor}))


def test_validar_rechaza_conteos_negativos():
    """fallidas=-1 y total=1 cuadran con 2 verificadas, y no significan nada."""
    base = _publico_limpio()
    assert (base["total_citas"], base["citas_verificadas"], base["citas_fallidas"]) == (3, 2, 1)
    with pytest.raises(CommitmentIncoherenteError) as exc:
        validar_publicable(dict(base, citas_fallidas=-1, total_citas=1))
    assert "negativo" in str(exc.value)


def test_validar_rechaza_conteos_de_mas_de_15_digitos():
    """Un entero de 16 dígitos no lo conserva exacto un lector de doble
    precisión (jq antes de 1.7): el commitment sería legítimo y la receta sin
    Python no lo verificaría."""
    base = _publico_limpio()
    assert base["citas_verificadas"] == 2
    validar_publicable(dict(base, citas_fallidas=10**15 - 3, total_citas=10**15 - 1))  # 15 dígitos: pasa
    with pytest.raises(CommitmentIncoherenteError) as exc:
        validar_publicable(dict(base, citas_fallidas=10**15 - 2, total_citas=10**15))
    assert "total_citas no cabe en 15 dígitos" in str(exc.value)


def test_validar_rechaza_verificadas_que_no_son_las_normas_aunque_el_total_cuadre():
    """Mutante M23. 3 verificadas + 0 fallidas = 3, y el total cuadra; pero
    las normas listadas son dos. Desde que el total es obligatorio, un conteo
    inflado solía caer por el total y esta comprobación quedaba sin test propio."""
    base = _publico_limpio()
    assert len(base["normas_verificadas"]) == 2 and base["total_citas"] == 3
    with pytest.raises(CommitmentIncoherenteError) as exc:
        validar_publicable(dict(base, citas_verificadas=3, citas_fallidas=0))
    assert "citas_verificadas" in str(exc.value)


def test_validar_rechaza_un_total_que_no_cuadra():
    """H5, mutante X06: nada fijaba que total == verificadas + fallidas."""
    with pytest.raises(CommitmentIncoherenteError) as exc:
        validar_publicable(dict(_publico_limpio(), total_citas=99))
    assert "total_citas" in str(exc.value)
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(dict(_publico_limpio(), citas_fallidas=0))


@pytest.mark.parametrize("campo", ["gid", "vigencia", "texto_hash", "fuente_url", "estado"])
def test_validar_exige_lo_que_identifica_a_cada_norma(campo):
    """Una norma que solo dice `estado: VERIFICADA` no dice cuál es ni contra
    qué texto se verificó."""
    validar_publicable(_norma())  # control
    sin = _publico_limpio()
    sin["normas_verificadas"] = [
        {k: v for k, v in sin["normas_verificadas"][0].items() if k != campo}
    ] + sin["normas_verificadas"][1:]
    for manual in (sin, _norma(**{campo: None}), _norma(**{campo: ""})):
        with pytest.raises(CommitmentIncoherenteError):
            validar_publicable(manual)


@pytest.mark.parametrize("valor", ["a" * 63, "a" * 65, "A" * 64, "g" * 64, "a" * 64 + "\n"])
def test_validar_exige_que_el_texto_hash_sea_un_sha256(valor):
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(_norma(texto_hash=valor))


@pytest.mark.parametrize("campo,valor", [
    ("gid", 161), ("texto_hash", 1.5), ("cuerpo", ["Código del Trabajo"]),
    ("fuente_url", {"url": "https://ejemplo/1"}), ("vigencia", True),
])
def test_validar_rechaza_tipos_inesperados_dentro_de_una_norma(campo, valor):
    """H5, mutante X05: los campos de una norma admitían cualquier tipo sin
    que ningún test lo notara."""
    with pytest.raises(CommitmentIncoherenteError):
        validar_publicable(_norma(**{campo: valor}))


def test_validar_admite_la_misma_norma_citada_dos_veces():
    """Límite declarado, no un descuido: los conteos son de CITAS. Un escrito
    que cita dos veces el artículo 161 lo lista dos veces."""
    base = _publico_limpio()
    repetida = dict(
        base, normas_verificadas=[base["normas_verificadas"][0]] * 2,
        citas_verificadas=2, total_citas=3, citas_fallidas=1,
    )
    validar_publicable(repetida)  # no lanza


# ── H5, mutante X14: escribir con la huella también pasa por la puerta ──

def test_escribir_con_huella_tambien_valida_y_no_deja_archivo(tmp_path):
    """`escribir_commitment(publico=False)` es el camino del opt-in. Sin la
    validación, por ahí salía a disco un dict con `origen` y un nombre."""
    manual = dict(_publico_limpio(), origen="demanda de Juan Pérez")
    destino = tmp_path / "commitment.json"
    with pytest.raises(CommitmentPIIError):
        escribir_commitment(manual, destino, publico=False)
    assert not destino.exists()
    with pytest.raises(CommitmentIncoherenteError):
        escribir_commitment(dict(_publico_limpio(), pack_hash="sin-corpus"), destino, publico=False)
    assert not destino.exists()
    # Control: uno limpio sí se escribe por ese mismo camino.
    escribir_commitment(_publico_limpio(), destino, publico=False)
    assert json.loads(destino.read_text(encoding="utf-8"))["pack_hash"] == "ea28fa1c0f9af6c1"
