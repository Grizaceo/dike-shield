"""Resolución del corpus canónico instalado, compartida por TODAS las superficies.

Antes de este módulo, `nif_studio/execution.py` leía `cfg["starter"]["roots"]`,
una clave que ningún comando del producto escribía: solo la fabricaba un test.
El efecto era que los cinco gates fail-closed de `starter/resolver.py`
(ARTICLE_TRUNCATED, DEROGATION_UNRESOLVED, TEMPORAL_PLACEHOLDER,
TEXT_HASH_MISSING, UNRESOLVABLE_GID) nunca se evaluaban sobre un artículo real
desde el CLI: toda consulta gobernada abortaba con "Resolver canónico no
configurado". El mecanismo correcto —`StarterManager.installed_corpus_roots()`,
que ya usaban `pichanga`, `cycle` y `dike_web`— estaba a un import de distancia.

Reglas de este módulo:

- `cfg["starter"]["roots"]` sigue teniendo prioridad, como override explícito.
- Si no está, se descubre el workspace del usuario y se usan sus snapshots
  sellados.
- Cuando no hay corpus, se devuelve SIEMPRE un motivo legible. Un fail-closed
  que no explica por qué se cerró es indistinguible de un producto roto.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_USERS_ROOT = Path.home() / ".dike" / "users"


@dataclass(frozen=True)
class CorpusResolution:
    """Corpus canónico disponible, con la procedencia de la decisión."""

    roots: tuple[Path, ...] = ()
    source: str = "none"  # "config" | "workspace" | "none"
    reason: str = ""
    user_id: str | None = None
    candidates: tuple[str, ...] = field(default=())

    def __bool__(self) -> bool:
        return bool(self.roots)


def _installed_users(users_root: Path) -> list[str]:
    """Usuarios cuyo workspace tiene al menos un paquete starter sellado."""
    if not users_root.is_dir():
        return []
    found: list[str] = []
    for user_dir in sorted(users_root.iterdir()):
        if not user_dir.is_dir():
            continue
        starter_dir = user_dir / "starter"
        if not starter_dir.is_dir():
            continue
        if any(pkg.joinpath("STATE.json").is_file()
               for pkg in starter_dir.iterdir() if pkg.is_dir()):
            found.append(user_dir.name)
    return found


def resolve_corpus_roots(
    cfg: dict | None = None,
    *,
    users_root: str | Path | None = None,
    user_id: str | None = None,
    tools_root: str | Path | None = None,
) -> CorpusResolution:
    """Devuelve los roots del corpus canónico y por qué.

    Nunca lanza: un corpus irresoluble se reporta como `roots=()` más un
    `reason`, para que el llamador abstenga con un mensaje accionable.
    """
    starter_cfg = (cfg or {}).get("starter") or {}

    explicit = starter_cfg.get("roots") or []
    if explicit:
        roots = tuple(Path(root).expanduser().resolve() for root in explicit)
        missing = [str(root) for root in roots if not root.is_dir()]
        if missing:
            return CorpusResolution(
                reason=f"starter.roots apunta a rutas inexistentes: {', '.join(missing)}",
            )
        return CorpusResolution(roots=roots, source="config")

    resolved_users_root = Path(
        users_root
        or starter_cfg.get("users_root")
        or os.environ.get("DIKE_USERS_ROOT")
        or DEFAULT_USERS_ROOT
    ).expanduser().resolve()

    available = _installed_users(resolved_users_root)
    chosen = (
        user_id
        or starter_cfg.get("user")
        or os.environ.get("DIKE_USER")
    )

    if chosen is None:
        if not available:
            return CorpusResolution(
                reason=(
                    f"no hay starter instalado en {resolved_users_root}. "
                    "Instala uno con `dike starter install` o define starter.roots."
                ),
            )
        if len(available) > 1:
            return CorpusResolution(
                candidates=tuple(available),
                reason=(
                    f"hay {len(available)} workspaces con starter instalado "
                    f"({', '.join(available)}); define starter.user en la configuración "
                    "o la variable DIKE_USER para elegir uno."
                ),
            )
        chosen = available[0]

    # Import diferido: StarterManager valida su toolchain en el constructor y
    # no queremos ese coste (ni ese fallo) en superficies que no usan corpus.
    try:
        from lexo_cli.pichanga.isolation import UserWorkspace
        from lexo_cli.starter.manager import DEFAULT_TOOLS_ROOT, StarterManager

        workspace = UserWorkspace(resolved_users_root, chosen)
        manager = StarterManager(
            workspace,
            tools_root=tools_root or starter_cfg.get("tools_root") or DEFAULT_TOOLS_ROOT,
        )
        roots = tuple(manager.installed_corpus_roots())
    except Exception as exc:  # noqa: BLE001 — el motivo se propaga al usuario
        return CorpusResolution(
            user_id=chosen,
            reason=f"no se pudo abrir el corpus del usuario '{chosen}': {exc}",
        )

    if not roots:
        return CorpusResolution(
            user_id=chosen,
            reason=(
                f"el workspace de '{chosen}' no tiene ningún snapshot sellado "
                f"en {resolved_users_root / chosen / 'starter'}."
            ),
        )
    return CorpusResolution(roots=roots, source="workspace", user_id=chosen)
