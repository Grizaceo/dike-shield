"""`docs/hackathon/KEYS.md` se ejecuta, no se lee.

El 2026-10-05 el documento traía una receta OpenSSL que fallaba sobre una firma
legítima por cuatro causas distintas, y nadie lo había notado porque nadie la
había corrido. Aquí cada bloque ```bash del documento se extrae y se ejecuta
LITERAL, en una carpeta temporal con artefactos sintéticos recién firmados.

Lo que este archivo exige:

  1. Cada bloque sale 0 sobre un kit legítimo, tal como está escrito.
  2. Con una variable alterada, falla.
  3. Los tres verificadores (API, `verificar_tercero.py`, receta OpenSSL) dan
     el mismo veredicto en cada caso.
  4. El test tiene dientes: si el documento verificara solo el hash, o si
     dejara de mirar el rol, este archivo lo nota.
  5. La tabla «afirmación → prueba» del documento apunta a tests que existen.

Si falta una herramienta (jq, openssl, basenc, bwrap), el test se SALTA con el
motivo a la vista. Nunca pasa en silencio.
"""

from __future__ import annotations

import ast
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

from lexo_cli.commitment import validar_publicable
from lexo_cli.mcp.lexo_legal_core.gates import detect_pii
from lexo_cli.tests._kit_commitment import (
    CARPETA_KIT,
    CASOS,
    CASOS_QUE_NO_VERIFICAN,
    CASOS_QUE_VERIFICAN,
    REPO,
    Kit,
    debe_verificar,
)

KEYS = CARPETA_KIT / "KEYS.md"
PUBKEY = CARPETA_KIT / "content-signing-key.pub"
EJEMPLO = (CARPETA_KIT / "commitment.json", CARPETA_KIT / "commitment.sig.json")
AVISO_PENDIENTE = "PENDIENTE ANTES DE PUBLICAR"
TESTS = Path(__file__).resolve().parent

#: Qué necesita cada bloque además de bash.
HERRAMIENTAS = {
    "camino1": (),
    "hash": (),
    "camino2": ("jq", "openssl", "sha256sum", "basenc", "mktemp", "sort", "cut", "tr", "tail", "sed", "grep", "wc"),
}
SALIDA_ESPERADA = {
    "camino1": "RESULTADO: VERIFICADO",
    "hash": "calculado:",
    "camino2": "Signature Verified Successfully",
}


# ── Extraer los bloques del documento ────────────────────────────────────


def _texto() -> str:
    return KEYS.read_text(encoding="utf-8")


def _bloques(texto: str) -> list[str]:
    return re.findall(r"^```bash\n(.*?)^```", texto, flags=re.DOTALL | re.MULTILINE)


def _clase(bloque: str) -> str:
    if "openssl pkeyutl" in bloque:
        return "camino2"
    if "verificar_tercero.py" in bloque:
        return "camino1"
    if "hashlib" in bloque:
        return "hash"
    return "desconocido"


def _bloque(clase: str, texto: str | None = None) -> str:
    encontrados = [b for b in _bloques(texto or _texto()) if _clase(b) == clase]
    assert len(encontrados) == 1, f"se esperaba un bloque {clase}, hay {len(encontrados)}"
    return encontrados[0]


def _exigir(clase: str) -> None:
    faltan = [h for h in ("bash", *HERRAMIENTAS[clase]) if shutil.which(h) is None]
    if faltan:
        pytest.skip(f"no se puede ejecutar el bloque «{clase}» de KEYS.md: falta {', '.join(faltan)}")


def _ejecutar(bloque: str, carpeta: Path) -> subprocess.CompletedProcess:
    """Corre el bloque tal cual, con `carpeta` como directorio de trabajo.

    Lo único que se prepara es que `python3` sea un intérprete con
    `cryptography`, que es el requisito que declara el documento.
    """
    apoyo = carpeta.parent / f"{carpeta.name}-apoyo"
    (apoyo / "bin").mkdir(parents=True, exist_ok=True)
    shim = apoyo / "bin" / "python3"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
    shim.chmod(0o755)
    guion = apoyo / "bloque.sh"
    guion.write_text(bloque, encoding="utf-8")
    env = dict(os.environ, PATH=f"{apoyo / 'bin'}{os.pathsep}{os.environ['PATH']}")
    return subprocess.run(
        ["bash", str(guion)], cwd=str(carpeta), env=env,
        capture_output=True, text=True, timeout=120,
    )


@pytest.fixture
def kit(tmp_path) -> Kit:
    return Kit(tmp_path / "kit")


# ── 1. Cada bloque, literal ──────────────────────────────────────────────


def test_todo_bloque_bash_esta_clasificado():
    """Un bloque bash nuevo que nadie ejecuta sería otra receta sin probar."""
    clases = sorted(_clase(b) for b in _bloques(_texto()))
    assert clases == ["camino1", "camino2", "hash"], clases


@pytest.mark.parametrize("clase", ["camino1", "camino2", "hash"])
def test_cada_bloque_se_ejecuta_literal(kit, clase):
    _exigir(clase)
    r = _ejecutar(_bloque(clase), kit.raiz)
    assert r.returncode == 0, f"{clase} falló sobre un kit legítimo:\n{r.stdout}\n{r.stderr}"
    assert SALIDA_ESPERADA[clase] in r.stdout + r.stderr
    if clase != "hash":
        assert kit.key_id in r.stdout, "el camino no imprime el key_id"
    # No deja basura en la carpeta del kit.
    assert sorted(p.name for p in kit.raiz.iterdir()) == [
        "commitment.json", "commitment.sig.json", "content-signing-key.pub", "verificar_tercero.py",
    ]


# ── 2. Una variable alterada hace fallar ─────────────────────────────────


@pytest.mark.parametrize("clase", ["camino1", "camino2"])
@pytest.mark.parametrize("caso", sorted(CASOS_QUE_NO_VERIFICAN))
def test_un_cambio_hace_fallar_los_dos_caminos(kit, clase, caso):
    _exigir(clase)
    bloque = _bloque(clase)
    assert _ejecutar(bloque, kit.raiz).returncode == 0, "control positivo"
    CASOS[caso](kit)
    r = _ejecutar(bloque, kit.raiz)
    assert r.returncode != 0, f"{clase} aceptó el caso «{caso}»:\n{r.stdout}"
    assert SALIDA_ESPERADA[clase] not in r.stdout + r.stderr


@pytest.mark.parametrize("caso", ["commitment_alterado", "duplicado_en_commitment"])
def test_el_bloque_del_hash_nota_el_cambio(kit, caso):
    _exigir("hash")
    bloque = _bloque("hash")
    assert _ejecutar(bloque, kit.raiz).returncode == 0, "control positivo"
    CASOS[caso](kit)
    assert _ejecutar(bloque, kit.raiz).returncode != 0


def test_el_bloque_del_hash_no_ve_un_sobre_reetiquetado(kit):
    """El documento dice que comparar hashes «no prueba nada por sí solo».
    Es cierto: un sobre con el rol cambiado pasa el bloque del hash y solo lo
    detienen los dos caminos completos."""
    _exigir("hash")
    _exigir("camino1")
    CASOS["rol_ajeno"](kit)
    assert _ejecutar(_bloque("hash"), kit.raiz).returncode == 0
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode != 0


# ── 3. Los tres verificadores coinciden ──────────────────────────────────


@pytest.mark.parametrize("caso", sorted(CASOS))
def test_los_tres_verificadores_coinciden(kit, caso):
    _exigir("camino2")
    CASOS[caso](kit)
    veredictos = {
        "API de lexo_cli": kit.veredicto_api(),
        "verificar_tercero.py": _ejecutar(_bloque("camino1"), kit.raiz).returncode == 0,
        "receta OpenSSL": _ejecutar(_bloque("camino2"), kit.raiz).returncode == 0,
    }
    assert len(set(veredictos.values())) == 1, f"{caso}: discrepan {veredictos}"
    assert veredictos["receta OpenSSL"] == debe_verificar(caso)


@pytest.mark.parametrize("clase", ["camino1", "camino2"])
@pytest.mark.parametrize("caso", sorted(CASOS_QUE_VERIFICAN))
def test_un_cambio_de_forma_no_hace_fallar_ningun_camino(kit, clase, caso):
    """Reordenar, reindentar, un BOM, CRLF o un escape equivalente no cambian
    el contenido: los dos caminos siguen verificando."""
    _exigir(clase)
    CASOS_QUE_VERIFICAN[caso](kit)
    r = _ejecutar(_bloque(clase), kit.raiz)
    assert r.returncode == 0, f"{clase} rechazó el caso «{caso}»:\n{r.stdout}\n{r.stderr}"


# ── 4. El test tiene dientes ─────────────────────────────────────────────

_BYTES_V2 = '"content-integrity:ed25519:dike-content-signature-v2:$H"'


def test_si_la_receta_verificara_solo_el_hash_se_nota(kit):
    """Aceptación de F2. Se reescribe el documento para que firme solo el
    `commitment_hash` (lo que decía antes) y se le pasa el mismo arnés: sobre
    una firma legítima, el bloque deja de salir 0."""
    _exigir("camino2")
    texto = _texto()
    assert texto.count(_BYTES_V2) == 1, "el ancla de los bytes firmados cambió"
    mutado = _bloque("camino2", texto.replace(_BYTES_V2, '"$H"'))

    assert _ejecutar(_bloque("camino2"), kit.raiz).returncode == 0, "control: el documento real pasa"
    r = _ejecutar(mutado, kit.raiz)
    assert r.returncode != 0, "una receta que verifica solo el hash pasó el test del documento"
    assert "Signature Verification Failure" in r.stdout + r.stderr


def test_si_la_receta_no_mirara_el_contrato_un_rol_ajeno_pasaria(kit):
    """El paso 1 no es decorativo. La receta arma los bytes con el rol fijo;
    sin comparar los campos del sobre, uno re-etiquetado como `authorization`
    saldría verificado."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    sin_contrato = _sin(bloque, _CONTROL_CONTRATO, "el control del contrato")

    CASOS["rol_ajeno"](kit)
    assert _ejecutar(bloque, kit.raiz).returncode != 0, "el documento real lo rechaza"
    assert _ejecutar(sin_contrato, kit.raiz).returncode == 0, (
        "sin el control del contrato debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


# Reauditoría 2 (H1 y H2). Cada control nuevo de la receta se quita, uno a la
# vez, y se comprueba que el caso que detenía vuelve a verificar. Si un control
# se puede quitar sin que nada cambie, sobra o el test no lo ejerce.

_CONTROL_CONTRATO = re.compile(
    r"jq -e '\.schema_version==.*?\n  \|\| \{ echo \"FALLA: schema_version.*?\n", flags=re.DOTALL)
_CONTROL_FORMA_DEL_SOBRE = re.compile(
    r"jq -e '\(keys == .*?\n  \|\| \{ echo \"FALLA: el sobre no tiene exactamente.*?\n", flags=re.DOTALL)
_CONTROL_UN_SOLO_OBJETO = re.compile(
    r"  jq -es 'length==1.*?\n    \|\| \{ echo \"FALLA: \$f no es un único objeto JSON.*?\n", flags=re.DOTALL)
_CONTROL_CLAVE_CANONICA = re.compile(
    r"tr -d '\\r' < \"\$K\".*?\n  \|\| \{ echo \"FALLA: \$K no es una clave pública PEM.*?\n", flags=re.DOTALL)


def _sin(bloque: str, control: re.Pattern, nombre: str) -> str:
    encontrados = control.findall(bloque)
    assert len(encontrados) == 1, f"no se encontró {nombre} en la receta (o aparece {len(encontrados)} veces)"
    return bloque.replace(encontrados[0], "")


@pytest.mark.parametrize("caso", [
    "campo_de_mas_en_el_sobre", "firma_con_salto_final", "firma_con_salto_en_medio",
    "key_id_con_salto_final", "hash_con_salto_final", "key_id_con_nul_en_medio",
])
def test_si_la_receta_no_mirara_la_forma_del_sobre_esto_pasaria(kit, caso):
    """La receta exige seis campos exactos y la forma de cada valor. Sin eso,
    un campo que nadie firmó verifica, y también una firma, un `key_id` o un
    hash con un salto de línea o un byte nulo pegados."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    sin_forma = _sin(bloque, _CONTROL_FORMA_DEL_SOBRE, "el control de la forma del sobre")
    # Así comparaba la receta antes: en el shell, que quita los saltos finales
    # y descarta los bytes nulos.
    for dentro_de_jq, en_el_shell in (
        ('jq -e --arg h "$H" \'.commitment_hash==$h\' "$S" >/dev/null', '[ "$H" = "$(jq -r .commitment_hash "$S")" ]'),
        ('jq -e --arg k "$KID" \'.key_id==$k\' "$S" >/dev/null', '[ "$KID" = "$(jq -r .key_id "$S")" ]'),
    ):
        assert sin_forma.count(dentro_de_jq) == 1, "la receta ya no compara dentro de jq"
        sin_forma = sin_forma.replace(dentro_de_jq, en_el_shell)

    CASOS[caso](kit)
    assert _ejecutar(bloque, kit.raiz).returncode != 0, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode != 0, "y el camino 1 también"
    assert _ejecutar(sin_forma, kit.raiz).returncode == 0, (
        "sin el control debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


@pytest.mark.parametrize("caso", ["algorithm_con_salto_final", "rol_con_nul_en_medio", "schema_version_con_nul_final"])
def test_si_la_receta_comparara_el_contrato_en_el_shell_esto_pasaria(kit, caso):
    """`$(…)` quita los saltos de línea finales y descarta los bytes nulos: un
    `algorithm` que es «ed25519» más un salto de línea se comparaba como
    «ed25519». Por eso el contrato se compara dentro de jq."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    en_el_shell = _CONTROL_CONTRATO.sub(
        lambda _m: (
            '[ "$(jq -r \'[.schema_version,.role,.algorithm]|join(" ")\' "$S")" = '
            '"dike-content-signature-v2 content-integrity ed25519" ] \\\n'
            '  || { echo "FALLA: schema_version, role o algorithm inesperados"; exit 1; }\n'
        ),
        bloque,
    )
    assert en_el_shell != bloque, "no se encontró el control del contrato"

    CASOS[caso](kit)
    assert _ejecutar(bloque, kit.raiz).returncode != 0, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode != 0, "y el camino 1 también"
    assert _ejecutar(en_el_shell, kit.raiz).returncode == 0, (
        "comparando en el shell debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


def test_si_la_receta_no_exigiera_un_solo_objeto_dos_documentos_pasarian(kit):
    """`jq` procesa todos los documentos de un archivo y se queda con el
    último: un primer documento con la firma vacía dejaba pasar al segundo."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    sin_control = _sin(bloque, _CONTROL_UN_SOLO_OBJETO, "el control de un solo objeto")

    CASOS["sobre_con_dos_documentos"](kit)
    assert _ejecutar(bloque, kit.raiz).returncode == 2, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode == 2, "y el camino 1 también"
    assert _ejecutar(sin_control, kit.raiz).returncode == 0, (
        "sin el control debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


def test_si_la_receta_no_mirara_los_numeros_un_entero_reescrito_pasaria(kit):
    """`jq` lee 2e0 y escribe 2: el hash coincide con el firmado. Python lee
    2.0 y no coincide. Sin el control de números, los dos caminos discrepan."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    control = re.search(r"#    Y los números.*?\nN=\$\(.*?\n\[ \"\$N\" = 0 \].*?\n", bloque, flags=re.DOTALL)
    assert control, "no se encontró el control de números de la receta"
    sin_control = bloque.replace(control.group(0), "")

    CASOS["entero_con_exponente"](kit)
    assert _ejecutar(bloque, kit.raiz).returncode == 2, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode == 2, "y el camino 1 también"
    assert _ejecutar(sin_control, kit.raiz).returncode == 0, (
        "sin el control debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


@pytest.mark.parametrize("caso", ["entero_con_cero_a_la_izquierda", "entero_con_signo_mas"])
def test_la_receta_rechaza_enteros_que_jq_normaliza(kit, caso):
    """Reauditoría 2 (H1). `jq` lee 02 y +2 como 2 y el hash coincide con el
    firmado; Python no los acepta. Los dos caminos salen 2."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    control = re.search(r"#    Y los números.*?\nN=\$\(.*?\n\[ \"\$N\" = 0 \].*?\n", bloque, flags=re.DOTALL)
    assert control, "no se encontró el control de números de la receta"

    CASOS[caso](kit)
    assert _ejecutar(bloque, kit.raiz).returncode == 2, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode == 2, "y el camino 1 también"
    assert _ejecutar(bloque.replace(control.group(0), ""), kit.raiz).returncode == 0, (
        "sin el control debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


@pytest.mark.parametrize("caso", ["clave_publica_con_texto_antes", "clave_publica_con_bom", "clave_publica_con_otra_clave_detras"])
def test_si_la_receta_no_exigiera_la_forma_canonica_de_la_clave_esto_pasaria(kit, caso):
    """OpenSSL lee una clave con texto antes, con un BOM o con otra clave
    detrás. El camino 1 exige la forma canónica; sin el mismo control en la
    receta, el mismo archivo verificaría por un camino y no por el otro."""
    _exigir("camino2")
    bloque = _bloque("camino2")
    sin_control = _sin(bloque, _CONTROL_CLAVE_CANONICA, "el control de la forma canónica de la clave")

    CASOS[caso](kit)
    assert _ejecutar(bloque, kit.raiz).returncode == 2, "el documento real lo rechaza"
    assert _ejecutar(_bloque("camino1"), kit.raiz).returncode == 2, "y el camino 1 también"
    assert _ejecutar(sin_control, kit.raiz).returncode == 0, (
        "sin el control debía pasar: si no pasa, este test ya no demuestra para qué sirve"
    )


# ── Búsqueda al azar de discrepancias ────────────────────────────────────

def _buscador():
    import importlib.util

    guion = REPO / "scripts" / "hackathon" / "buscar_discrepancias.py"
    spec = importlib.util.spec_from_file_location("buscar_discrepancias", guion)
    mod = importlib.util.module_from_spec(spec)
    escribia, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = escribia
    return mod


def test_una_busqueda_al_azar_no_encuentra_discrepancias(tmp_path):
    """La batería prueba las entradas que a alguien se le ocurrieron. Aquí se
    altera al azar uno de los tres archivos, 200 veces con una semilla fija, y
    los tres verificadores tienen que seguir de acuerdo. La búsqueda larga es
    `scripts/hackathon/buscar_discrepancias.py`."""
    _exigir("camino2")
    res = _buscador().buscar(tmp_path / "busqueda", casos=200, semilla=20261006)
    assert res.casos == 200
    assert not res.discrepan, "\n".join(f"{n}: {d} -> {v}" for n, d, v in res.discrepan)
    # Si ninguna alteración verificara, o todas, la búsqueda no estaría probando nada.
    assert 0 < res.verifican < res.casos, res.verifican


def test_la_busqueda_ve_una_discrepancia_cuando_la_hay(tmp_path):
    """El arnés de la búsqueda tiene dientes: con una receta a la que se le
    quitó un control, la entrada que ese control detenía sale como discrepancia."""
    _exigir("camino2")
    mod = _buscador()
    debil = _sin(_bloque("camino2"), _CONTROL_CLAVE_CANONICA, "el control de la forma canónica de la clave")
    comparador = mod.Comparador(tmp_path / "busqueda", receta=debil)
    comparador.poner()
    assert set(comparador.veredictos().values()) == {True}, "control: el kit sin alterar verifica por los tres"

    clave = "content-signing-key.pub"
    comparador.poner({clave: b"clave de Dike\n" + comparador.base[clave]})
    v = comparador.veredictos()
    assert v == {"biblioteca": False, "verificar_tercero.py": False, "receta": True}, v
    assert mod.discrepan(v)
    assert mod.discrepan({"biblioteca": False, "verificar_tercero.py": "excepción KeyError", "receta": False})
    assert not mod.discrepan({"biblioteca": False, "verificar_tercero.py": False, "receta": False})


# ── El hash canónico: jq y Python ────────────────────────────────────────


def test_jq_y_python_dan_el_mismo_hash(tmp_path):
    """La receta calcula el hash con `jq -cSj`; Diké, con `json.dumps`. Tienen
    que coincidir en todo lo que un commitment puede llevar."""
    if shutil.which("jq") is None or shutil.which("sha256sum") is None:
        pytest.skip("falta jq o sha256sum: no se puede comparar la canonicalización")
    dificil = {
        "zeta": 1, "alfa": {"ñ": None, "Z": [], "a": {}},
        "texto": "comillas \" y « », barra \\ , salto\n, tab\t, retorno\r, control \u0001",
        "unicode": "ñandú €  — 𝔘 😀   fin",
        # Hasta 15 dígitos, que es lo que un commitment puede llevar: un jq
        # anterior a 1.7 redondea los enteros más largos.
        "enteros": [0, -3, 999999999999999, -999999999999999],
        "anidado": [{"b": 1, "a": [None, "x", {"k": "v"}]}],
        "vacia": "", "url": "https://nuevo.leychile.cl/servicios/Navegar/get_norma_json?idNorma=207436&x=<y>",
    }
    f = tmp_path / "c.json"
    f.write_text(json.dumps(dificil, ensure_ascii=False, indent=3), encoding="utf-8")
    esperado = hashlib.sha256(
        json.dumps(dificil, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    r = subprocess.run(
        f"jq -cSj . {f.name} | sha256sum | cut -d' ' -f1",
        shell=True, cwd=str(tmp_path), capture_output=True, text=True, timeout=60,
    )
    assert r.stdout.strip() == esperado, r.stderr


# ── La clave publicada ───────────────────────────────────────────────────


def _key_id(pem: bytes) -> str:
    pub = serialization.load_pem_public_key(pem)
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def _key_id_publicado() -> str:
    m = re.search(r"\| `key_id` \| `([0-9a-f]{16})` \|", _texto())
    assert m, "KEYS.md no declara el key_id"
    return m.group(1)


def test_la_clave_impresa_es_la_del_archivo():
    m = re.search(r"-----BEGIN PUBLIC KEY-----.*?-----END PUBLIC KEY-----", _texto(), flags=re.DOTALL)
    assert m, "KEYS.md no imprime la clave pública"
    impresa = m.group(0).encode("ascii") + b"\n"
    assert impresa.split() == PUBKEY.read_bytes().split(), "la clave impresa no es la del archivo"
    assert _key_id(impresa) == _key_id_publicado()


def test_la_carpeta_no_trae_claves_privadas():
    patron = re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
    revisados = 0
    for archivo in CARPETA_KIT.rglob("*"):
        if not archivo.is_file() or "__pycache__" in archivo.parts or "scratch" in archivo.parts:
            continue
        revisados += 1
        assert not patron.search(archivo.read_bytes()), f"clave privada en {archivo.name}"
        assert archivo.suffix != ".pem", f"{archivo.name}: las claves públicas se publican como .pub"
    assert revisados >= 4


# ── El ejemplo firmado con la llave real (F6) ────────────────────────────


def _sandbox(kit_dir: Path, guion: str) -> subprocess.CompletedProcess:
    """Ejecuta `guion` sin /home, sin red y con el entorno vacío."""
    return subprocess.run(
        ["bwrap", "--unshare-all", "--die-with-parent", "--clearenv",
         "--ro-bind", "/usr", "/usr", "--symlink", "usr/bin", "/bin",
         "--symlink", "usr/lib", "/lib", "--symlink", "usr/lib", "/lib64",
         "--ro-bind-try", "/etc/ssl", "/etc/ssl",
         "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
         "--bind", str(kit_dir), "/work", "--chdir", "/work",
         "--setenv", "PATH", "/usr/bin", "--setenv", "HOME", "/sin-home",
         "bash", "-c", guion],
        capture_output=True, text=True, timeout=120,
    )


def _exigir_sandbox() -> None:
    _exigir("camino2")
    if shutil.which("bwrap") is None:
        pytest.skip("falta bwrap: no se puede ensayar la verificación sin /home ni red")
    for interprete in ("/usr/bin/python3",):
        ok = subprocess.run([interprete, "-c", "import cryptography"], capture_output=True)
        if ok.returncode != 0:
            pytest.skip("el python3 del sistema no trae `cryptography`: el camino 1 no corre aislado")
    if not Path("/usr/lib").is_dir() or _sandbox(Path("/usr"), "true").returncode != 0:
        pytest.skip("bwrap no puede montar este sistema: no se puede ensayar el aislamiento")


def _guion_de_los_dos_caminos() -> str:
    return (
        "set -u\n"
        "test ! -e /home || { echo 'HAY /home'; exit 90; }\n"
        "ls /sys/class/net 2>/dev/null | grep -v '^lo$' && { echo 'HAY RED'; exit 91; }\n"
        "cat > /tmp/c1.sh <<'FIN_C1'\n" + _bloque("camino1") + "FIN_C1\n"
        "cat > /tmp/c2.sh <<'FIN_C2'\n" + _bloque("camino2") + "FIN_C2\n"
        "bash /tmp/c1.sh; echo \"camino1=$?\"\n"
        "bash /tmp/c2.sh; echo \"camino2=$?\"\n"
    )


def test_los_dos_caminos_funcionan_sin_home_ni_red(kit):
    """«Sin red, sin credenciales y sin acceso a nuestros sistemas», medido:
    sin /home (ni perfil, ni corpus, ni custodia), sin red, entorno vacío y el
    python del sistema."""
    _exigir_sandbox()
    r = _sandbox(kit.raiz, _guion_de_los_dos_caminos())
    assert "camino1=0" in r.stdout and "camino2=0" in r.stdout, r.stdout + r.stderr
    assert "HAY /home" not in r.stdout and "HAY RED" not in r.stdout
    assert r.stdout.count(kit.key_id) >= 2

    CASOS["commitment_alterado"](kit)
    r = _sandbox(kit.raiz, _guion_de_los_dos_caminos())
    assert "camino1=1" in r.stdout and "camino2=1" in r.stdout, r.stdout + r.stderr


def test_el_aviso_de_pendiente_es_coherente_con_la_carpeta():
    """Mientras falte el ejemplo firmado, el documento tiene que decirlo; y
    cuando esté, el aviso tiene que haberse borrado."""
    hay_ejemplo = all(p.is_file() for p in EJEMPLO)
    assert any(p.is_file() for p in EJEMPLO) == hay_ejemplo, "el ejemplo está a medias"
    assert (AVISO_PENDIENTE in _texto()) == (not hay_ejemplo)


def test_el_ejemplo_del_kit_verifica_con_la_clave_publicada(tmp_path):
    """Aceptación de F6. El ejemplo se firma con la llave real, fuera de la
    suite: ningún test la toca. Mientras los dos archivos existan, este test
    exige que verifiquen con la clave publicada, por los dos caminos."""
    if not all(p.is_file() for p in EJEMPLO):
        pytest.skip(
            "PENDIENTE F6: faltan docs/hackathon/commitment.json y commitment.sig.json "
            "firmados con la llave real. No existe ningún sobre V2 de la clave publicada (K3)."
        )
    _exigir("camino2")
    copia = tmp_path / "kit"
    copia.mkdir()
    for nombre in ("commitment.json", "commitment.sig.json", "content-signing-key.pub", "verificar_tercero.py"):
        shutil.copyfile(CARPETA_KIT / nombre, copia / nombre)
    publicado = _key_id_publicado()

    commitment = json.loads((copia / "commitment.json").read_text(encoding="utf-8"))
    validar_publicable(commitment)
    assert "document_sha256" not in commitment
    # Lo que KEYS.md dice del ejemplo: seis citas, cuatro verificadas, dos fuera.
    assert (commitment["total_citas"], commitment["citas_verificadas"], commitment["citas_fallidas"]) == (6, 4, 2)
    assert len(commitment["normas_verificadas"]) == 4
    assert json.loads((copia / "commitment.sig.json").read_text(encoding="utf-8"))["key_id"] == publicado

    for clase in ("camino1", "camino2"):
        r = _ejecutar(_bloque(clase), copia)
        assert r.returncode == 0, f"{clase}:\n{r.stdout}\n{r.stderr}"
        assert publicado in r.stdout

    if shutil.which("bwrap") is not None:
        _exigir_sandbox()
        r = _sandbox(copia, _guion_de_los_dos_caminos())
        assert "camino1=0" in r.stdout and "camino2=0" in r.stdout, r.stdout + r.stderr

    alterado = dict(commitment, citas_verificadas=commitment["citas_verificadas"] + 1)
    (copia / "commitment.json").write_text(json.dumps(alterado, ensure_ascii=False), encoding="utf-8")
    for clase in ("camino1", "camino2"):
        assert _ejecutar(_bloque(clase), copia).returncode == 1, f"{clase} aceptó el ejemplo alterado"


def test_la_firma_del_kit_esta_en_el_registro():
    """Toda firma hecha con la llave real se anota cuando se hace. Si alguien
    cambia el ejemplo del kit sin registrar la firma nueva, esto falla."""
    if not all(p.is_file() for p in EJEMPLO):
        pytest.skip("no hay ejemplo firmado en el kit: no hay firma que buscar en el registro")
    registro = CARPETA_KIT / "REGISTRO_DE_FIRMAS.md"
    assert registro.is_file(), "falta docs/hackathon/REGISTRO_DE_FIRMAS.md"
    firmado = json.loads(EJEMPLO[1].read_text(encoding="utf-8"))["commitment_hash"]
    filas = [l for l in registro.read_text(encoding="utf-8").splitlines() if l.startswith("|") and firmado in l]
    assert len(filas) == 1, f"la firma {firmado[:16]}… aparece {len(filas)} veces en el registro"
    assert "**Vigente.**" in filas[0], "el ejemplo del kit lleva una firma que el registro no da por vigente"
    vigentes = [l for l in registro.read_text(encoding="utf-8").splitlines() if l.startswith("|") and "**Vigente.**" in l]
    assert len(vigentes) == 1, "el registro tiene que tener exactamente una firma vigente para el kit"


# ── Lo que el documento afirma sobre la ley y sobre sus propios límites ──


def _cache_ley_19799() -> Path | None:
    candidatos = []
    if os.environ.get("LEXO_BCN_CACHE_DIR"):
        candidatos.append(Path(os.environ["LEXO_BCN_CACHE_DIR"]))
    candidatos.append(
        Path.home() / ".hermes" / "workspaces" / "lexo" / "Vault" / "Lexo" / "Vigente" / "Ley_General" / "_bcn_cache"
    )
    for d in candidatos:
        f = d / "norma_196640.json"
        if f.is_file():
            return f
    return None


def _normalizar(texto: str) -> str:
    return re.sub(r"\s+", " ", texto).strip()


def test_las_citas_de_la_ley_19799_son_literales():
    """En KEYS.md las comillas « » se reservan para citas textuales de la ley.
    Cada una tiene que estar, palabra por palabra, en el texto de BCN."""
    citas = [_normalizar(c) for c in re.findall(r"«([^»]+)»", _texto())]
    assert len(citas) >= 2, "KEYS.md ya no cita la ley: revisar este test"
    cache = _cache_ley_19799()
    if cache is None:
        pytest.skip("no está el caché local de BCN (norma_196640.json): no se pueden cotejar las citas de la Ley 19.799")
    crudo = json.dumps(json.loads(cache.read_text(encoding="utf-8")), ensure_ascii=False)
    ley = _normalizar(re.sub(r"<[^>]+>", " ", html.unescape(html.unescape(crudo))))
    for cita in citas:
        assert cita in ley, f"cita no literal de la Ley 19.799: «{cita}»"


def _bloquea(texto: str) -> bool:
    c = detect_pii(texto)
    return bool(c.get("rut") or c.get("email") or c.get("phone"))


def test_los_limites_declarados_del_control_de_pii_son_reales():
    """KEYS.md declara qué NO ve el control de datos personales. Si un día lo
    ve, este test falla y hay que corregir el documento, no dejarlo viejo."""
    # Controles positivos: lo que sí detecta.
    assert _bloquea("RUT 12.345.678-5")
    assert _bloquea("escribir a juan@example.com")
    assert _bloquea("llamar al +56 9 1234 5678")
    # Lo que el documento declara como límite.
    assert not _bloquea("RUT 12.345.678 - 5"), "ya detecta RUT con espacios: actualizar KEYS.md"
    assert not _bloquea("demanda de Juan Pérez González"), "ya detecta nombres: actualizar KEYS.md"
    assert not _bloquea("domiciliado en calle Los Olmos 123"), "ya bloquea direcciones: actualizar KEYS.md"
    assert not _bloquea("teléfono +56 2 2345 6789"), "ya bloquea teléfonos fijos: actualizar KEYS.md"
    for limite in ("nombres", "direcciones", "teléfonos fijos", "RUT escrito con espacios"):
        assert limite in _texto(), f"KEYS.md ya no declara el límite: {limite}"


# ── 5. La tabla «afirmación → prueba» ────────────────────────────────────


def _filas_de_la_tabla() -> list[tuple[str, list[tuple[str, str]]]]:
    texto = _texto()
    seccion = texto[texto.index("## Afirmaciones y pruebas"):]
    filas = []
    for linea in seccion.splitlines():
        celdas = [c.strip() for c in linea.strip().strip("|").split("|")]
        if len(celdas) != 3 or set(celdas[0]) <= {"-"} or celdas[0] == "Afirmación":
            continue
        refs, archivo = [], None
        for token in re.findall(r"`([^`]+)`", celdas[1]):
            if "::" not in token:
                continue
            izq, nombre = token.split("::", 1)
            archivo = izq or archivo
            refs.append((archivo, nombre))
        filas.append((celdas[0], refs))
    return filas


def _tests_definidos(archivo: Path) -> set[str]:
    arbol = ast.parse(archivo.read_text(encoding="utf-8"))
    return {n.name for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef)}


def test_la_tabla_apunta_a_tests_que_existen():
    filas = _filas_de_la_tabla()
    assert len(filas) >= 25, f"la tabla tiene {len(filas)} filas: ¿se rompió el formato?"
    for afirmacion, refs in filas:
        assert refs, f"afirmación sin prueba: {afirmacion}"
        for archivo, nombre in refs:
            assert archivo, f"{afirmacion}: referencia sin archivo"
            ruta = TESTS / archivo
            assert ruta.is_file(), f"{afirmacion}: no existe {archivo}"
            assert nombre in _tests_definidos(ruta), f"{afirmacion}: {archivo} no define {nombre}"


def test_el_documento_no_cita_rutas_del_repositorio_privado():
    """El kit se exporta solo: una ruta `docs/hackathon/...` o `lexo_cli/...`
    en el documento sería un enlace roto para quien lo recibe."""
    for linea in _texto().splitlines():
        assert "docs/hackathon/" not in linea and "lexo_cli/" not in linea, linea


def test_raiz_del_repo_es_la_del_test():
    assert (REPO / "lexo_cli").is_dir() and KEYS.is_file()
