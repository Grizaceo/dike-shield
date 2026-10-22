"""Fail-closed resolution of explicit Diké GIDs against Starter Graph snapshots."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from threading import Lock
from typing import Iterable

from lexo_cli.gid import a_gid_runtime, motivo_no_identidad
from lexo_cli._vendor.tools.starter_graph.iris import a_base_actual, a_base_legada
from lexo_cli.starter.text_defects import (
    TEXT_DEFECT_STATUS,
    TextDefectCatalogError,
    load_catalog as load_text_defects,
    text_defect,
)


_ALIAS_CATALOG = Path(__file__).with_name("normative_aliases.v1.json")
_DEFECT_CATALOG = Path(__file__).with_name("text_defects.v1.json")

# Un artículo autoderogado: su cuerpo normativo *es* la derogación. No basta con
# que el texto contenga "derogado": en el Código del Trabajo, 6 de los 20
# artículos que mencionan la palabra siguen vigentes y solo derogan un inciso
# (p. ej. el art. 44, "INCISO DEROGADO."). El gate debe distinguirlos.
_SELF_DEROGATION = re.compile(
    r"^\W*(?:(?:art(?:í|i)culo|art\.)\s*[^\n]{0,48}?[.\-–—]+\s*)?derogad[oa]s?\b\W*$",
    re.IGNORECASE,
)
# Un texto jurídico completo termina en puntuación terminal. El art. 162 CT del
# vault corta en "…del": el hash es correcto y el artículo es incitable.
_TERMINAL_PUNCTUATION = ('.', ':', ';', '!', '?', '"', '”', '»', ')', ']')
# Orígenes temporales que el parser inventó cuando la fuente no traía fecha.
# No son vigencias verificables: los 584 artículos del Código del Trabajo usan
# 1900-01-01 como relleno.
_PLACEHOLDER_ORIGINS = frozenset({"1900-01-01", "0001-01-01"})
# Algunas ventanas proceden de una versión consolidada: su `from` es la fecha
# del snapshot extraído, NO una prueba de entrada en vigencia. Para un `as_of`
# anterior el sistema debe abstenerse por falta de texto histórico, no afirmar
# falsamente que la norma todavía no existía.
_SNAPSHOT_DERIVATION = re.compile(r"\bversi[oó]n\s+consolidada\b", re.IGNORECASE)
# Esta derivación acredita una entrada en vigencia expresa. Si contradice una
# ventana de snapshot, debe prevalecer: es evidencia temporal más específica.
_ENTRY_INTO_FORCE_DERIVATION = re.compile(
    r"\b(?:primera\s+)?entrada\s+en\s+vigencia\b", re.IGNORECASE,
)


class NormativeResolutionError(ValueError):
    def __init__(self, code: str, identifier: str, detail: str):
        self.code = code
        self.identifier = identifier
        super().__init__(f"{code}: {identifier}: {detail}")


@dataclass(frozen=True)
class ResolvedNormEvidence:
    gid: str
    eli: str
    norm_eli: str
    leychile_code: str
    eid: str
    text_sha256: str
    text: str
    temporal_from: str
    temporal_to: str | None
    temporal_derivation: str
    temporal_status: str
    in_force: bool
    citation_status: str
    source_path: str
    dataset_version: str
    provenance: dict
    source_url: str = ""
    retrieved_at: str = ""
    historical_text_status: str = "CURRENT_VERSION_APPLIES"
    # P10 (HITL «i»): motivo por el que un texto atestado no es citable.
    citation_defect: str | None = None
    # P10 (HITL «h»): notas de BCN del artículo; no son texto de la norma.
    bcn_notes: tuple[str, ...] = ()
    # P12 (decisión 2): por qué está OUT_OF_FORCE. `SUPERSEDED_VERSION` = venció
    # la versión del texto que tenemos (el artículo puede seguir rigiendo con
    # otro texto); `DEROGATION` = el artículo dejó de regir. None si no aplica.
    out_of_force_reason: str | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        # P12: los gates HITL-4 sellan `canonical_payload_hash` de este dict.
        # Sin motivo (lo normal: fuentes en vigor) la clave no aparece y el
        # hash de un gate pendiente creado antes de P12 no cambia.
        if data.get("out_of_force_reason") is None:
            data.pop("out_of_force_reason", None)
        return data


class StarterCorpusResolver:
    """Build an exact bidirectional GID/ELI index from a versioned alias catalog."""

    def __init__(
        self,
        roots: Iterable[str | Path] = (),
        *,
        aliases_path: str | Path = _ALIAS_CATALOG,
        as_of: date | None = None,
        defects_path: str | Path = _DEFECT_CATALOG,
    ):
        self.roots = tuple(Path(root).expanduser().resolve() for root in roots)
        self.as_of = as_of or date.today()
        try:
            self._text_defects = load_text_defects(defects_path)
        except TextDefectCatalogError as exc:
            raise NormativeResolutionError("TEXT_DEFECTS_CATALOG_INVALID", str(defects_path), str(exc)) from exc
        catalog = self._read(Path(aliases_path))
        if catalog.get("format") != "lexo-normative-aliases-v1":
            raise NormativeResolutionError("ALIAS_CATALOG_INVALID", str(aliases_path), "formato inválido")
        aliases = catalog.get("leychileCodeToAlias")
        if not isinstance(aliases, dict) or not aliases:
            raise NormativeResolutionError("ALIAS_CATALOG_INVALID", str(aliases_path), "catálogo vacío")
        self.aliases_version = str(catalog.get("aliasesVersion", ""))
        self._aliases = {str(code): str(alias) for code, alias in aliases.items()}
        if len(set(self._aliases.values())) != len(self._aliases):
            raise NormativeResolutionError("AMBIGUOUS_ALIAS", str(aliases_path), "alias duplicado")
        self._binding_cache: dict | None = None
        self._by_gid: dict[str, ResolvedNormEvidence] = {}
        self._by_eli: dict[str, ResolvedNormEvidence] = {}
        self._load()

    @staticmethod
    def _tree_sha256(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(8, "big"))
            digest.update(relative)
            content = path.read_bytes()
            digest.update(len(content).to_bytes(8, "big"))
            digest.update(content)
        return digest.hexdigest()

    def binding(self) -> dict:
        """Describe the exact immutable corpus bytes used by this resolver.

        Hashea el árbol completo del snapshot (8.533 artículos, ~1,5 s). Los
        snapshots son inmutables por construcción —viven bajo
        `snapshots/<digest>/` y su ruta ES su hash—, así que recalcularlo en
        cada llamada no aporta ninguna garantía adicional dentro de la vida de
        un resolver, y sí hacía que cada clic de la web esperara segundos.
        """
        if self._binding_cache is not None:
            return self._binding_cache
        # 2.0: caché a disco — el snapshot es inmutable (su ruta ES su hash),
        # así que el binding calculado sobre él también lo es. Recalcular el
        # tree_sha256 en cada proceso costaba ~4,4 s de los 6,3 s actuales.
        disk = self._binding_desde_disco()
        if disk is not None:
            self._binding_cache = disk
            return disk
        corpora = []
        for root in self.roots:
            manifest = root / "MANIFEST.json"
            manifest_bytes = manifest.read_bytes() if manifest.is_file() else b""
            corpora.append({
                "root": str(root),
                "snapshot_hash": self._tree_sha256(root),
                "manifest_present": manifest.is_file(),
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(),
            })
        self._binding_cache = {
            "format": "dike-normative-binding-v1",
            "aliases_version": self.aliases_version,
            "corpora": corpora,
        }
        self._binding_a_disco(self._binding_cache)
        return self._binding_cache

    # -- caché a disco del binding (2.0) ------------------------------------

    def _binding_cache_file(self) -> Path | None:
        if not self.roots:
            return None
        # La ruta del snapshot ES su hash: clave estable e inmutable.
        digest = self.roots[0].name[:16]
        # `DIKE_BINDING_CACHE_DIR` redirige el caché (la suite lo manda a un
        # temporal; auditoría 2026-10-13: escribía 5 entradas por corrida en el
        # del operador, igual que P10 con el caché de raíces).
        base = os.environ.get("DIKE_BINDING_CACHE_DIR") or str(Path.home() / ".dike" / "binding_cache")
        return Path(base) / f"{digest}.json"

    def _binding_desde_disco(self) -> dict | None:
        path = self._binding_cache_file()
        if path is None or not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("root") != str(self.roots[0]):
                return None
            return data.get("binding")
        except Exception:
            return None

    def _binding_a_disco(self, binding: dict) -> None:
        path = self._binding_cache_file()
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"root": str(self.roots[0]), "binding": binding}),
                encoding="utf-8",
            )
        except Exception:
            # Persistir es optimización, no contrato.
            pass

    @staticmethod
    def _read(path: Path) -> dict:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise NormativeResolutionError("PACKAGE_INVALID", str(path), str(exc)) from exc
        if not isinstance(value, dict):
            raise NormativeResolutionError("PACKAGE_INVALID", str(path), "nodo no es objeto")
        return value

    @staticmethod
    def _article_token(eid: str) -> str:
        token = eid.removeprefix("art_").lower()
        if token.isdigit():
            return f"{int(token):04d}"
        return token.replace("-", "_")

    @staticmethod
    def _temporal_index(root: Path) -> dict[str, list[dict]]:
        """Ventanas de `vigencia/` agrupadas por recurso, leídas una sola vez.

        Antes cada artículo releía el directorio entero para encontrar la suya:
        con 4.020 artículos y 4.024 ventanas eso son ~16 millones de lecturas y
        el corpus tardaba 6 minutos en cargar. El coste es lineal, no cuadrático.
        """
        index: dict[str, list[dict]] = {}
        temporal_dir = root / "vigencia"
        if not temporal_dir.is_dir():
            return index
        for path in sorted(temporal_dir.glob("*.json")):
            window = StarterCorpusResolver._read(path)
            resource = window.get("resource")
            if isinstance(resource, str):
                index.setdefault(resource, []).append(window)
        return index

    @staticmethod
    def _window_values(candidates: list[dict], identifier: str) -> tuple[str, str | None, str]:
        """Valida una ventana única y conserva su mejor explicación de origen."""
        if not candidates:
            raise NormativeResolutionError("TEMPORAL_UNKNOWN", identifier, "sin ventana temporal")
        unique = {(item.get("from"), item.get("to")) for item in candidates}
        if len(unique) != 1:
            raise NormativeResolutionError("TEMPORAL_UNKNOWN", identifier, "ventanas contradictorias")
        start, end = next(iter(unique))
        try:
            date.fromisoformat(str(start))
            if end is not None:
                date.fromisoformat(str(end))
        except ValueError as exc:
            raise NormativeResolutionError("TEMPORAL_UNKNOWN", identifier, "fecha inválida") from exc
        derivations = [
            str(item.get("derivation", "")).strip()
            for item in candidates
            if str(item.get("derivation", "")).strip()
        ]
        # La entrada en vigencia acreditada gana a la descripción de snapshot;
        # si no hay ninguna de ellas, se conserva la primera explicación.
        derivation = next(
            (value for value in derivations if _ENTRY_INTO_FORCE_DERIVATION.search(value)),
            next(
                (value for value in derivations if _SNAPSHOT_DERIVATION.search(value)),
                derivations[0] if derivations else "",
            ),
        )
        return str(start), None if end is None else str(end), derivation

    @classmethod
    def _temporal(
        cls, windows: dict[str, list[dict]], eli: str, article: dict, parent: dict,
    ) -> tuple[str, str | None, str, bool]:
        """Obtiene la mejor evidencia temporal de artículo y norma madre.

        Una ventana de artículo extraída desde un snapshot no demuestra por sí
        sola la entrada en vigencia. Si la norma madre aporta una entrada en
        vigencia explícita posterior, esa evidencia más fuerte prevalece.
        """
        inline = article.get("temporal")
        article_candidates: list[dict] = []
        if isinstance(inline, dict):
            article_candidates.append(inline)
        article_candidates.extend(windows.get(eli, ()))
        start, end, derivation = cls._window_values(article_candidates, eli)

        parent_eli = str(parent.get("@id", ""))
        parent_candidates = [
            window for window in windows.get(parent_eli, ())
            if _ENTRY_INTO_FORCE_DERIVATION.search(str(window.get("derivation", "")))
        ]
        if not parent_candidates or not _SNAPSHOT_DERIVATION.search(derivation):
            return start, end, derivation, False
        try:
            parent_start, parent_end, parent_derivation = cls._window_values(
                parent_candidates, parent_eli,
            )
        except NormativeResolutionError as exc:
            if exc.code != "TEMPORAL_UNKNOWN":
                raise
            # La contradicción pertenece a la evidencia de esta norma madre;
            # no debe tumbar artículos ni packs ajenos. Conservamos la ventana
            # de artículo solo como referencia y la clasificamos aparte.
            return start, end, derivation, True
        if date.fromisoformat(parent_start) > date.fromisoformat(start):
            return parent_start, parent_end, parent_derivation, False
        return start, end, derivation, False

    @staticmethod
    def _manifest_retrieved_on(manifest: dict) -> date | None:
        """Fecha de captura sellada del pack, si el productor la declaró.

        Sin `retrievedAt` no se puede probar que una fecha sea solo un piso de
        snapshot. El estado dudoso queda como `FUTURE` (bloquea), pero el pack
        no se invalida si sus ventanas no requieren esa excepción histórica.
        """
        raw = str(manifest.get("retrievedAt", "")).strip()
        if not raw:
            return None
        try:
            captured_on = datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
        except ValueError:
            return None
        # Una adquisición no puede acreditar hechos antes de que ocurra. Ante un
        # reloj/manifiesto adelantado, se ignora el dato en vez de degradar una
        # vigencia diferida real a incertidumbre histórica.
        return captured_on if captured_on <= date.today() else None

    @staticmethod
    def is_self_derogated(text: str) -> bool:
        """El cuerpo normativo del artículo es, íntegramente, su derogación."""
        return bool(_SELF_DEROGATION.fullmatch(text.strip()))

    @staticmethod
    def is_truncated(text: str) -> bool:
        """El texto corta antes de cerrar la frase: completitud no acreditable."""
        return not text.strip().endswith(_TERMINAL_PUNCTUATION)

    @staticmethod
    def _completeness(eli: str, text: str) -> None:
        """Separa integridad criptográfica de suficiencia jurídica.

        Un `textSha256` correcto certifica fielmente un texto truncado. La
        completitud es una propiedad del contenido, no de los bytes.
        """
        if StarterCorpusResolver.is_truncated(text):
            raise NormativeResolutionError(
                "ARTICLE_TRUNCATED", eli,
                "el texto no cierra la frase: posible truncamiento de la fuente",
            )

    @staticmethod
    def _temporal_integrity(eli: str, text: str, start: str, end: str | None) -> None:
        """Modela `[from,to)` con estado explícito; rechaza el relleno temporal."""
        if start in _PLACEHOLDER_ORIGINS:
            raise NormativeResolutionError(
                "TEMPORAL_PLACEHOLDER", eli,
                f"origen de vigencia {start} es un relleno del parser, no una fecha jurídica",
            )
        if StarterCorpusResolver.is_self_derogated(text) and end is None:
            raise NormativeResolutionError(
                "DEROGATION_UNRESOLVED", eli,
                "artículo derogado con ventana [from,to) abierta: la derogación "
                "debe cerrar la ventana, no quedar implícita",
            )

    @staticmethod
    def _citation_status(eli: str, article: dict, text_sha256: str) -> str:
        """Require an explicit completeness attestation bound to exact text bytes.

        A valid hash proves integrity, not that the source extraction is complete.
        The producer must therefore attest citability and bind that decision to the
        same text hash. Missing, stale, or ambiguous attestations fail closed.
        """
        citation = article.get("citation")
        if not isinstance(citation, dict):
            raise NormativeResolutionError(
                "ARTICLE_NOT_CITABLE", eli, "sin atestación explícita de completitud",
            )
        if citation.get("status") != "CITABLE":
            raise NormativeResolutionError(
                "ARTICLE_NOT_CITABLE", eli, f"estado {citation.get('status', 'UNKNOWN')}",
            )
        if citation.get("completenessVerified") is not True:
            raise NormativeResolutionError(
                "ARTICLE_NOT_CITABLE", eli, "completitud no verificada",
            )
        if citation.get("textSha256") != text_sha256:
            raise NormativeResolutionError(
                "ARTICLE_NOT_CITABLE", eli, "atestación no corresponde al texto actual",
            )
        if not str(citation.get("verificationMethod", "")).strip():
            raise NormativeResolutionError(
                "ARTICLE_NOT_CITABLE", eli, "método de verificación ausente",
            )
        return "CITABLE"

    def _temporal_status(
        self,
        start: str,
        end: str | None,
        derivation: str,
        retrieved_on: date | None,
        parent_temporal_conflict: bool = False,
    ) -> str:
        if parent_temporal_conflict:
            return "TEMPORAL_UNKNOWN"
        start_date = date.fromisoformat(start)
        if self.as_of < start_date:
            # Una versión consolidada solo acredita un piso de disponibilidad si
            # su fecha ya existía al capturar el pack. Si viene después, es una
            # entrada en vigor diferida que debe permanecer como FUTURE.
            if (
                _SNAPSHOT_DERIVATION.search(derivation)
                and retrieved_on is not None
                and start_date <= retrieved_on
            ):
                return "UNKNOWN_BEFORE_SNAPSHOT"
            return "FUTURE"
        if end is not None and self.as_of >= date.fromisoformat(end):
            return "OUT_OF_FORCE"
        return "IN_FORCE"

    @classmethod
    def _out_of_force_reason(cls, temporal_status: str, derivation: str, text: str) -> str | None:
        """Distingue derogación de versión vencida sin ampliar el vocabulario.

        Medido en P12 sobre el pack 85334a05: las 186 ventanas del DL 3.500
        cerradas el 2026-08-31 son de la «versión consolidada de la que se
        extrajo el texto» (entró otra versión el 1-sep); las 339 derogaciones
        traen la derivación de la nota marginal/D.O. Rotular «derogado» a las
        primeras hace citar mal.
        """
        if temporal_status != "OUT_OF_FORCE":
            return None
        if _SNAPSHOT_DERIVATION.search(derivation) and not cls.is_self_derogated(text):
            return "SUPERSEDED_VERSION"
        return "DEROGATION"

    def _load(self) -> None:
        for root in self.roots:
            if not root.is_dir():
                raise NormativeResolutionError("PACKAGE_INVALID", str(root), "ruta inexistente")
            windows = self._temporal_index(root)
            manifest_path = root / "MANIFEST.json"
            manifest = self._read(manifest_path) if manifest_path.is_file() else {}
            retrieved_on = self._manifest_retrieved_on(manifest)
            resources: dict[str, dict] = {}
            for path in sorted((root / "normas").glob("*.json")):
                resource = self._read(path)
                if resource.get("@type") == "LegalResource" and resource.get("@id"):
                    resources[str(resource["@id"])] = resource
            for path in sorted((root / "articulos").glob("*.json")):
                article = self._read(path)
                if article.get("@type") != "Article":
                    continue
                eli = str(article.get("@id", ""))
                parent = resources.get(str(article.get("isPartOf", "")))
                if parent is None:
                    raise NormativeResolutionError("ARTICLE_INCOMPLETE", eli or str(path), "LegalResource no resoluble")
                code = str(parent.get("leychileCode", ""))
                alias = self._aliases.get(code)
                if alias is None:
                    raise NormativeResolutionError("UNRESOLVABLE_GID", code, "cuerpo sin alias explícito")
                text = article.get("text")
                declared = article.get("textSha256")
                if not isinstance(text, str) or not text.strip():
                    raise NormativeResolutionError("ARTICLE_INCOMPLETE", eli, "texto ausente")
                if not isinstance(declared, str) or not re.fullmatch(r"[0-9a-f]{64}", declared):
                    raise NormativeResolutionError("TEXT_HASH_MISSING", eli, "textSha256 inválido")
                actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
                if declared != actual:
                    raise NormativeResolutionError("TEXT_HASH_MISMATCH", eli, "sha256(text) no coincide")
                self._completeness(eli, text)
                citation_status = self._citation_status(eli, article, actual)
                # P10 (HITL «i»): la atestación selló un texto con defecto de
                # extracción conocido. No es fatal: se resuelve, no como CITABLE.
                citation_defect = text_defect(text, actual, self._text_defects)
                if citation_defect is not None:
                    citation_status = TEXT_DEFECT_STATUS
                eid = str(article.get("eId", ""))
                token = self._article_token(eid)
                if not token:
                    raise NormativeResolutionError("ARTICLE_INCOMPLETE", eli, "eId ausente")
                start, end, temporal_derivation, parent_temporal_conflict = self._temporal(
                    windows, eli, article, parent,
                )
                self._temporal_integrity(eli, text, start, end)
                temporal_status = self._temporal_status(
                    start, end, temporal_derivation, retrieved_on, parent_temporal_conflict,
                )
                in_force = temporal_status == "IN_FORCE"
                article_provenance = dict(article.get("provenance") or {})
                parent_provenance = dict(parent.get("provenance") or {})
                source_url = str(
                    article.get("sourceDocumentUrl")
                    or parent.get("sourceDocumentUrl")
                    or article_provenance.get("wasDerivedFrom")
                    or parent_provenance.get("wasDerivedFrom")
                    or ""
                )
                retrieved_at = str(
                    article_provenance.get("retrievedAt")
                    or parent_provenance.get("retrievedAt")
                    or manifest.get("retrievedAt")
                    or ""
                )
                historical_text_status = (
                    "HISTORICAL_TEXT_UNAVAILABLE"
                    if temporal_status == "UNKNOWN_BEFORE_SNAPSHOT"
                    else "CURRENT_VERSION_APPLIES"
                )
                gid = f"cl.norma.{alias}:art:{token}"
                evidence = ResolvedNormEvidence(
                    gid=gid,
                    eli=eli,
                    norm_eli=str(parent["@id"]),
                    leychile_code=code,
                    eid=eid,
                    text_sha256=actual,
                    text=text,
                    temporal_from=start,
                    temporal_to=end,
                    temporal_derivation=temporal_derivation,
                    temporal_status=temporal_status,
                    in_force=in_force,
                    citation_status=citation_status,
                    source_path=str(path),
                    dataset_version=str((article.get("provenance") or {}).get("datasetVersion", "")),
                    provenance=article_provenance,
                    source_url=source_url,
                    retrieved_at=retrieved_at,
                    historical_text_status=historical_text_status,
                    citation_defect=citation_defect,
                    out_of_force_reason=self._out_of_force_reason(temporal_status, temporal_derivation, text),
                    bcn_notes=tuple(
                        str(note) for note in (article.get("bcnNotes") or []) if isinstance(note, str) and note.strip()
                    ),
                )
                if gid in self._by_gid or eli in self._by_eli:
                    raise NormativeResolutionError("AMBIGUOUS_ALIAS", gid, "colisión GID/ELI")
                self._by_gid[gid] = evidence
                self._by_eli[eli] = evidence
        if self.roots and not self._by_gid:
            # Un root que existe pero no contiene articulos/*.json cargaba CERO
            # articulos en silencio, y entonces todo GID fallaba como
            # UNRESOLVABLE_GID — indistinguible de "esa norma no esta en el pack".
            # Un corpus vacio es un error de instalacion, no una respuesta.
            raise NormativeResolutionError(
                "PACKAGE_INVALID",
                ", ".join(str(root) for root in self.roots),
                "el corpus no contiene artículos indexables",
            )

    def resolve(self, gid: str) -> ResolvedNormEvidence:
        # Lectura dual (ARCH-003 F1): la v2 se reduce a la clave runtime; se sigue
        # devolviendo la evidencia con su GID runtime.
        clave = a_gid_runtime(gid)
        if clave is None:
            motivo = motivo_no_identidad(gid)
            raise NormativeResolutionError("UNRESOLVABLE_GID", gid,
                                           f"no es identidad ({motivo})" if motivo else "formato inválido")
        try:
            return self._by_gid[clave]
        except KeyError as exc:
            raise NormativeResolutionError("UNRESOLVABLE_GID", gid, "sin mapping explícito") from exc

    def resolve_eli(self, eli: str) -> ResolvedNormEvidence:
        # ARCH-004: el mismo IRI bajo https://dike.invalid/ o bajo la base legada
        # https://lexo.cl/ (packs sellados antes del 2026-10-14) es el mismo nodo.
        for candidato in (eli, a_base_actual(eli), a_base_legada(eli)):
            if candidato in self._by_eli:
                return self._by_eli[candidato]
        raise NormativeResolutionError("UNRESOLVABLE_ELI", eli, "no existe en snapshot")

    def resolve_many(self, gids: Iterable[str]) -> list[ResolvedNormEvidence]:
        return [self.resolve(gid) for gid in gids]


# ── Instancias compartidas por proceso ───────────────────────────────────────
# Los snapshots son inmutables (su ruta contiene su propio hash), así que un
# resolver ya construido sobre los mismos roots sirve para todo el proceso.
# Sin esto cada petición de la web reconstruía el índice completo del corpus:
# la búsqueda de normas costaba entre 3 y 26 segundos por consulta.
_RESOLVER_CACHE: dict[tuple, "StarterCorpusResolver"] = {}
_RESOLVER_LOCK = Lock()


def shared_resolver(roots, *, as_of: date | None = None) -> "StarterCorpusResolver":
    """Resolver compartido, cacheado por corpus **y fecha de evaluación**."""
    cutoff = as_of or date.today()
    key = (
        tuple(str(Path(root).expanduser().resolve()) for root in roots),
        cutoff.isoformat(),
    )
    with _RESOLVER_LOCK:
        cached = _RESOLVER_CACHE.get(key)
        if cached is None:
            cached = StarterCorpusResolver(roots, as_of=cutoff)
            _RESOLVER_CACHE[key] = cached
    return cached


def reset_shared_resolvers() -> None:
    """Olvida los resolvers cacheados. Para tests que instalan otro corpus."""
    with _RESOLVER_LOCK:
        _RESOLVER_CACHE.clear()
