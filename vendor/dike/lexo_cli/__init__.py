"""LexO CLI — re-exporta la configuración desde el módulo canónico.

El paquete tuvo durante un tiempo un DEFAULT_CONFIG duplicado en este módulo
con el binario de conda hardcodeado a una máquina concreta
("/home/<usuario>/.miniconda/bin") y un start.sh desactualizado. Todo el runtime
importa desde `lexo_cli.config` (que deriva conda_bin del intérprete activo),
así que el duplicado era un fósil muerto hasta que alguien lo usara. Aquí solo
se re-exporta para no romper `from lexo_cli import load_config`, manteniendo
una sola fuente de verdad.
"""

from __future__ import annotations

from lexo_cli.config import (  # noqa: F401 — re-export público
    CONFIG_ENV_VAR,
    CONFIG_PATHS,
    DEFAULT_CONFIG,
    load_config,
    project_root,
    subagents_root,
)

__all__ = [
    "CONFIG_ENV_VAR",
    "CONFIG_PATHS",
    "DEFAULT_CONFIG",
    "load_config",
    "project_root",
    "subagents_root",
]
