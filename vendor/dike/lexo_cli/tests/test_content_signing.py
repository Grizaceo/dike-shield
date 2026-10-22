"""Tests de la firma de contenido.

REGLA H12: todo test negativo tiene gemelo positivo y detector de excepción.
El módulo heredado `custody_signing.verify_signature` hace `except Exception:
return False`, que traga cualquier fallo. Este módulo NO lo hace, y estos
tests son la razón: si alguien reintroduce el `except` ancho, el control
negativo por-motivo falla.

También se prueba la SEPARACIÓN DE ROLES V2: role + hash firmados juntos.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import warnings
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization

import lexo_cli.content_signing as cs
from lexo_cli.commitment import (
    CommitmentIncoherenteError,
    CommitmentPIIError,
    HuellaPublicadaWarning,
)
from lexo_cli.content_signing import (
    CommitmentAlteradoError,
    ContentSignature,
    ContentSigningError,
    DuplicateKeyError,
    commitment_hash,
    content_key_path,
    content_public_pem,
    escribir_firma,
    generar_content_key,
    firmar_commitment,
    leer_clave_publica,
    leer_json_estricto,
    reject_duplicate_keys,
    verificar_archivos,
    verificar_commitment,
    verificar_commitment_legacy,
)

V2 = "dike-content-signature-v2"
V1 = "dike-content-signature-v1"

COMMITMENT = {
    "schema_version": "dike-constancia-commitment-v2",
    "pack_hash": "ea28fa1c0f9af6c1",
    "as_of": "2026-10-05",
    "fecha_constancia": "2026-10-05T09:17:55Z",
    "total_citas": 1,
    "citas_verificadas": 1,
    "citas_fallidas": 0,
    "normas_verificadas": [
        {
            "gid": "cl.norma.ct:art:0161",
            "vigencia": "IN_FORCE",
            "texto_hash": "a" * 64,
            "fuente_url": "https://ejemplo/1",
            "estado": "VERIFICADA",
        },
    ],
    "alcance": "identidad, integridad y vigencia",
    "advertencias": ["Diké NO verifica que la norma fundamente lo afirmado."],
}


@pytest.fixture
def key(tmp_path) -> Path:
    p, _ = generar_content_key(tmp_path / "content-key.pem")
    return p


# ── CONTROL POSITIVO ────────────────────────────────────────────

def test_control_positivo_firma_verifica(key):
    """Control positivo: firma V2 válida verifica True."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    assert sobre.algorithm == "ed25519"
    assert sobre.role == "content-integrity"
    assert sobre.schema_version == "dike-content-signature-v2"
    assert len(sobre.signature_hex) == 128  # 64 bytes en hex
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()
    assert verificar_commitment(COMMITMENT, sobre, pub) is True


def test_key_id_estable_para_la_misma_llave(key):
    s1 = firmar_commitment(COMMITMENT, key_path=key)
    s2 = firmar_commitment(COMMITMENT, key_path=key)
    assert s1.key_id == s2.key_id
    assert len(s1.key_id) == 16


def test_hash_estable_entre_ordenes_de_claves():
    a = {"z": 1, "a": 2}
    b = {"a": 2, "z": 1}
    assert commitment_hash(a) == commitment_hash(b)


# ── CONTROL NEGATIVO: commitment alterado ───────────────────────

def test_negativo_commitment_alterado_es_distinguible(key):
    """El control negativo clave: NO debe ser un False genérico."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    alterado = dict(COMMITMENT, citas_verificadas=99)
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()

    assert commitment_hash(alterado) != commitment_hash(COMMITMENT), (
        "el commitment alterado debe cambiar el hash; si no cambia, "
        "este test no está probando lo que dice probar"
    )
    with pytest.raises(CommitmentAlteradoError):
        verificar_commitment(alterado, sobre, pub)


def test_negativo_firma_de_otra_llave_rechazada(key, tmp_path):
    """Firma correcta en forma, de otra llave → InvalidSignature → False."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    otra, _ = generar_content_key(tmp_path / "otra.pem")
    pub_otra = serialization.load_pem_private_key(
        otra.read_bytes(), password=None
    ).public_key()

    assert verificar_commitment(COMMITMENT, sobre, pub_otra) is False


def test_verificador_no_traga_excepciones_amplias(key):
    """Detector de la regla H12: un `except Exception` rompería esto."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    corrupto = ContentSignature(
        key_id=sobre.key_id,
        algorithm=sobre.algorithm,
        commitment_hash=sobre.commitment_hash,
        signature_hex="ZZZZ_no_es_hex",
        role=sobre.role,
        schema_version=sobre.schema_version,
    )
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()
    with pytest.raises(ValueError):
        verificar_commitment(COMMITMENT, corrupto, pub)


def test_sobre_incompleto_falla_con_mensaje_claro():
    with pytest.raises(ContentSigningError) as exc:
        ContentSignature.from_dict({"key_id": "abc"})
    assert "faltan" in str(exc.value)


# ── SEPARACIÓN DE ROLES V2 ──────────────────────────────────────

def test_no_firma_sin_llave_configurada(tmp_path, monkeypatch):
    """Fail-closed: sin llave de contenido, no firma."""
    monkeypatch.delenv("LEXO_CONTENT_SIGNING_KEY_PATH", raising=False)
    monkeypatch.delenv("LEXO_CUSTODY_SIGNING_KEY_PATH", raising=False)
    with pytest.raises(ContentSigningError) as exc:
        content_key_path({"custody": {"signing_key_path": str(tmp_path / "auth.pem")}})
    assert "autorización" in str(exc.value) or "autorizacion" in str(exc.value).lower()


def test_no_sobrescribe_llave_existente(key):
    """Regenerar una llave invalidaría firmas ya emitidas."""
    with pytest.raises(ContentSigningError):
        generar_content_key(key)


def test_llave_debe_ser_0600_desde_creacion(tmp_path):
    """0600 desde creación, no solo después del write."""
    p, _ = generar_content_key(tmp_path / "k.pem")
    assert (p.stat().st_mode & 0o777) == 0o600
    # Si se cambia, falla al firmar
    p.chmod(0o644)
    with pytest.raises(ContentSigningError) as exc:
        firmar_commitment(COMMITMENT, key_path=p)
    assert "0600" in str(exc.value)


def test_pubkey_no_expone_material_privado(key, monkeypatch):
    monkeypatch.setenv("LEXO_CONTENT_SIGNING_KEY_PATH", str(key))
    pem = content_public_pem({})
    assert b"PUBLIC KEY" in pem
    assert b"PRIVATE" not in pem
    assert b"PRIVATE KEY" not in pem


def test_sobre_va_y_vuelve(tmp_path, key):
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    destino = tmp_path / "commitment.sig.json"
    h = escribir_firma(sobre, destino)
    recargado = ContentSignature.from_dict(
        json.loads(destino.read_text(encoding="utf-8"))
    )
    assert recargado.signature_hex == sobre.signature_hex
    assert recargado.key_id == sobre.key_id
    assert len(h) == 64


# ── V2: separación de dominio role+hash ─────────────────────────

def test_replay_role_con_misma_llave_falla(key):
    """Una misma llave NO puede firmar role 'authorization'.

    El contrato V2 firma role+hash; cambiar el role invalida la firma.
    """
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()
    # Sobre con role alterado → debe fallar
    sobre_auth = ContentSignature(
        key_id=sobre.key_id,
        algorithm=sobre.algorithm,
        commitment_hash=sobre.commitment_hash,
        signature_hex=sobre.signature_hex,
        role="authorization",
        schema_version=sobre.schema_version,
    )
    assert verificar_commitment(COMMITMENT, sobre, pub) is True
    with pytest.raises(ContentSigningError):
        verificar_commitment(COMMITMENT, sobre_auth, pub)


def test_firma_entre_roles_con_una_llave_sintetica(key):
    """Con UNA llave sintética, ambas direcciones de replay fallan."""
    # Firmar con role 'content-integrity'
    sobre = firmar_commitment(COMMITMENT, key_path=key, role="content-integrity")
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()
    # Replay como 'authorization' → falla
    sobre_auth = ContentSignature(
        key_id=sobre.key_id, algorithm=sobre.algorithm,
        commitment_hash=sobre.commitment_hash, signature_hex=sobre.signature_hex,
        role="authorization", schema_version=sobre.schema_version,
    )
    with pytest.raises(ContentSigningError):
        verificar_commitment(COMMITMENT, sobre_auth, pub)
    # Replay como otro content-integrity con distinto commitment_hash → falla
    compromiso_otro = dict(COMMITMENT, citas_verificadas=99)
    sobre_otro = ContentSignature(
        key_id=sobre.key_id, algorithm=sobre.algorithm,
        commitment_hash=commitment_hash(compromiso_otro),
        signature_hex=sobre.signature_hex,
        role="content-integrity", schema_version=sobre.schema_version,
    )
    assert verificar_commitment(COMMITMENT, sobre, pub) is True
    with pytest.raises(CommitmentAlteradoError):
        verificar_commitment(COMMITMENT, sobre_otro, pub)


# ── V2: rechazo de claves duplicadas ────────────────────────────

def test_reject_duplicate_keys_valid():
    reject_duplicate_keys('{"a":1,"b":2}')


def test_reject_duplicate_keys_rejects():
    with pytest.raises(DuplicateKeyError):
        reject_duplicate_keys('{"a":1,"a":2}')


def test_reject_duplicate_keys_rejects_nested():
    with pytest.raises(DuplicateKeyError):
        reject_duplicate_keys('{"a":{"b":1,"b":2}}')


# ── LEGACY V1 ───────────────────────────────────────────────────

def test_legacy_v1_firma_real_pasa(key):
    """Firma V1 real (solo sobre commitment_hash) verifica con legacy."""
    from lexo_cli.content_signing import derive_key_id

    c_hash = commitment_hash(COMMITMENT)
    key_obj = serialization.load_pem_private_key(key.read_bytes(), password=None)
    firma_v1 = key_obj.sign(bytes.fromhex(c_hash))
    v1 = ContentSignature(
        key_id=derive_key_id(key_obj.public_key()),
        algorithm="ed25519",
        commitment_hash=c_hash,
        signature_hex=firma_v1.hex(),
        role="content-integrity",
        schema_version="dike-content-signature-v1",
    )
    pub = key_obj.public_key()
    assert verificar_commitment_legacy(COMMITMENT, v1, pub) is True


def test_legacy_v1_rechaza_schema_v2(key):
    """Una firma V1 (schema v1) no pasa por verificar_commitment V2."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    v1 = ContentSignature(
        key_id=sobre.key_id, algorithm=sobre.algorithm,
        commitment_hash=sobre.commitment_hash, signature_hex=sobre.signature_hex,
        role=sobre.role, schema_version="dike-content-signature-v1",
    )
    pub = serialization.load_pem_private_key(
        key.read_bytes(), password=None
    ).public_key()
    with pytest.raises(ContentSigningError):
        verificar_commitment(COMMITMENT, v1, pub)


# ═════════════════════════════════════════════════════════════════════════
# REMEDIACIÓN 2 (2026-10-05) — tests que matan a los mutantes de la reauditoría
#
# Con la suite anterior en verde sobrevivían 9 de 14 mutantes: el rol podía
# salir de los bytes firmados, la llave podía nacer 0644, la vía legacy podía
# no verificar nada. Cada bloque de abajo nombra el mutante que mata.
# ═════════════════════════════════════════════════════════════════════════


def _pub(key: Path):
    return serialization.load_pem_private_key(key.read_bytes(), password=None).public_key()


def _priv(key: Path):
    return serialization.load_pem_private_key(key.read_bytes(), password=None)


def _bytes_v2(role: str, algorithm: str, schema: str, c_hash: str) -> bytes:
    """El contrato V2 reescrito aquí, sin llamar al módulo: es el oráculo."""
    return hashlib.sha256(f"{role}:{algorithm}:{schema}:{c_hash}".encode("utf-8")).hexdigest().encode("utf-8")


def _sobre(key: Path, *, role: str, algorithm: str = "ed25519", schema: str = V2,
           firmado_como: tuple[str, str, str] | None = None) -> ContentSignature:
    """Sobre armado a mano: firma los bytes de `firmado_como` y se etiqueta aparte."""
    c_hash = commitment_hash(COMMITMENT)
    r, a, sv = firmado_como or (role, algorithm, schema)
    firma = _priv(key).sign(_bytes_v2(r, a, sv, c_hash))
    return ContentSignature(
        key_id=cs.derive_key_id(_pub(key)), algorithm=algorithm, commitment_hash=c_hash,
        signature_hex=firma.hex(), role=role, schema_version=schema,
    )


# ── M01, M03, M04: rol, schema_version y algorithm dentro de los bytes firmados ──

def test_contrato_v2_bytes_firmados_fijos(key):
    """Los bytes firmados son exactamente estos. Si cambian, las firmas ya
    emitidas dejan de verificar: este test es el ancla del contrato."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    esperado = _bytes_v2("content-integrity", "ed25519", V2, commitment_hash(COMMITMENT))
    assert cs._datos_firma(sobre) == esperado
    assert len(esperado) == 64  # hex ASCII, no los 32 bytes del digest
    # Y la firma verifica contra el oráculo, no solo contra el módulo.
    _pub(key).verify(bytes.fromhex(sobre.signature_hex), esperado)


@pytest.mark.parametrize("campo,valor", [
    ("role", "authorization"),
    ("algorithm", "ed448"),
    ("schema_version", V1),
    ("commitment_hash", "b" * 64),
])
def test_datos_firma_cambia_al_cambiar_cada_campo(key, campo, valor):
    base = firmar_commitment(COMMITMENT, key_path=key)
    otro = dataclasses.replace(base, **{campo: valor})
    assert getattr(base, campo) != valor, "el control no cambia nada: test vacío"
    assert cs._datos_firma(base) != cs._datos_firma(otro), (
        f"{campo} no está dentro de los bytes firmados"
    )


# ── M01, M14: el rol queda ligado a la firma, en las dos direcciones ──

def test_rol_ligado_a_la_firma_en_ambas_direcciones(key):
    pub = _pub(key)
    ci = firmar_commitment(COMMITMENT, key_path=key, role="content-integrity")
    # El sobre del otro rol se arma a mano: `firmar_commitment` ya no lo emite (H11).
    au = _sobre(key, role="authorization")
    assert ci.role == "content-integrity" and au.role == "authorization"

    # Positivos: cada firma verifica bajo SU rol.
    assert verificar_commitment(COMMITMENT, ci, pub, role_esperado="content-integrity") is True
    assert verificar_commitment(COMMITMENT, au, pub, role_esperado="authorization") is True

    # Negativos criptográficos: re-etiquetar el sobre y esperar el rol nuevo.
    # El campo pasa la validación; lo que falla es la firma.
    ci_como_au = dataclasses.replace(ci, role="authorization")
    au_como_ci = dataclasses.replace(au, role="content-integrity")
    assert verificar_commitment(COMMITMENT, ci_como_au, pub, role_esperado="authorization") is False
    assert verificar_commitment(COMMITMENT, au_como_ci, pub, role_esperado="content-integrity") is False

    # Y las dos firmas son distintas: firmar no ignora el rol.
    assert ci.signature_hex != au.signature_hex


# ── Reauditoría 2 (H11): este módulo solo firma su rol ──

def test_firmar_no_emite_el_rol_de_autorizacion(key):
    """`authorization` está en la lista cerrada para poder esperarlo al
    verificar. Con ese parámetro, la llave de contenido firmaba un sobre del
    otro rol: la regla «nunca la misma llave para las dos cosas» dependía de
    que nadie lo pasara."""
    assert firmar_commitment(COMMITMENT, key_path=key, role="content-integrity").role == "content-integrity"
    with pytest.raises(ContentSigningError) as exc:
        firmar_commitment(COMMITMENT, key_path=key, role="authorization")
    assert "ROLE_NOT_SIGNABLE" in str(exc.value)


# ── Reauditoría 2 (H5, mutante Y10): el rol esperado también sale de la lista ──

def test_verificar_rechaza_un_rol_esperado_fuera_de_la_lista(key):
    """Un sobre firmado de verdad para un rol inventado, verificado esperando
    ese mismo rol: campo y firma cuadran. Lo único que lo detiene es que el
    rol esperado no está en la lista cerrada."""
    inventado = _sobre(key, role="otro-rol")
    _pub(key).verify(bytes.fromhex(inventado.signature_hex), cs._datos_firma(inventado))  # la firma ES válida
    with pytest.raises(ContentSigningError) as exc:
        verificar_commitment(COMMITMENT, inventado, _pub(key), role_esperado="otro-rol")
    assert "rol esperado no admitido" in str(exc.value)
    # Control: un rol de la lista, firmado para ese rol, verifica.
    autorizacion = _sobre(key, role="authorization")
    assert verificar_commitment(COMMITMENT, autorizacion, _pub(key), role_esperado="authorization") is True


# ── R4: lista cerrada de roles y algorithm validado (ambigüedad del «:») ──

@pytest.mark.parametrize("rol", ["content-integrity:ed25519", "", "Content-Integrity", "otro"])
def test_firmar_rechaza_rol_fuera_de_la_lista(key, rol):
    with pytest.raises(ContentSigningError):
        firmar_commitment(COMMITMENT, key_path=key, role=rol)


def test_verificar_rechaza_algorithm_que_no_es_ed25519(key):
    pub = _pub(key)
    bueno = firmar_commitment(COMMITMENT, key_path=key)
    assert verificar_commitment(COMMITMENT, bueno, pub) is True
    with pytest.raises(ContentSigningError):
        verificar_commitment(COMMITMENT, dataclasses.replace(bueno, algorithm="rsa"), pub)


def test_corrimiento_del_delimitador_no_verifica(key):
    """Hallazgo R4. Una firma hecha para role='content-integrity:ed25519' produce
    los mismos bytes que role='content-integrity' + algorithm='ed25519:ed25519'.
    Sin validar `algorithm`, verificaba como content-integrity."""
    pub = _pub(key)
    corrido = _sobre(
        key, role="content-integrity", algorithm="ed25519:ed25519",
        firmado_como=("content-integrity:ed25519", "ed25519", V2),
    )
    # La firma ES válida sobre esos bytes: el rechazo tiene que venir del campo.
    _pub(key).verify(bytes.fromhex(corrido.signature_hex), cs._datos_firma(corrido))
    with pytest.raises(ContentSigningError):
        verificar_commitment(COMMITMENT, corrido, pub)


# ── L2: el sobre no tiene valores por defecto ──

_SOBRE_COMPLETO = {
    "schema_version": V2, "role": "content-integrity", "algorithm": "ed25519",
    "key_id": "0" * 16, "commitment_hash": "a" * 64, "signature": "b" * 128,
}


def test_from_dict_acepta_el_sobre_completo():
    s = ContentSignature.from_dict(dict(_SOBRE_COMPLETO))
    assert s.to_dict() == _SOBRE_COMPLETO


@pytest.mark.parametrize("campo", sorted(_SOBRE_COMPLETO))
def test_from_dict_exige_cada_campo(campo):
    d = dict(_SOBRE_COMPLETO)
    del d[campo]
    with pytest.raises(ContentSigningError) as exc:
        ContentSignature.from_dict(d)
    assert campo in str(exc.value)


@pytest.mark.parametrize("campo", sorted(_SOBRE_COMPLETO))
def test_from_dict_exige_cadenas(campo):
    with pytest.raises(ContentSigningError):
        ContentSignature.from_dict(dict(_SOBRE_COMPLETO, **{campo: None}))


@pytest.mark.parametrize("extra", [{"firmante": "Corte Suprema"}, {"fecha_con_valor_legal": True}, {"nota": None}])
def test_from_dict_rechaza_campos_de_mas(extra):
    """Reauditoría 2 (H2). Un campo de más no está firmado. Con una firma
    válida al lado, quien lo lee podría darlo por acreditado."""
    with pytest.raises(ContentSigningError) as exc:
        ContentSignature.from_dict(dict(_SOBRE_COMPLETO, **extra))
    assert next(iter(extra)) in str(exc.value)


def test_verificar_archivos_rechaza_un_sobre_con_un_campo_de_mas(tmp_path, key):
    c, s = _archivos(tmp_path, key)
    assert verificar_archivos(c, s, _pub(key)) is True
    sobre = json.loads(s.read_text(encoding="utf-8"))
    s.write_text(json.dumps(dict(sobre, firmante="Corte Suprema")), encoding="utf-8")
    with pytest.raises(ContentSigningError):
        verificar_archivos(c, s, _pub(key))


# ── M06, F2r, F3r: la llave nace 0600, no se pisa y no sigue enlaces ──

@pytest.fixture
def umask_022():
    previa = os.umask(0o022)
    try:
        yield
    finally:
        os.umask(previa)


def test_llave_nace_0600_en_el_descriptor(tmp_path, monkeypatch, umask_022):
    """Se mira el modo en el instante de abrir, no después. Un 0644 corregido
    luego con chmod deja una ventana en que la llave es legible por otros."""
    vistos: list[tuple[int, int]] = []
    real_open = os.open

    def espia(path, flags, mode=0o777, *a, **kw):
        fd = real_open(path, flags, mode, *a, **kw)
        if str(path).endswith("k.pem"):
            vistos.append((os.fstat(fd).st_mode & 0o777, flags))
        return fd

    monkeypatch.setattr(cs.os, "open", espia)
    p, _ = generar_content_key(tmp_path / "k.pem")

    assert vistos, "el espía no vio abrir la llave: test vacío"
    modo, flags = vistos[0]
    assert modo == 0o600, f"la llave se creó {oct(modo)}"
    assert flags & os.O_EXCL, "sin O_EXCL la creación no es atómica"
    assert flags & os.O_NOFOLLOW
    assert (p.stat().st_mode & 0o777) == 0o600


def test_directorios_creados_son_0700(tmp_path, umask_022):
    p, _ = generar_content_key(tmp_path / "a" / "b" / "k.pem")
    assert ((tmp_path / "a").stat().st_mode & 0o777) == 0o700
    assert ((tmp_path / "a" / "b").stat().st_mode & 0o777) == 0o700
    assert p.is_file()


def test_los_directorios_nacen_0700(tmp_path, monkeypatch, umask_022):
    """Reauditoría 2 (H5, mutante Y02). Se mira el modo que deja `mkdir`, no
    el final: un directorio que nace 0755 y se corrige después estuvo abierto
    mientras tanto."""
    al_nacer: list[int] = []
    real_mkdir = os.mkdir

    def espia(path, mode=0o777, *a, **kw):
        real_mkdir(path, mode, *a, **kw)
        al_nacer.append(os.stat(path).st_mode & 0o777)

    monkeypatch.setattr(cs.os, "mkdir", espia)
    generar_content_key(tmp_path / "a" / "b" / "k.pem")
    assert al_nacer == [0o700, 0o700], [oct(m) for m in al_nacer]


def test_una_llave_a_medio_escribir_no_queda_en_disco(tmp_path, monkeypatch):
    """Reauditoría 2 (H5, mutante Y04). Si la escritura se corta, el archivo
    que quedó es una llave truncada con el nombre de la buena."""
    destino = tmp_path / "k.pem"
    real_fdopen = os.fdopen

    class _SeCorta:
        def __init__(self, f):
            self.f = f

        def __enter__(self):
            return self

        def __exit__(self, *a):
            self.f.close()
            return False

        def write(self, datos):
            self.f.write(datos[: len(datos) // 2])
            self.f.flush()
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(cs.os, "fdopen", lambda fd, *a, **kw: _SeCorta(real_fdopen(fd, *a, **kw)))
    with pytest.raises(OSError):
        generar_content_key(destino)
    assert not destino.exists(), "quedó una llave a medio escribir"

    monkeypatch.undo()
    p, _ = generar_content_key(destino)  # control: sin el corte, se crea
    assert p.is_file()


def test_no_firma_con_una_llave_que_no_es_ed25519(tmp_path):
    """Reauditoría 2 (H5, mutante Y06). El sobre declara `ed25519`; con una
    llave de otra curva diría una cosa y habría firmado con otra."""
    from cryptography.hazmat.primitives.asymmetric import ec

    otra = tmp_path / "p256.pem"
    otra.write_bytes(ec.generate_private_key(ec.SECP256R1()).private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
    ))
    otra.chmod(0o600)
    with pytest.raises(ContentSigningError) as exc:
        firmar_commitment(COMMITMENT, key_path=otra)
    assert "Ed25519" in str(exc.value)
    with pytest.raises(ContentSigningError):
        content_public_pem(key_path=otra)


def test_no_pisa_un_archivo_aunque_el_chequeo_previo_mienta(tmp_path, monkeypatch):
    """Carrera F2r. Entre «¿existe?» y «abrir» otro proceso puede crear el
    archivo. Aquí el chequeo previo miente siempre: solo O_EXCL protege."""
    destino = tmp_path / "k.pem"
    destino.write_bytes(b"llave ajena")
    monkeypatch.setattr(Path, "exists", lambda self: False)
    with pytest.raises(ContentSigningError):
        generar_content_key(destino)
    assert destino.read_bytes() == b"llave ajena"


def test_no_sigue_un_symlink_colgante(tmp_path):
    """F3r. Antes la llave se escribía en el destino del enlace."""
    fuera = tmp_path / "otro_lugar" / "destino_inesperado.pem"
    fuera.parent.mkdir()
    enlace = tmp_path / "k.pem"
    enlace.symlink_to(fuera)
    with pytest.raises(ContentSigningError):
        generar_content_key(enlace)
    assert not fuera.exists(), "se escribió una llave a través del enlace"
    assert enlace.is_symlink()


# ── M07, M08: la vía legacy verifica de verdad y solo acepta V1 ──

def _sobre_v1(key: Path) -> ContentSignature:
    c_hash = commitment_hash(COMMITMENT)
    return ContentSignature(
        key_id=cs.derive_key_id(_pub(key)), algorithm="ed25519", commitment_hash=c_hash,
        signature_hex=_priv(key).sign(bytes.fromhex(c_hash)).hex(),
        role="content-integrity", schema_version=V1,
    )


def test_legacy_otra_llave_da_false(key, tmp_path):
    v1 = _sobre_v1(key)
    otra, _ = generar_content_key(tmp_path / "otra.pem")
    assert verificar_commitment_legacy(COMMITMENT, v1, _pub(key)) is True
    assert verificar_commitment_legacy(COMMITMENT, v1, _pub(otra)) is False


def test_legacy_firma_alterada_da_false(key):
    v1 = _sobre_v1(key)
    primero = "0" if v1.signature_hex[0] != "0" else "1"
    alterada = dataclasses.replace(v1, signature_hex=primero + v1.signature_hex[1:])
    assert verificar_commitment_legacy(COMMITMENT, v1, _pub(key)) is True
    assert verificar_commitment_legacy(COMMITMENT, alterada, _pub(key)) is False


def test_legacy_rechaza_un_sobre_v2(key):
    v2 = firmar_commitment(COMMITMENT, key_path=key)
    assert v2.schema_version == V2
    with pytest.raises(ContentSigningError):
        verificar_commitment_legacy(COMMITMENT, v2, _pub(key))


# ── D2: lector estricto de archivos (rechaza claves duplicadas) ──

def _archivos(tmp_path, key) -> tuple[Path, Path]:
    c, s = tmp_path / "commitment.json", tmp_path / "commitment.sig.json"
    c.write_text(json.dumps(COMMITMENT, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    escribir_firma(firmar_commitment(COMMITMENT, key_path=key), s)
    return c, s


def test_verificar_archivos_positivo(tmp_path, key):
    c, s = _archivos(tmp_path, key)
    assert verificar_archivos(c, s, _pub(key)) is True


def test_verificar_archivos_rechaza_claves_duplicadas(tmp_path, key):
    """Con json.load corriente la última clave gana y la firma verifica,
    mientras quien lee el archivo ve primero el valor falso."""
    c, s = _archivos(tmp_path, key)
    texto = c.read_text(encoding="utf-8")
    c.write_text(texto.replace("{", '{\n  "citas_verificadas": 99,', 1), encoding="utf-8")
    assert json.loads(c.read_text(encoding="utf-8"))["citas_verificadas"] == 1  # última gana
    with pytest.raises(DuplicateKeyError):
        verificar_archivos(c, s, _pub(key))


def test_verificar_archivos_rechaza_sobre_sin_schema_version(tmp_path, key):
    c, s = _archivos(tmp_path, key)
    sobre = json.loads(s.read_text(encoding="utf-8"))
    del sobre["schema_version"]
    s.write_text(json.dumps(sobre), encoding="utf-8")
    with pytest.raises(ContentSigningError):
        verificar_archivos(c, s, _pub(key))


@pytest.mark.parametrize("texto,error", [
    ('{"a":1,"a":2}', DuplicateKeyError),
    ('{"a":{"b":1,"b":2}}', DuplicateKeyError),
    ('{"a":1,"\\u0061":2}', DuplicateKeyError),
    ('{"a":', ContentSigningError),
    ('[1,2]', ContentSigningError),
    ('{"a":NaN}', ContentSigningError),
    # Un entero se admite escrito de una sola forma.
    ('{"a":2.0}', ContentSigningError),
    ('{"a":2e0}', ContentSigningError),
    ('{"a":-0}', ContentSigningError),
])
def test_leer_json_estricto_rechaza(tmp_path, texto, error):
    f = tmp_path / "x.json"
    f.write_text(texto, encoding="utf-8")
    with pytest.raises(error):
        leer_json_estricto(f)


def test_leer_json_estricto_acepta_enteros_simples_y_un_bom(tmp_path):
    f = tmp_path / "x.json"
    f.write_bytes(b"\xef\xbb\xbf" + b'{"a":0,"b":-3,"c":999999999999999,"d":-999999999999999}')
    assert leer_json_estricto(f) == {"a": 0, "b": -3, "c": 999999999999999, "d": -999999999999999}


@pytest.mark.parametrize("literal", ["1000000000000000", "-1000000000000000", "12345678901234567890"])
def test_leer_json_estricto_rechaza_enteros_de_mas_de_15_digitos(tmp_path, literal):
    """Un jq anterior a 1.7 los redondea (9007199254740993 pasa a ...992) y
    calcularía otro hash canónico. Para que todos los verificadores coincidan,
    ninguno los admite."""
    f = tmp_path / "x.json"
    f.write_text('{"a":' + literal + "}", encoding="utf-8")
    with pytest.raises(ContentSigningError) as exc:
        leer_json_estricto(f)
    assert "15 dígitos" in str(exc.value)


def test_firma_con_espacios_no_verifica(key):
    """`bytes.fromhex` ignora los espacios. Sin un control de formato, una
    firma con un espacio de más verificaba aquí y no con OpenSSL."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    assert verificar_commitment(COMMITMENT, sobre, _pub(key)) is True
    for mala in (sobre.signature_hex + " ", sobre.signature_hex[:64] + " " + sobre.signature_hex[64:],
                 sobre.signature_hex + "00", sobre.signature_hex[:-2]):
        with pytest.raises(ValueError):
            verificar_commitment(COMMITMENT, dataclasses.replace(sobre, signature_hex=mala), _pub(key))


def test_firma_en_mayusculas_no_verifica(key):
    """Reauditoría 2 (H2). La firma se emite en minúsculas y solo así se
    acepta: si las mayúsculas verificaran, se podría cambiar un valor del sobre
    sin invalidarlo, y el documento dice que cualquier cambio lo invalida."""
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    assert sobre.signature_hex == sobre.signature_hex.lower(), "control: se emite en minúsculas"
    i = next(i for i, c in enumerate(sobre.signature_hex) if c in "abcdef")
    una = sobre.signature_hex[:i] + sobre.signature_hex[i].upper() + sobre.signature_hex[i + 1:]
    for mala in (sobre.signature_hex.upper(), una):
        with pytest.raises(ValueError):
            verificar_commitment(COMMITMENT, dataclasses.replace(sobre, signature_hex=mala), _pub(key))


def test_leer_json_estricto_acepta_la_misma_clave_en_objetos_distintos(tmp_path):
    f = tmp_path / "x.json"
    f.write_text('{"a":1,"b":{"a":1},"c":[{"x":1},{"x":1}]}', encoding="utf-8")
    assert leer_json_estricto(f)["b"] == {"a": 1}


# ── R2: la llave de contenido no puede ser el archivo de la de autorización ──

def test_firmar_rechaza_la_llave_de_autorizacion(key, tmp_path, monkeypatch):
    otra, _ = generar_content_key(tmp_path / "auth.pem")
    monkeypatch.setenv("LEXO_CUSTODY_SIGNING_KEY_PATH", str(otra))
    assert firmar_commitment(COMMITMENT, key_path=key).role == "content-integrity"  # positivo

    monkeypatch.setenv("LEXO_CUSTODY_SIGNING_KEY_PATH", str(key))
    with pytest.raises(ContentSigningError) as exc:
        firmar_commitment(COMMITMENT, key_path=key)
    assert "autorización" in str(exc.value)


def test_firmar_rechaza_la_llave_de_autorizacion_por_enlace_o_por_config(key, tmp_path, monkeypatch):
    monkeypatch.delenv("LEXO_CUSTODY_SIGNING_KEY_PATH", raising=False)
    alias = tmp_path / "alias.pem"
    alias.symlink_to(key)
    cfg = {"custody": {"signing_key_path": str(key), "content_signing_key_path": str(alias)}}
    with pytest.raises(ContentSigningError):
        firmar_commitment(COMMITMENT, cfg=cfg)


def test_una_copia_de_la_llave_en_otro_archivo_no_se_detecta(key, tmp_path, monkeypatch):
    """Límite DECLARADO en KEYS.md, no una garantía. La guardia compara
    archivos; no lee la otra llave. Si algún día lo detecta, este test falla
    y hay que corregir el documento."""
    copia = tmp_path / "copia-de-la-misma-llave.pem"
    copia.write_bytes(key.read_bytes())
    copia.chmod(0o600)
    monkeypatch.setenv("LEXO_CUSTODY_SIGNING_KEY_PATH", str(copia))
    sobre = firmar_commitment(COMMITMENT, key_path=key)
    assert verificar_commitment(COMMITMENT, sobre, _pub(copia)) is True


# ── P2, P3, P4: lo que se firma tiene que ser publicable ──

def test_firmar_rechaza_campos_prohibidos(key):
    for campo in ("documento", "origen", "cita_raw", "problemas", "detalles"):
        with pytest.raises(CommitmentPIIError):
            firmar_commitment(dict(COMMITMENT, **{campo: "x"}), key_path=key)


def test_firmar_rechaza_pii_en_un_campo_que_se_publica(key):
    assert firmar_commitment(dict(COMMITMENT, alcance="identidad y vigencia"), key_path=key)
    with pytest.raises(CommitmentPIIError):
        firmar_commitment(dict(COMMITMENT, alcance="demandante RUT 12.345.678-5"), key_path=key)


def test_firmar_rechaza_la_huella_sin_opt_in(key):
    con_huella = dict(COMMITMENT, document_sha256="c" * 64, document_bytes="10")
    with pytest.raises(CommitmentPIIError):
        firmar_commitment(con_huella, key_path=key)
    with pytest.warns(HuellaPublicadaWarning):
        sobre = firmar_commitment(con_huella, key_path=key, permitir_huella=True)
    assert verificar_commitment(con_huella, sobre, _pub(key)) is True


def test_firmar_sin_huella_no_advierte(key):
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        firmar_commitment(COMMITMENT, key_path=key)


def test_firmar_rechaza_conteo_incoherente(key):
    with pytest.raises(CommitmentIncoherenteError):
        firmar_commitment(dict(COMMITMENT, citas_verificadas=99), key_path=key)


# ── Reauditoría 2: el archivo de la clave pública tiene una sola escritura ──

def _pem(key: Path) -> bytes:
    return _pub(key).public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)


def test_leer_clave_publica_acepta_la_forma_canonica_y_el_salto_de_windows(tmp_path, key):
    f = tmp_path / "k.pub"
    for datos in (_pem(key), _pem(key).replace(b"\n", b"\r\n"), _pem(key).rstrip(b"\n")):
        f.write_bytes(datos)
        assert cs.derive_key_id(leer_clave_publica(f)) == cs.derive_key_id(_pub(key))


@pytest.mark.parametrize("como", ["tabulador_vertical", "espacio_duro", "texto_antes", "bom", "dos_claves", "linea_en_blanco"])
def test_leer_clave_publica_rechaza_lo_que_openssl_no_leeria_igual(tmp_path, key, como):
    """`cryptography` carga todos estos archivos y devuelve la misma clave.
    OpenSSL rechaza los dos primeros: una búsqueda al azar encontró que la
    receta sin Python y la biblioteca daban veredictos distintos."""
    pem = _pem(key)
    lineas = pem.split(b"\n")
    otra, _ = generar_content_key(tmp_path / "otra.pem")
    datos = {
        "tabulador_vertical": b"\n".join([lineas[0], lineas[1][:20] + b"\x0b" + lineas[1][20:], *lineas[2:]]),
        "espacio_duro": b"\n".join([lineas[0], lineas[1][:20] + b"\xc2\xa0" + lineas[1][20:], *lineas[2:]]),
        "texto_antes": b"clave de Dike\n" + pem,
        "bom": b"\xef\xbb\xbf" + pem,
        "dos_claves": pem + _pem(otra),
        "linea_en_blanco": pem.replace(b"-----\n", b"-----\n\n", 1),
    }[como]
    f = tmp_path / "k.pub"
    f.write_bytes(datos)
    with pytest.raises(ContentSigningError) as exc:
        leer_clave_publica(f)
    assert "forma canónica" in str(exc.value)


def test_leer_clave_publica_rechaza_lo_que_no_es_una_clave_ed25519(tmp_path):
    from cryptography.hazmat.primitives.asymmetric import ec

    f = tmp_path / "k.pub"
    f.write_text("esto no es un PEM", encoding="utf-8")
    with pytest.raises(ContentSigningError):
        leer_clave_publica(f)
    f.write_bytes(ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
    with pytest.raises(ContentSigningError) as exc:
        leer_clave_publica(f)
    assert "Ed25519" in str(exc.value)
    with pytest.raises(ContentSigningError):
        leer_clave_publica(tmp_path / "no_existe.pub")
