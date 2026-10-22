"""Opciones `--user` / `--users-root` compartidas por los comandos de workspace.

Dos defectos que este módulo cierra:

1. `--user` era obligatorio en `materias`, `gre`, `cycle`, `starter` y
   `pichanga`. El wizard de `dike onboard` ya persiste el usuario elegido y
   `dike web` lo usa; el resto del CLI seguía exigiendo teclearlo, y con el
   nombre exacto: `--user Maria` (con mayúscula) creaba un workspace fantasma
   e informaba éxito, mientras el perfil real quedaba intacto.

2. Al declararse solo en el parser padre, el orden natural
   `dike materias list --user maria` fallaba con «unrecognized arguments».
   Aquí la opción se declara también en cada subcomando con
   `default=argparse.SUPPRESS`, de modo que solo aparece en el namespace
   cuando se pasa y nunca pisa el valor del padre.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from lexo_cli.starter.userconfig import active_user, active_users_root

_USER_HELP = "Usuario del workspace (por defecto, el usuario activo de `dike onboard`)"
_ROOT_HELP = "Carpeta de workspaces (por defecto, la de tu configuración)"


def add_user_flags(parser: argparse.ArgumentParser, *, subcommand: bool = False) -> None:
    """Agrega `--user` y `--users-root` al parser (padre o subcomando)."""
    extra = {"default": argparse.SUPPRESS} if subcommand else {"default": None}
    parser.add_argument("--user", help=_USER_HELP, **extra)
    parser.add_argument("--users-root", help=_ROOT_HELP, **extra)


def resolve_users_root(args) -> str:
    return str(Path(getattr(args, "users_root", None) or active_users_root()).expanduser())


def resolve_user(args, *, comando: str) -> str:
    """Usuario efectivo, o un error que dice exactamente cómo arreglarlo."""
    user = getattr(args, "user", None) or active_user()
    if user:
        return str(user)
    raise SystemExit(
        f"✕ No sé con qué usuario trabajar en `dike {comando}`.\n"
        "  Configura tu usuario una sola vez con:  dike onboard\n"
        f"  O indícalo en este comando con:        dike {comando} --user <tu-nombre>"
    )


def warn_if_workspace_missing(users_root: str, user: str) -> None:
    """Avisa cuando el usuario indicado no tiene workspace todavía.

    `--user Maria` (con el nombre mal escrito) creaba `~/.dike/users/Maria/`
    en silencio y devolvía «✓ guardado», mientras el perfil real seguía sin
    tocarse. Peor: ese directorio de más hacía que el journal HITL dejara de
    resolverse por descubrimiento y `dike hitl list` saliera vacío.
    """
    root = Path(users_root).expanduser()
    if (root / user).is_dir() or not root.is_dir():
        return
    existentes = sorted(entry.name for entry in root.iterdir() if entry.is_dir())
    if not existentes:
        return
    print(f"⚠ El usuario «{user}» no tiene workspace en {root}.")
    print("  Usuarios existentes: " + ", ".join(existentes))
    print("  Si te equivocaste de nombre, cancela (Ctrl+C) antes de que se cree uno nuevo.")
