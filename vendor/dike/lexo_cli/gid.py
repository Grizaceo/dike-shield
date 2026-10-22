"""Lectura dual de GID (ARCH-003, fase F1).

Acepta el dialecto runtime `cl.norma.<alias>:art:<token>` y el v2
`cl.v2.norma.<slug>:art:<etiqueta>`, y los reduce a la clave con la que el runtime indexa hoy
(alias UMJ + token runtime). La escritura no cambia en F1: todo lo que el runtime emite sigue
en el dialecto runtime. Esta es la única copia del regex runtime; antes había cinco.

La v2 se lee con la biblioteca `dike-id` (packages/dike-id), no con un regex propio. Un GID v2
que el runtime no puede representar sin inventar devuelve None (S23: sin similitud ni
degradación):
- una expresión (`:ver:`) o una subunidad (`inc`, `num`, `lit`);
- un desambiguador `:x:`;
- la Ñ, que el runtime escribe como N;
- un slug sin código UMJ en el registro.

El dialecto runtime también se lee estricto (punto 5): la etiqueta debe ser exactamente la que el
runtime escribe (`dike_id.leer_etiqueta_legada`, dialecto `runtime`, y su re-escritura idéntica).
Se rechaza `art:0000`, los sufijos truncados de la v1 (`0007qua`), la etiqueta de la política v1
(`0007bis`), la sin relleno (`11`) y cualquier otra que mezcle dígitos sin ser canónica. Los
tokens de solo palabras (`primero`, `transitorio_primero`) son identidad: el resolver los emite tal
cual cuando el `eId` del paquete es una palabra (`_article_token`). El alias no se valida contra el registro: hay
alias reales de normas bloqueadas (`codigo_mineria`, 166 unidades en IndexO) que el runtime indexa.
"""
from __future__ import annotations

import re
import sys
from functools import cache
from pathlib import Path

try:
    import dike_id
except ModuleNotFoundError as e:
    if e.name != "dike_id":
        raise
    # Hay intérpretes que ven el perfil solo por PYTHONPATH y no instalan sus dependencias: el venv
    # de Hermes con que corre IndexO (2026-09-29) o /usr/bin/python3. dike-id vive en este mismo
    # repo, así que se carga desde su ruta, como lo haría la instalación editable. Los entornos uv
    # y el venv del CLI lo declaran (pyproject.toml, [tool.uv.sources]). Uno instalado siempre gana.
    sys.path.append(str(Path(__file__).resolve().parents[1] / "packages" / "dike-id" / "python" / "src"))
    import dike_id
from dike_id import registros

RUNTIME = re.compile(r"^cl\.norma\.([a-z0-9_-]+):art:([a-z0-9_-]+)$")
_PALABRAS = re.compile(r"[a-z]+(?:_[a-z]+)*")


def _token_runtime(etiqueta: str) -> str | None:
    """La etiqueta si es exactamente lo que el runtime escribe; None si no es identidad."""
    if _PALABRAS.fullmatch(etiqueta):
        return etiqueta
    leido, _ = dike_id.leer_etiqueta_legada(etiqueta)
    if leido is None or leido[3] != "runtime":
        return None
    n, suf, trans, _ = leido
    reescrito = ("t_" if trans else "") + f"{n:04d}" + "".join(f"_{t}" for t in suf)
    return etiqueta if reescrito == etiqueta else None


def motivo_no_identidad(gid: str | None) -> str | None:
    """Por qué un `cl.norma.<alias>:art:<etiqueta>` no es identidad; None si lo es o no es de ese
    dialecto. Para errores explícitos: el llamador no degrada (S23)."""
    m = RUNTIME.fullmatch(gid or "")
    if not m or _token_runtime(m.group(2)) is not None:
        return None
    return dike_id.leer_etiqueta_legada(m.group(2))[1] or "etiqueta_no_canonica"


@cache
def _umj_de_slug() -> dict[str, str]:
    return {slug: umj for umj, slug in registros.alias_umj().items()}


def a_runtime(gid: str | None) -> tuple[str, str] | None:
    """(alias, token) runtime de un GID de artículo en cualquier dialecto, o None."""
    g = gid or ""
    m = RUNTIME.fullmatch(g)
    if m:
        return (m.group(1), m.group(2)) if _token_runtime(m.group(2)) else None
    if not g.startswith("cl.v2.norma."):
        return None
    try:
        ast = dike_id.parse(g)
    except dike_id.ErrorGID:
        return None
    u = ast["unit"]
    if ast["ver"] is not None or u is None or u["type"] != "art":
        return None
    if u["x"] or u["inc"] or u["num"] or u["lit"] or u["class"] not in (None, "trans"):
        return None
    lab = u["label"]
    if "num" not in lab or "ñ" in lab["suf"]:
        return None
    alias = _umj_de_slug().get(ast["slug"])
    if alias is None:
        return None
    token = f"{lab['num']:04d}" + "".join(f"_{t}" for t in lab["suf"])
    return alias, ("t_" + token if u["class"] == "trans" else token)


def a_gid_runtime(gid: str | None) -> str | None:
    """El mismo artículo en el dialecto runtime, o None."""
    par = a_runtime(gid)
    return f"cl.norma.{par[0]}:art:{par[1]}" if par else None


def alias_de(gid: str | None) -> str | None:
    par = a_runtime(gid)
    return par[0] if par else None
