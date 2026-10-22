"""Tests del verificador de tercero (`docs/hackathon/verificar_tercero.py`).

Es el archivo que ejecuta alguien de fuera, y hasta el 2026-10-05 no tenía un
solo test: la reauditoría lo probó a mano. Aquí se ejecuta como lo ejecutaría
un tercero —por subproceso, sin importar nada— y se fija su contrato de salida:

    0  verificado
    1  NO verificado: los archivos se leyeron, pero algo no cuadra
    2  no se pudo evaluar: uso incorrecto, archivo ilegible, JSON inválido o
       con claves duplicadas, sobre incompleto o con un campo de más

REGLA H12: cada negativo altera UNA variable sobre el positivo y comprueba el
motivo impreso, no solo el código de salida.
"""

from __future__ import annotations

import ast
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from lexo_cli.tests._kit_commitment import CASOS, COMMITMENT, V1, V2, VERIFICADOR, Kit, debe_verificar


@pytest.fixture
def kit(tmp_path) -> Kit:
    return Kit(tmp_path / "kit")


# ── Independencia: el verificador no usa nuestro código ──

def test_no_importa_nada_de_lexo_cli():
    arbol = ast.parse(VERIFICADOR.read_text(encoding="utf-8"))
    modulos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Import):
            modulos.update(a.name.split(".")[0] for a in nodo.names)
        elif isinstance(nodo, ast.ImportFrom) and nodo.module:
            modulos.add(nodo.module.split(".")[0])
    assert modulos <= {"__future__", "hashlib", "json", "sys", "pathlib", "cryptography"}, modulos


# ── Positivos ──

def test_positivo_verifica_e_imprime_el_key_id(kit):
    r = kit.correr()
    assert r.returncode == 0, r.stdout + r.stderr
    assert "RESULTADO: VERIFICADO" in r.stdout
    assert kit.key_id in r.stdout


def test_positivo_el_formato_del_archivo_no_importa(kit):
    """Reordenar o compactar el JSON conserva el hash canónico."""
    kit.c.write_text(json.dumps(COMMITMENT, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    assert kit.correr().returncode == 0


def test_la_salida_no_atribuye_a_dike_la_correccion_sustantiva(kit):
    """I2: antes imprimía que la corrección sustantiva «la verificó Diké»."""
    salida = kit.correr().stdout
    assert "verificó Diké" not in salida
    assert "Diké NO verifica" in salida


# ── Exit 1: NO verificado ──

def test_commitment_alterado(kit):
    kit.c.write_text(json.dumps(dict(COMMITMENT, citas_verificadas=99), ensure_ascii=False), encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 1
    assert "NO COINCIDE" in r.stdout and "VERIFICADO" not in r.stdout.replace("NO VERIFICADO", "")


def test_clave_parecida_no_es_duplicado_pero_cambia_el_hash(kit):
    texto = kit.c.read_text(encoding="utf-8").replace('"citas_verificadas"', '"Citas_verificadas"')
    kit.c.write_text(texto, encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 1 and "NO COINCIDE" in r.stdout


def test_firma_con_un_digito_cambiado(kit):
    f = kit.sobre_dict()["signature"]
    kit.reescribir_sobre(signature=("0" if f[0] != "0" else "1") + f[1:])
    r = kit.correr()
    assert r.returncode == 1 and "INVÁLIDA" in r.stdout


def test_otra_llave(kit):
    kit.otra_pubkey()
    r = kit.correr()
    assert r.returncode == 1 and "no fue hecha con esta llave" in r.stdout


def test_key_id_alterado(kit):
    kit.reescribir_sobre(key_id="0" * 16)
    r = kit.correr()
    assert r.returncode == 1 and "no fue hecha con esta llave" in r.stdout


def test_rol_ajeno(kit):
    kit.reescribir_sobre(role="authorization")
    r = kit.correr()
    assert r.returncode == 1 and "role" in r.stdout


def test_rol_ajeno_firmado_de_verdad(kit):
    """Una firma legítima para OTRO rol tampoco pasa: no es un commitment."""
    kit.reescribir_sobre(role="authorization", signature=kit.firma_cruda("authorization", "ed25519", V2))
    assert kit.correr().returncode == 1


def test_algorithm_ajeno(kit):
    kit.reescribir_sobre(algorithm="rsa")
    r = kit.correr()
    assert r.returncode == 1 and "algorithm" in r.stdout


def test_corrimiento_del_delimitador(kit):
    """R4: firma hecha para role='content-integrity:ed25519', presentada como
    content-integrity con algorithm='ed25519:ed25519'. Mismos bytes firmados."""
    kit.reescribir_sobre(
        algorithm="ed25519:ed25519",
        signature=kit.firma_cruda("content-integrity:ed25519", "ed25519", V2),
    )
    r = kit.correr()
    assert r.returncode == 1 and "algorithm" in r.stdout


def test_v1_legitima_se_rechaza(kit):
    """KEYS.md decía que el verificador «acepta» V1. No: la rechaza (K4)."""
    kit.reescribir_sobre(schema_version=V1, signature=kit.firma_v1())
    r = kit.correr()
    assert r.returncode == 1
    assert "V1" in r.stdout and "RESULTADO: VERIFICADO" not in r.stdout


def test_v2_reetiquetada_como_v1(kit):
    kit.reescribir_sobre(schema_version=V1)
    assert kit.correr().returncode == 1


def test_v1_reetiquetada_como_v2(kit):
    kit.reescribir_sobre(signature=kit.firma_v1())
    r = kit.correr()
    assert r.returncode == 1 and "INVÁLIDA" in r.stdout


def test_pubkey_que_no_es_ed25519(kit):
    otra = ec.generate_private_key(ec.SECP256R1()).public_key()
    kit.pub.write_bytes(otra.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ))
    r = kit.correr()
    assert r.returncode == 1 and "Ed25519" in r.stdout


# ── Exit 2: no se pudo evaluar ──

def _duplicar(texto: str, antes: str, falso: str) -> str:
    assert texto.count(antes) == 1
    return texto.replace(antes, falso + antes)


def test_duplicado_primer_nivel_falso_primero(kit):
    kit.duplicar_en(kit.c, "citas_verificadas", "99")
    assert json.loads(kit.c.read_text(encoding="utf-8"))["citas_verificadas"] == 2, "control: la última gana"
    r = kit.correr()
    assert r.returncode == 2 and "duplicadas" in r.stdout and "citas_verificadas" in r.stdout


def test_duplicado_primer_nivel_falso_ultimo(kit):
    t = kit.c.read_text(encoding="utf-8").rstrip()
    assert t.endswith("}")
    kit.c.write_text(t[:-1].rstrip() + ',\n  "citas_verificadas": 99\n}\n', encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2 and "duplicadas" in r.stdout


def test_duplicado_anidado(kit):
    t = kit.c.read_text(encoding="utf-8")
    kit.c.write_text(_duplicar(t, '"estado": "VERIFICADA",\n      "fuente_url": "https://ejemplo/1"',
                               '"estado": "FALLO",\n      '), encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2 and "estado" in r.stdout


def test_duplicado_por_escape_unicode(kit):
    t = kit.c.read_text(encoding="utf-8")
    kit.c.write_text(t.replace("{", '{\n  "citas_\\u0076erificadas": 99,', 1), encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2 and "duplicadas" in r.stdout


def test_duplicado_en_el_sobre(kit):
    kit.duplicar_en(kit.s, "role", '"authorization"')
    r = kit.correr()
    assert r.returncode == 2 and "role" in r.stdout


@pytest.mark.parametrize("campo", ["schema_version", "role", "algorithm", "key_id", "commitment_hash", "signature"])
def test_sobre_sin_un_campo(kit, campo):
    """L2: sin `schema_version` lexo_cli aceptaba y este verificador no.
    Ahora los dos rechazan cualquier sobre incompleto."""
    kit.reescribir_sobre(**{campo: None})
    r = kit.correr()
    assert r.returncode == 2 and campo in r.stdout
    assert "Traceback" not in r.stderr


def test_firma_que_no_es_hex(kit):
    kit.reescribir_sobre(signature="ZZZZ_no_es_hex")
    r = kit.correr()
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_sobre_con_un_campo_de_mas(kit):
    """Reauditoría 2 (H2). El sobre es cerrado: un campo que la firma no cubre
    no se ignora, se rechaza, y el mensaje lo nombra."""
    kit.reescribir_sobre(firmante="Corte Suprema")
    r = kit.correr()
    assert r.returncode == 2 and "firmante" in r.stdout
    assert "RESULTADO: NO SE PUDO EVALUAR" in r.stdout and "Traceback" not in r.stderr


def test_firma_en_mayusculas(kit):
    """La firma tiene una sola escritura. En mayúsculas es otro valor en el
    sobre, y cambiar un valor del sobre lo invalida."""
    kit.reescribir_sobre(signature=kit.sobre_dict()["signature"].upper())
    r = kit.correr()
    assert r.returncode == 2 and "minúsculas" in r.stdout and "Traceback" not in r.stderr


def test_nan_no_es_evaluable(kit):
    """Reauditoría 2 (H5, W03). `NaN` no es JSON: la entrada no se evalúa.
    Sin este control salía 1 por otra razón (el hash no coincide) y un test
    que solo pide «no verifica» no lo distinguía."""
    t = kit.c.read_text(encoding="utf-8")
    assert t.count('"citas_fallidas": 1') == 1
    kit.c.write_text(t.replace('"citas_fallidas": 1', '"citas_fallidas": NaN'), encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2, r.stdout + r.stderr
    assert "NaN" in r.stdout and "Traceback" not in r.stderr


def test_surrogate_suelto_no_hace_caer_al_verificador(kit):
    """Reauditoría 2 (H5, W05). Un `\\ud800` suelto no se puede codificar en
    UTF-8. Un traceback también sale distinto de 0: aquí se exige la salida 2
    con su mensaje, no una caída."""
    t = kit.c.read_text(encoding="utf-8")
    kit.c.write_text(t.replace("Acredita identidad", "Acredita \\ud800 identidad"), encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2, r.stdout + r.stderr
    assert "Unicode" in r.stdout and "Traceback" not in r.stderr


@pytest.mark.parametrize("texto", ['{"a":', "[1, 2]", '"cadena"', ""])
def test_commitment_que_no_es_un_objeto_json(kit, texto):
    kit.c.write_text(texto, encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_archivo_inexistente(kit):
    r = kit.correr(str(kit.raiz / "no_existe.json"), str(kit.s), str(kit.pub))
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_pubkey_ilegible(kit):
    kit.pub.write_text("esto no es un PEM", encoding="utf-8")
    r = kit.correr()
    assert r.returncode == 2 and "Traceback" not in r.stderr


def test_uso_incorrecto(kit):
    r = kit.correr(str(kit.c))
    assert r.returncode == 2 and "Uso" in r.stdout


# ── Los dos verificadores coinciden ──

@pytest.mark.parametrize("caso", sorted(CASOS))
def test_la_api_y_el_verificador_de_tercero_dan_el_mismo_veredicto(kit, caso):
    CASOS[caso](kit)
    tercero = kit.correr().returncode == 0
    api = kit.veredicto_api()
    assert tercero == api, f"{caso}: tercero={'acepta' if tercero else 'rechaza'}, API={'acepta' if api else 'rechaza'}"
    assert tercero == debe_verificar(caso)
