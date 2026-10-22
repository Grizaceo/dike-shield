"""Firma de contenido: la capa que permite verificar sin confiarnos ni en red.

DISEÑO (decidido 2026-10-05, tras grounding en Ley 19.799 y práctica de
RFC 3161 vs OpenTimestamps):

Esta capa firma el COMMITMENT, no el escrito. Su alcance exacto es:

  SÍ acredita  — que el commitment no se alteró después de firmado.
                 Verificable por un tercero sin credenciales, sin red y sin
                 acceso a nuestros sistemas: con `verificar_tercero.py` o con
                 `jq` + coreutils + OpenSSL 3 (receta en docs/hackathon/KEYS.md,
                 ejecutada por test_keys_md_ejecutable.py).

  NO acredita  — que la fecha tenga valor legal en Chile. Para eso la
                 Ley 19.799 art. 5º Nº 2 exige "un fechado electrónico
                 otorgado por un prestador acreditado". Ni esta firma ni un
                 proof OpenTimestamps cumplen eso. Decir lo contrario sería
                 falso, y está escrito aquí para que nadie lo prometa.

  NO acredita  — quién firmó. La firma prueba QUE se firmó con esta llave,
                 no QUIÉN es el titular. Lo que la Ley 19.799 prevé para dar
                 fe de ese vínculo es el certificado de firma electrónica
                 (art. 2º letra b), que otorga un prestador de servicios de
                 certificación (art. 11). Esta llave no tiene certificado: su
                 titularidad habría que probarla por otros medios, conforme a
                 las reglas generales (art. 5º, inciso final). Fuera de alcance.

ROL DE LLAVE — regla de operación:

  `signing-key.pem`                  → AUTORIZACIÓN. Firma las propuestas
                                      `nif_patch` (write_service, HITL-5).
  `content-signing-key.pem` (esta)   → INTEGRIDAD. Firma commitments.

Nunca la misma llave. Comprometer la de autorización no debe exponer la de
contenido, ni al revés. Qué hace cumplir el código y qué no:

  · `content_key_path` nunca cae a `signing_key_path`.
  · La firma V2 liga el rol: una firma de un rol no verifica como otro.
  · `firmar_commitment` se niega a firmar si las dos rutas configuradas son
    el mismo archivo, también a través de un enlace simbólico.
  · Lo que NO detecta: una COPIA de la misma llave guardada en otro archivo.

Por qué firmar el HASH y no el JSON: el hash canónico no depende del orden de
las claves ni de la indentación, así que reordenar o reindentar el archivo
conserva la firma. Agregar, quitar o cambiar un campo o un valor SÍ la invalida
(`CommitmentAlteradoError`): eso es lo que la firma protege.

CONTRATO V2 (2026-10-05, post-auditoría Opus 5.5):
  Se firman los 64 caracteres hex de
      sha256("role:algorithm:schema_version:commitment_hash")
  Esto impide replay entre roles con una misma llave.
  `role` sale de una lista cerrada y `algorithm` se valida: sin eso el «:»
  es ambiguo (una firma para el rol "content-integrity:ed25519" verificaba
  como "content-integrity").
  El verificador independiente (docs/hackathon/verificar_tercero.py) NO importa
  lexo_cli, y los dos deben dar el mismo veredicto sobre los mismos archivos
  (test_verificar_tercero.py).
  V1 (legacy): firmaba solo commitment_hash, sin ligar el rol. No se emite, y
  nunca se publicó ninguna; `verificar_commitment_legacy` existe para leerlas.

LO QUE SE FIRMA TIENE QUE SER PUBLICABLE:
  `firmar_commitment` pasa el commitment por `commitment.validar_publicable`
  antes de firmar. Una firma no se puede retirar; por eso el último control
  está aquí y no solo en quien arma el commitment.
"""
from __future__ import annotations

import hashlib
import json
import os
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from lexo_cli.commitment import (
    HuellaPublicadaWarning,
    tiene_huella,
    validar_publicable,
)

CONTENT_SIGNATURE_SCHEMA_VERSION = "dike-content-signature-v2"
_SCHEMA_V1 = "dike-content-signature-v1"
_ALGORITMO = "ed25519"

_ENV_KEY_PATH = "LEXO_CONTENT_SIGNING_KEY_PATH"
_CFG_KEY_PATH = ("custody", "content_signing_key_path")
# La llave del OTRO rol. Se lee solo su ruta, para negarse a usar el mismo archivo.
_ENV_AUTH_KEY_PATH = "LEXO_CUSTODY_SIGNING_KEY_PATH"
_CFG_AUTH_KEY_PATH = ("custody", "signing_key_path")

#: Rol declarado en el sobre. Evita que alguien confunda esta firma con la de
#: autorización y la use como si acreditara quién firmó.
_ROL = "content-integrity"

#: Lista CERRADA de roles. Un rol es parte de los bytes firmados, separado por
#: «:»; si fuera texto libre, "content-integrity:ed25519" y "content-integrity"
#: darían los mismos bytes con otro reparto de campos. «authorization» está
#: aquí para que una futura firma V2 de ese rol no pueda chocar con esta, y
#: para poder decir «esperaba ese rol» al verificar. Este módulo no lo firma:
#: `firmar_commitment` solo emite `content-integrity`.
ROLES_VALIDOS = frozenset({_ROL, "authorization"})

_CAMPOS_SOBRE = ("schema_version", "role", "algorithm", "key_id", "commitment_hash", "signature")


class ContentSigningError(RuntimeError):
    """No se puede firmar o el sobre no es utilizable: falta llave, modo
    incorrecto, llave corrupta, sobre incompleto, rol o algoritmo inesperados."""


class DuplicateKeyError(ValueError):
    """El JSON de entrada tiene claves duplicadas."""


class CommitmentAlteradoError(ValueError):
    """El commitment no corresponde al que se firmó (hash distinto)."""


@dataclass(frozen=True)
class ContentSignature:
    """Sobre de firma de contenido. Solo hashes y material público."""

    key_id: str
    algorithm: str
    commitment_hash: str
    signature_hex: str
    role: str
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "role": self.role,
            "algorithm": self.algorithm,
            "key_id": self.key_id,
            "commitment_hash": self.commitment_hash,
            "signature": self.signature_hex,
        }

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ContentSignature":
        """Lee un sobre. SIN valores por defecto y SIN campos de más.

        Antes `role`, `algorithm` y `schema_version` se rellenaban si faltaban,
        y un sobre sin `schema_version` verificaba aquí mientras el verificador
        de tercero lo rechazaba. Dos verificadores que discrepan no sirven.
        """
        if not isinstance(d, dict):
            raise ContentSigningError("el sobre no es un objeto JSON")
        faltan = [k for k in _CAMPOS_SOBRE if not isinstance(d.get(k), str)]
        if faltan:
            raise ContentSigningError(
                f"sobre incompleto, faltan o no son cadenas: {faltan}"
            )
        # Cerrado, como el commitment: un campo de más no está firmado, y quien
        # lo lee junto a una firma válida podría darlo por acreditado.
        sobran = sorted(set(d) - set(_CAMPOS_SOBRE))
        if sobran:
            raise ContentSigningError(
                f"el sobre trae campos que la firma no cubre: {sobran}"
            )
        return ContentSignature(
            key_id=d["key_id"],
            algorithm=d["algorithm"],
            commitment_hash=d["commitment_hash"],
            signature_hex=d["signature"],
            role=d["role"],
            schema_version=d["schema_version"],
        )


# ── llave ────────────────────────────────────────────────────────────────


def content_key_path(cfg: dict | None = None) -> Path:
    """Ruta de la llave de contenido. Fail-closed si no hay ninguna.

    NUNCA cae a `signing_key_path`: son roles distintos y la confusión sería
    exactamente el fallo que la regla dura busca evitar.
    """
    env = os.environ.get(_ENV_KEY_PATH)
    if env:
        return Path(env).expanduser()
    value: Any = cfg or {}
    for part in _CFG_KEY_PATH:
        value = value.get(part) if isinstance(value, dict) else None
    if not value:
        raise ContentSigningError(
            "SIGNATURE_UNAVAILABLE: no hay llave de contenido configurada "
            f"({_ENV_KEY_PATH} o custody.content_signing_key_path). "
            "La llave de autorización NO sirve para esto."
        )
    return Path(str(value)).expanduser()


def _ruta_llave_autorizacion(cfg: dict | None) -> Path | None:
    env = os.environ.get(_ENV_AUTH_KEY_PATH)
    if env:
        return Path(env).expanduser()
    value: Any = cfg or {}
    for part in _CFG_AUTH_KEY_PATH:
        value = value.get(part) if isinstance(value, dict) else None
    return Path(str(value)).expanduser() if value else None


def _assert_no_es_la_llave_de_autorizacion(path: Path, cfg: dict | None) -> None:
    """Se niega a firmar commitments con el archivo de la llave de autorización.

    Compara archivos, no cadenas: un enlace simbólico o una ruta relativa al
    mismo archivo también se rechazan. Lo que NO detecta es una COPIA de la
    misma llave guardada en otro archivo: eso exigiría leer la otra llave, y
    este módulo no la toca.
    """
    auth = _ruta_llave_autorizacion(cfg)
    if auth is None:
        return
    try:
        misma = os.path.samefile(path, auth)
    except OSError:
        return  # alguna de las dos no existe: no pueden ser el mismo archivo
    if misma:
        raise ContentSigningError(
            "ROLE_KEY_REUSE: la llave de contenido y la de autorización son el "
            "mismo archivo. Son roles distintos y llevan llaves distintas."
        )


def _load_content_private_key(path: Path) -> Ed25519PrivateKey:
    if not path.is_file():
        raise ContentSigningError(f"llave de contenido no existe: {path}")
    mode = path.stat().st_mode & 0o777
    if mode != 0o600:
        raise ContentSigningError(f"la llave de contenido debe ser 0600, tiene {oct(mode)}")
    try:
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (ValueError, TypeError) as exc:
        raise ContentSigningError(
            f"la llave de contenido no se pudo leer ({type(exc).__name__})"
        ) from exc
    if not isinstance(key, Ed25519PrivateKey):
        raise ContentSigningError(f"se esperaba Ed25519, hay {type(key).__name__}")
    return key


def comprobar_llave_de_contenido(cfg: dict | None = None) -> str:
    """Comprueba que se podrá firmar, sin firmar nada. Devuelve el `key_id`.

    Para quien quiere fallar ANTES de hacer el trabajo: hay llave configurada,
    existe, es 0600, es Ed25519 y no es el archivo de la de autorización.
    """
    path = content_key_path(cfg)
    _assert_no_es_la_llave_de_autorizacion(path, cfg)
    return derive_key_id(_load_content_private_key(path).public_key())


def derive_key_id(public_key: Ed25519PublicKey) -> str:
    """Fingerprint SHA-256 de la clave pública. No expone material privado."""
    raw = public_key.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    return hashlib.sha256(raw).hexdigest()[:16]


def _crear_directorio_privado(directorio: Path) -> None:
    """Crea los directorios que falten con modo 0700. No toca los que existen."""
    faltan: list[Path] = []
    actual = directorio
    while not actual.exists():
        faltan.append(actual)
        if actual.parent == actual:
            break
        actual = actual.parent
    for nuevo in reversed(faltan):
        try:
            os.mkdir(nuevo, 0o700)
        except FileExistsError:
            continue  # lo creó otro proceso: no es nuestro, no se le cambia el modo
        os.chmod(nuevo, 0o700)  # el umask puede haber recortado el modo de mkdir


def generar_content_key(destino: str | Path) -> tuple[Path, str]:
    """Crea la llave de contenido (Ed25519, 0600 desde creación). Devuelve (ruta, key_id).

    NO sobrescribe una llave existente: hacerlo invalidaría commitments ya
    firmados. Para rotar hay que generar una nueva y republicar el mapa de
    llaves por `key_id`.

    La creación es atómica (`O_EXCL`): no hay un «¿existe?» previo que otro
    proceso pueda ganar, y un enlace simbólico en `destino` —colgante o no— se
    rechaza en vez de seguirse.
    """
    p = Path(destino).expanduser()
    _crear_directorio_privado(p.parent)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(str(p), flags, 0o600)
    except FileExistsError:
        raise ContentSigningError(f"ya existe llave en {p}; no se sobrescribe") from None
    try:
        # Un umask muy restrictivo deja menos de 0600; nunca más. Se ajusta
        # sobre el descriptor, no sobre la ruta.
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(pem)
    except BaseException:
        p.unlink(missing_ok=True)
        raise
    return p, derive_key_id(key.public_key())


def content_public_key(cfg: dict | None = None) -> Ed25519PublicKey:
    """Clave pública para verificar. Puede salir del repo público."""
    return _load_content_private_key(content_key_path(cfg)).public_key()


def content_public_pem(cfg: dict | None = None, *, key_path: str | Path | None = None) -> bytes:
    """Pubkey en PEM, para publicar. No expone material privado.

    Con `key_path` se deriva de ESA llave: quien firma con una ruta explícita
    publica la pubkey de la misma ruta, no la de la configuración.
    """
    path = Path(key_path).expanduser() if key_path else content_key_path(cfg)
    return _load_content_private_key(path).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )


def leer_clave_publica(path: str | Path) -> Ed25519PublicKey:
    """Lee de disco una clave pública Ed25519 en PEM, en su forma canónica.

    Es lo que debe usar quien verifica con un ARCHIVO de clave. `cryptography`
    ignora caracteres sueltos dentro del PEM (un tabulador vertical, un espacio
    duro) y OpenSSL no: el mismo archivo verificaba por un camino y no por el
    otro. Aquí vale una sola escritura, la que emiten los dos. Se admiten el
    salto de línea de Windows y que falte el salto final; nada más: ni texto
    antes, ni un BOM, ni una segunda clave detrás.
    """
    nombre = Path(path).name
    try:
        pem = Path(path).read_bytes()
        key = serialization.load_pem_public_key(pem)
    except OSError as exc:
        raise ContentSigningError(f"no se pudo leer {nombre} ({type(exc).__name__})") from exc
    except (ValueError, TypeError) as exc:
        raise ContentSigningError(f"{nombre} no es una clave pública PEM") from exc
    pem = pem.replace(b"\r", b"")
    if not pem.endswith(b"\n"):
        pem += b"\n"
    if pem != key.public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo):
        raise ContentSigningError(f"{nombre} no es una clave pública PEM en su forma canónica")
    if not isinstance(key, Ed25519PublicKey):
        raise ContentSigningError(f"se esperaba una clave pública Ed25519, hay {type(key).__name__}")
    return key


# ── validación de entrada ────────────────────────────────────────────────


def _pares_sin_duplicados(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: dict[str, int] = {}
    for k, _v in pairs:
        seen[k] = seen.get(k, 0) + 1
    dups = [k for k, n in seen.items() if n > 1]
    if dups:
        raise DuplicateKeyError(f"claves JSON duplicadas: {dups}")
    return dict(pairs)


def _constante_no_json(nombre: str) -> Any:
    raise ContentSigningError(f"JSON inválido: {nombre} no es un valor JSON")


def _numero_no_entero(literal: str) -> Any:
    raise ContentSigningError(
        f"número no admitido ({literal}): un commitment solo lleva enteros simples"
    )


def _entero_canonico(literal: str) -> int:
    if literal == "-0":
        raise ContentSigningError("número no admitido (-0): un commitment solo lleva enteros simples")
    # Hasta 15 dígitos: un lector de doble precisión (jq antes de 1.7) redondea
    # los enteros más largos, y su hash canónico saldría distinto del nuestro.
    if len(literal.lstrip("-")) > 15:
        raise ContentSigningError("número no admitido: un commitment solo lleva enteros de hasta 15 dígitos")
    return int(literal)


def _loads_estricto(text: str) -> Any:
    # Un entero se puede escribir de varias formas (2, 2e0, 2.0; 0 y -0) y
    # cada herramienta las normaliza a su manera: `jq` deja 2e0 en 2 y Python
    # lo vuelve 2.0. Para que todos los verificadores den el mismo veredicto,
    # la única forma admitida es el entero simple.
    try:
        return json.loads(
            text,
            object_pairs_hook=_pares_sin_duplicados,
            parse_constant=_constante_no_json,
            parse_float=_numero_no_entero,
            parse_int=_entero_canonico,
        )
    except DuplicateKeyError:
        raise
    except json.JSONDecodeError:
        raise ContentSigningError("JSON inválido") from None


def reject_duplicate_keys(text: str) -> None:
    """Rechaza texto JSON con claves duplicadas, a cualquier profundidad.

    `json.loads` corriente se queda con la ÚLTIMA aparición: un archivo puede
    mostrar primero un valor falso y verificar con el verdadero.
    """
    _loads_estricto(text)


def leer_json_estricto(path: str | Path) -> dict[str, Any]:
    """Lee un commitment o un sobre desde disco. Rechaza claves duplicadas,
    constantes que no son JSON (NaN, Infinity), números que no sean enteros
    simples de hasta 15 dígitos y raíces que no son un objeto. Tolera un BOM
    inicial."""
    try:
        text = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        raise ContentSigningError(
            f"no se pudo leer {Path(path).name} ({type(exc).__name__})"
        ) from exc
    data = _loads_estricto(text)
    if not isinstance(data, dict):
        raise ContentSigningError(f"{Path(path).name}: la raíz no es un objeto JSON")
    return data


# ── firma ─────────────────────────────────────────────────────────────────


def commitment_hash(commitment: dict[str, Any]) -> str:
    """Hash canónico del commitment. Estable: mismo contenido, mismo hash."""
    raw = json.dumps(
        commitment, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _datos_firma(sobre: ContentSignature) -> bytes:
    """Bytes firmados: role + algorithm + schema_version + commitment_hash.

    Contrato V2: separación de dominio explícita. Una firma de content-integrity
    no verifica como authorization, y viceversa.
    """
    raw = (
        sobre.role + ":" + sobre.algorithm + ":" + sobre.schema_version + ":" + sobre.commitment_hash
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest().encode("utf-8")


_HEX = frozenset("0123456789abcdef")


def _firma_a_bytes(firma_hex: str) -> bytes:
    """64 bytes en hexadecimal, exactos y en minúsculas, que es como se emiten.
    `bytes.fromhex` a secas ignora los espacios, y una firma con un espacio de
    más verificaba aquí y no con OpenSSL. Las mayúsculas se rechazan para que
    un sobre firmado tenga una sola escritura: cambiar cualquier valor lo
    invalida."""
    if len(firma_hex) != 128 or not set(firma_hex) <= _HEX:
        raise ValueError("la firma del sobre no son 64 bytes en hexadecimal (minúsculas)")
    return bytes.fromhex(firma_hex)


def firmar_commitment(
    commitment: dict[str, Any],
    *,
    cfg: dict | None = None,
    key_path: str | Path | None = None,
    role: str = _ROL,
    permitir_huella: bool = False,
) -> ContentSignature:
    """Firma el commitment. Devuelve el sobre; no escribe nada en disco.

    Contrato V2: la firma cubre role + algorithm + schema_version + commitment_hash.

    Antes de firmar comprueba que el commitment sea publicable
    (`validar_publicable`): solo las claves del esquema, ningún dato personal
    de alta certeza, conteos que cuadran. La huella del escrito
    (`document_sha256`) se rechaza salvo `permitir_huella=True`, que además
    emite `HuellaPublicadaWarning`.

    Raises:
        ContentSigningError: rol distinto de `content-integrity`, llave
            ausente o mal configurada, o es el archivo de la llave de
            autorización.
        CommitmentPIIError / CommitmentIncoherenteError: el commitment no es
            publicable.
    """
    if role != _ROL:
        # Reauditoría 2 (H11): con role="authorization" la llave de contenido
        # firmaba un sobre del otro rol. La regla «nunca la misma llave para
        # las dos cosas» no puede depender de que nadie pase ese parámetro.
        raise ContentSigningError(
            f"ROLE_NOT_SIGNABLE: aquí solo se firma el rol {_ROL!r}, no {role!r}. "
            "Otro rol lo firma otra llave, en otro módulo."
        )
    validar_publicable(commitment, permitir_huella=permitir_huella)
    if tiene_huella(commitment):
        warnings.warn(
            "se firma un commitment que lleva la huella SHA-256 del escrito: "
            "quien tenga un escrito candidato puede confirmar si es este.",
            HuellaPublicadaWarning,
            stacklevel=2,
        )
    path = Path(key_path).expanduser() if key_path else content_key_path(cfg)
    _assert_no_es_la_llave_de_autorizacion(path, cfg)
    key = _load_content_private_key(path)
    sin_firma = ContentSignature(
        key_id=derive_key_id(key.public_key()),
        algorithm=_ALGORITMO,
        commitment_hash=commitment_hash(commitment),
        signature_hex="",
        role=role,
        schema_version=CONTENT_SIGNATURE_SCHEMA_VERSION,
    )
    firma = key.sign(_datos_firma(sin_firma))
    return ContentSignature(
        key_id=sin_firma.key_id,
        algorithm=sin_firma.algorithm,
        commitment_hash=sin_firma.commitment_hash,
        signature_hex=firma.hex(),
        role=sin_firma.role,
        schema_version=sin_firma.schema_version,
    )


def verificar_commitment(
    commitment: dict[str, Any],
    sobre: ContentSignature,
    public_key: Ed25519PublicKey,
    *,
    role_esperado: str = _ROL,
) -> bool:
    """Verifica la firma. Devuelve True/False; NO traga excepciones.

    Contrato V2: valida schema_version, algorithm y role como CAMPOS antes de
    mirar la firma, y la firma cubre los tres más el hash.

    Devuelve False cuando la firma no es de esta llave (incluido un `key_id`
    que no corresponde a la pubkey presentada). Lanza cuando el sobre no cumple
    el contrato (`ContentSigningError`) o cuando el commitment no es el firmado
    (`CommitmentAlteradoError`): son motivos distintos y quien llama los ve.
    """
    if sobre.schema_version != CONTENT_SIGNATURE_SCHEMA_VERSION:
        raise ContentSigningError(
            f"schema_version inesperado: {sobre.schema_version!r} "
            f"(esperado {CONTENT_SIGNATURE_SCHEMA_VERSION!r})"
        )
    if sobre.algorithm != _ALGORITMO:
        raise ContentSigningError(
            f"algorithm inesperado: {sobre.algorithm!r} (esperado {_ALGORITMO!r})"
        )
    if role_esperado not in ROLES_VALIDOS:
        raise ContentSigningError(f"rol esperado no admitido: {role_esperado!r}")
    if sobre.role != role_esperado:
        raise ContentSigningError(f"role incompatible: {sobre.role!r} != {role_esperado!r}")
    c_hash = commitment_hash(commitment)
    if sobre.commitment_hash != c_hash:
        raise CommitmentAlteradoError(
            f"el commitment cambió tras la firma: firmado {sobre.commitment_hash[:16]}…, "
            f"ahora {c_hash[:16]}…"
        )
    if sobre.key_id != derive_key_id(public_key):
        return False
    try:
        public_key.verify(_firma_a_bytes(sobre.signature_hex), _datos_firma(sobre))
    except InvalidSignature:
        return False
    return True


def verificar_archivos(
    commitment_path: str | Path,
    sig_path: str | Path,
    public_key: Ed25519PublicKey,
    *,
    role_esperado: str = _ROL,
) -> bool:
    """Verifica un commitment y su sobre leídos de disco, con el lector estricto.

    Es lo que debe usar quien verifica ARCHIVOS: `verificar_commitment` recibe
    dicts ya cargados y no puede saber si el archivo traía claves duplicadas.
    """
    commitment = leer_json_estricto(commitment_path)
    sobre = ContentSignature.from_dict(leer_json_estricto(sig_path))
    return verificar_commitment(commitment, sobre, public_key, role_esperado=role_esperado)


def verificar_commitment_legacy(
    commitment: dict[str, Any],
    sobre: ContentSignature,
    public_key: Ed25519PublicKey,
) -> bool:
    """Vía LEGACY para firmas V1 (solo commitment_hash, sin separación de rol).

    Etiqueta explícitamente el límite: rol NO autenticado.
    No emite nuevas firmas V1.
    """
    if sobre.schema_version != _SCHEMA_V1:
        raise ContentSigningError(
            f"no es firma V1 legacy: {sobre.schema_version!r}"
        )
    c_hash = commitment_hash(commitment)
    if sobre.commitment_hash != c_hash:
        raise CommitmentAlteradoError(
            f"el commitment cambió tras la firma: firmado {sobre.commitment_hash[:16]}…, "
            f"ahora {c_hash[:16]}…"
        )
    try:
        # V1 firmaba solo el hash crudo: data = bytes.fromhex(c_hash)
        public_key.verify(bytes.fromhex(sobre.signature_hex), bytes.fromhex(c_hash))
    except InvalidSignature:
        return False
    return True


def escribir_firma(sobre: ContentSignature, destino: str | Path) -> str:
    """Escribe el sobre a disco. Devuelve su hash. No firma nada."""
    p = Path(destino)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(sobre.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    raw = json.dumps(
        sobre.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()
