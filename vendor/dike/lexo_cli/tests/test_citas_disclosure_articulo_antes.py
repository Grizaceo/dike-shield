"""Reauditoría 2 (H6): el artículo que va ANTES del nombre de la norma.

`_menciones_sin_verbatim` buscaba el artículo después de la mención («la Ley
21.719 en su art. 5»). En un escrito chileno va antes («artículo 161 del
Código del Trabajo»), así que marcaba «Código» siempre, y toda constancia
llevaba la advertencia «el texto menciona normas sin artículo pinpoint»
aunque cada norma tuviera el suyo. La advertencia quedó dentro del ejemplo
firmado del kit.

La regla nueva es conservadora a propósito: una mención solo se da por
cubierta si el artículo está pegado delante Y cae dentro de una cita que el
gate extrajo. Los tests de abajo fijan los dos lados.
"""

from __future__ import annotations

from lexo_cli.citation_check import _menciones_sin_verbatim, citation_disclosure

ESCRITO = (
    "PRIMERO.- La demandada invocó la causal del artículo 161 del Código del Trabajo.\n"
    "SEGUNDO.- El artículo 162 del Código del Trabajo dispone que el aviso deberá darse.\n"
    "QUINTO.- A mayor abundamiento, el artículo 60 obliga al empleador.\n"
    "SEXTO.- Lo anterior se refuerza con el artículo 9999 del Código del Trabajo.\n"
)
REFERENCIAS = [
    {"raw": "artículo 161 del Código del Trabajo", "gid": "cl.norma.ct:art:0161", "supported": True},
    {"raw": "artículo 162 del Código del Trabajo dispone", "gid": "cl.norma.ct:art:0162", "supported": True},
    {"raw": "artículo 60", "gid": "", "supported": False},
    {"raw": "artículo 9999 del Código del Trabajo", "gid": "", "supported": False},
]
PINPOINT = "sin artículo pinpoint"


def _advierte(check: dict, texto: str) -> bool:
    return any(PINPOINT in a for a in citation_disclosure(check, texto)["advertencias"])


def test_el_articulo_antes_de_la_norma_no_se_declara_como_punto_ciego():
    assert _menciones_sin_verbatim(ESCRITO, REFERENCIAS) == []
    assert not _advierte({"references": REFERENCIAS, "supported": ["0161", "0162"]}, ESCRITO)


def test_sin_las_citas_del_gate_se_sigue_declarando():
    """Control: sin saber qué extrajo el gate no se da nada por cubierto. Es
    el comportamiento anterior, y es el que queda para quien llame sin citas."""
    assert _menciones_sin_verbatim(ESCRITO) == ["Código"]
    assert _menciones_sin_verbatim(ESCRITO, []) == ["Código"]
    assert _advierte({"references": [], "supported": []}, ESCRITO)


def test_una_norma_sin_articulo_junto_a_una_cita_se_sigue_declarando():
    texto = "Según la Ley 21.719, procede el artículo 161 del Código del Trabajo."
    refs = [{"raw": "artículo 161 del Código del Trabajo", "gid": "cl.norma.ct:art:0161", "supported": True}]
    assert _menciones_sin_verbatim(texto, refs) == ["Ley 21.719"]
    assert _advierte({"references": refs, "supported": ["0161"]}, texto)


def test_una_norma_que_cae_en_la_cola_de_una_cita_se_sigue_declarando():
    """El tramo que reconoce la gramática arrastra hasta dos palabras de la
    prosa que sigue. Una norma que quede ahí dentro no tiene el artículo
    pegado delante: no se da por cubierta."""
    texto = "Rige el artículo 161 del Código del Trabajo y Ley 21.719 en lo demás."
    refs = [{"raw": "artículo 161 del Código del Trabajo y Ley", "gid": "cl.norma.ct:art:0161", "supported": True}]
    assert _menciones_sin_verbatim(texto, refs) == ["Ley 21.719"]


def test_un_articulo_delante_que_el_gate_no_extrajo_no_cubre_la_mencion():
    """El artículo está pegado delante, pero el gate no reportó esa cita: ni
    verificada ni fallida. Sigue siendo un punto ciego."""
    texto = "Procede conforme al artículo 5 de la Ley 19.799."
    assert _menciones_sin_verbatim(texto, []) == ["Ley 19.799"]
    refs = [{"raw": "artículo 5 de la Ley 19.799", "gid": "", "supported": False}]
    assert _menciones_sin_verbatim(texto, refs) == []


def test_la_norma_que_aparece_sola_en_otro_parrafo_se_sigue_declarando():
    texto = ESCRITO + "SÉPTIMO.- Todo ello conforme al Código Civil.\n"
    assert _menciones_sin_verbatim(texto, REFERENCIAS) == ["Código"]


def test_el_orden_anterior_sigue_funcionando():
    assert _menciones_sin_verbatim("La Ley 21.719 en su art. 5 lo exige.") == []
    assert _menciones_sin_verbatim("El contrato se rige por la autonomía de la voluntad.") == []
