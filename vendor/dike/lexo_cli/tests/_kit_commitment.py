"""Kit sintético de verificación, compartido por los tests del commitment.

Arma en una carpeta temporal lo que recibe un tercero —`commitment.json`,
`commitment.sig.json`, `content-signing-key.pub` y una copia de
`verificar_tercero.py`— firmado con una llave desechable. La llave real nunca
entra a un test.

`CASOS` son alteraciones de UNA variable sobre ese kit. Las usan el test del
verificador de tercero y el del documento: los tres verificadores (API de
lexo_cli, `verificar_tercero.py` y la receta de `jq` + OpenSSL de KEYS.md)
tienen que dar el mismo veredicto en cada una.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization

from lexo_cli.content_signing import (
    ContentSigningError,
    DuplicateKeyError,
    escribir_firma,
    firmar_commitment,
    generar_content_key,
    leer_clave_publica,
    verificar_archivos,
)

REPO = Path(__file__).resolve().parents[2]
CARPETA_KIT = REPO / "docs" / "hackathon"
VERIFICADOR = CARPETA_KIT / "verificar_tercero.py"

V2 = "dike-content-signature-v2"
V1 = "dike-content-signature-v1"

COMMITMENT = {
    "schema_version": "dike-constancia-commitment-v2",
    "pack_hash": "ea28fa1c0f9af6c1",
    "as_of": "2026-10-05",
    "fecha_constancia": "2026-10-05T09:17:55Z",
    "total_citas": 3,
    "citas_verificadas": 2,
    "citas_fallidas": 1,
    "normas_verificadas": [
        {"gid": "cl.norma.ct:art:0161", "cuerpo": "Código del Trabajo art. 161",
         "vigencia": "IN_FORCE", "vigencia_legible": "vigente",
         "texto_hash": "a" * 64, "fuente_url": "https://ejemplo/1", "estado": "VERIFICADA"},
        {"gid": "cl.norma.ct:art:0162", "cuerpo": "Código del Trabajo art. 162",
         "vigencia": "IN_FORCE", "vigencia_legible": "vigente",
         "texto_hash": "b" * 64, "fuente_url": "https://ejemplo/2", "estado": "VERIFICADA"},
    ],
    # Tildes, comillas, barra invertida y salto de línea: lo que rompe una
    # canonicalización hecha a medias.
    "alcance": "Acredita identidad, integridad y vigencia; «no» la corrección de \"paráfrasis\".\n\tRuta de ejemplo: C:\\tmp — ñandú.",
    "advertencias": ["Diké NO verifica que la norma fundamente lo afirmado."],
}


def pem_publico(llave: Path) -> bytes:
    priv = serialization.load_pem_private_key(llave.read_bytes(), password=None)
    return priv.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


class Kit:
    """Carpeta con los archivos que recibe un tercero."""

    def __init__(self, raiz: Path):
        raiz.mkdir(parents=True, exist_ok=True)
        self.raiz = raiz
        # La llave privada vive FUERA de la carpeta que se entrega.
        self.llave, self.key_id = generar_content_key(raiz.parent / f"{raiz.name}-privada" / "k.pem")
        self.c = raiz / "commitment.json"
        self.s = raiz / "commitment.sig.json"
        self.pub = raiz / "content-signing-key.pub"
        self.c.write_text(
            json.dumps(COMMITMENT, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        self.sobre = firmar_commitment(COMMITMENT, key_path=self.llave)
        escribir_firma(self.sobre, self.s)
        self.pub.write_bytes(pem_publico(self.llave))
        shutil.copyfile(VERIFICADOR, raiz / "verificar_tercero.py")

    def priv(self):
        return serialization.load_pem_private_key(self.llave.read_bytes(), password=None)

    def c_hash(self) -> str:
        raw = json.dumps(COMMITMENT, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def firma_cruda(self, role: str, algorithm: str, schema: str) -> str:
        """Firma V2 hecha a mano para un (rol, algoritmo, esquema) cualquiera."""
        datos = hashlib.sha256(
            f"{role}:{algorithm}:{schema}:{self.c_hash()}".encode()
        ).hexdigest().encode()
        return self.priv().sign(datos).hex()

    def firma_v1(self) -> str:
        return self.priv().sign(bytes.fromhex(self.c_hash())).hex()

    def sobre_dict(self) -> dict:
        return json.loads(self.s.read_text(encoding="utf-8"))

    def reescribir_sobre(self, **cambios) -> None:
        d = self.sobre_dict()
        for k, v in cambios.items():
            if v is None:
                d.pop(k, None)
            else:
                d[k] = v
        self.s.write_text(json.dumps(d, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def reescribir_commitment(self, **cambios) -> None:
        self.c.write_text(
            json.dumps(dict(COMMITMENT, **cambios), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def duplicar_en(self, archivo: Path, clave: str, valor_falso: str) -> None:
        """Antepone una clave repetida: el valor falso queda PRIMERO en el texto."""
        t = archivo.read_text(encoding="utf-8")
        archivo.write_text(t.replace("{", f'{{\n  "{clave}": {valor_falso},', 1), encoding="utf-8")

    def otra_pubkey(self) -> None:
        otra, _ = generar_content_key(self.raiz.parent / f"{self.raiz.name}-otra" / "k.pem")
        self.pub.write_bytes(pem_publico(otra))

    def correr(self, *args: str) -> subprocess.CompletedProcess:
        """Ejecuta el verificador de tercero como lo haría alguien de fuera."""
        argv = list(args) or [str(self.c), str(self.s), str(self.pub)]
        return subprocess.run(
            [sys.executable, str(VERIFICADOR), *argv],
            capture_output=True, text=True, cwd=str(self.raiz), timeout=60,
        )

    def veredicto_api(self) -> bool:
        """True si la API de lexo_cli acepta los mismos archivos."""
        try:
            return verificar_archivos(self.c, self.s, leer_clave_publica(self.pub)) is True
        except (ContentSigningError, DuplicateKeyError, ValueError):
            return False


def _texto(archivo: Path, viejo: str, nuevo: str) -> None:
    t = archivo.read_text(encoding="utf-8")
    assert t.count(viejo) == 1, f"{viejo!r} aparece {t.count(viejo)} veces en {archivo.name}"
    archivo.write_text(t.replace(viejo, nuevo), encoding="utf-8")


def _dentro_del_pem(k: "Kit", trozo: bytes) -> None:
    """Mete `trozo` en medio del base64 de la clave pública."""
    lineas = k.pub.read_bytes().split(b"\n")
    lineas[1] = lineas[1][:20] + trozo + lineas[1][20:]
    k.pub.write_bytes(b"\n".join(lineas))


def _otro_pem(k: "Kit") -> bytes:
    otra, _ = generar_content_key(k.raiz.parent / f"{k.raiz.name}-otra" / "k.pem")
    return pem_publico(otra)


def _con_una_mayuscula(hexa: str) -> str:
    """El mismo valor hexadecimal con una sola letra en mayúscula."""
    i = next(i for i, c in enumerate(hexa) if c in "abcdef")
    return hexa[:i] + hexa[i].upper() + hexa[i + 1:]


def _cero_negativo(k: "Kit") -> None:
    """Un commitment legítimo con un 0, reescrito después como -0 (mismo valor)."""
    con_cero = dict(COMMITMENT, total_citas=2, citas_fallidas=0)
    k.c.write_text(json.dumps(con_cero, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    escribir_firma(firmar_commitment(con_cero, key_path=k.llave), k.s)
    assert k.veredicto_api(), "control: con el 0 escrito normal, verifica"
    _texto(k.c, '"citas_fallidas": 0', '"citas_fallidas": -0')


def _conteo_firmado_a_mano(k: "Kit", fallidas: int) -> None:
    """Reemplaza el kit por un commitment con ese conteo, firmado a mano con la
    llave del kit: la firma es válida para ese contenido."""
    c = dict(COMMITMENT, citas_fallidas=fallidas, total_citas=fallidas + 2)
    k.c.write_text(json.dumps(c, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    h = hashlib.sha256(
        json.dumps(c, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    datos = hashlib.sha256(f"content-integrity:ed25519:{V2}:{h}".encode()).hexdigest().encode()
    k.reescribir_sobre(commitment_hash=h, signature=k.priv().sign(datos).hex())


def _entero_de_16_digitos(k: "Kit") -> None:
    """Un conteo de 16 dígitos, FIRMADO de verdad a mano (el firmador de Diké
    no lo firma). Python lo lee exacto; un jq anterior a 1.7 lo redondea y
    calcula otro hash. Por eso ninguno de los tres lo evalúa."""
    _conteo_firmado_a_mano(k, 10**15)


#: nombre -> alteración de UNA variable sobre el kit legítimo. Estos NO verifican.
CASOS_QUE_NO_VERIFICAN = {
    "commitment_alterado": lambda k: k.reescribir_commitment(citas_verificadas=99),
    "duplicado_en_commitment": lambda k: k.duplicar_en(k.c, "citas_verificadas", "99"),
    "duplicado_en_sobre": lambda k: k.duplicar_en(k.s, "role", '"authorization"'),
    "sin_schema_version": lambda k: k.reescribir_sobre(schema_version=None),
    "sin_role": lambda k: k.reescribir_sobre(role=None),
    "sin_algorithm": lambda k: k.reescribir_sobre(algorithm=None),
    "rol_ajeno": lambda k: k.reescribir_sobre(role="authorization"),
    "rol_con_espacio_final": lambda k: k.reescribir_sobre(role="content-integrity "),
    "rol_ajeno_firmado_de_verdad": lambda k: k.reescribir_sobre(
        role="authorization", signature=k.firma_cruda("authorization", "ed25519", V2)),
    "algorithm_ajeno": lambda k: k.reescribir_sobre(algorithm="rsa"),
    "delimitador_corrido": lambda k: k.reescribir_sobre(
        algorithm="ed25519:ed25519", signature=k.firma_cruda("content-integrity:ed25519", "ed25519", V2)),
    "v1_legitima": lambda k: k.reescribir_sobre(schema_version=V1, signature=k.firma_v1()),
    "v1_reetiquetada_v2": lambda k: k.reescribir_sobre(signature=k.firma_v1()),
    "firma_alterada": lambda k: k.reescribir_sobre(
        signature=("00" if k.sobre_dict()["signature"][:2] != "00" else "11") + k.sobre_dict()["signature"][2:]),
    "firma_no_hex": lambda k: k.reescribir_sobre(signature="ZZZZ"),
    # `bytes.fromhex` ignora espacios: sin un control de formato, Python
    # aceptaba esta firma y OpenSSL no.
    "firma_con_espacio_final": lambda k: k.reescribir_sobre(signature=k.sobre_dict()["signature"] + " "),
    "firma_con_un_byte_de_mas": lambda k: k.reescribir_sobre(signature=k.sobre_dict()["signature"] + "00"),
    "key_id_alterado": lambda k: k.reescribir_sobre(key_id="0" * 16),
    # El commitment intacto y, en el sobre, otro hash bien formado. La firma
    # sigue siendo válida para el contenido: lo único que lo detiene es comparar
    # el hash calculado con el que declara el sobre.
    "hash_del_sobre_cambiado": lambda k: k.reescribir_sobre(commitment_hash="0" * 64),
    "otra_pubkey": lambda k: k.otra_pubkey(),
    # El mismo entero escrito de otra forma. jq lo deja en 2 y Python en 2.0:
    # sin una regla común, un camino aceptaba y el otro no.
    "entero_con_exponente": lambda k: _texto(k.c, '"citas_verificadas": 2', '"citas_verificadas": 2e0'),
    "entero_como_decimal": lambda k: _texto(k.c, '"citas_verificadas": 2', '"citas_verificadas": 2.0'),
    "cero_negativo": _cero_negativo,
    "escape_de_surrogate_suelto": lambda k: _texto(k.c, "Acredita identidad", "Acredita \\ud800 identidad"),
    "sobre_que_es_una_lista": lambda k: k.s.write_text("[]", encoding="utf-8"),
    "commitment_vacio": lambda k: k.c.write_text("{}", encoding="utf-8"),
    # ── Reauditoría 2 (H1): entradas en que la receta sin Python verificaba y
    # los otros dos no. `jq` lee 02 y +2 como 2; `$(…)` en bash quita los saltos
    # de línea finales y descarta los bytes nulos antes de comparar; `basenc`
    # ignora los saltos de línea.
    "entero_con_cero_a_la_izquierda": lambda k: _texto(k.c, '"citas_verificadas": 2', '"citas_verificadas": 02'),
    "entero_con_signo_mas": lambda k: _texto(k.c, '"citas_verificadas": 2', '"citas_verificadas": +2'),
    "entero_de_16_digitos_firmado_de_verdad": _entero_de_16_digitos,
    "byte_nulo_al_final_del_commitment": lambda k: k.c.write_bytes(k.c.read_bytes() + b"\x00"),
    # El archivo de la clave tiene una sola escritura. `cryptography` ignora un
    # carácter suelto dentro del PEM y OpenSSL no: la misma clave verificaba
    # por un camino y no por el otro.
    "clave_publica_con_un_tabulador_vertical_dentro": lambda k: _dentro_del_pem(k, b"\x0b"),
    "clave_publica_con_un_espacio_duro_dentro": lambda k: _dentro_del_pem(k, b"\xc2\xa0"),
    "clave_publica_con_texto_antes": lambda k: k.pub.write_bytes(b"clave de Dike\n" + k.pub.read_bytes()),
    "clave_publica_con_bom": lambda k: k.pub.write_bytes(b"\xef\xbb\xbf" + k.pub.read_bytes()),
    "clave_publica_con_otra_clave_detras": lambda k: k.pub.write_bytes(k.pub.read_bytes() + _otro_pem(k)),
    "clave_publica_con_una_linea_en_blanco_dentro": lambda k: k.pub.write_bytes(
        k.pub.read_bytes().replace(b"-----\n", b"-----\n\n", 1)),
    "firma_con_salto_final": lambda k: k.reescribir_sobre(signature=k.sobre_dict()["signature"] + "\n"),
    "firma_con_salto_en_medio": lambda k: k.reescribir_sobre(
        signature=k.sobre_dict()["signature"][:64] + "\n" + k.sobre_dict()["signature"][64:]),
    "key_id_con_salto_final": lambda k: k.reescribir_sobre(key_id=k.sobre_dict()["key_id"] + "\n"),
    "hash_con_salto_final": lambda k: k.reescribir_sobre(commitment_hash=k.sobre_dict()["commitment_hash"] + "\n"),
    "algorithm_con_salto_final": lambda k: k.reescribir_sobre(algorithm="ed25519\n"),
    "rol_con_nul_en_medio": lambda k: k.reescribir_sobre(role="content\x00-integrity"),
    "key_id_con_nul_en_medio": lambda k: k.reescribir_sobre(
        key_id=k.sobre_dict()["key_id"][:4] + "\x00" + k.sobre_dict()["key_id"][4:]),
    "schema_version_con_nul_final": lambda k: k.reescribir_sobre(schema_version=V2 + "\x00"),
    "key_id_en_mayusculas": lambda k: k.reescribir_sobre(key_id=_con_una_mayuscula(k.sobre_dict()["key_id"])),
    "hash_en_mayusculas": lambda k: k.reescribir_sobre(
        commitment_hash=_con_una_mayuscula(k.sobre_dict()["commitment_hash"])),
    # Dos documentos en un archivo: `jq` los procesa todos y se queda con el
    # último; un primer documento con la firma vacía dejaba pasar al segundo.
    "sobre_con_dos_documentos": lambda k: k.s.write_text(
        '{"signature": ""}\n' + k.s.read_text(encoding="utf-8"), encoding="utf-8"),
    "commitment_con_dos_documentos": lambda k: k.c.write_text(
        k.c.read_text(encoding="utf-8") + "{}\n", encoding="utf-8"),
    # ── Reauditoría 2 (H2): el sobre es cerrado y tiene una sola escritura.
    # Antes estos dos verificaban, y el documento decía que alterar el sobre
    # hacía fallar los dos caminos.
    "campo_de_mas_en_el_sobre": lambda k: k.reescribir_sobre(firmante="Corte Suprema"),
    "firma_en_mayusculas": lambda k: k.reescribir_sobre(signature=k.sobre_dict()["signature"].upper()),
    "firma_con_una_mayuscula": lambda k: k.reescribir_sobre(
        signature=_con_una_mayuscula(k.sobre_dict()["signature"])),
}

#: Cambios de FORMA del archivo que no tocan ningún valor. Estos SÍ verifican,
#: y los tres verificadores tienen que estar de acuerdo también en eso.
CASOS_QUE_VERIFICAN = {
    "positivo": lambda k: None,
    "compacto_y_reordenado": lambda k: k.c.write_text(
        json.dumps(dict(reversed(list(COMMITMENT.items()))), ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8"),
    "saltos_crlf": lambda k: k.c.write_bytes(k.c.read_bytes().replace(b"\n", b"\r\n")),
    "bom_en_el_commitment": lambda k: k.c.write_bytes(b"\xef\xbb\xbf" + k.c.read_bytes()),
    "bom_en_el_sobre": lambda k: k.s.write_bytes(b"\xef\xbb\xbf" + k.s.read_bytes()),
    "escape_unicode_equivalente": lambda k: _texto(k.c, "Código del Trabajo art. 161", "C\\u00f3digo del Trabajo art. 161"),
    "escape_unicode_equivalente_en_el_sobre": lambda k: _texto(k.s, '"content-integrity"', '"content-integrit\\u0079"'),
    "sobre_compacto_y_reordenado": lambda k: k.s.write_text(
        json.dumps(dict(reversed(list(k.sobre_dict().items()))), separators=(",", ":")), encoding="utf-8"),
    "clave_publica_con_crlf": lambda k: k.pub.write_bytes(k.pub.read_bytes().replace(b"\n", b"\r\n")),
    "clave_publica_sin_salto_final": lambda k: k.pub.write_bytes(k.pub.read_bytes().rstrip(b"\n")),
    # total_citas = 999.999.999.999.999: el mayor que cabe en 15 dígitos.
    "entero_de_15_digitos_firmado_de_verdad": lambda k: _conteo_firmado_a_mano(k, 10**15 - 3),
}

CASOS = {**CASOS_QUE_VERIFICAN, **CASOS_QUE_NO_VERIFICAN}


def debe_verificar(caso: str) -> bool:
    return caso in CASOS_QUE_VERIFICAN
