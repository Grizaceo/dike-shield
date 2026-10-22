from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from .iris import BASE, BASE_LEGADA, es_eli_propio, es_legado
from .manifest import verify_manifest
from .utils import canonical_json_bytes, read_json, sha256_bytes

NODE_DIRS = ("normas", "articulos", "vigencia", "provenance")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
# Ver lexo_cli/starter/resolver.py: la autoderogación es estructural (el cuerpo
# del artículo *es* la derogación), no una subcadena "derogad" cualquiera.
_SELF_DEROGATION = re.compile(
    r"^\W*(?:(?:art(?:í|i)culo|art\.)\s*[^\n]{0,48}?[.\-–—]+\s*)?derogad[oa]s?\b\W*$",
    re.IGNORECASE,
)
_TERMINAL_PUNCTUATION = ('.', ':', ';', '!', '?', '"', '”', '»', ')', ']')
_PLACEHOLDER_ORIGINS = frozenset({"1900-01-01", "0001-01-01"})


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    errors: tuple[str, ...]
    warnings: tuple[str, ...] = ()


def _parse_date(value: Any, label: str, errors: list[str]) -> date | None:
    if not isinstance(value, str):
        errors.append(f"{label}: fecha ISO-8601 ausente o inválida.")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        errors.append(f"{label}: fecha ISO-8601 inválida: {value!r}.")
        return None


def _load_nodes(root: Path, errors: list[str]) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for directory in NODE_DIRS:
        path = root / directory
        if not path.is_dir():
            errors.append(f"Falta directorio obligatorio: {directory}/")
            continue
        for file_path in sorted(path.glob("*.json")):
            try:
                node = read_json(file_path)
            except Exception as exc:
                errors.append(f"JSON inválido {file_path.relative_to(root)}: {exc}")
                continue
            node_id = node.get("@id") if isinstance(node, dict) else None
            if not isinstance(node_id, str) or not node_id:
                errors.append(f"Nodo sin @id: {file_path.relative_to(root)}")
                continue
            if node_id in nodes:
                errors.append(f"@id duplicado: {node_id}")
            nodes[node_id] = node
    edge_dir = root / "edges"
    if not edge_dir.is_dir():
        errors.append("Falta directorio obligatorio: edges/")
    else:
        for file_path in sorted(edge_dir.glob("*.json")):
            try:
                edge = read_json(file_path)
            except Exception as exc:
                errors.append(f"JSON inválido {file_path.relative_to(root)}: {exc}")
                continue
            if not isinstance(edge, dict) or not edge.get("@id"):
                errors.append(f"Edge sin @id: {file_path.relative_to(root)}")
                continue
            edges.append(edge)
    return nodes, edges


def _validate_resource(node: dict[str, Any], errors: list[str]) -> None:
    node_id = node.get("@id", "<sin-id>")
    node_type = node.get("@type")
    if node_type == "LegalResource":
        if not es_eli_propio(node_id):
            errors.append(f"ID ELI propio inválido: {node_id}")
        if not str(node.get("leychileCode", "")):
            errors.append(f"Norma sin leychileCode: {node_id}")
        if not node.get("title"):
            errors.append(f"Norma sin título: {node_id}")
        if not isinstance(node.get("temporal"), dict):
            errors.append(f"Norma sin ventana temporal: {node_id}")
    elif node_type == "Article":
        text = node.get("text")
        if not node.get("eId") or not node.get("isPartOf") or not isinstance(text, str) or not text.strip():
            errors.append(f"Artículo incompleto: {node_id}")
        if isinstance(text, str) and text.strip() and not text.strip().endswith(
            _TERMINAL_PUNCTUATION,
        ):
            errors.append(
                f"Artículo truncado: el texto no cierra la frase: {node_id}",
            )
        declared = node.get("textSha256")
        if not isinstance(declared, str) or not _HEX64.fullmatch(declared):
            errors.append(f"Artículo sin textSha256 válido: {node_id}")
        elif isinstance(text, str):
            actual = sha256_bytes(text.encode("utf-8"))
            if not hmac.compare_digest(declared, actual):
                errors.append(f"textSha256 no coincide con text: {node_id}")
            citation = node.get("citation")
            if not isinstance(citation, dict):
                errors.append(f"Artículo no citable: falta atestación de completitud: {node_id}")
            elif (
                citation.get("status") != "CITABLE"
                or citation.get("completenessVerified") is not True
                or citation.get("textSha256") != actual
                or not str(citation.get("verificationMethod", "")).strip()
            ):
                errors.append(f"Artículo no citable: atestación inválida: {node_id}")
    provenance = node.get("provenance")
    if node_type in {"LegalResource", "Article"}:
        if not isinstance(provenance, dict):
            errors.append(f"Recurso sin PROV-O mínimo: {node_id}")
        elif not provenance.get("wasDerivedFrom") or not provenance.get("generatedAtTime") or not provenance.get("datasetVersion"):
            errors.append(f"Procedencia incompleta: {node_id}")


def _validate_temporal(node: dict[str, Any], errors: list[str]) -> None:
    if node.get("@type") != "TemporalWindow":
        return
    label = str(node.get("@id", "ventana"))
    if "from" not in node or "to" not in node:
        errors.append(f"{label}: intervalo [from,to) incompleto.")
        return
    start = _parse_date(node.get("from"), f"{label}.from", errors)
    end_value = node.get("to")
    end = None if end_value is None else _parse_date(end_value, f"{label}.to", errors)
    if start is not None and end is not None and end <= start:
        errors.append(f"{label}: intervalo [from,to) inválido; to debe ser posterior a from.")


def _validate_vigencia_coherence(nodes: dict[str, dict[str, Any]], errors: list[str]) -> None:
    """La capa temporal debe representar vigencia, no rellenarla.

    Dos defectos distintos y ambos fail-closed: (a) un origen `from` que el
    parser inventó cuando la fuente no traía fecha, y (b) un artículo cuyo
    cuerpo es su propia derogación pero cuya ventana sigue abierta, con lo que
    el pack lo declararía vigente.
    """
    windows_by_resource: dict[str, list[dict[str, Any]]] = {}
    for node in nodes.values():
        if node.get("@type") == "TemporalWindow":
            windows_by_resource.setdefault(str(node.get("resource", "")), []).append(node)

    for node in nodes.values():
        if node.get("@type") != "Article":
            continue
        node_id = str(node.get("@id", "<sin-id>"))
        text = node.get("text")
        if not isinstance(text, str):
            continue
        windows = list(windows_by_resource.get(node_id, ()))
        inline = node.get("temporal")
        if isinstance(inline, dict):
            windows.append(inline)
        if not windows:
            continue
        if any(str(window.get("from")) in _PLACEHOLDER_ORIGINS for window in windows):
            errors.append(
                f"Vigencia con origen placeholder (no es una fecha jurídica): {node_id}"
            )
        if _SELF_DEROGATION.fullmatch(text.strip()) and any(
            window.get("to") is None for window in windows
        ):
            errors.append(
                f"Artículo derogado con ventana [from,to) abierta: {node_id}"
            )


def _canonical_json_check(root: Path, errors: list[str]) -> None:
    for path in sorted(root.rglob("*.json")):
        if any(part in {"__pycache__", ".snapshots"} for part in path.relative_to(root).parts):
            continue
        try:
            value = read_json(path)
        except Exception:
            continue
        if path.read_bytes() != canonical_json_bytes(value):
            errors.append(f"JSON no canónico/JCS: {path.relative_to(root)}")


def _ttl_uri(value: str) -> str:
    if not value.startswith(("http://", "https://")) or any(char in value for char in "<>\n\r"):
        raise ValueError(f"URI no exportable a Turtle: {value!r}")
    return f"<{value}>"


def _ttl_literal(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
    return f'"{escaped}"'


def export_turtle(package_dir: str | Path, output_path: str | Path) -> Path:
    root = Path(package_dir)
    errors: list[str] = []
    nodes, edges = _load_nodes(root, errors)
    if errors:
        raise ValueError("No se puede exportar Turtle: " + "; ".join(errors))
    lines = [
        f"@prefix lexo: <{BASE}vocab/> .",
        "@prefix prov: <http://www.w3.org/ns/prov#> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for node_id, node in sorted(nodes.items()):
        node_type = node.get("@type")
        type_map = {
            "LegalResource": "lexo:LegalResource",
            "Article": "lexo:Article",
            "TemporalWindow": "lexo:TemporalWindow",
            "prov:Activity": "prov:Activity",
            "prov:Entity": "prov:Entity",
        }
        if node_type in type_map:
            lines.append(f"{_ttl_uri(node_id)} a {type_map[node_type]} .")
        provenance = node.get("provenance") or {}
        source = provenance.get("wasDerivedFrom")
        if isinstance(source, str):
            lines.append(f"{_ttl_uri(node_id)} prov:wasDerivedFrom {_ttl_uri(source)} .")
        if node_type == "LegalResource":
            lines.append(f"{_ttl_uri(node_id)} lexo:leychileCode {_ttl_literal(str(node['leychileCode']))} .")
        if node_type == "Article":
            lines.append(f"{_ttl_uri(node_id)} lexo:eId {_ttl_literal(str(node['eId']))} .")
            lines.append(f"{_ttl_uri(node_id)} lexo:isPartOf {_ttl_uri(str(node['isPartOf']))} .")
        if node_type == "TemporalWindow":
            lines.append(f"{_ttl_uri(node_id)} lexo:from {_ttl_literal(str(node['from']))}^^xsd:date .")
            if node.get("to") is not None:
                lines.append(f"{_ttl_uri(node_id)} lexo:to {_ttl_literal(str(node['to']))}^^xsd:date .")
    for edge in sorted(edges, key=lambda item: item["@id"]):
        predicate = {
            "CONTAINS": "lexo:CONTAINS",
            "DERIVED_FROM": "lexo:DERIVED_FROM",
            "MODIFIES": "lexo:MODIFIES",
        }.get(edge.get("type"))
        if predicate:
            lines.append(f"{_ttl_uri(str(edge['source']))} {predicate} {_ttl_uri(str(edge['target']))} .")
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _iris_legados(nodes: dict[str, dict[str, Any]], edges: list[dict[str, Any]]) -> int:
    """Cuántas referencias del grafo usan todavía la base legada (ARCH-004)."""
    total = 0
    for node in nodes.values():
        total += sum(isinstance(node.get(k), str) and es_legado(node[k]) for k in ("@id", "isPartOf", "resource"))
    for edge in edges:
        total += sum(isinstance(edge.get(k), str) and es_legado(edge[k]) for k in ("@id", "source", "target"))
    return total


def validate_package(
    package_dir: str | Path,
    *,
    export_turtle: str | Path | None = None,
    legado: str = "advertir",
) -> ValidationReport:
    """Valida el paquete. `legado` dice qué hacer con IRI bajo `https://lexo.cl/`
    (dominio ajeno, ARCH-004): «advertir» los acepta con una advertencia —los
    packs sellados antes del 2026-10-14 los traen—, «rechazar» los vuelve error.
    Lo que se construye o se publica se valida con «rechazar»."""
    if legado not in ("advertir", "rechazar"):
        raise ValueError(f"legado debe ser 'advertir' o 'rechazar', no {legado!r}")
    root = Path(package_dir)
    errors: list[str] = []
    warnings: list[str] = []
    if export_turtle is not None:
        try:
            globals()["export_turtle"](root, export_turtle)
        except Exception as exc:
            errors.append(str(exc))

    manifest_report = verify_manifest(root)
    errors.extend(manifest_report.errors)
    for required in (
        root / "schemas" / "starter_resource.schema.json",
        root / "shapes" / "starter_graph.shacl.ttl",
        root / "context.jsonld",
        root / "pack.json",
    ):
        if not required.is_file():
            errors.append(f"Falta artefacto de contrato: {required.relative_to(root)}")

    nodes, edges = _load_nodes(root, errors)
    report_path = root / "BUILD_REPORT.json"
    try:
        report = read_json(report_path)
    except Exception as exc:
        errors.append(f"BUILD_REPORT.json inválido o ausente: {exc}")
        report = {}
    article_files = list((root / "articulos").glob("*.json"))
    norm_files = list((root / "normas").glob("*.json"))
    if (root / "MANIFEST.json").is_file():
        try:
            manifest_entries = read_json(root / "MANIFEST.json").get("files", [])
        except Exception:
            manifest_entries = []
    else:
        manifest_entries = []
    manifest_articles = sum(
        isinstance(item, dict) and str(item.get("path", "")).startswith("articulos/")
        for item in manifest_entries
    )
    expected_counts = {
        "articleCount": (len(article_files), manifest_articles),
        "normCount": (len(norm_files), sum(
            isinstance(item, dict) and str(item.get("path", "")).startswith("normas/")
            for item in manifest_entries
        )),
        "edgeCount": (len(list((root / "edges").glob("*.json"))), sum(
            isinstance(item, dict) and str(item.get("path", "")).startswith("edges/")
            for item in manifest_entries
        )),
    }
    for label, (disk_count, manifest_count) in expected_counts.items():
        declared = report.get(label)
        if declared != disk_count or declared != manifest_count:
            errors.append(
                f"BUILD_REPORT.{label} no coincide: report={declared}, "
                f"disco={disk_count}, manifest={manifest_count}"
            )
    for node in nodes.values():
        _validate_resource(node, errors)
        _validate_temporal(node, errors)
    _validate_vigencia_coherence(nodes, errors)

    legados = _iris_legados(nodes, edges)
    if legados:
        mensaje = (f"{legados} referencias usan la base legada {BASE_LEGADA} (dominio ajeno); "
                   f"los packs nuevos usan {BASE}")
        (errors if legado == "rechazar" else warnings).append(mensaje)

    node_ids = set(nodes)
    for edge in edges:
        edge_id = edge.get("@id", "<sin-id>")
        if edge.get("type") not in {"CONTAINS", "DERIVED_FROM", "MODIFIES"}:
            errors.append(f"Tipo de edge no permitido: {edge_id}")
        for side in ("source", "target"):
            ref = edge.get(side)
            if ref not in node_ids:
                errors.append(f"Referencia huérfana/orphan en {edge_id}.{side}: {ref}")

    for node in nodes.values():
        if node.get("@type") == "Article" and node.get("isPartOf") not in node_ids:
            errors.append(f"Artículo con isPartOf huérfano: {node.get('@id')}")
        if node.get("@type") == "TemporalWindow" and node.get("resource") not in node_ids:
            errors.append(f"Vigencia con resource huérfano: {node.get('@id')}")

    _canonical_json_check(root, errors)
    return ValidationReport(not errors, tuple(errors), tuple(warnings))


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Validar Starter Graph v1 de forma fail-closed")
    parser.add_argument("package", type=Path)
    parser.add_argument("--export-turtle", type=Path)
    parser.add_argument("--legado", choices=("advertir", "rechazar"), default="advertir",
                        help="qué hacer con IRI bajo la base legada (dominio ajeno, ARCH-004)")
    args = parser.parse_args(argv)
    report = validate_package(args.package, export_turtle=args.export_turtle, legado=args.legado)
    print(json.dumps({"ok": report.ok, "errors": list(report.errors), "warnings": list(report.warnings)}, ensure_ascii=False, indent=2))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
