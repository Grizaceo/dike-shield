from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

from .manifest import create_manifest, verify_manifest
from .utils import canonical_json_bytes, distributable_files, read_json, sha256_bytes, sha256_file, write_canonical_json
from .iris import iri

NODE_DIRS = ("normas", "articulos", "edges", "vigencia", "provenance")


def snapshot_hash(package_dir: str | Path) -> str:
    root = Path(package_dir)
    entries = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in distributable_files(root)
    ]
    return sha256_bytes(canonical_json_bytes(entries))


def _node_index(root: Path) -> dict[str, tuple[str, dict[str, Any]]]:
    index: dict[str, tuple[str, dict[str, Any]]] = {}
    for directory in NODE_DIRS:
        for path in sorted((root / directory).glob("*.json")):
            value = read_json(path)
            node_id = value.get("@id") if isinstance(value, dict) else None
            if not node_id:
                raise ValueError(f"Nodo sin @id: {path}")
            if node_id in index:
                raise ValueError(f"@id duplicado: {node_id}")
            index[str(node_id)] = (path.relative_to(root).as_posix(), value)
    return index


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _diff(old: Any, new: Any, path: str = "") -> list[dict[str, Any]]:
    if type(old) is not type(new):
        return [{"op": "replace", "path": path, "value": new}]
    if isinstance(old, dict):
        operations: list[dict[str, Any]] = []
        for key in sorted(old.keys() - new.keys()):
            operations.append({"op": "remove", "path": f"{path}/{_escape_pointer(str(key))}"})
        for key in sorted(new.keys() - old.keys()):
            operations.append({"op": "add", "path": f"{path}/{_escape_pointer(str(key))}", "value": new[key]})
        for key in sorted(old.keys() & new.keys()):
            operations.extend(_diff(old[key], new[key], f"{path}/{_escape_pointer(str(key))}"))
        return operations
    if isinstance(old, list):
        return [] if old == new else [{"op": "replace", "path": path, "value": new}]
    return [] if old == new else [{"op": "replace", "path": path, "value": new}]


def _auxiliary_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in distributable_files(root)
        if path.relative_to(root).parts[0] not in NODE_DIRS
    }


def create_update(base_dir: str | Path, target_dir: str | Path, patch_path: str | Path) -> dict[str, Any]:
    base = Path(base_dir)
    target = Path(target_dir)
    if not verify_manifest(base).ok or not verify_manifest(target).ok:
        raise ValueError("Ambos paquetes deben tener MANIFEST válido antes del diff.")
    if _auxiliary_hashes(base) != _auxiliary_hashes(target):
        raise ValueError("v1 solo admite diffs por nodo; cambiaron archivos de control/contrato.")
    old = _node_index(base)
    new = _node_index(target)
    nodes: list[dict[str, Any]] = []
    for node_id in sorted(old.keys() | new.keys()):
        if node_id not in old:
            rel, value = new[node_id]
            nodes.append({"@id": node_id, "relativePath": rel, "operations": [{"op": "add", "path": "", "value": value}]})
        elif node_id not in new:
            rel, _ = old[node_id]
            nodes.append({"@id": node_id, "relativePath": rel, "operations": [{"op": "remove", "path": ""}]})
        else:
            old_rel, old_value = old[node_id]
            new_rel, new_value = new[node_id]
            if old_rel != new_rel:
                raise ValueError(f"v1 no admite mover un @id entre paths: {node_id}")
            operations = _diff(old_value, new_value)
            if operations:
                nodes.append({"@id": node_id, "relativePath": old_rel, "operations": operations})
    document = {
        "@id": iri(f"updates/{snapshot_hash(base)[:16]}-{snapshot_hash(target)[:16]}"),
        "baseSnapshotHash": snapshot_hash(base),
        "format": "lexo-jsonpatch-by-id-v1",
        "nodes": nodes,
        "targetSnapshotHash": snapshot_hash(target),
    }
    write_canonical_json(Path(patch_path), document)
    return document


def _pointer_parts(path: str) -> list[str]:
    if path == "":
        return []
    if not path.startswith("/"):
        raise ValueError(f"JSON Pointer inválido: {path}")
    return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]


def _apply_operation(document: Any, operation: dict[str, Any]) -> Any:
    op = operation.get("op")
    parts = _pointer_parts(str(operation.get("path", "")))
    if not parts:
        if op == "remove":
            return None
        if op in {"add", "replace"}:
            return operation.get("value")
        raise ValueError(f"Operación jsonpatch no soportada: {op}")
    parent = document
    for part in parts[:-1]:
        if isinstance(parent, list):
            parent = parent[int(part)]
        else:
            parent = parent[part]
    key = parts[-1]
    if isinstance(parent, list):
        index = len(parent) if key == "-" else int(key)
        if op == "add":
            parent.insert(index, operation.get("value"))
        elif op == "replace":
            parent[index] = operation.get("value")
        elif op == "remove":
            parent.pop(index)
        else:
            raise ValueError(f"Operación jsonpatch no soportada: {op}")
    else:
        if op in {"add", "replace"}:
            parent[key] = operation.get("value")
        elif op == "remove":
            del parent[key]
        else:
            raise ValueError(f"Operación jsonpatch no soportada: {op}")
    return document


def apply_update(package_dir: str | Path, patch_path: str | Path) -> str:
    root = Path(package_dir)
    manifest_report = verify_manifest(root)
    if not manifest_report.ok:
        raise ValueError("MANIFEST base inválido: " + "; ".join(manifest_report.errors))
    patch = read_json(Path(patch_path))
    if patch.get("format") != "lexo-jsonpatch-by-id-v1":
        raise ValueError("Formato de update no soportado.")
    if snapshot_hash(root) != patch.get("baseSnapshotHash"):
        raise ValueError("baseSnapshotHash no coincide; update rechazado.")
    manifest = read_json(root / "MANIFEST.json")
    for node_patch in patch.get("nodes", []):
        rel = str(node_patch["relativePath"])
        path = root / rel
        if not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Path fuera del paquete: {rel}")
        document: Any = read_json(path) if path.exists() else None
        for operation in node_patch.get("operations", []):
            document = _apply_operation(document, operation)
        if document is None:
            path.unlink(missing_ok=True)
        else:
            if document.get("@id") != node_patch.get("@id"):
                raise ValueError(f"El patch alteró @id: {node_patch.get('@id')}")
            write_canonical_json(path, document)
    actual = snapshot_hash(root)
    if actual != patch.get("targetSnapshotHash"):
        raise ValueError(f"targetSnapshotHash no coincide: {actual}")
    source = manifest["dataSource"]
    create_manifest(
        root,
        retrieved_at=manifest["retrievedAt"],
        dataset_version=source["datasetVersion"],
        conditions_version=source["conditionsVersion"],
        package_version=manifest["packageVersion"],
    )
    verified = verify_manifest(root)
    if not verified.ok:
        raise ValueError("Update produjo MANIFEST inválido: " + "; ".join(verified.errors))
    return actual


def create_verified_snapshot(package_dir: str | Path, snapshot_dir: str | Path) -> str:
    source = Path(package_dir)
    report = verify_manifest(source)
    if not report.ok:
        raise ValueError("No se puede snapshotear un paquete inválido: " + "; ".join(report.errors))
    target = Path(snapshot_dir)
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    digest = snapshot_hash(target)
    write_canonical_json(target / "SNAPSHOT.json", {"format": "lexo-verified-snapshot-v1", "snapshotHash": digest})
    return digest


def rollback_to_snapshot(package_dir: str | Path, snapshot_dir: str | Path) -> str:
    target = Path(package_dir)
    snapshot = Path(snapshot_dir)
    metadata_path = snapshot / "SNAPSHOT.json"
    if not metadata_path.is_file():
        raise ValueError("Snapshot sin hash verificado.")
    metadata = read_json(metadata_path)
    expected = metadata.get("snapshotHash")
    actual = snapshot_hash(snapshot)
    if actual != expected:
        raise ValueError(f"Snapshot hash inválido: esperado {expected}, observado {actual}")
    manifest_report = verify_manifest(snapshot)
    if not manifest_report.ok:
        raise ValueError("Snapshot MANIFEST inválido: " + "; ".join(manifest_report.errors))
    staging = target.with_name(f".{target.name}.rollback")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(snapshot, staging, ignore=shutil.ignore_patterns("SNAPSHOT.json"))
    if snapshot_hash(staging) != expected:
        shutil.rmtree(staging)
        raise ValueError("Copia de rollback no conserva el hash.")
    if target.exists():
        shutil.rmtree(target)
    staging.replace(target)
    return snapshot_hash(target)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Diff, apply y rollback del Starter Graph")
    sub = parser.add_subparsers(dest="command", required=True)
    diff_parser = sub.add_parser("diff")
    diff_parser.add_argument("base", type=Path)
    diff_parser.add_argument("target", type=Path)
    diff_parser.add_argument("patch", type=Path)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("package", type=Path)
    apply_parser.add_argument("patch", type=Path)
    snap_parser = sub.add_parser("snapshot")
    snap_parser.add_argument("package", type=Path)
    snap_parser.add_argument("snapshot", type=Path)
    rollback_parser = sub.add_parser("rollback")
    rollback_parser.add_argument("package", type=Path)
    rollback_parser.add_argument("snapshot", type=Path)
    args = parser.parse_args(argv)
    if args.command == "diff":
        result: Any = create_update(args.base, args.target, args.patch)
    elif args.command == "apply":
        result = {"snapshotHash": apply_update(args.package, args.patch)}
    elif args.command == "snapshot":
        result = {"snapshotHash": create_verified_snapshot(args.package, args.snapshot)}
    else:
        result = {"snapshotHash": rollback_to_snapshot(args.package, args.snapshot)}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
