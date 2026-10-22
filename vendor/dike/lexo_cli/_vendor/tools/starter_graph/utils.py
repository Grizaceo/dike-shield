from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from pathlib import Path
from typing import Any


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic JCS-compatible JSON for the v1 value domain.

    Starter Graph v1 emits strings, integers, booleans, arrays, objects and
    null only.  For that restricted domain, sorted UTF-8 JSON without
    insignificant whitespace is RFC 8785/JCS compatible.
    """

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def write_canonical_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_json_bytes(value))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(char for char in normalized if not unicodedata.combining(char))
    compact = re.sub(r"[^a-zA-Z0-9]+", "_", ascii_value).strip("_").lower()
    return compact or "sin_nombre"


def distributable_files(root: Path) -> list[Path]:
    """Rutas del paquete que entran en el hash del snapshot, en orden estable.

    El conjunto y el orden son parte del CONTRATO: entran en `snapshot_hash`, así
    que cambiarlos cambiaría el hash de todo el corpus. El test
    `tests/test_h8_arranque.py` congela ese comportamiento.

    Por qué no `relative_to`: la versión anterior lo llamaba DOS veces por
    archivo —en el filtro y en la clave de orden—, y cada llamada reconstruye la
    ruta desde cero en `pathlib`. Con los 34.216 archivos del snapshot eran
    342.148 reconstrucciónes: ~10 s de los ~12 s de arranque de `dike buscar`.
    (Medido: hashear los 34.216 archivos cuesta 1,0 s. El resto era pathlib.)
    `os.walk` entrega la ruta relativa al directorio de partida, así que no hace
    falta reconstruirla.

    Fail-closed: las exclusiones por nombre de archivo y de directorio se
    mantienen idénticas, y los directorios excluidos se podan en el recorrido en
    vez de bajarse y descartarse después.
    """
    excluded_names = {"MANIFEST.json", "SNAPSHOT.json"}
    excluded_parts = {"__pycache__", ".pytest_cache", ".snapshots"}

    collected: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        rel_dir = current.relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in excluded_parts]
        prefix = rel_dir.as_posix() if rel_dir.parts else ""
        for filename in filenames:
            if filename in excluded_names:
                continue
            rel = f"{prefix}/{filename}" if prefix else filename
            collected.append((rel, current / filename))

    collected.sort(key=lambda par: par[0])
    return [path for _, path in collected]


class Report:
    """Minimal validation/reporting object with a fail-fast error list."""

    def __init__(self) -> None:
        self.ok = True
        self.errors: list[str] = []

    def fail(self, message: str) -> None:
        self.ok = False
        self.errors.append(message)
