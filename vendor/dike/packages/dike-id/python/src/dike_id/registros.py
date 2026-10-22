"""Registros empaquetados de dike-id (copia generada de spec/registries/).

- `normas()`: entradas del registro de normas (S28), con su `estado_alta` y su bloqueo.
- `slugs(incluir_propuestas=True)`: slugs canónicos para S2. Nunca incluye los bloqueados;
  con `incluir_propuestas=False`, solo los `aprobada` (hoy ninguno: toda alta pasa por
  review-graph).
- `alias_umj(incluir_bloqueadas=False)`: código UMJ → slug, para `desde_legado` (lectura dual).
- `alias_legado(incluir_bloqueadas=False)`: todo código heredado de los almacenes (UMJ, grafo
  canónico, review-graph) → slug. Es un superconjunto de `alias_umj`.
- `tribunales()`: {court_slug: {rol_tipo, …}} para S26.
"""
from __future__ import annotations

import functools
import json
import pathlib

_DIR = pathlib.Path(__file__).resolve().parent / "_generated" / "registries"


@functools.cache
def _cargar(nombre: str) -> dict:
    return json.loads((_DIR / f"{nombre}.json").read_text(encoding="utf-8"))


def normas() -> list[dict]:
    return _cargar("norms")["normas"]


def slugs(incluir_propuestas: bool = True) -> frozenset[str]:
    estados = {"aprobada", "propuesta"} if incluir_propuestas else {"aprobada"}
    return frozenset(n["slug_propuesto"] for n in normas()
                     if n["slug_propuesto"] and n["estado_alta"] in estados)


def alias_umj(incluir_bloqueadas: bool = False) -> dict[str, str]:
    return {n["umj_codigo"]: n["slug_propuesto"] for n in normas()
            if n["umj_codigo"] and n["slug_propuesto"] and (incluir_bloqueadas or n["estado_alta"] != "bloqueada")}


def alias_legado(incluir_bloqueadas: bool = False) -> dict[str, str]:
    return {c: n["slug_propuesto"] for n in normas() for c in n["codigos_legado"]
            if n["slug_propuesto"] and (incluir_bloqueadas or n["estado_alta"] != "bloqueada")}


def tribunales() -> dict[str, frozenset[str]]:
    return {t["court_slug"]: frozenset(r["tipo"] for r in t["rol_tipos"]) for t in _cargar("courts")["tribunales"]}
