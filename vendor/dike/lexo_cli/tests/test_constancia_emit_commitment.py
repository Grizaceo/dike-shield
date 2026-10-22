"""`dike constancia --emit-commitment DIR [--sign]` (F5 de la remediación 2).

KEYS.md decía que `dike constancia` «emite dos artefactos» cuando el comando no
tenía ninguna opción para escribir un commitment. Ahora la tiene, y estos tests
fijan lo que promete:

  · lo que escribe pasa el verificador de tercero;
  · las citas que no se verificaron no entran al commitment;
  · si no puede emitir (sin llave, sin citas verificadas, PII, destino ocupado)
    sale 2 y no deja ningún archivo.

El motor de citas se sustituye por un gate fijo: aquí se prueba la emisión, no
el corpus. El recorrido con el corpus real es `test_demo_bli_e2e.py`.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization

from lexo_cli import content_signing as cs
from lexo_cli.commands import analizar, constancia
from lexo_cli.content_signing import generar_content_key

REPO = Path(__file__).resolve().parents[2]
VERIFICADOR = REPO / "docs" / "hackathon" / "verificar_tercero.py"

ESCRITO = (
    "PRIMERO.- causal del artículo 161 del Código del Trabajo.\n"
    "SEGUNDO.- El artículo 162 del Código del Trabajo exige comunicación escrita.\n"
    "QUINTO.- A mayor abundamiento, el artículo 60 obliga al empleador.\n"
    "SEXTO.- Lo anterior se refuerza con el artículo 9999 del Código del Trabajo.\n"
)

_OK = [
    ("cl.norma.ct:art:0161", "artículo 161 del Código del Trabajo", "a" * 64),
    ("cl.norma.ct:art:0162", "artículo 162 del Código del Trabajo exige", "b" * 64),
]
_FALLO = [
    ("", "artículo 60", "AMBIGUOUS"),
    ("cl.norma.ct:art:9999", "artículo 9999 del Código del Trabajo", "UNRESOLVABLE"),
]


class _Resolver:
    def binding(self):
        return {"corpora": [{"snapshot_hash": "ea28fa1c0f9af6c1" + "0" * 48}]}


def _gate(ok=_OK, fallo=_FALLO) -> dict:
    refs = [{"raw": raw, "gid": gid, "status": "RESOLVED", "supported": True} for gid, raw, _ in ok]
    refs += [{"raw": raw, "gid": gid, "status": st, "supported": False} for gid, raw, st in fallo]
    return {
        "analysis_status": "CITATIONS_VERIFIED" if not fallo else "CITATIONS_UNVERIFIED",
        "citation_reasons": [f"{raw}: {st}" for _, raw, st in fallo],
        "citation_check": {"references": refs, "not_in_force": [], "temporal_uncertain": []},
        "canonical_sources": [{
            "gid": gid, "text_sha256": h, "temporal_status": "IN_FORCE",
            "source_url": "https://nuevo.leychile.cl/servicios/Navegar/get_norma_json?idNorma=207436",
            "retrieved_at": "2026-08-13T19:48:38Z",
            "historical_text_status": "CURRENT_VERSION_CONFIRMED",
        } for gid, _, h in ok],
    }


@pytest.fixture
def motor(monkeypatch):
    """Sustituye corpus y gate. Devuelve la lista donde cae la salida --json."""
    emitted: list[dict] = []
    monkeypatch.setattr(constancia, "load_config", lambda: {})
    monkeypatch.setattr(constancia, "resolve_document", lambda _d: ESCRITO)
    monkeypatch.setattr(constancia, "canonical_resolver_for", lambda _cfg, *, as_of=None: (_Resolver(), ""))
    monkeypatch.setattr(analizar, "_citation_gate", lambda *a, **k: _gate())
    monkeypatch.setattr(constancia, "output_json", emitted.append)
    monkeypatch.delenv("LEXO_CONTENT_SIGNING_KEY_PATH", raising=False)
    monkeypatch.delenv("LEXO_CUSTODY_SIGNING_KEY_PATH", raising=False)
    return emitted


@pytest.fixture
def llave(tmp_path, monkeypatch) -> tuple[Path, str]:
    ruta, key_id = generar_content_key(tmp_path / "custodia" / "content-signing-key.pem")
    monkeypatch.setenv("LEXO_CONTENT_SIGNING_KEY_PATH", str(ruta))
    return ruta, key_id


def _args(directorio: Path | None, *, sign: bool = False, origen: str = "demanda laboral (prueba)"):
    return SimpleNamespace(
        documento="/home/abogado/casos/reservado/demanda_cliente.md",
        as_of=None, as_json=True, origen=origen,
        emit_commitment=str(directorio) if directorio is not None else None,
        sign=sign,
    )


def _err(capsys) -> str:
    """stderr en una sola línea: Rich corta según el ancho, y una ruta temporal
    larga parte un mensaje por la mitad."""
    return " ".join(capsys.readouterr().err.split())


def _vacia(directorio: Path) -> bool:
    return not directorio.exists() or not any(directorio.iterdir())


def _tercero(directorio: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(VERIFICADOR), "commitment.json", "commitment.sig.json", "content-signing-key.pub"],
        capture_output=True, text=True, cwd=str(directorio), timeout=60,
    )


# ── Superficie ──

def test_superficie_de_los_flags():
    parser = argparse.ArgumentParser(prog="dike")
    constancia.register(parser.add_subparsers(dest="comando"))
    args = parser.parse_args(["constancia", "e.md", "--emit-commitment", "salida", "--sign"])
    assert args.emit_commitment == "salida" and args.sign is True
    sin = parser.parse_args(["constancia", "e.md"])
    assert sin.emit_commitment is None and sin.sign is False


def test_sin_los_flags_el_comando_no_cambia(motor, tmp_path):
    """Quien llama a handle() con el Namespace antiguo sigue funcionando."""
    args = SimpleNamespace(documento="escrito", as_of=None, as_json=True, origen=None)
    assert constancia.handle(args) == 1
    assert motor[-1]["meta"]["citas_fallidas"] == 2


# ── Aceptación de F5: con llave, los archivos pasan el verificador de tercero ──

def test_emite_firma_y_el_tercero_verifica(motor, llave, tmp_path):
    ruta, key_id = llave
    d = tmp_path / "salida"

    codigo = constancia.handle(_args(d, sign=True))

    assert codigo == 1, "hay 2 citas sin verificar: la constancia sigue saliendo 1"
    assert sorted(p.name for p in d.iterdir()) == [
        "commitment.json", "commitment.sig.json", "content-signing-key.pub",
    ]
    r = _tercero(d)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULTADO: VERIFICADO" in r.stdout and key_id in r.stdout

    sobre = json.loads((d / "commitment.sig.json").read_text(encoding="utf-8"))
    assert sobre["key_id"] == key_id and sobre["role"] == "content-integrity"
    # La pubkey escrita es la de la llave con que se firmó.
    priv = serialization.load_pem_private_key(ruta.read_bytes(), password=None)
    assert (d / "content-signing-key.pub").read_bytes() == priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    assert b"PRIVATE" not in (d / "content-signing-key.pub").read_bytes()


def test_lo_no_verificado_no_entra_al_commitment(motor, llave, tmp_path):
    """La abstención: 2 citas rechazadas, y de ellas solo viaja el número."""
    d = tmp_path / "salida"
    constancia.handle(_args(d, sign=True))
    texto = (d / "commitment.json").read_text(encoding="utf-8")
    c = json.loads(texto)

    assert c["total_citas"] == 4 and c["citas_verificadas"] == 2 and c["citas_fallidas"] == 2
    assert [n["gid"] for n in c["normas_verificadas"]] == ["cl.norma.ct:art:0161", "cl.norma.ct:art:0162"]
    assert "9999" not in texto and "artículo 60" not in texto
    assert "AMBIGUOUS" not in texto and "UNRESOLVABLE" not in texto
    # Control: la constancia completa SÍ las trae (si no, el test no prueba nada).
    assert "9999" in json.dumps(motor[-1], ensure_ascii=False)


def test_el_commitment_no_lleva_ruta_origen_prosa_ni_huella(motor, llave, tmp_path):
    d = tmp_path / "salida"
    constancia.handle(_args(d, sign=True))
    texto = (d / "commitment.json").read_text(encoding="utf-8")
    c = json.loads(texto)

    for fuga in ("/home/", "demanda_cliente", "demanda laboral", "exige", "cita_raw", "origen", "documento"):
        assert fuga not in texto, f"fuga: {fuga!r}"
    assert "document_sha256" not in c and "document_bytes" not in c
    assert len(c["pack_hash"]) == 16
    # Control: esos datos existían en la constancia de la que salió.
    constancia_json = json.dumps(motor[-1], ensure_ascii=False)
    assert "demanda_cliente" in constancia_json and "exige" in constancia_json


def test_el_commitment_lleva_estos_campos_y_ninguno_mas(motor, llave, tmp_path):
    """KEYS.md dice qué revela un commitment. Es esta lista, completa."""
    d = tmp_path / "salida"
    constancia.handle(_args(d, sign=True))
    c = json.loads((d / "commitment.json").read_text(encoding="utf-8"))
    assert sorted(c) == [
        "_aviso_huella_omitida", "advertencias", "alcance", "as_of", "citas_fallidas",
        "citas_verificadas", "fecha_constancia", "normas_verificadas", "pack_hash",
        "schema_version", "total_citas",
    ]
    for norma in c["normas_verificadas"]:
        assert sorted(norma) == [
            "cuerpo", "estado", "fuente_url", "gid", "texto_hash", "vigencia", "vigencia_legible",
        ]
    assert c["fecha_constancia"].endswith("Z") and c["alcance"] and c["advertencias"]


def test_todas_verificadas_sale_0(motor, llave, tmp_path, monkeypatch):
    monkeypatch.setattr(analizar, "_citation_gate", lambda *a, **k: _gate(fallo=[]))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 0
    assert _tercero(d).returncode == 0
    assert json.loads((d / "commitment.json").read_text(encoding="utf-8"))["citas_fallidas"] == 0


def test_sin_sign_escribe_solo_el_commitment(motor, tmp_path):
    d = tmp_path / "salida"
    assert constancia.handle(_args(d)) == 1
    assert [p.name for p in d.iterdir()] == ["commitment.json"]


def test_el_json_de_stdout_no_cambia_al_emitir(motor, llave, tmp_path, capsys):
    constancia.handle(_args(None))
    sin = motor[-1]
    constancia.handle(_args(tmp_path / "salida", sign=True))
    con = motor[-1]
    assert len(motor) == 2, "la emisión no debe imprimir un segundo JSON"
    assert {k: v for k, v in sin.items() if k != "meta"} == {k: v for k, v in con.items() if k != "meta"}
    assert "commitment.json escrito" in _err(capsys)


# ── Aceptación de F5: sin llave, exit distinto de 0 y carpeta vacía ──

def test_sin_llave_no_firma_y_no_deja_nada(motor, tmp_path, capsys):
    d = tmp_path / "salida"
    codigo = constancia.handle(_args(d, sign=True))
    assert codigo == 2
    assert _vacia(d)
    assert "SIGNATURE_UNAVAILABLE" in _err(capsys)
    assert motor == [], "sin llave se rechaza antes de verificar nada"


def test_llave_con_permisos_abiertos_no_firma(motor, llave, tmp_path, capsys):
    llave[0].chmod(0o644)
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d) and "0600" in _err(capsys)


def test_no_firma_con_la_llave_de_autorizacion(motor, llave, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("LEXO_CUSTODY_SIGNING_KEY_PATH", str(llave[0]))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d) and "ROLE_KEY_REUSE" in _err(capsys)


def test_sign_sin_emit_commitment_es_un_error(motor, llave):
    args = _args(None, sign=True)
    assert constancia.handle(args) == 2
    assert motor == []


# ── No emite lo que no puede sostener ──

def test_ninguna_cita_verificada_no_emite(motor, llave, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(analizar, "_citation_gate", lambda *a, **k: _gate(ok=[]))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d)
    assert "COMMITMENT_UNAVAILABLE" in _err(capsys)
    assert motor[-1]["meta"]["citas_verificadas"] == 0, "control: la constancia sí se imprimió"


def test_escrito_sin_citas_no_emite(motor, llave, tmp_path, monkeypatch):
    monkeypatch.setattr(constancia, "resolve_document", lambda _d: "Solicitud sin cita normativa.")
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d) and motor[-1]["veredicto"] == "SIN_CITAS"


def test_sin_corpus_no_emite(motor, llave, tmp_path, monkeypatch):
    monkeypatch.setattr(constancia, "canonical_resolver_for", lambda _cfg, *, as_of=None: (None, "sin corpus"))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d) and motor[-1]["veredicto"] == "SIN_CORPUS"


def test_pii_en_el_origen_no_emite(motor, llave, tmp_path, capsys):
    d = tmp_path / "salida"
    codigo = constancia.handle(_args(d, sign=True, origen="demanda de Juan Pérez, RUT 12.345.678-5"))
    assert codigo == 2
    assert _vacia(d)
    err = _err(capsys)
    assert "COMMITMENT_UNAVAILABLE" in err and "12.345.678" not in err


# ── No sobrescribe y no deja archivos a medias ──

def test_no_sobrescribe_un_commitment_existente(motor, llave, tmp_path, capsys):
    d = tmp_path / "salida"
    d.mkdir()
    (d / "commitment.json").write_text("commitment anterior", encoding="utf-8")
    assert constancia.handle(_args(d, sign=True)) == 2
    assert (d / "commitment.json").read_text(encoding="utf-8") == "commitment anterior"
    assert [p.name for p in d.iterdir()] == ["commitment.json"]
    assert "ya existe" in _err(capsys)


def test_no_deja_un_commitment_nuevo_junto_a_una_firma_vieja(motor, tmp_path):
    """Sin --sign solo se escribiría commitment.json; junto a un sobre viejo
    quedaría un par que no verifica."""
    d = tmp_path / "salida"
    d.mkdir()
    (d / "commitment.sig.json").write_text("{}", encoding="utf-8")
    assert constancia.handle(_args(d)) == 2
    assert [p.name for p in d.iterdir()] == ["commitment.sig.json"]


def test_destino_que_no_es_carpeta(motor, tmp_path):
    f = tmp_path / "archivo"
    f.write_text("x", encoding="utf-8")
    assert constancia.handle(_args(f)) == 2
    assert f.read_text(encoding="utf-8") == "x"


def test_si_lo_escrito_no_verifica_se_borra_todo(motor, llave, tmp_path, monkeypatch, capsys):
    """Fail-closed: o queda el juego completo y verificado, o no queda nada."""
    monkeypatch.setattr(cs, "verificar_archivos", lambda *a, **k: False)
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert _vacia(d)
    assert "COMMITMENT_UNAVAILABLE" in _err(capsys)


def test_si_falla_la_escritura_no_quedan_archivos_a_medias(motor, llave, tmp_path, monkeypatch):
    d = tmp_path / "salida"
    d.mkdir()
    (d / "ajeno.txt").write_text("no es nuestro", encoding="utf-8")
    real = cs.verificar_archivos

    def falla(*a, **k):
        assert (d / "commitment.json").exists(), "control: ya se había escrito algo"
        raise OSError("disco lleno")

    monkeypatch.setattr(cs, "verificar_archivos", falla)
    assert constancia.handle(_args(d, sign=True)) == 2
    assert [p.name for p in d.iterdir()] == ["ajeno.txt"], "se borra lo propio y nada más"
    assert real is not falla


# ═════════════════════════════════════════════════════════════════════════
# Reauditoría 2 (2026-10-06)
# ═════════════════════════════════════════════════════════════════════════

# ── H3: si la escritura se corta, tampoco queda el archivo a medias ──

class _SeCorta:
    """Archivo que escribe la mitad y falla: disco lleno o Ctrl-C."""

    def __init__(self, f, exc):
        self.f, self.exc = f, exc

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.f.close()
        return False

    def write(self, datos):
        self.f.write(datos[: len(datos) // 2])
        self.f.flush()
        raise self.exc


def _cortar_la_escritura(monkeypatch, n: int, exc: BaseException) -> None:
    """Hace fallar la escritura del archivo n-ésimo DESPUÉS de crearlo."""
    import builtins

    cuenta = {"n": 0}

    def falso_open(ruta, modo="r", *a, **k):
        f = builtins.open(ruta, modo, *a, **k)
        if modo == "xb":
            cuenta["n"] += 1
            if cuenta["n"] == n:
                return _SeCorta(f, exc)
        return f

    monkeypatch.setattr(constancia, "open", falso_open, raising=False)


@pytest.mark.parametrize("n", [1, 2, 3])
def test_si_el_disco_se_llena_no_queda_el_archivo_a_medias(motor, llave, tmp_path, monkeypatch, capsys, n):
    """commitment.json, commitment.sig.json y la clave pública, uno a la vez.
    Antes el archivo que se estaba escribiendo quedaba en disco, truncado."""
    _cortar_la_escritura(monkeypatch, n, OSError(28, "No space left on device"))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert not d.exists(), f"quedó {sorted(p.name for p in d.iterdir())}"
    assert "COMMITMENT_UNAVAILABLE" in _err(capsys)


@pytest.mark.parametrize("n", [1, 2, 3])
def test_un_ctrl_c_al_escribir_no_deja_nada(motor, llave, tmp_path, monkeypatch, n):
    """El caso que importaba: un Ctrl-C en el segundo archivo dejaba un
    commitment.json completo y, al lado, una firma truncada."""
    _cortar_la_escritura(monkeypatch, n, KeyboardInterrupt())
    d = tmp_path / "salida"
    with pytest.raises(KeyboardInterrupt):
        constancia.handle(_args(d, sign=True))
    assert not d.exists(), f"quedó {sorted(p.name for p in d.iterdir())}"


def test_si_la_escritura_se_corta_lo_ajeno_no_se_toca(motor, llave, tmp_path, monkeypatch):
    d = tmp_path / "salida"
    d.mkdir()
    (d / "ajeno.txt").write_text("no es nuestro", encoding="utf-8")
    _cortar_la_escritura(monkeypatch, 2, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        constancia.handle(_args(d, sign=True))
    assert [p.name for p in d.iterdir()] == ["ajeno.txt"], "se borra lo propio y nada más"


# ── H5 (mutante Z07): tras un fallo no queda la carpeta que creó el CLI ──

def test_tras_un_fallo_no_queda_la_carpeta_que_creo(motor, llave, tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "verificar_archivos", lambda *a, **k: False)
    d = tmp_path / "nueva" / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert not d.exists(), "quedó la carpeta vacía que el CLI había creado"


# ── H5 (mutantes Z02 y Z03): un enlace simbólico colgante en el destino ──
# Son dos defensas y cada una tapaba la falta de la otra: con las dos rotas a
# la vez la suite quedaba en verde y el CLI escribía fuera de la carpeta.

def _enlace_colgante(tmp_path: Path) -> tuple[Path, Path]:
    fuera = tmp_path / "otro_lugar" / "destino_inesperado.json"
    fuera.parent.mkdir()
    d = tmp_path / "salida"
    d.mkdir()
    (d / "commitment.json").symlink_to(fuera)
    return d, fuera


def test_la_comprobacion_previa_ve_un_enlace_colgante(motor, llave, tmp_path, capsys):
    """Primera defensa. `Path.exists()` sigue el enlace y dice que no hay
    nada: hay que mirar también `is_symlink()`. Se rechaza antes de verificar
    una sola cita."""
    d, fuera = _enlace_colgante(tmp_path)
    assert constancia.handle(_args(d, sign=True)) == 2
    assert "ya existe commitment.json" in _err(capsys)
    assert motor == [], "tenía que rechazarse antes de verificar nada"
    assert not fuera.exists() and (d / "commitment.json").is_symlink()


def test_la_escritura_no_sigue_un_enlace_aunque_la_comprobacion_previa_mienta(motor, llave, tmp_path, monkeypatch, capsys):
    """Segunda defensa. Aquí la comprobación previa no ve nada: solo la
    apertura exclusiva impide escribir a través del enlace."""
    d, fuera = _enlace_colgante(tmp_path)
    monkeypatch.setattr(constancia, "_precheck_commitment", lambda *a, **k: None)
    assert constancia.handle(_args(d, sign=True)) == 2
    assert not fuera.exists(), "se escribió fuera de la carpeta, a través del enlace"
    assert [p.name for p in d.iterdir()] == ["commitment.json"] and (d / "commitment.json").is_symlink()
    assert "COMMITMENT_UNAVAILABLE" in _err(capsys)


def test_la_escritura_no_pisa_un_archivo_aunque_la_comprobacion_previa_mienta(motor, llave, tmp_path, monkeypatch):
    d = tmp_path / "salida"
    d.mkdir()
    (d / "commitment.sig.json").write_text("firma anterior", encoding="utf-8")
    monkeypatch.setattr(constancia, "_precheck_commitment", lambda *a, **k: None)
    assert constancia.handle(_args(d, sign=True)) == 2
    assert (d / "commitment.sig.json").read_text(encoding="utf-8") == "firma anterior"
    assert [p.name for p in d.iterdir()] == ["commitment.sig.json"], "y lo que alcanzó a escribir, se borró"


# ── H4: sin un corpus que nombrar no hay commitment ──

class _ResolverRoto:
    def binding(self):
        raise RuntimeError("el manifest no se pudo leer")


class _ResolverDosCorpus:
    def binding(self):
        return {"corpora": [{"snapshot_hash": "a" * 40}, {"snapshot_hash": "b" * 40}]}


class _ResolverSinManifest:
    def binding(self):
        return {"corpora": [{}]}


class _ResolverConBasura:
    def binding(self):
        return {"corpora": ["no es un objeto"]}


@pytest.mark.parametrize("resolver,etiqueta", [
    (_ResolverRoto, "sin-corpus"), (_ResolverDosCorpus, "varios-corpus"), (_ResolverSinManifest, "sin-manifest"),
    (_ResolverConBasura, "sin-manifest"),
])
def test_sin_un_pack_hash_de_verdad_no_emite(motor, llave, tmp_path, monkeypatch, capsys, resolver, etiqueta):
    """Las citas se verificaron, pero el `pack_hash` es una etiqueta de
    reserva. Antes el CLI emitía y firmaba un commitment que decía `sin-corpus`."""
    monkeypatch.setattr(constancia, "canonical_resolver_for", lambda _cfg, *, as_of=None: (resolver(), ""))
    d = tmp_path / "salida"
    assert constancia.handle(_args(d, sign=True)) == 2
    assert not d.exists()
    err = _err(capsys)
    assert "COMMITMENT_UNAVAILABLE" in err and "pack_hash" in err
    # Control: la constancia sí se imprimió, con la etiqueta a la vista.
    assert motor[-1]["meta"]["pack_hash"] == etiqueta and motor[-1]["meta"]["citas_verificadas"] == 2


def test_el_pack_hash_de_un_solo_corpus_son_sus_16_primeros_hex(motor, llave, tmp_path):
    d = tmp_path / "salida"
    constancia.handle(_args(d, sign=True))
    c = json.loads((d / "commitment.json").read_text(encoding="utf-8"))
    assert c["pack_hash"] == "ea28fa1c0f9af6c1"
    assert constancia._manifest_hash({}) == "ea28fa1c0f9af6c1"
