"""Adapter from Diké private workspaces to the shared Starter Graph toolchain."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from threading import Lock

from lexo_cli.pichanga.isolation import UserWorkspace
from lexo_cli.starter.resolver import StarterCorpusResolver


_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")

# Cache por proceso de los snapshots ya verificados, con su lock. La clave es
# el contenido exacto de los STATE.json instalados: reinstalar, actualizar o
# hacer rollback cambia el sello y por tanto la clave.
_ROOTS_CACHE: dict[tuple, tuple[Path, ...]] = {}
_ROOTS_CACHE_LOCK = Lock()


def _installed_signature(starter_root: Path) -> tuple:
    """Firma barata de qué paquetes están instalados y con qué sello."""
    if not starter_root.is_dir():
        return (str(starter_root), ())
    signatures = []
    for state_path in sorted(starter_root.glob("*/STATE.json")):
        try:
            digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
        except OSError:
            digest = "missing"
        signatures.append((str(state_path), digest))
    return (str(starter_root), tuple(signatures))


def reset_corpus_roots_cache() -> None:
    """Vacía el cache. Para tests y para tras instalar un paquete nuevo."""
    with _ROOTS_CACHE_LOCK:
        _ROOTS_CACHE.clear()


DEFAULT_TOOLS_ROOT = Path(os.environ.get("DIKE_STARTER_TOOLS_ROOT", Path.home() / ".hermes/workspaces/lexo/Vault/Lexo"))


class StarterManager:
    def __init__(self, workspace: UserWorkspace, *, tools_root: str | Path = DEFAULT_TOOLS_ROOT):
        self.workspace = workspace.ensure()
        self.tools_root = Path(tools_root).expanduser().resolve()
        # La comprobación exigía que existiera `<tools_root>/tools/starter_graph`
        # —una carpeta del equipo que desarrolló Diké— aunque el código que se
        # importa más abajo es la copia vendorizada del propio paquete. En
        # cualquier instalación nueva eso abortaba con «Starter Graph toolchain
        # not found: /home/<x>/...»: un error en inglés, con una ruta cruda y
        # sin ninguna acción posible. Si la toolchain del vault no está, la
        # vendorizada basta, que es la que de hecho se usa.
        if not (self.tools_root / "tools/starter_graph").is_dir():
            vendored = Path(__file__).resolve().parent.parent / "_vendor"
            if not (vendored / "tools/starter_graph").is_dir():
                raise ValueError(
                    "La toolchain de paquetes normativos no está disponible en "
                    f"{self.tools_root} ni en la copia interna de Diké. "
                    "Reinstala el paquete con `pip install -e .`."
                )
            self.tools_root = vendored
        # Import the starter_graph package from the VENDORIZED copy in this
        # repo (lexo_cli/_vendor/tools/starter_graph), NOT from
        # <tools_root>/tools: that copy lives in the developer's home and
        # stayed on the pre-gates version (no ARTICLE_TRUNCATED, no
        # citability attestation, no vigencia coherence) — a manager that
        # imported it would validate packages green by absence of checks
        # (defect N-12, Anexo B.5). Importing as "tools.starter_graph" is
        # NOT safe either: other editable installs in this venv register a
        # "tools" package that shadows the vault's tools/ directory.
        from lexo_cli._vendor.tools.starter_graph import manifest as _manifest
        from lexo_cli._vendor.tools.starter_graph import update as _update
        from lexo_cli._vendor.tools.starter_graph import validate as _validate

        self.manifest = _manifest
        self.validate = _validate
        self.update = _update

    @staticmethod
    def _name(name: str) -> str:
        if not _NAME.fullmatch(name):
            raise ValueError("invalid starter package name")
        return name

    def package_root(self, name: str) -> Path:
        return self.workspace.resolve(f"starter/{self._name(name)}")

    def package_path(self, name: str) -> Path:
        return self.package_root(name) / "current"

    def _assert_source_valid(self, source: Path) -> None:
        manifest = self.manifest.verify_manifest(source)
        if not manifest.ok:
            raise ValueError("MANIFEST inválido: " + "; ".join(manifest.errors))
        validation = self.validate.validate_package(source)
        if not validation.ok:
            raise ValueError("Starter Graph inválido: " + "; ".join(validation.errors))
        # The shared manifest protects package bytes, but the legal evidence
        # contract also requires textSha256 to bind the actual article text.
        StarterCorpusResolver([source])

    @staticmethod
    def _metadata(path: Path) -> dict:
        manifest = json.loads((path / "MANIFEST.json").read_text(encoding="utf-8"))
        report = json.loads((path / "BUILD_REPORT.json").read_text(encoding="utf-8"))
        return {
            "dataset_version": str((manifest.get("dataSource") or {}).get("datasetVersion", "")),
            "retrieved_at": str(manifest.get("retrievedAt", "")),
            "article_count": int(report.get("articleCount", 0)),
            "norm_count": int(report.get("normCount", 0)),
        }

    def install(self, source: str | Path, name: str) -> dict:
        source_path = Path(source).expanduser().resolve()
        self._assert_source_valid(source_path)
        package_root = self.package_root(name)
        package_root.mkdir(parents=True, exist_ok=True)
        destination = self.package_path(name)
        staging = package_root / ".install-staging"
        if staging.exists():
            shutil.rmtree(staging)
        shutil.copytree(source_path, staging)
        try:
            self._assert_source_valid(staging)
            if destination.exists():
                shutil.rmtree(destination)
            staging.replace(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        digest = self.update.snapshot_hash(destination)
        snapshot = package_root / "snapshots" / digest
        self.update.create_verified_snapshot(destination, snapshot)
        self._write_state(name, digest, snapshot)
        return {
            "name": name, "path": str(destination), "snapshot_hash": digest,
            "snapshot": str(snapshot), "valid": True, "network_used": False,
            **self._metadata(destination),
        }

    def _sealed_snapshot_errors(self, name: str) -> list[str]:
        """Errores de la instantánea sellada que abre la búsqueda (vacía si está bien)."""
        state_path = self.package_root(name) / "STATE.json"
        if not state_path.is_file():
            return ["sin STATE.json: no hay instantánea sellada que la búsqueda pueda abrir"]
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            expected = str(state["snapshotHash"])
            snapshot = Path(state["snapshot"]).expanduser().resolve()
        except Exception as exc:  # noqa: BLE001 — se reporta, no se lanza
            return [f"STATE.json ilegible: {exc}"]
        if not snapshot.is_relative_to((self.package_root(name) / "snapshots").resolve()):
            return ["la instantánea sellada está fuera del workspace"]
        try:
            self._assert_source_valid(snapshot)
            actual = self.update.snapshot_hash(snapshot)
        except Exception as exc:  # noqa: BLE001
            return [f"instantánea sellada inválida ({snapshot.name[:12]}…): {exc}"]
        if actual != expected:
            return [f"instantánea sellada con hash distinto al de STATE.json ({snapshot.name[:12]}…)"]
        return []

    def _current_drift_errors(self, name: str, current_digest: str | None) -> list[str]:
        """`current/` distinto de lo sellado en STATE.json (vacía si coinciden).

        Auditoría 2026-10-13: `lawyer-pilot` tenía `current/` con la corrección
        D2 (1.473 archivos distintos) y STATE.json apuntando a la instantánea
        anterior; `verify` decía «verificado» porque solo comparaba la sellada
        consigo misma. Lo que abre la búsqueda es lo sellado, así que un
        `current/` divergente es un pack a medio migrar, no un pack verificado.
        """
        if current_digest is None:
            return []
        state_path = self.package_root(name) / "STATE.json"
        try:
            expected = str(json.loads(state_path.read_text(encoding="utf-8"))["snapshotHash"])
        except Exception:  # noqa: BLE001 — ya lo reporta _sealed_snapshot_errors
            return []
        if current_digest != expected:
            return [f"current/ ({current_digest[:12]}…) difiere de la instantánea sellada en STATE.json ({expected[:12]}…): "
                    "la búsqueda abre la sellada; re-sella con `dike starter rollback <ruta-snapshot>` o reinstala"]
        return []

    def _write_state(self, name: str, digest: str, snapshot: Path) -> None:
        state = {"format": "dike-installed-starter-v1", "name": name, "snapshotHash": digest, "snapshot": str(snapshot)}
        (self.package_root(name) / "STATE.json").write_text(json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def verify(self, name: str) -> dict:
        path = self.package_path(name)
        manifest = self.manifest.verify_manifest(path)
        validation = self.validate.validate_package(path)
        digest = self.update.snapshot_hash(path) if path.is_dir() else None
        errors = list(manifest.errors) + list(validation.errors)
        # P9: la búsqueda no abre `current/` sino la instantánea sellada de
        # STATE.json. Verificar solo `current/` decía «verificado» con esa
        # instantánea vacía y `dike buscar` fallando para el mismo usuario.
        errors += self._sealed_snapshot_errors(name)
        errors += self._current_drift_errors(name, digest)
        metadata = self._metadata(path) if path.is_dir() and not errors else {}
        return {
            "name": name, "path": str(path), "valid": not errors,
            "snapshot_hash": digest, "errors": errors,
            "warnings": list(validation.warnings), **metadata,
        }

    def apply_update(self, name: str, patch_path: str | Path) -> dict:
        current = self.package_path(name)
        self._assert_source_valid(current)
        before = self.update.snapshot_hash(current)
        rollback_snapshot = self.package_root(name) / "snapshots" / f"pre-update-{before}"
        self.update.create_verified_snapshot(current, rollback_snapshot)
        try:
            digest = self.update.apply_update(current, patch_path)
            self._assert_source_valid(current)
        except Exception:
            self.update.rollback_to_snapshot(current, rollback_snapshot)
            raise
        snapshot = self.package_root(name) / "snapshots" / digest
        self.update.create_verified_snapshot(current, snapshot)
        self._write_state(name, digest, snapshot)
        return {"name": name, "snapshot_hash": digest, "rollback_snapshot": str(rollback_snapshot), "valid": True}

    def rollback(self, name: str, snapshot_path: str | Path) -> dict:
        snapshot = Path(snapshot_path).expanduser().resolve()
        allowed = (self.package_root(name) / "snapshots").resolve()
        if not snapshot.is_relative_to(allowed):
            raise ValueError("rollback snapshot is outside this user's package")
        digest = self.update.rollback_to_snapshot(self.package_path(name), snapshot)
        self._assert_source_valid(self.package_path(name))
        self._write_state(name, digest, snapshot)
        return {"name": name, "snapshot_hash": digest, "valid": True}

    def list_packages(self) -> list[dict]:
        starter_root = self.workspace.resolve("starter")
        result: list[dict] = []
        for child in sorted(starter_root.iterdir() if starter_root.exists() else []):
            if child.is_dir() and (child / "current").is_dir():
                result.append({"name": child.name, **{k: v for k, v in self.verify(child.name).items() if k != "name"}})
        return result

    def installed_corpus_roots(self) -> list[Path]:
        """Return only immutable snapshots sealed by each package STATE.json.

        Verificar un paquete cuesta ~11 s: recorre y hashea los 8.533 artículos
        del snapshot. La web construía un `NIFRuntime` (y por tanto llamaba
        aquí) en CADA petición, así que cada clic del abogado pagaba esa
        verificación completa, dos veces cuando la acción además releía el
        caso. El resultado se cachea por proceso, con la misma garantía que
        `nif_studio.execution.canonical_resolver_for`: la validación completa
        corre una vez por firma de STATE.json; si el sello cambia, la clave
        cambia y se vuelve a verificar.
        """
        starter_root = self.workspace.resolve("starter")
        key = _installed_signature(starter_root)
        with _ROOTS_CACHE_LOCK:
            cached = _ROOTS_CACHE.get(key)
        if cached is not None:
            return list(cached)
        # 2.0: caché a disco — la verificación completa (~28 s) solo corre una
        # vez por firma de STATE.json, no una vez por proceso.
        disk = self._roots_desde_disco(key)
        if disk is not None:
            with _ROOTS_CACHE_LOCK:
                _ROOTS_CACHE[key] = tuple(disk)
            return list(disk)
        roots = self._verify_installed_corpus_roots(starter_root)
        self._roots_a_disco(key, roots)
        with _ROOTS_CACHE_LOCK:
            _ROOTS_CACHE[key] = tuple(roots)
        return roots

    # -- caché a disco de roots verificados (2.0) ---------------------------

    def _roots_cache_file(self, key: tuple) -> Path:
        digest = hashlib.sha256(repr(key).encode("utf-8")).hexdigest()[:16]
        # P10: `DIKE_ROOTS_CACHE_DIR` redirige el caché (la suite lo manda a
        # un temporal; antes escribía en el del operador con claves /tmp/pytest).
        base = os.environ.get("DIKE_ROOTS_CACHE_DIR") or str(Path.home() / ".dike" / "roots_cache")
        return Path(base) / f"{digest}.json"

    def _roots_desde_disco(self, key: tuple) -> list[Path] | None:
        """Leer roots desde caché a disco, verificando que siguen siendo válidas.

        A07/CORE-02: el caché a disco NO es una fuente de autoridad. Las roots
        deben verificar que siguen siendo snapshots aprobados antes de ser
        aceptadas. Si alguna root no pasa la verificación, se descarta todo
        el caché y se fuerza verificación completa.
        """
        path = self._roots_cache_file(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("key") != repr(key):
                return None
            roots = [Path(r) for r in data.get("roots", [])]
        except Exception:
            return None
        # Verificar que cada root sigue siendo un snapshot válido
        if not self._verify_roots_from_cache(roots):
            return None
        return roots

    def _verify_roots_from_cache(self, roots: list[Path]) -> bool:
        """Verificar que las roots del cache siguen siendo snapshots válidos.

        Cada root debe:
        1. Existir como directorio
        2. Tener un STATE.json válido en el paquete correspondiente
        3. El snapshot hash debe coincidir con el STATE.json
        4. El snapshot debe estar dentro del workspace del usuario
        """
        if not roots:
            return True
        starter_root = self.workspace.resolve("starter")
        for root in roots:
            # 1. Existir como directorio
            if not root.is_dir():
                return False
            # 2. Encontrar el paquete correspondiente (el root debe estar dentro de snapshots/)
            try:
                rel = root.relative_to(starter_root)
            except ValueError:
                return False
            # El path debe ser: <package>/snapshots/<hash>
            if len(rel.parts) < 3 or rel.parts[1] != "snapshots":
                return False
            package_name = rel.parts[0]
            package_root = starter_root / package_name
            state_path = package_root / "STATE.json"
            if not state_path.is_file():
                return False
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                expected_hash = str(state["snapshotHash"])
                snapshot_path = Path(state["snapshot"]).expanduser().resolve()
            except Exception:
                return False
            # 3. El snapshot hash debe coincidir
            if snapshot_path != root:
                return False
            # 4. El snapshot debe estar dentro del workspace
            allowed = (package_root / "snapshots").resolve()
            if not root.resolve().is_relative_to(allowed):
                return False
            # 5. El snapshot debe ser válido (mismo check que _verify_installed_corpus_roots)
            try:
                self._assert_source_valid(root)
                actual_hash = self.update.snapshot_hash(root)
                if actual_hash != expected_hash:
                    return False
            except Exception:
                return False
        return True

    def _roots_a_disco(self, key: tuple, roots: list[Path]) -> None:
        try:
            path = self._roots_cache_file(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"key": repr(key), "roots": [str(r) for r in roots]}),
                encoding="utf-8",
            )
        except Exception:
            # Persistir es optimización, no contrato.
            pass

    def _verify_installed_corpus_roots(self, starter_root: Path) -> list[Path]:
        roots: list[Path] = []
        for package_root in sorted(starter_root.iterdir() if starter_root.exists() else []):
            if not package_root.is_dir() or not (package_root / "STATE.json").is_file():
                continue
            state_path = package_root / "STATE.json"
            try:
                state = json.loads(state_path.read_text(encoding="utf-8"))
                expected = str(state["snapshotHash"])
                snapshot = Path(state["snapshot"]).expanduser().resolve()
            except Exception as exc:
                raise ValueError(f"Estado de starter inválido: {state_path}: {exc}") from exc
            allowed = (package_root / "snapshots").resolve()
            if not snapshot.is_relative_to(allowed):
                raise ValueError("El snapshot sellado está fuera del workspace")
            self._assert_source_valid(snapshot)
            actual = self.update.snapshot_hash(snapshot)
            if actual != expected:
                raise ValueError(f"Snapshot hash no coincide para {package_root.name}")
            roots.append(snapshot)
        return roots
