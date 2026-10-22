"""LexO CLI — config, paths, defaults."""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any

import yaml

# ── Defaults ────────────────────────────────────────────────────────────────


def _default_conda_bin() -> str:
    """El directorio de binarios del intérprete actual, si es utilizable.

    IndexO se levanta con `start.sh`, que necesita un `python` con torch en el
    PATH. El del proceso que llama es la mejor apuesta disponible sin
    configurar nada; si no existe, se devuelve cadena vacía y el autostart no
    inyecta un PATH inventado.
    """
    import sys

    candidato = Path(sys.executable).resolve().parent
    return str(candidato) if candidato.is_dir() else ""


DEFAULT_CONFIG = {
    "vault": {
        "path": str(Path.home() / ".hermes" / "workspaces" / "lexo" / "Vault" / "Lexo" / "Vigente"),
        "indexo_url": "http://localhost:7861",
        "indexo_enabled": True,
        "indexo_hybrid": True,
        "indexo_autostart": True,
        # v3 is the canonical runtime. start.sh remains a compatibility wrapper
        # but new configurations should name the target runtime explicitly.
        "indexo_start_script": str(
            Path.home() / ".hermes" / "profiles" / "lexo-alpha"
            / "_legal_repos" / "indexo-retriever-prod" / "start_v3.sh"
        ),
        # Se deriva del intérprete que está corriendo, no de la máquina de
        # quien escribió esto: "/home/<usuario>/.miniconda/bin" quedaba en el
        # default y en cualquier otro equipo apuntaba a un directorio
        # inexistente, así que el autostart de IndexO fallaba en silencio.
        "indexo_conda_bin": _default_conda_bin(),
        "indexo_start_timeout": 90,
    },
    "cases": {
        "root": str(Path.home() / ".dike" / "users" / "default" / "cases"),
    },
    "output": {
        "format": "text",
        "verbose": False,
    },
    "conversation": {
        "backend": "hermes",
        "hermes_profile": "lexo-lawyer",
        "inject_default_skills": False,
    },
    "legal_area_default": "civil",
}

CONFIG_ENV_VAR = "LEXO_CONFIG"
CONFIG_PATHS = [
    Path(".lexo.yaml"),
    Path(".lexo.yml"),
    Path.home() / ".lexo" / "config.yaml",
    Path.home() / ".lexo" / "config.yml",
]


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load config from file, env var, or defaults."""
    cfg = copy.deepcopy(DEFAULT_CONFIG)

    if config_path:
        p = Path(config_path)
        if p.exists():
            _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        return cfg

    env_path = os.environ.get(CONFIG_ENV_VAR)
    if env_path:
        p = Path(env_path)
        if p.exists():
            _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
        return cfg

    for p in CONFIG_PATHS:
        if p.exists():
            _merge(cfg, yaml.safe_load(p.read_text(encoding="utf-8")) or {})
            return cfg

    return cfg


def _merge(base: dict, override: dict) -> None:
    """Deep-merge override into base (mutates base)."""
    for k, v in override.items():
        if isinstance(v, dict) and k in base and isinstance(base[k], dict):
            _merge(base[k], v)
        else:
            base[k] = v


def project_root() -> Path:
    """Return the root of the lexo-harness package."""
    return Path(__file__).resolve().parent.parent


def subagents_root() -> Path:
    """Return the path to subagents/ directory."""
    return project_root() / "subagents"
