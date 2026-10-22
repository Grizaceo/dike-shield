"""Aislamiento de la suite respecto del journal HITL real (P07).

Regresión de la auditoría externa 2026-09-11: la suite escribía gates HITL-4
reales en el journal del operador — 12 de los 13 eventos de `~/.dike/events.db`
venían de corridas de tests, y el journal es append-only (la contaminación no
se puede borrar, solo prevenirse y marcarse).

Contrato de este archivo:

1. `DIKE_HITL_DB` se fija a una base temporal si el operador no fijó una.
   Todas las superficies que resuelven el journal por `resolve_hitl_db()` —
   CLI, subprocess de tests, MCP— escriben ahí durante la suite. Si el
   operador o CI ya exportó una ruta, se respeta.

2. Una guardia de sesión compara los journals REALES antes/después de la
   corrida y falla si hubo escritura productiva (incluido un journal NUEVO
   bajo `~/.dike`). La falla es la marca auditada (ruta + delta en el
   mensaje); nunca se borra nada.

3. `os.environ` se restaura al terminar cada test. Un test (o el código que
   ejercita in-process, p. ej. `nif edit --signing-key`, que escribe
   `LEXO_CUSTODY_SIGNING_KEY_PATH`) que muta el entorno sin monkeypatch no
   puede contaminar a los siguientes (post-cierre 0919: p28 firmaba con la
   clave filtrada por un test de CLI anterior).

No se toca HOME ni DIKE_USERS_ROOT: los tests que miden pisos de recall leen
el corpus sellado instalado (lectura), y esa medición no debe degradarse a
skip. El aislamiento requerido es de escritura, no de lectura.
"""

from __future__ import annotations

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

_REAL_HOME = Path.home()
_DIKE = _REAL_HOME / ".dike"
_ANTES: dict[str, dict[str, int] | None] = {}
# P10: el caché de raíces verificadas del operador (`~/.dike/roots_cache`).
_ROOTS_CACHE = _DIKE / "roots_cache"
_ROOTS_ANTES: set[str] = set()
# Auditoría 2026-10-13: la suite también dejaba workspaces nuevos en
# `~/.dike/users` (un `test-user` por corrida, vía el MCP por stdio) y
# entradas en `~/.dike/binding_cache`. Misma guardia: baseline y comparación.
_USERS = _DIKE / "users"
_USERS_ANTES: set[str] = set()
_BINDING_CACHE = _DIKE / "binding_cache"
_BINDING_ANTES: set[str] = set()


def _medida(db: Path) -> dict[str, int] | None:
    """Conteos (gates, eventos, seq máx) de un journal real; None si no existe."""
    if not db.is_file():
        return None
    try:
        uri = f"file:{db.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as con:
            gates = con.execute("SELECT COUNT(*) FROM hitl_gates").fetchone()[0]
            eventos = con.execute("SELECT COUNT(*) FROM hitl_events").fetchone()[0]
        return {"gates": gates, "eventos": eventos}
    except (sqlite3.Error, TypeError):
        return None


def _journals_reales() -> list[Path]:
    found = [_DIKE / "events.db"]
    users = _DIKE / "users"
    if users.is_dir():
        found.extend(sorted(u / "events.db" for u in users.iterdir() if u.is_dir()))
    return found


def pytest_configure(config: pytest.Config) -> None:
    if not os.environ.get("DIKE_HITL_DB"):
        journal_dir = tempfile.mkdtemp(prefix="dike-suite-journal-")
        os.environ["DIKE_HITL_DB"] = os.path.join(journal_dir, "events.db")
    # P07: los logs estructurados (data/logs/*.jsonl) tampoco son destino de la
    # suite; los subagentes escriben ahí al correr sus smoke tests.
    if not os.environ.get("LEXO_LOGS_DIR"):
        os.environ["LEXO_LOGS_DIR"] = tempfile.mkdtemp(prefix="dike-suite-logs-")
    # P07: el monitor de sesgo automático escribe en data/sqlite/benchmarks.db
    # (vía agent_runner). Redirigido a un temporal para la suite.
    if not os.environ.get("LEXO_BENCHMARKS_DB"):
        os.environ["LEXO_BENCHMARKS_DB"] = os.path.join(
            tempfile.mkdtemp(prefix="dike-suite-bench-"), "benchmarks.db"
        )
    # P10: el caché de raíces también: la suite agregaba entradas con claves
    # /tmp/pytest-of-… al del operador (819 acumuladas al medirlo).
    if not os.environ.get("DIKE_ROOTS_CACHE_DIR"):
        os.environ["DIKE_ROOTS_CACHE_DIR"] = tempfile.mkdtemp(prefix="dike-suite-roots-")
    if _ROOTS_CACHE.is_dir():
        _ROOTS_ANTES.update(p.name for p in _ROOTS_CACHE.glob("*.json"))
    if not os.environ.get("DIKE_BINDING_CACHE_DIR"):
        os.environ["DIKE_BINDING_CACHE_DIR"] = tempfile.mkdtemp(prefix="dike-suite-binding-")
    if _BINDING_CACHE.is_dir():
        _BINDING_ANTES.update(p.name for p in _BINDING_CACHE.glob("*.json"))
    if _USERS.is_dir():
        _USERS_ANTES.update(p.name for p in _USERS.iterdir() if p.is_dir())
    for db in _journals_reales():
        _ANTES[str(db)] = _medida(db)


@pytest.fixture(autouse=True)
def _entorno_aislado():
    """Restaura `os.environ` tal como estaba antes del test (contrato 3)."""
    antes = dict(os.environ)
    yield
    if os.environ != antes:
        os.environ.clear()
        os.environ.update(antes)


@pytest.fixture(scope="session", autouse=True)
def _guardia_journal_real():
    """Marca auditada de escritura productiva: compara antes/después."""
    yield
    cambios: dict[str, dict] = {}
    # 1. Journals que existían al inicio: comparar con su baseline.
    for db, antes in _ANTES.items():
        ahora = _medida(Path(db))
        if ahora != antes:
            cambios[db] = {"antes": antes, "despues": ahora}
    # 2. Journals nuevos creados durante la corrida (p. ej. un user workspace
    #    que no existía): un journal bajo ~/.dike con gates > 0 es escritura
    #    productiva, aunque el baseline fuera inexistente.
    for db in _journals_reales():
        if str(db) in _ANTES:
            continue
        ahora = _medida(db)
        if ahora and ahora["gates"] > 0:
            cambios[str(db)] = {"antes": None, "despues": ahora}
    assert not cambios, (
        "P07: la suite escribió en journals HITL reales (comparación "
        f"antes/después). Delta: {cambios}. El journal es append-only: no se "
        "borra; esta marca deja constancia para su revisión."
    )
    nuevos = sorted(
        p.name for p in (_ROOTS_CACHE.glob("*.json") if _ROOTS_CACHE.is_dir() else [])
        if p.name not in _ROOTS_ANTES
    )
    assert not nuevos, (
        f"P10: la suite escribió {len(nuevos)} entrada(s) en el caché de raíces real "
        f"({_ROOTS_CACHE}): {nuevos[:5]}. Debe usar DIKE_ROOTS_CACHE_DIR."
    )
    nuevos_binding = sorted(
        p.name for p in (_BINDING_CACHE.glob("*.json") if _BINDING_CACHE.is_dir() else [])
        if p.name not in _BINDING_ANTES
    )
    assert not nuevos_binding, (
        f"la suite escribió {len(nuevos_binding)} entrada(s) en el caché de binding real "
        f"({_BINDING_CACHE}): {nuevos_binding[:5]}. Debe usar DIKE_BINDING_CACHE_DIR."
    )
    nuevos_users = sorted(
        p.name for p in (_USERS.iterdir() if _USERS.is_dir() else []) if p.is_dir() and p.name not in _USERS_ANTES
    )
    assert not nuevos_users, (
        f"la suite creó {len(nuevos_users)} workspace(s) en {_USERS}: {nuevos_users}. "
        "Un subproceso (MCP por stdio, CLI) debe heredar DIKE_USERS_ROOT; no se borra: "
        "esta marca deja constancia para su revisión."
    )
