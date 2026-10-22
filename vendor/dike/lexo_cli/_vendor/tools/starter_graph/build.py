"""BCN SPARQL → LexO Starter Graph Package v1.

The live path uses only https://datos.bcn.cl/sparql (no API key). Article
structure is parsed from the public ``hasXmlDocument`` resource exposed by the
LOD record. Tests use a bounded public mini-fixture; no private vault is read.
"""

from __future__ import annotations

import argparse
import json
import shutil
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from .manifest import DEFAULT_CONDITIONS_VERSION, SPARQL_ENDPOINT, create_manifest
from .iris import USER_AGENT, iri
from .utils import read_json, sha256_bytes, slug, write_canonical_json

MODULE_DIR = Path(__file__).resolve().parent
BCN = "http://datos.bcn.cl/ontologies/bcn-norms#"
DC = "http://purl.org/dc/elements/1.1/"
XML_NS = "http://www.leychile.cl/esquemas"


class SparqlClient:
    def __init__(self, *, endpoint: str = SPARQL_ENDPOINT, timeout: int = 60, retries: int = 3) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self.retries = retries

    def query(self, query: str) -> list[dict[str, Any]]:
        data = urllib.parse.urlencode(
            {"query": query, "format": "application/sparql-results+json"}
        ).encode("utf-8")
        request = urllib.request.Request(
            self.endpoint,
            data=data,
            headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
        )
        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    if response.status != 200:
                        raise RuntimeError(f"SPARQL HTTP {response.status}")
                    return json.load(response).get("results", {}).get("bindings", [])
            except Exception as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)
        raise RuntimeError(f"BCN SPARQL falló tras {self.retries} intentos: {last_error}")


def _binding(row: dict[str, Any], key: str, default: Any = None) -> Any:
    value = row.get(key)
    return value.get("value", default) if isinstance(value, dict) else default


def _pack_specs(pack_ids: Iterable[str]) -> list[dict[str, Any]]:
    specs: list[dict[str, Any]] = []
    for pack_id in pack_ids:
        path = MODULE_DIR / "packs" / f"{pack_id}.json"
        if not path.is_file():
            raise ValueError(f"Pack desconocido: {pack_id}")
        specs.append(read_json(path))
    return specs


def _pack_codes(specs: Iterable[dict[str, Any]]) -> list[str]:
    result: list[str] = []
    for spec in specs:
        for code in (spec.get("normativeSelectors") or {}).get("leychileCodes", []):
            code = str(code)
            if code not in result:
                result.append(code)
    return result


def _metadata_query(codes: list[str]) -> str:
    if not codes or any(not code.isdigit() for code in codes):
        raise ValueError("leychileCode debe ser numérico")
    values = " ".join(codes)
    return f"""PREFIX bcn: <{BCN}>
PREFIX dc: <{DC}>
SELECT ?norm ?code ?number ?title ?type ?publish ?promulgation ?version ?latest ?xml WHERE {{
 VALUES ?code {{ {values} }}
 ?norm a bcn:Norm ; bcn:leychileCode ?code ; bcn:hasNumber ?number .
 OPTIONAL {{ ?norm dc:title ?title }} OPTIONAL {{ ?norm bcn:type ?type }}
 OPTIONAL {{ ?norm bcn:publishDate ?publish }} OPTIONAL {{ ?norm bcn:promulgationDate ?promulgation }}
 OPTIONAL {{ ?norm bcn:versionDate ?version }} OPTIONAL {{ ?norm bcn:isLatestVersion ?latest }}
 OPTIONAL {{ ?norm bcn:hasXmlDocument ?xml }}
}} ORDER BY ?code ?norm"""


def _relations_query(codes: list[str]) -> str:
    values = " ".join(codes)
    return f"""PREFIX bcn: <{BCN}>
SELECT DISTINCT ?sourceCode ?targetCode ?predicate ?sourceUri ?targetUri WHERE {{
 VALUES ?sourceCode {{ {values} }} VALUES ?targetCode {{ {values} }}
 {{ ?sourceUri bcn:modifiesTo ?targetUri . BIND("modifiesTo" AS ?predicate) }}
 UNION {{ ?targetUri bcn:isModifiedBy ?sourceUri . BIND("isModifiedBy" AS ?predicate) }}
 ?sourceUri bcn:leychileCode ?sourceCode . ?targetUri bcn:leychileCode ?targetCode .
}} LIMIT 1000"""


def _dataset_version_query(as_of: str) -> str:
    # The upper bound is mandatory: BCN currently contains a corrupt 2878 date.
    return f"""PREFIX bcn: <{BCN}>
SELECT (MAX(?date) AS ?maxDate) WHERE {{
 ?norm a bcn:Norm ; bcn:publishDate ?date .
 FILTER(?date <= "{as_of}"^^<http://www.w3.org/2001/XMLSchema#date>)
}}"""


def _record_score(record: dict[str, Any]) -> tuple[int, int, str]:
    return (
        1 if "/es@" not in str(record.get("sourceUri", "")) else 0,
        1 if record.get("xmlDocument") else 0,
        str(record.get("versionDate") or ""),
    )


def _fetch_xml(url: str, *, max_attempts: int = 4) -> str:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1", "User-Agent": USER_AGENT},
    )
    last_error: Exception | None = None
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                if response.status != 200:
                    raise RuntimeError(f"XML HTTP {response.status}")
                return response.read().decode("utf-8")
        except RuntimeError as exc:
            # Distinguish HTTP 429 (rate-limit) for a clearer error + longer backoff.
            if "HTTP 429" in str(exc):
                last_error = RuntimeError("XML público BCN rate-limited (HTTP 429)")
                # Exponential backoff with jitter; give the origin a real pause.
                time.sleep(min(2 ** (attempt + 2), 30) + 0.5 * (attempt + 1))
                continue
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
        except Exception as exc:
            last_error = exc
            if attempt < max_attempts - 1:
                time.sleep(2**attempt)
    raise RuntimeError(f"XML público BCN no disponible: {url}: {last_error}")


def _live_source(
    codes: list[str], limit: int, retrieved_at: str, client: SparqlClient
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str, list[str]]:
    selected = codes[:limit]
    rows = client.query(_metadata_query(selected))
    by_code: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(_binding(row, "code", ""))
        if not code:
            continue
        candidate = {
            "sourceUri": _binding(row, "norm"),
            "leychileCode": code,
            "number": str(_binding(row, "number", "")),
            "title": _binding(row, "title", "SIN TÍTULO BCN"),
            "type": str(_binding(row, "type", "norma")).rsplit("#", 1)[-1],
            "publishDate": _binding(row, "publish"),
            "promulgationDate": _binding(row, "promulgation"),
            "versionDate": _binding(row, "version") or _binding(row, "publish"),
            "isLatestVersion": str(_binding(row, "latest", "1")) == "1",
            "xmlDocument": _binding(row, "xml"),
            "xml": None,
        }
        if code not in by_code or _record_score(candidate) > _record_score(by_code[code]):
            by_code[code] = candidate
    records = [by_code[code] for code in selected if code in by_code]
    warnings: list[str] = []
    missing = [code for code in selected if code not in by_code]
    if missing:
        warnings.append("No recuperados desde SPARQL: " + ", ".join(missing))
    fetched = 0
    for record in records:
        # ``leychileCode`` was obtained from SPARQL. The no-key obtxml resource
        # is the same public document relation exposed as hasXmlDocument.
        url = record.get("xmlDocument") or (
            "https://www.leychile.cl/Consulta/obtxml?opt=7&idNorma=" + record["leychileCode"]
        )
        record["xmlDocument"] = url
        try:
            record["xml"] = _fetch_xml(str(url))
            fetched += 1
        except RuntimeError as exc:
            warnings.append(str(exc))
    if records and fetched == 0:
        # Every XML fetch failed (rate-limit/network). The pack would ship with
        # normas but zero articulos — surface this as a hard degradation signal.
        warnings.append(
            "DEGRADADO: no se pudo bajar el XML de artículos (rate-limit BCN). "
            "El paquete queda sin artículos; reintente más tarde o use el fixture offline."
        )
    try:
        relation_rows = client.query(_relations_query([record["leychileCode"] for record in records]))
        relations = [
            {
                "predicate": _binding(row, "predicate"),
                "sourceCode": str(_binding(row, "sourceCode", "")),
                "targetCode": str(_binding(row, "targetCode", "")),
                "sourceUri": _binding(row, "sourceUri"),
                "targetUri": _binding(row, "targetUri"),
            }
            for row in relation_rows
        ]
    except RuntimeError as exc:
        warnings.append(f"Relaciones BCN degradadas: {exc}")
        relations = []
    version_rows = client.query(_dataset_version_query(retrieved_at[:10]))
    dataset_version = str(_binding(version_rows[0], "maxDate", retrieved_at[:10])) if version_rows else retrieved_at[:10]
    return records, relations, dataset_version, warnings


def _child_text(element: ET.Element, name: str) -> str:
    # BCN nests NombreParte/TituloParte under Metadatos in real obtxml while
    # Texto is usually direct. Descendant lookup handles both shapes.
    child = element.find(f".//{{{XML_NS}}}{name}")
    return " ".join("".join(child.itertext()).split()) if child is not None else ""


def _parse_articles(record: dict[str, Any], norm_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    xml_text = record.get("xml")
    if not xml_text:
        return [], {}
    root = ET.fromstring(xml_text)
    xml_meta = {
        "fechaVersion": root.attrib.get("fechaVersion"),
        "derogado": root.attrib.get("derogado"),
        "schemaVersion": root.attrib.get("SchemaVersion"),
    }
    articles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for part in root.iter(f"{{{XML_NS}}}EstructuraFuncional"):
        if not str(part.attrib.get("tipoParte", "")).lower().startswith("art"):
            continue
        name = _child_text(part, "NombreParte") or _child_text(part, "TituloParte")
        text = _child_text(part, "Texto")
        if not text:
            continue
        transitory = str(part.attrib.get("transitorio", "")).lower() == "transitorio"
        base = f"art_{'transitorio_' if transitory else ''}{slug(name)}"
        eid = base if base not in seen else f"{base}_{slug(str(part.attrib.get('idParte', len(seen) + 1)))}"
        seen.add(eid)
        article_id = f"{norm_id}/{eid}"
        articles.append(
            {
                "@id": article_id,
                "@type": "Article",
                "bcnIdParte": part.attrib.get("idParte"),
                "eId": eid,
                "isPartOf": norm_id,
                "isTransitory": transitory,
                "label": _child_text(part, "TituloParte") or name,
                "text": text,
                "versionDate": part.attrib.get("fechaVersion") or xml_meta.get("fechaVersion"),
            }
        )
    return articles, xml_meta


def _eli_id(record: dict[str, Any]) -> str:
    year = str(record.get("publishDate") or record.get("versionDate") or "0000")[:4]
    return iri(f"eli/cl/{slug(str(record.get('type', 'norma')))}/{slug(str(record['number']))}/{year}")


def _provenance(source: str, retrieved_at: str, dataset_version: str, activity_id: str) -> dict[str, Any]:
    return {
        "@type": "prov:Entity",
        "datasetVersion": dataset_version,
        "generatedAtTime": retrieved_at,
        "wasDerivedFrom": source,
        "wasGeneratedBy": activity_id,
    }


def _edge(kind: str, source: str, target: str) -> dict[str, Any]:
    digest = sha256_bytes(f"{kind}\n{source}\n{target}".encode("utf-8"))[:24]
    return {"@id": iri(f"edges/{digest}"), "@type": "Edge", "source": source, "target": target, "type": kind}


def _copy_contracts(stage: Path) -> None:
    # JSON contracts are rewritten canonically so their bytes are included in
    # the same deterministic hashing regime as graph nodes.
    write_canonical_json(
        stage / "context.jsonld",
        json.loads((MODULE_DIR / "resources" / "context.jsonld").read_text(encoding="utf-8")),
    )
    schema_target = stage / "schemas" / "starter_resource.schema.json"
    write_canonical_json(
        schema_target,
        read_json(MODULE_DIR / "schemas" / "starter_resource.schema.json"),
    )
    shape_target = stage / "shapes" / "starter_graph.shacl.ttl"
    shape_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(MODULE_DIR / "shapes" / "starter_graph.shacl.ttl", shape_target)


def build_package(
    out: str | Path,
    *,
    fixture: str | Path | None = None,
    limit: int = 5,
    packs: Iterable[str] = ("chile-base",),
    retrieved_at: str | None = None,
    leychile_codes: Iterable[str] | None = None,
    conditions_version: str = DEFAULT_CONDITIONS_VERSION,
    client: SparqlClient | None = None,
) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("limit debe ser >= 1")
    retrieved_at = retrieved_at or datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    specs = _pack_specs(tuple(packs))
    warnings: list[str] = []
    if fixture is not None:
        data = read_json(Path(fixture))
        records = list(data.get("records", []))[:limit]
        relations = list(data.get("relations", []))
        dataset_version = str(data.get("datasetVersion") or retrieved_at[:10])
        warnings.append(str(data.get("fixtureScope", "fixture de prueba")))
    else:
        codes = [str(code) for code in leychile_codes] if leychile_codes else _pack_codes(specs)
        records, relations, dataset_version, warnings = _live_source(codes, limit, retrieved_at, client or SparqlClient())
    if not records:
        raise ValueError("Fuente sin registros: no se construye un paquete vacío.")

    output = Path(out)
    stage = output.with_name(f".{output.name}.building")
    if stage.exists():
        shutil.rmtree(stage)
    for directory in ("normas", "articulos", "edges", "vigencia", "provenance", "exports"):
        (stage / directory).mkdir(parents=True, exist_ok=True)
    _copy_contracts(stage)

    run_seed = f"{retrieved_at}|{dataset_version}|" + ",".join(str(record["leychileCode"]) for record in records)
    run_id = sha256_bytes(run_seed.encode("utf-8"))[:20]
    source_id = iri(f"prov/bcn-dataset/{dataset_version}")
    activity_id = iri(f"prov/starter-build/{run_id}")
    write_canonical_json(stage / "provenance" / "bcn_source.json", {
        "@id": source_id, "@type": "prov:Entity", "attribution": "Ley Chile – Biblioteca del Congreso Nacional",
        "datasetVersion": dataset_version, "source": SPARQL_ENDPOINT,
    })
    write_canonical_json(stage / "provenance" / "build_activity.json", {
        "@id": activity_id, "@type": "prov:Activity", "generatedAtTime": retrieved_at, "used": source_id,
    })

    norm_by_code: dict[str, str] = {}
    edges: dict[str, dict[str, Any]] = {}
    article_count = 0
    for record in records:
        code = str(record["leychileCode"])
        norm_id = _eli_id(record)
        norm_by_code[code] = norm_id
        articles, xml_meta = _parse_articles(record, norm_id)
        start = xml_meta.get("fechaVersion") or record.get("versionDate") or record.get("publishDate")
        if not start:
            raise ValueError(f"Norma {code} sin fecha para [from,to).")
        end = record.get("nextVersionDate") if not record.get("isLatestVersion", True) else None
        provenance = _provenance(str(record["sourceUri"]), retrieved_at, dataset_version, activity_id)
        norm = {
            "@context": "../context.jsonld", "@id": norm_id, "@type": "LegalResource",
            "eli": {"jurisdiction": "cl", "number": str(record["number"]), "type": slug(str(record.get("type", "norma"))), "year": int(str(record.get("publishDate") or start)[:4])},
            "leychileCode": code, "promulgationDate": record.get("promulgationDate"), "provenance": provenance,
            "publicationDate": record.get("publishDate"), "sourceDocumentUrl": record.get("xmlDocument"),
            "sourceUri": record["sourceUri"], "temporal": {"from": start, "to": end}, "title": record["title"], "versionDate": start,
        }
        write_canonical_json(stage / "normas" / f"norma_{code}.json", norm)
        write_canonical_json(stage / "vigencia" / f"vigencia_norma_{code}.json", {
            "@id": f"{norm_id}/vigencia", "@type": "TemporalWindow",
            "derivation": "versionDate/isLatestVersion + XML fechaVersion; intervalo semiabierto",
            "from": start, "resource": norm_id, "to": end,
        })
        edge = _edge("DERIVED_FROM", norm_id, source_id); edges[edge["@id"]] = edge
        for article in articles:
            article_count += 1
            article_id = article["@id"]
            article_start = article.pop("versionDate") or start
            text_hash = sha256_bytes(article["text"].encode("utf-8"))
            article.update({
                "@context": "../context.jsonld", "provenance": provenance,
                "temporal": {"from": article_start, "to": None},
                "textSha256": text_hash,
                "citation": {
                    "status": "UNKNOWN", "completenessVerified": False,
                    "textSha256": text_hash,
                    "verificationMethod": "producer-unverified-leychile-xml",
                },
            })
            write_canonical_json(stage / "articulos" / f"articulo_{code}_{article['eId']}.json", article)
            write_canonical_json(stage / "vigencia" / f"vigencia_articulo_{code}_{article['eId']}.json", {
                "@id": f"{article_id}/vigencia", "@type": "TemporalWindow",
                "derivation": "XML EstructuraFuncional@fechaVersion; intervalo semiabierto",
                "from": article_start, "resource": article_id, "to": None,
            })
            for edge in (_edge("CONTAINS", norm_id, article_id), _edge("DERIVED_FROM", article_id, source_id)):
                edges[edge["@id"]] = edge

    omitted = 0
    for relation in relations:
        source = norm_by_code.get(str(relation.get("sourceCode")))
        target = norm_by_code.get(str(relation.get("targetCode")))
        if source and target:
            edge = _edge("MODIFIES", source, target); edges[edge["@id"]] = edge
        else:
            omitted += 1
    if omitted:
        warnings.append(f"{omitted} relaciones externas omitidas para impedir huérfanos.")
    for index, edge in enumerate(sorted(edges.values(), key=lambda item: item["@id"]), 1):
        write_canonical_json(stage / "edges" / f"edge_{index:05d}_{edge['type'].lower()}.json", edge)

    write_canonical_json(stage / "pack.json", {
        "@id": iri("packages/starter-graph/v1"), "format": "lexo-starter-graph-v1",
        "includedLeychileCodes": sorted(norm_by_code), "packs": specs, "version": "1.0.0",
    })
    report = {
        "@id": iri(f"reports/starter-build/{run_id}"), "articleCount": article_count,
        "datasetVersion": dataset_version, "edgeCount": len(edges), "normCount": len(records),
        "omittedExternalRelationCount": omitted, "retrievedAt": retrieved_at, "source": SPARQL_ENDPOINT,
        "stopReason": "build_complete_pending_validation", "warnings": warnings,
    }
    write_canonical_json(stage / "BUILD_REPORT.json", report)

    from .validate import export_turtle, validate_package
    export_turtle(stage, stage / "exports" / "graph.ttl")
    create_manifest(stage, retrieved_at=retrieved_at, dataset_version=dataset_version, conditions_version=conditions_version)
    validation = validate_package(stage, legado="rechazar")
    if not validation.ok:
        (stage / "MANIFEST.json").unlink(missing_ok=True)
        raise RuntimeError("Paquete inválido; MANIFEST retirado: " + "; ".join(validation.errors))
    report["stopReason"] = "build_hash_validate_ok"
    write_canonical_json(stage / "BUILD_REPORT.json", report)
    create_manifest(stage, retrieved_at=retrieved_at, dataset_version=dataset_version, conditions_version=conditions_version)
    final_validation = validate_package(stage, legado="rechazar")
    if not final_validation.ok:
        (stage / "MANIFEST.json").unlink(missing_ok=True)
        raise RuntimeError("Paquete inválido al cerrar: " + "; ".join(final_validation.errors))
    if output.exists():
        shutil.rmtree(output)
    stage.replace(output)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Starter Graph v1 desde BCN SPARQL sin API key")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--pack", action="append", dest="packs", default=[])
    parser.add_argument("--code", action="append", dest="codes")
    parser.add_argument("--fixture", type=Path)
    parser.add_argument("--retrieved-at")
    args = parser.parse_args(argv)
    result = build_package(
        args.output, fixture=args.fixture, limit=args.limit, packs=tuple(args.packs or ["chile-base"]),
        retrieved_at=args.retrieved_at, leychile_codes=args.codes,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
