"""Shared command integration for executable NIF plans."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from threading import Lock
from typing import Any

from lexo_cli.starter.discovery import DEFAULT_USERS_ROOT, resolve_corpus_roots
from lexo_cli.starter.resolver import StarterCorpusResolver
from lexo_cli.vault import search_vault_detailed

from .executor import SearchOutcome, execute_plan
from .plan import resolve_plan

# Process-local canonical resolver cache. Keyed by resolved roots + STATE
# signatures so that changing explicit roots / user / users_root or the
# installed snapshot invalidates the cache. Lives only within one process:
# first call performs full validation, subsequent identical calls reuse it.
_canonical_cache: dict[tuple, Any] = {}
_canonical_cache_lock = Lock()


def _file_signature(path: Path) -> tuple[str, str]:
    """Cheap, exact signature for small control files (especially STATE.json)."""
    try:
        return (str(path.resolve()), hashlib.sha256(path.read_bytes()).hexdigest())
    except OSError:
        return (str(path), "missing")


def _installed_state_signatures(users_root: Path, user: str | None) -> tuple:
    """Signatures that identify which immutable snapshots are installed.

    STATE files are tiny and contain both snapshot path and snapshot hash. Reading
    them is cheap; the expensive package/hash validation still happens on the
    first cache miss inside ``resolve_corpus_roots``.
    """
    if user:
        pattern_root = users_root / user / "starter"
        states = sorted(pattern_root.glob("*/STATE.json")) if pattern_root.is_dir() else []
    else:
        states = sorted(users_root.glob("*/starter/*/STATE.json")) if users_root.is_dir() else []
    return tuple(_file_signature(path) for path in states)


def _explicit_root_signatures(roots: tuple[str, ...]) -> tuple:
    signatures = []
    for raw in roots:
        root = Path(raw).expanduser().resolve()
        controls = []
        for name in ("STATE.json", "SNAPSHOT.json", "MANIFEST.json"):
            path = root / name
            if path.is_file():
                stat = path.stat()
                controls.append((name, stat.st_mtime_ns, stat.st_size))
        signatures.append((str(root), tuple(controls)))
    return tuple(signatures)


def _cache_key(cfg: dict, *, as_of=None) -> tuple:
    """Build a cheap pre-validation key; never calls ``resolve_corpus_roots``.

    ``as_of`` is part of the semantic identity: the same immutable snapshot
    resolves a provision differently on different dates.
    """
    starter_cfg = (cfg or {}).get("starter") or {}
    explicit_roots = tuple(str(item) for item in (starter_cfg.get("roots") or ()))
    users_root = Path(
        starter_cfg.get("users_root")
        or os.environ.get("DIKE_USERS_ROOT")
        or DEFAULT_USERS_ROOT
    ).expanduser().resolve()
    user = str(starter_cfg.get("user") or os.environ.get("DIKE_USER") or "")
    tools_root = str(
        starter_cfg.get("tools_root")
        or os.environ.get("DIKE_STARTER_TOOLS_ROOT")
        or ""
    )
    source_signature = (
        _explicit_root_signatures(explicit_roots)
        if explicit_roots
        else _installed_state_signatures(users_root, user or None)
    )
    return (
        id(resolve_corpus_roots),
        explicit_roots,
        str(users_root),
        user,
        tools_root,
        source_signature,
        as_of.isoformat() if as_of is not None else None,
    )


def canonical_resolver_for(cfg: dict, *, as_of=None):
    """Resolver canónico de la instalación, o (None, motivo) si no hay corpus.

    El motivo viaja hasta el usuario: un fail-closed que solo dice "no
    configurado" no distingue "no instalaste el pack" de "el pack está
    corrupto", y ambas se arreglan distinto.

    Resultado cacheado por proceso para evitar re-validar (~15s) en
    llamadas idénticas dentro del mismo comando (p.ej. `preguntar --normas`
    invoca dos veces). La cache se invalida automáticamente cuando cambian
    los roots explícitos, el user, el users_root, o el STATE.json del
    snapshot instalado.
    """
    key = _cache_key(cfg, as_of=as_of)

    with _canonical_cache_lock:
        cached = _canonical_cache.get(key)
        if cached is not None:
            return cached[0], cached[1]

    # Slow path: full validation (~12s for a cold chile-base snapshot). Failed
    # discovery/resolution is intentionally not cached because it may be transient.
    resolution = resolve_corpus_roots(cfg)
    if not resolution:
        return None, resolution.reason
    try:
        resolver = StarterCorpusResolver(resolution.roots, as_of=as_of)
        error = ""
    except Exception as exc:  # noqa: BLE001 — corpus inválido debe ser audible
        resolver = None
        error = (
            f"corpus canónico inválido ({', '.join(str(r) for r in resolution.roots)}): {exc}"
        )

    if resolver is not None:
        with _canonical_cache_lock:
            _canonical_cache[key] = (resolver, error)

    return resolver, error


def _reset_canonical_cache() -> None:
    """Test-only hook: clear the process-local resolver cache."""
    with _canonical_cache_lock:
        _canonical_cache.clear()


def execute_nif_plan(nif: dict, *, command: str, cfg: dict, area: str):
    if not isinstance(nif, dict) or not nif:
        raise ValueError("Se requiere NIF para ejecutar un plan gobernado")
    plan = resolve_plan(nif, command=command)
    resolver, resolver_error = canonical_resolver_for(cfg)

    def strict_index(query: str, gids: tuple[str, ...], legal_area: str) -> SearchOutcome:
        # Los GIDs NO se concatenan a la consulta: son identificadores opacos
        # ("cl.norma.ct:art:0162") que el índice semántico no puede embeber, y
        # al mezclarlos con la pregunta desplazaban los términos jurídicos
        # reales, destruyendo el retrieval. La resolución por GID es trabajo
        # del resolver canónico, no del índice.
        outcome = search_vault_detailed(query.strip(), 5, cfg, legal_area, strict=True)
        return SearchOutcome(outcome.results, outcome.backend, outcome.degraded, outcome.errors)

    return execute_plan(
        plan,
        area=area,
        index_search=strict_index,
        canonical_resolver=resolver,
        canonical_unavailable_reason=resolver_error,
    )


def evidence_text(execution) -> str:
    parts: list[str] = []
    for index, item in enumerate(execution.evidence, 1):
        gid = item.get("gid")
        eli = item.get("eli")
        digest = item.get("text_sha256")
        text = item.get("text") or item.get("raw_content") or item.get("content") or ""
        label = gid or item.get("filename") or item.get("path") or f"evidencia-{index}"
        trace = " | ".join(value for value in [eli, digest] if value)
        parts.append(f"[Fuente {index}: {label}{' | ' + trace if trace else ''}] {str(text)[:1200]}")
    return "\n".join(parts)
