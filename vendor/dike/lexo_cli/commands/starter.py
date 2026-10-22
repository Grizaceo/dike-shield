"""CLI adapter for local verified Starter Graph packages."""

from __future__ import annotations

import json
from pathlib import Path

from lexo_cli.gre import UserWorkspace
from lexo_cli.starter.manager import DEFAULT_TOOLS_ROOT, StarterManager
from lexo_cli.commands.useropt import (
    add_user_flags, resolve_user, resolve_users_root, warn_if_workspace_missing,
)


def register(subparsers) -> None:
    parser = subparsers.add_parser("starter", help="Instala y verifica Starter Graphs públicos")
    add_user_flags(parser)
    parser.add_argument("--tools-root", default=str(DEFAULT_TOOLS_ROOT))
    actions = parser.add_subparsers(dest="starter_action", required=True)

    install = actions.add_parser("install")
    add_user_flags(install, subcommand=True)
    install.add_argument("source")
    install.add_argument("--name", required=True)
    install.add_argument("--json", action="store_true", dest="as_json")

    verify = actions.add_parser("verify")
    add_user_flags(verify, subcommand=True)
    verify.add_argument("name")
    verify.add_argument("--json", action="store_true", dest="as_json")

    listing = actions.add_parser("list")
    add_user_flags(listing, subcommand=True)
    listing.add_argument("--json", action="store_true", dest="as_json")

    update = actions.add_parser("update")
    add_user_flags(update, subcommand=True)
    update.add_argument("name")
    update.add_argument("patch")
    update.add_argument("--json", action="store_true", dest="as_json")

    rollback = actions.add_parser("rollback")
    add_user_flags(rollback, subcommand=True)
    rollback.add_argument("name")
    rollback.add_argument("snapshot")
    rollback.add_argument("--json", action="store_true", dest="as_json")

    build = actions.add_parser("build")
    add_user_flags(build, subcommand=True)
    build.add_argument("pack_id")
    build.add_argument("--limit", type=int, default=10)
    build.add_argument("--json", action="store_true", dest="as_json")
    parser.set_defaults(func=handle)


def handle(args) -> int:
    users_root = resolve_users_root(args)
    user = resolve_user(args, comando="starter")
    warn_if_workspace_missing(users_root, user)
    manager = StarterManager(UserWorkspace(users_root, user), tools_root=args.tools_root)
    if args.starter_action == "install":
        result = manager.install(args.source, args.name)
    elif args.starter_action == "verify":
        result = manager.verify(args.name)
    elif args.starter_action == "list":
        result = manager.list_packages()
    elif args.starter_action == "update":
        result = manager.apply_update(args.name, args.patch)
    elif args.starter_action == "rollback":
        result = manager.rollback(args.name, args.snapshot)
    elif args.starter_action == "build":
        # El build de starter packs delega en el toolchain externo
        # (starter_graph.build) y luego instala el paquete resultante.
        from lexo_cli._vendor.tools.starter_graph.build import build_package
        from lexo_cli.starter.userconfig import DEFAULT_TOOLS_ROOT
        tools_root = Path(args.tools_root or DEFAULT_TOOLS_ROOT)
        starter_graph_dir = tools_root / "tools" / "starter_graph"
        if not starter_graph_dir.is_dir():
            raise ValueError(f"Starter Graph toolchain no encontrada en {tools_root}")
        import sys
        sys.path.insert(0, str(starter_graph_dir.parent))
        workdir = manager.workspace.root / ".build-staging" / args.pack_id
        if workdir.exists():
            import shutil
            shutil.rmtree(workdir)
        workdir.mkdir(parents=True)
        result = build_package(workdir, packs=[args.pack_id], limit=args.limit)
        installed = manager.install(workdir, args.pack_id)
        result["installed"] = installed
    else:
        raise ValueError(args.starter_action)
    if getattr(args, "as_json", False):
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        _render(args.starter_action, result)
    # P9: un verificador que termina en 0 con el paquete roto no le sirve a un
    # script ni al panel; «CON PROBLEMAS» ahora también es un código de salida.
    if args.starter_action == "verify" and not result.get("valid"):
        return 1
    return 0


def _paquete(item: dict) -> None:
    estado = "verificado" if item.get("valid") else "CON PROBLEMAS"
    print(f"· {item.get('name')} — {estado}")
    if item.get("norm_count") or item.get("article_count"):
        print(f"    {item.get('norm_count', 0)} cuerpos legales · {item.get('article_count', 0)} artículos")
    if item.get("retrieved_at"):
        print(f"    Obtenido de la fuente oficial el {str(item['retrieved_at'])[:10]}")
    for error in item.get("errors") or []:
        print(f"    ✕ {error}")


def _render(action: str, result) -> None:
    """Salida legible: antes era `print(result)` — el `repr` del dict."""
    if action == "list":
        if not result:
            print("No tienes ningún paquete normativo instalado.")
            print("  Instala el tuyo con: dike onboard")
            return
        print(f"{len(result)} paquete(s) normativo(s) en tu biblioteca:\n")
        for item in result:
            _paquete(item)
        return
    if action == "verify":
        _paquete(result)
        return
    if action == "install":
        print(f"✓ Paquete «{result.get('name')}» instalado y sellado.")
        print(f"    {result.get('norm_count', 0)} cuerpos legales · {result.get('article_count', 0)} artículos")
        print("    Sin uso de red." if result.get("network_used") is False else "")
        return
    print(f"✓ Listo: {result.get('name', '')} (sello {str(result.get('snapshot_hash', ''))[:12]}…)")
