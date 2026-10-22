"""El demo del hackathon termina en la abstención (F3 de la remediación 2).

El demo anterior verificaba 4 de 4 y cerraba mostrando un hash. Peor: su
escrito atribuía al art. 163 «el recurso de casación en el fondo» y al 161 «la
estabilidad en el empleo», y las dos salían VERIFICADA, porque Diké no verifica
la atribución. Aquí se fija lo contrario: el demo tiene que mostrar dos citas
rechazadas, con su motivo, y probar que no están en el commitment firmado.

Corre el motor REAL contra el corpus instalado. Sin corpus se salta, con el
motivo a la vista; no simula.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CARPETA = REPO / "docs" / "hackathon"
DEMO = CARPETA / "demo_bli_e2e.py"
ESCRITO = CARPETA / "escrito_demo.md"
VERIFICADOR = CARPETA / "verificar_tercero.py"


def _entorno() -> dict[str, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    env.pop("LEXO_CONTENT_SIGNING_KEY_PATH", None)  # el demo no hereda ninguna llave
    return env


def _exigir_corpus() -> None:
    from lexo_cli.config import load_config
    from lexo_cli.nif_studio.execution import canonical_resolver_for

    try:
        resolver, error = canonical_resolver_for(load_config())
    except Exception as exc:  # noqa: BLE001 — cualquier fallo aquí es «no hay corpus utilizable»
        pytest.skip(f"no se pudo abrir el corpus canónico ({type(exc).__name__}): el demo necesita el motor real")
    if resolver is None:
        pytest.skip(f"no hay corpus canónico instalado ({error}): el demo necesita el motor real")


def _bajo_docs() -> set[str]:
    return {str(p.relative_to(CARPETA)) for p in CARPETA.rglob("*") if "__pycache__" not in p.parts}


@pytest.fixture(scope="module")
def corrida(tmp_path_factory):
    _exigir_corpus()
    out = tmp_path_factory.mktemp("demo") / "salida"
    antes = _bajo_docs()
    r = subprocess.run(
        [sys.executable, str(DEMO), "--out", str(out)],
        capture_output=True, text=True, timeout=900, env=_entorno(), cwd=str(REPO),
    )
    return r, out, antes


def test_el_demo_sale_0(corrida):
    r, _out, _ = corrida
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-1500:]


def test_el_commitment_del_demo_trae_cuatro_verificadas_y_dos_fallidas(corrida):
    _r, out, _ = corrida
    texto = (out / "kit" / "commitment.json").read_text(encoding="utf-8")
    c = json.loads(texto)
    assert c["citas_fallidas"] == 2 and c["citas_verificadas"] == 4 and c["total_citas"] == 6
    assert [n["gid"] for n in c["normas_verificadas"]] == [
        "cl.norma.ct:art:0161", "cl.norma.ct:art:0162", "cl.norma.ct:art:0163", "cl.norma.ct:art:0168",
    ]
    # Aceptación de F3: ni «9999» ni «artículo 60» aparecen en el commitment.
    assert "9999" not in texto and "artículo 60" not in texto
    assert "document_sha256" not in c and "origen" not in c and str(out) not in texto


def test_el_demo_termina_en_la_abstencion_no_en_el_hash(corrida):
    r, _out, _ = corrida
    salida = r.stdout
    inicio = salida.index("LO QUE DIKÉ SE NEGÓ A CERTIFICAR")
    assert salida.index("[5/5]") < inicio, "la abstención tiene que ser lo último, después del control negativo"
    final = salida[inicio:]
    assert "«artículo 60»" in final and "AMBIGUOUS" in final
    assert "«artículo 9999 del Código del Trabajo»" in final and "UNRESOLVABLE" in final
    assert "citas_fallidas = 2" in final
    # Después de la abstención no viene ningún hash ni otro paso.
    assert not re.search(r"[0-9a-f]{64}", final) and "[" not in final.replace("[5/5]", "")


def test_el_control_negativo_es_estricto(corrida):
    r, out, _ = corrida
    tramo = r.stdout[r.stdout.index("[5/5]"):r.stdout.index("LO QUE DIKÉ SE NEGÓ A CERTIFICAR")]
    assert "exit 1" in tramo and "NO COINCIDE" in tramo
    # Y se reproduce fuera del demo, con el verificador de tercero.
    def tercero(carpeta: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(VERIFICADOR), "commitment.json", "commitment.sig.json", "content-signing-key.pub"],
            capture_output=True, text=True, cwd=str(carpeta), timeout=60,
        )
    assert tercero(out / "kit").returncode == 0
    n = tercero(out / "alterado")
    assert n.returncode == 1 and "NO COINCIDE" in n.stdout


def test_el_demo_dice_que_llave_uso_y_no_deja_nada_bajo_docs(corrida):
    r, out, antes = corrida
    assert "llave SINTÉTICA" in r.stdout and "no es la clave publicada" in r.stdout
    llave = out / "llave-sintetica" / "content-signing-key.pem"
    assert llave.is_file() and (llave.stat().st_mode & 0o777) == 0o600
    sobre = json.loads((out / "kit" / "commitment.sig.json").read_text(encoding="utf-8"))
    assert sobre["key_id"] in r.stdout
    assert sobre["key_id"] != "3c7b3fde075efbe3", "el demo firmó con la llave publicada"
    assert _bajo_docs() == antes, "el demo escribió bajo docs/hackathon"


def test_el_demo_no_escribe_sobre_una_carpeta_con_contenido(tmp_path):
    ocupada = tmp_path / "ocupada"
    ocupada.mkdir()
    (ocupada / "algo.txt").write_text("no tocar", encoding="utf-8")
    r = subprocess.run(
        [sys.executable, str(DEMO), "--out", str(ocupada)],
        capture_output=True, text=True, timeout=120, env=_entorno(), cwd=str(REPO),
    )
    assert r.returncode == 1 and "DEMO FALLIDO" in r.stdout
    assert [p.name for p in ocupada.iterdir()] == ["algo.txt"]


# ── El escrito no atribuye de memoria ────────────────────────────────────

#: artículo -> frases del ESCRITO que tienen que estar en el texto del artículo.
_ANCLAS = {
    "161": ["necesidades de la empresa"],
    "162": ["el aviso deberá darse al trabajador, con copia a la Inspección del Trabajo respectiva, "
            "a lo menos con treinta días de anticipación"],
    # El caché de BCN intercala notas al margen en el texto («hubiere estado
    # L. 19.010 Art. 5º vigente…»): las anclas se eligen entre nota y nota.
    "163": ["vigente un año o más y el empleador le pusiere término", "por años de servicio"],
    "168": ["recurrir al juzgado competente", "sesenta días hábiles", "improcedente"],
}
#: Lo que decía el escrito anterior (J3). No está en esos artículos.
_ATRIBUCIONES_FALSAS = {"163": "casación en el fondo", "161": "estabilidad en el empleo"}


def _plano(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip().lower()


def _articulos_del_codigo_del_trabajo() -> dict[str, str] | None:
    candidatos = []
    if os.environ.get("LEXO_BCN_CACHE_DIR"):
        candidatos.append(Path(os.environ["LEXO_BCN_CACHE_DIR"]))
    candidatos.append(
        Path.home() / ".hermes" / "workspaces" / "lexo" / "Vault" / "Lexo" / "Vigente" / "Ley_General" / "_bcn_cache"
    )
    cache = next((d / "norma_207436.json" for d in candidatos if (d / "norma_207436.json").is_file()), None)
    if cache is None:
        return None
    textos: dict[str, str] = {}

    def recorrer(nodo) -> None:
        if isinstance(nodo, dict):
            t = nodo.get("t")
            if isinstance(t, str) and len(t) > 100:
                limpio = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(t)))).strip()
                m = re.match(r"Art\. (\d+)\.", limpio)
                if m:
                    textos.setdefault(m.group(1), limpio)
            for v in nodo.values():
                recorrer(v)
        elif isinstance(nodo, list):
            for v in nodo:
                recorrer(v)

    recorrer(json.loads(cache.read_text(encoding="utf-8")))
    return textos


def test_las_atribuciones_del_escrito_estan_en_el_texto_de_cada_articulo():
    """Cotejo mecánico contra el caché local de BCN. No reemplaza la revisión
    de un abogado: comprueba que las frases del escrito son las del artículo."""
    articulos = _articulos_del_codigo_del_trabajo()
    if articulos is None:
        pytest.skip("no está el caché local de BCN (norma_207436.json): no se puede cotejar el escrito del demo")
    escrito = _plano(ESCRITO.read_text(encoding="utf-8"))
    for numero, frases in _ANCLAS.items():
        assert numero in articulos, f"el caché no trae el art. {numero}"
        articulo = _plano(articulos[numero])
        for frase in frases:
            assert _plano(frase) in escrito, f"el escrito ya no dice «{frase}»: actualizar las anclas"
            assert _plano(frase) in articulo, f"art. {numero}: «{frase}» no está en su texto"
    # Control: las atribuciones del escrito anterior no pasan este mismo cotejo.
    for numero, frase in _ATRIBUCIONES_FALSAS.items():
        assert _plano(frase) not in _plano(articulos[numero])
        assert _plano(frase) not in escrito
