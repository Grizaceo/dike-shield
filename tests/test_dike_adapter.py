"""Observed Diké constancia cases: 2 VERIFICADA, 1 AMBIGUOUS, 1 UNRESOLVABLE."""

from __future__ import annotations

from pathlib import Path

from shield.cuerpos import CANONICAL_NAMES, canonicalize
from shield.dike_adapter import verificar

SYNTHETIC = """Escrito sintético de prueba.

Según el artículo 161 del Código del Trabajo, el contrato puede terminar
por las necesidades de la empresa. El trabajador puede reclamar conforme
al artículo 168 del Código del Trabajo.

El artículo 60 no identifica cuerpo. Cita inventada: artículo 9999 del Código del Trabajo.
"""


def test_cuerpos_has_twenty_five_canonical_names() -> None:
    assert len(CANONICAL_NAMES) == 25
    assert canonicalize("Código del Trabajo") == "Código del Trabajo"
    assert canonicalize("codigo del trabajo") == "Código del Trabajo"
    assert canonicalize("ct") == "Código del Trabajo"
    assert canonicalize("no-es-un-cuerpo") is None


def test_constancia_two_verified_ambiguous_unresolvable() -> None:
    lexo = Path.home() / ".lexo"
    before = lexo.stat().st_mtime if lexo.exists() else None
    result = verificar(SYNTHETIC)
    after = lexo.stat().st_mtime if lexo.exists() else None
    if before is not None:
        assert after == before

    detalles = result.get("detalles") or []
    by_raw = {
        d.get("cita_raw"): d
        for d in detalles
        if isinstance(d, dict)
    }

    art161 = by_raw.get("artículo 161 del Código del Trabajo")
    art168 = by_raw.get("artículo 168 del Código del Trabajo")
    art60 = by_raw.get("artículo 60")
    art9999 = by_raw.get("artículo 9999 del Código del Trabajo")
    assert art161 and art168 and art60 and art9999

    assert art161["estado"] == "VERIFICADA"
    assert art161["resolucion"] == "RESOLVED"
    assert art161["gid"] == "cl.norma.ct:art:0161"

    assert art168["estado"] == "VERIFICADA"
    assert art168["resolucion"] == "RESOLVED"
    assert art168["gid"] == "cl.norma.ct:art:0168"

    assert art60["estado"] == "FALLO"
    assert art60["resolucion"] == "AMBIGUOUS"

    assert art9999["estado"] == "FALLO"
    assert art9999["resolucion"] == "UNRESOLVABLE"

    estados = [d.get("estado") for d in (art161, art168, art60, art9999)]
    assert estados.count("VERIFICADA") == 2
    assert {art60["resolucion"], art9999["resolucion"]} == {"AMBIGUOUS", "UNRESOLVABLE"}
