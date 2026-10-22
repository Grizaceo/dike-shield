"""Capa de selección de materias sobre el corpus sellado (biblioteca modular).

El snapshot sellado NO se re-particiona: la modularidad es una capa de
selección por usuario. Cada usuario declara en `materias.json` qué cuerpos
legales le interesan; el resolver sigue siendo fail-closed para cuerpos no
instalados, y esta capa traduce esa ausencia a un mensaje accionable
("No tienes el Código Penal en tu biblioteca. ¿Lo agrego?").

Reglas:
- El perfil vive en `<users_root>/<user>/materias.json`.
- `materias` es la lista de materias elegidas (ids del catálogo).
- `cuerpos` es la lista efectiva de cuerpos (derivada de las materias +
  `base_siempre_activa`), persistida para auditoría.
- Un perfil ausente NO es un error: significa "sin selección" (todo el
  corpus queda disponible, comportamiento histórico).
"""

from __future__ import annotations

import json
from pathlib import Path

_CATALOG = Path(__file__).with_name("materias_catalog.v1.json")

# Materias que el wizard ofrece por defecto (las más comunes en la práctica).
DEFAULT_MATERIAS = ["civil", "laboral"]


def load_catalog() -> dict:
    data = json.loads(_CATALOG.read_text(encoding="utf-8"))
    if data.get("format") != "lexo-materias-catalog-v1":
        raise ValueError("catálogo de materias inválido")
    return data


def materias_disponibles() -> list[dict]:
    """Lista de materias seleccionables, en orden del catálogo."""
    catalog = load_catalog()
    return [
        {"id": mid, **meta}
        for mid, meta in catalog["materias"].items()
    ]


def cuerpos_de_materias(materias: list[str]) -> list[str]:
    """Cuerpos efectivos para una selección de materias (orden estable)."""
    catalog = load_catalog()
    base = catalog.get("base_siempre_activa") or []
    selected = set(materias)
    cuerpos: list[str] = []
    for cid, meta in catalog["cuerpos"].items():
        if cid in base or selected.intersection(meta.get("materias", ())):
            cuerpos.append(cid)
    return cuerpos


def cuerpo_label(alias: str) -> str:
    catalog = load_catalog()
    meta = catalog["cuerpos"].get(alias)
    return meta["label"] if meta else alias


def materia_label(materia_id: str) -> str:
    catalog = load_catalog()
    meta = catalog["materias"].get(materia_id)
    return meta["label"] if meta else materia_id


def _profile_path(users_root: str | Path, user_id: str) -> Path:
    return Path(users_root).expanduser().resolve() / user_id / "materias.json"


def load_profile(users_root: str | Path, user_id: str) -> dict | None:
    """Perfil de materias del usuario, o None si no existe (sin selección)."""
    path = _profile_path(users_root, user_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def save_profile(users_root: str | Path, user_id: str, materias: list[str]) -> dict:
    """Persiste el perfil de materias del usuario y devuelve el perfil escrito."""
    materias = [m for m in materias if m in {x["id"] for x in materias_disponibles()}]
    cuerpos = cuerpos_de_materias(materias)
    profile = {
        "format": "lexo-materias-profile-v1",
        "user": user_id,
        "materias": sorted(materias),
        "cuerpos": cuerpos,
    }
    path = _profile_path(users_root, user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return profile


def active_cuerpos(users_root: str | Path, user_id: str) -> set[str] | None:
    """Cuerpos activos del usuario, o None si no hay perfil (todo activo)."""
    profile = load_profile(users_root, user_id)
    if profile is None:
        return None
    return set(profile.get("cuerpos") or [])


def cuerpo_fuera_de_materias_message(alias: str, users_root: str | Path, user_id: str) -> str:
    """Mensaje cuando un cuerpo quedó oculto por el filtro de materias.

    El mensaje anterior decía «No tienes el Código Civil en tu biblioteca» y
    era falso: el Código Civil estaba instalado, sellado y verificado —de
    hecho el resultado oculto salió de él—; lo que el abogado había elegido es
    trabajar solo materia ambiental. Decirle que le falta una norma que sí
    tiene, y ofrecerle «agregarla», lo manda a reparar algo que no está roto.

    Solo aplica cuando existe un perfil de materias (selección explícita): sin
    perfil no hay filtro y no hay nada que explicar.
    """
    if active_cuerpos(users_root, user_id) is None:
        return ""
    label = cuerpo_label(alias)
    return (
        f"{label} quedó fuera: está en tu biblioteca, pero no entre las "
        f"materias que seleccionaste. Inclúyelo con `dike materias "
        f"--user {user_id} add {alias}`, o busca en toda la biblioteca con "
        "`dike buscar --todas-las-materias`."
    )


# Nombre anterior. Se mantiene para no romper llamadas externas, pero el
# mensaje es el nuevo: el viejo afirmaba algo que no era cierto.
missing_cuerpo_message = cuerpo_fuera_de_materias_message
