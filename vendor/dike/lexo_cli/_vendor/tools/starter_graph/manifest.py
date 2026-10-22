from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .utils import canonical_json_bytes, distributable_files, read_json, sha256_bytes, sha256_file, write_canonical_json
from .iris import iri

ATTRIBUTION = "Ley Chile – Biblioteca del Congreso Nacional"
SPARQL_ENDPOINT = "https://datos.bcn.cl/sparql"
NAVIGATION_SERVICE = "https://nuevo.leychile.cl/servicios/Navegar/get_norma_json"
# Endpoints públicos de BCN que no requieren API key, con el método declarado.
# La prohibición de extracción masiva de las Condiciones de Uso §3 apunta a la
# API con clave; el gate es que el manifiesto no pueda declarar esa vía. El
# SPARQL sirve metadatos y el servicio de navegación sirve el articulado, que el
# grafo LOD no expone: el paquete necesita ambos y debe decir cuál usó.
AUTHORIZED_ENDPOINTS = {
    SPARQL_ENDPOINT: "SPARQL Linked Open Data sin API key",
    NAVIGATION_SERVICE: "servicio público de navegación sin API key, una norma por petición",
}
DEFAULT_ENDPOINT = NAVIGATION_SERVICE
DEFAULT_CONDITIONS_VERSION = "Condiciones de Uso API Ley Chile v1.0, verificadas 2026-08-09"


@dataclass(frozen=True)
class ManifestVerification:
    ok: bool
    errors: tuple[str, ...]


def create_manifest(
    package_dir: str | Path,
    *,
    retrieved_at: str,
    dataset_version: str,
    conditions_version: str = DEFAULT_CONDITIONS_VERSION,
    package_version: str = "1.0.0",
    endpoint: str = DEFAULT_ENDPOINT,
) -> dict[str, Any]:
    root = Path(package_dir)
    files = [
        {
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in distributable_files(root)
    ]
    core: dict[str, Any] = {
        "@id": iri("packages/starter-graph/v1/manifest"),
        "format": "lexo-starter-graph-manifest-v1",
        "packageVersion": package_version,
        "source": ATTRIBUTION,
        "retrievedAt": retrieved_at,
        "dataSource": {
            "endpoint": endpoint,
            "method": AUTHORIZED_ENDPOINTS.get(endpoint, "endpoint no autorizado"),
            "datasetVersion": dataset_version,
            "conditionsVersion": conditions_version,
        },
        "componentLicenses": {
            "legalTexts": {
                "copyrightStatus": "outside-copyright-per-BCN-section-9",
                "basis": "Declaración institucional BCN, Condiciones de Uso API Ley Chile §9",
                "attributionRequired": True,
            },
            "bcnMetadataFacts": {
                "scope": "datos fácticos mínimos; no se copia la ontología ni la compilación BCN",
                "bcnOntologyCopied": False,
            },
            "schema": {
                "origin": "LexO-owned",
                "license": "MIT",
                "derivedFromBcnOntology": False,
            },
        },
        "aiUse": {
            "intendedUse": "consulta/retrieval y visualización del paquete",
            "trainingRequiresExpressBCNAuthorization": True,
            "warning": "El entrenamiento o ajuste de modelos con componentes obtenidos de BCN requiere autorización expresa de la BCN.",
        },
        "files": files,
    }
    manifest = dict(core)
    manifest["manifestCoreSha256"] = sha256_bytes(canonical_json_bytes(core))
    write_canonical_json(root / "MANIFEST.json", manifest)
    return manifest


def _safe_relative_path(value: str) -> bool:
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def verify_manifest(package_dir: str | Path) -> ManifestVerification:
    root = Path(package_dir)
    path = root / "MANIFEST.json"
    errors: list[str] = []
    if not path.is_file():
        return ManifestVerification(False, ("Falta MANIFEST.json; el paquete no es distribuible.",))
    try:
        manifest = read_json(path)
    except Exception as exc:
        return ManifestVerification(False, (f"MANIFEST.json inválido: {exc}",))

    if manifest.get("source") != ATTRIBUTION:
        errors.append("Atribución legal source incorrecta o ausente.")
    if not manifest.get("retrievedAt"):
        errors.append("Falta retrievedAt/fecha de obtención.")
    data_source = manifest.get("dataSource") or {}
    if data_source.get("endpoint") not in AUTHORIZED_ENDPOINTS:
        errors.append("La fuente de datos no es un endpoint público de BCN sin API key.")
    if not data_source.get("datasetVersion") or not data_source.get("conditionsVersion"):
        errors.append("Falta versión de dataset o de condiciones vigente.")
    licenses = manifest.get("componentLicenses") or {}
    if (licenses.get("legalTexts") or {}).get("copyrightStatus") != "outside-copyright-per-BCN-section-9":
        errors.append("Falta licencia/estado de los textos legales conforme a BCN §9.")
    schema = licenses.get("schema") or {}
    if schema.get("origin") != "LexO-owned" or schema.get("derivedFromBcnOntology") is not False:
        errors.append("El esquema propio no está declarado de forma fail-closed.")
    ai_use = manifest.get("aiUse") or {}
    if ai_use.get("trainingRequiresExpressBCNAuthorization") is not True:
        errors.append("Falta advertencia de autorización expresa para entrenamiento IA.")

    core = {key: value for key, value in manifest.items() if key != "manifestCoreSha256"}
    expected_core_hash = sha256_bytes(canonical_json_bytes(core))
    if manifest.get("manifestCoreSha256") != expected_core_hash:
        errors.append("manifestCoreSha256 no coincide.")

    listed: set[str] = set()
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        errors.append("MANIFEST files vacío o inválido.")
        entries = []
    for item in entries:
        rel = item.get("path", "") if isinstance(item, dict) else ""
        if not _safe_relative_path(rel):
            errors.append(f"Ruta insegura en MANIFEST: {rel!r}")
            continue
        listed.add(rel)
        file_path = root / rel
        if not file_path.is_file():
            errors.append(f"Archivo listado ausente: {rel}")
            continue
        actual_hash = sha256_file(file_path)
        if actual_hash != item.get("sha256"):
            errors.append(f"sha256 no coincide: {rel}")
        if file_path.stat().st_size != item.get("bytes"):
            errors.append(f"bytes no coincide: {rel}")

    actual = {path.relative_to(root).as_posix() for path in distributable_files(root)}
    for unexpected in sorted(actual - listed):
        errors.append(f"Archivo distribuible no listado en MANIFEST: {unexpected}")
    for absent in sorted(listed - actual):
        errors.append(f"Archivo del MANIFEST no pertenece al snapshot: {absent}")

    return ManifestVerification(not errors, tuple(errors))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Crear o verificar MANIFEST del Starter Graph")
    sub = parser.add_subparsers(dest="command", required=True)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("package", type=Path)
    create_parser = sub.add_parser("create")
    create_parser.add_argument("package", type=Path)
    create_parser.add_argument("--retrieved-at", required=True)
    create_parser.add_argument("--dataset-version", required=True)
    args = parser.parse_args(argv)
    if args.command == "create":
        print(json.dumps(create_manifest(args.package, retrieved_at=args.retrieved_at, dataset_version=args.dataset_version), ensure_ascii=False, indent=2))
        return 0
    report = verify_manifest(args.package)
    print(json.dumps({"ok": report.ok, "errors": list(report.errors)}, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
