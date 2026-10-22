"""
nif_board.py — NIF Shared State Board

Pizarra compartida donde el NIF vive como single source of truth.
Los subagentes (y el usuario) leen, parchean y observan el NIF.

Arquitectura:
- nif.json          → NIF canónico actual
- nif_history/      → snapshots versionados (uno por patch aplicado)
- nif_patches.jsonl → log append-only de todos los patches

El board es file-based (no necesita servidor). Usa file locking
básico para evitar conflictos de escritura simultánea.

Patrón: cada subagente hace board.read() → trabaja → board.write(patch)
El siguiente subagente ve el NIF actualizado + puede hacer board.diff()
para ver qué cambió desde su última lectura.

Integración con:
- NormativeInteractionFrame (nif.py) → modelo del NIF
- NIFPatch (nif_patch.py) → parches atómicos
- LexOCoordinator → inyecta el board en cada subagente
- CLI commands → el usuario lee y edita el NIF
"""

from __future__ import annotations

import json
import os
import re
import sys
import sqlite3
import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Path setup
BOARD_ROOT = Path(__file__).resolve().parent.parent
if str(BOARD_ROOT) not in sys.path:
    sys.path.insert(0, str(BOARD_ROOT))

from pydantic import ValidationError

from shared.schemas.nif import NormativeInteractionFrame
from shared.schemas.nif_patch import (
    NIFPatch,
    NIFPatchResult,
    NIFDiff,
    PatchOperation,
)


class NIFBoardIntegrityError(RuntimeError):
    """El estado materializado no puede justificarse por el journal de patches."""


class NIFAlreadyExists(ValueError):
    """Ya hay un NIF inicializado para este caso.

    Se decide dentro de la transacción de inserción: comprobarlo antes, desde
    el llamador, deja una ventana en la que dos procesos inicializan el mismo
    expediente y lo dejan ilegible de forma permanente.
    """


# ---------------------------------------------------------------------------
#  Helpers
# ---------------------------------------------------------------------------

# Identificadores de expediente: nombre, no repr arbitrario. Se admiten las
# ramas de `nif fork`, que usan el separador '--branch--'.
_CASE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}(--branch--[A-Za-z0-9._-]{1,64})?")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(nif: dict, field_path: str) -> tuple[dict | list, str | int]:
    """Resuelve un path como 'hypotheses[0].evidence_for' y retorna
    (parent, key_or_index) donde aplicar el valor.
    Levanta KeyError/IndexError/ValueError si el path no existe o es inválido.

    BUG-003: Rechaza índices negativos y paths vacíos.
    """
    if not field_path or not field_path.strip():
        raise ValueError(f"field_path no puede estar vacío")

    parts = []
    current = ""
    for ch in field_path:
        if ch == ".":
            if current:
                parts.append(current)
                current = ""
        elif ch == "[":
            if current:
                parts.append(current)
                current = ""
        elif ch == "]":
            idx = int(current)
            if idx < 0:
                raise IndexError(f"Índice negativo {idx} no permitido en path '{field_path}'")
            parts.append(idx)
            current = ""
        else:
            current += ch
    if current:
        parts.append(current)

    if not parts:
        raise ValueError(f"field_path '{field_path}' no produce partes válidas")

    node = nif
    for part in parts[:-1]:
        if isinstance(part, int):
            if not isinstance(node, list) or part >= len(node):
                raise IndexError(f"Índice {part} fuera de rango en path '{field_path}'")
            node = node[part]
        else:
            if not isinstance(node, dict) or part not in node:
                raise KeyError(f"Campo '{part}' no encontrado en path '{field_path}'")
            node = node[part]

    last = parts[-1]
    if isinstance(last, int):
        if not isinstance(node, list):
            raise TypeError(f"Se esperaba lista en path '{field_path}', se encontró {type(node).__name__}")
        return node, last
    return node, last


def _get_value(nif: dict, field_path: str) -> Any:
    """Obtiene el valor actual de un campo del NIF."""
    parent, key = _resolve_path(nif, field_path)
    return parent[key]


def _set_value(nif: dict, field_path: str, value: Any) -> Any:
    """Setea un valor en el NIF. Retorna el valor anterior."""
    parent, key = _resolve_path(nif, field_path)
    previous = parent[key] if isinstance(key, str) and key in parent else (
        parent[key] if isinstance(key, int) and key < len(parent) else None
    )
    parent[key] = value
    return previous


def _apply_operation(nif: dict, field_path: str, op: PatchOperation, value: Any) -> Any:
    """Aplica una operación sobre el NIF. Retorna el valor anterior."""
    if op == PatchOperation.replace:
        return _set_value(nif, field_path, value)

    elif op == PatchOperation.append:
        current = _get_value(nif, field_path)
        if isinstance(current, list):
            current.append(value)
        elif isinstance(current, str):
            _set_value(nif, field_path, current + "\n" + str(value))
        else:
            _set_value(nif, field_path, [current, value] if current is not None else [value])
        return current

    elif op == PatchOperation.insert:
        current = _get_value(nif, field_path)
        if isinstance(current, list):
            idx = value.get("_index", 0) if isinstance(value, dict) and "_index" in value else 0
            item = value.get("_value", value) if isinstance(value, dict) and "_index" in value else value
            current.insert(idx, item)
        return None

    elif op == PatchOperation.delete:
        current = _get_value(nif, field_path)
        if isinstance(current, list):
            if isinstance(value, int):
                removed = current.pop(value)
            else:
                current.remove(value)
                removed = value
        elif isinstance(current, str):
            _set_value(nif, field_path, "")
            removed = current
        else:
            removed = current
            _set_value(nif, field_path, None)
        return removed

    elif op == PatchOperation.merge:
        current = _get_value(nif, field_path)
        if isinstance(current, dict) and isinstance(value, dict):
            current.update(value)
        return copy.deepcopy(current)

    return None


# ---------------------------------------------------------------------------
#  NIFBoard
# ---------------------------------------------------------------------------

class NIFBoard:
    """Pizarra compartida del NIF para un caso.

    Uso típico de un subagente:
        board = NIFBoard(case_id="caso-abc")
        nif = board.read()
        # ... trabaja con el NIF ...
        result = board.write(patch)
        if result.success:
            print(f"NIF actualizado a v{result.nif_version}")

    Uso típico del usuario:
        board = NIFBoard(case_id="caso-abc")
        nif = board.read()
        print(board.summary(nif))
        board.user_edit("hypotheses[0].evidence_for", "Nuevo argumento...")
    """

    def __init__(self, case_id: str, cases_root: str | None = None):
        # Un case_id no validado creaba directorios con cualquier cosa que le
        # pasaran: el directorio de casos de producción acabó con carpetas
        # "<MagicMock name='mock.case_id' id=...>" dejadas por la suite. Un
        # identificador de expediente es un nombre, no un repr arbitrario.
        if not _CASE_ID.fullmatch(str(case_id)):
            raise ValueError(f"case_id inválido: {case_id!r}")
        self.case_id = case_id
        profile_root = BOARD_ROOT.parent
        self.cases_root = cases_root or str(profile_root / "data" / "cases")
        self.case_dir = Path(self.cases_root) / case_id

        # Backend: SQLite con WAL mode (reemplaza fcntl/flock)
        self.db_path = self.case_dir / "nif_board.db"
        self.case_dir.mkdir(parents=True, exist_ok=True)
        self._init_db()

        # Archivos legacy (migración one-shot desde formato anterior)
        self._legacy_nif_path = self.case_dir / "nif.json"
        self._legacy_patches_path = self.case_dir / "nif_patches.jsonl"
        self._legacy_history_dir = self.case_dir / "nif_history"
        self._legacy_version_file = self.case_dir / "nif_version.txt"
        self._migrate_if_needed()

    # ------------------------------------------------------------------
    #  SQLite initialization
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create tables and enable WAL mode for safe concurrent access.

        Setting ``journal_mode`` itself obtains an exclusive SQLite lock. A
        case can be opened concurrently before its database exists, so wait
        and retry that one-time setup instead of leaking ``database is
        locked`` out of the constructor.
        """
        import time

        for attempt in range(5):
            try:
                with sqlite3.connect(str(self.db_path), timeout=5) as con:
                    con.execute("PRAGMA busy_timeout=5000")
                    con.execute("PRAGMA journal_mode=WAL")
                    con.execute("PRAGMA synchronous=NORMAL")
                    con.executescript("""
                CREATE TABLE IF NOT EXISTS nif_state (
                    version INTEGER PRIMARY KEY AUTOINCREMENT,
                    data_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS nif_patches (
                    patch_id TEXT PRIMARY KEY,
                    case_id TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    field_path TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    value_json TEXT,
                    reason TEXT DEFAULT '',
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (version) REFERENCES nif_state(version)
                );
                CREATE INDEX IF NOT EXISTS idx_patches_case ON nif_patches(case_id);
                CREATE INDEX IF NOT EXISTS idx_patches_version ON nif_patches(version);
                CREATE TRIGGER IF NOT EXISTS nif_state_no_update
                BEFORE UPDATE ON nif_state BEGIN SELECT RAISE(ABORT, 'nif_state is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS nif_state_no_delete
                BEFORE DELETE ON nif_state BEGIN SELECT RAISE(ABORT, 'nif_state is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS nif_patches_no_update
                BEFORE UPDATE ON nif_patches BEGIN SELECT RAISE(ABORT, 'nif_patches is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS nif_patches_no_delete
                BEFORE DELETE ON nif_patches BEGIN SELECT RAISE(ABORT, 'nif_patches is append-only'); END;
            """)
                return
            except sqlite3.OperationalError as exc:
                if "locked" not in str(exc).lower() or attempt == 4:
                    raise
                time.sleep(0.05 * (attempt + 1))

    def _verify_history(self, con: sqlite3.Connection) -> None:
        """Toda versión posterior a la inicial debe tener patches asociados."""
        versions = [row[0] for row in con.execute(
            "SELECT version FROM nif_state ORDER BY version"
        ).fetchall()]
        for version in versions[1:]:
            row = con.execute(
                "SELECT COUNT(*) FROM nif_patches WHERE case_id=? AND version=?",
                (self.case_id, version),
            ).fetchone()
            if row is None or int(row[0]) < 1:
                raise NIFBoardIntegrityError(
                    f"NIF version {version} no tiene journal para caso {self.case_id}"
                )

    def _migrate_if_needed(self) -> None:
        """One-shot migration from legacy file-based format to SQLite."""
        if not self._legacy_nif_path.exists():
            return
        # Check if already migrated (SQLite has data)
        with sqlite3.connect(str(self.db_path)) as con:
            row = con.execute("SELECT COUNT(*) FROM nif_state").fetchone()
            if row and row[0] > 0:
                return  # Already migrated
        # Migrate: read legacy nif.json
        try:
            nif_data = json.loads(self._legacy_nif_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            nif_data = self._empty_nif(self.case_id)
        now = _now()
        with sqlite3.connect(str(self.db_path)) as con:
            con.execute(
                "INSERT INTO nif_state (version, data_json, updated_at) VALUES (1, ?, ?)",
                (json.dumps(nif_data, ensure_ascii=False), now),
            )
        # Migrate legacy patches
        if self._legacy_patches_path.exists():
            for line in self._legacy_patches_path.read_text().splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    p = json.loads(line)
                    with sqlite3.connect(str(self.db_path)) as con:
                        con.execute(
                            """INSERT OR IGNORE INTO nif_patches
                               (patch_id, case_id, version, agent_id, field_path,
                                operation, value_json, reason, timestamp)
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                            (p.get("patch_id", ""), self.case_id,
                             p.get("nif_version", 1),
                             p.get("agent_id", "unknown"),
                             p.get("field_path", ""),
                             p.get("operation", "replace"),
                             json.dumps(p.get("value")),
                             p.get("reason", ""),
                             p.get("timestamp", now)),
                        )
                except (json.JSONDecodeError, Exception):
                    continue
        # Rename legacy files to .legacy suffix so they don't interfere
        for legacy_path in [self._legacy_nif_path, self._legacy_patches_path,
                            self._legacy_version_file]:
            if legacy_path.exists():
                legacy_path.rename(legacy_path.with_suffix(legacy_path.suffix + ".legacy"))
        # Move history dir
        if self._legacy_history_dir.exists():
            self._legacy_history_dir.rename(
                self._legacy_history_dir.with_name("nif_history.legacy"))
        self._legacy_nif_path = self.case_dir / "nif.json.legacy"

    # ------------------------------------------------------------------
    #  Read
    # ------------------------------------------------------------------

    def read(self) -> dict | None:
        """Lee el NIF canónico actual desde SQLite. Retorna None si no existe.
        Sin lock — WAL mode permite lecturas concurrentes sin bloqueo."""
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                self._verify_history(con)
                row = con.execute(
                    "SELECT data_json FROM nif_state ORDER BY version DESC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                return json.loads(row[0])
        except (sqlite3.Error, json.JSONDecodeError):
            return None

    def _read_nif_safe(self, max_retries: int = 3) -> dict | None:
        """Lee el NIF con retry ante race conditions.
        WAL mode minimiza esto, pero se mantiene el retry por robustez."""
        for attempt in range(max_retries):
            try:
                return self.read()
            except (sqlite3.Error, json.JSONDecodeError):
                if attempt < max_retries - 1:
                    import time
                    time.sleep(0.01 * (attempt + 1))
                else:
                    return None

    # ------------------------------------------------------------------
    #  Read methods (continued)
    # ------------------------------------------------------------------

    def read_section(self, field_path: str) -> Any:
        """Lee solo una sección del NIF sin lock.

        Pull-based (P3): los subagentes leen solo lo que necesitan
        en vez de todo el NIF. Reduce context rot (P6).

        Args:
            field_path: Path del campo, ej: 'norms', 'hypotheses[0]', 'facts.known'

        Returns:
            El valor del campo, o None si no existe.
        """
        nif = self.read()
        if nif is None:
            return None
        try:
            parent, key = _resolve_path(nif, field_path)
            return parent[key]
        except (KeyError, IndexError, TypeError):
            return None

    def read_for_role(self, agent_role: str) -> dict:
        """Retorna solo las secciones del NIF relevantes para un rol.

        Pull-based (P3, Raj/IKEA): cada agente recibe solo lo que necesita,
        no todo el NIF. Reduce context rot (P6, Superlinked).

        Args:
            agent_role: 'researcher' | 'case_designer' | 'contradictor' | 'juez' | 'rhetoric_writer'

        Returns:
            dict con las secciones relevantes + _meta con version/case_id/view_for.
        """
        nif = self.read()
        if nif is None:
            return {}

        role_views: dict[str, list[str]] = {
            "researcher": ["legal_question", "problem_type", "gaps", "facts"],
            "case_designer": ["legal_question", "norms", "facts", "gaps", "conflicts"],
            "contradictor": ["hypotheses", "norms", "confidence"],
            "juez": ["hypotheses", "norms", "confidence", "gaps", "conflicts"],
            "rhetoric_writer": ["hypotheses", "norms", "facts", "confidence"],
        }

        sections = role_views.get(agent_role, list(nif.keys()))
        view: dict[str, Any] = {}
        for section in sections:
            if section in nif:
                view[section] = nif[section]
        view["_meta"] = {
            "version": self.version(),
            "case_id": self.case_id,
            "view_for": agent_role,
        }
        return view

    def read_typed(self) -> NormativeInteractionFrame | None:
        """Lee el NIF como modelo Pydantic tipado."""
        raw = self.read()
        if raw is None:
            return None
        return NormativeInteractionFrame(**raw)

    def version(self) -> int:
        """Retorna la versión actual del NIF (0 si no existe)."""
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                row = con.execute(
                    "SELECT MAX(version) FROM nif_state"
                ).fetchone()
                return row[0] if row and row[0] else 0
        except sqlite3.Error:
            return 0

    # ------------------------------------------------------------------
    #  Write (aplicar patch) — via SQLite transaction (reemplaza fcntl)
    # ------------------------------------------------------------------

    def write(self, patch: NIFPatch) -> NIFPatchResult:
        """Aplica un parche como una versión atómica del NIF."""
        return self.write_many([patch])

    def write_many(self, patches: list[NIFPatch]) -> NIFPatchResult:
        """Aplica varios patches en una transacción y una sola versión."""
        if not patches:
            return NIFPatchResult(success=False, error="Se requiere al menos un patch")
        invalid = next((patch for patch in patches if patch.case_id != self.case_id), None)
        if invalid is not None:
            return NIFPatchResult(
                success=False,
                patch=invalid,
                error=f"Patch case_id={invalid.case_id} no coincide con board case_id={self.case_id}",
            )

        try:
            with sqlite3.connect(str(self.db_path)) as con:
                con.execute("BEGIN IMMEDIATE")
                self._verify_history(con)
                row = con.execute(
                    "SELECT data_json FROM nif_state ORDER BY version DESC LIMIT 1"
                ).fetchone()
                nif = json.loads(row[0]) if row is not None else self._empty_nif(self.case_id)

                for patch in patches:
                    try:
                        try:
                            previous = copy.deepcopy(_get_value(nif, patch.field_path))
                        except KeyError:
                            if patch.operation is not PatchOperation.replace:
                                raise
                            # replace puede crear solo la clave terminal; los padres
                            # continúan siendo resueltos estrictamente por _set_value.
                            previous = None
                        _apply_operation(nif, patch.field_path, patch.operation, patch.value)
                        patch.previous_value = previous
                    except (KeyError, IndexError, ValueError, TypeError) as exc:
                        con.execute("ROLLBACK")
                        return NIFPatchResult(
                            success=False,
                            patch=patch,
                            error=f"Error aplicando patch en '{patch.field_path}': {exc}",
                        )

                try:
                    validated = NormativeInteractionFrame.model_validate(nif)
                except ValidationError as exc:
                    con.execute("ROLLBACK")
                    return NIFPatchResult(
                        success=False,
                        patch=patches[-1],
                        error=(
                            "Los patches producirían un NIF inválido "
                            f"({len(exc.errors())} error(es) de schema): {exc.errors()[:3]}"
                        ),
                    )

                normalized = validated.model_dump(mode="json")
                now = _now()
                cursor = con.execute(
                    "INSERT INTO nif_state (data_json, updated_at) VALUES (?, ?)",
                    (json.dumps(normalized, ensure_ascii=False, sort_keys=True), now),
                )
                new_version = int(cursor.lastrowid)

                for patch in patches:
                    con.execute(
                        """INSERT INTO nif_patches
                           (patch_id, case_id, version, agent_id, field_path,
                            operation, value_json, reason, timestamp)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (patch.patch_id, self.case_id, new_version,
                         patch.agent_id, patch.field_path, patch.operation.value,
                         json.dumps(patch.value, ensure_ascii=False), patch.reason, now),
                    )
                con.execute("COMMIT")

            return NIFPatchResult(success=True, patch=patches[-1], nif_version=new_version)
        except NIFBoardIntegrityError:
            raise
        except Exception as exc:
            return NIFPatchResult(
                success=False, patch=patches[-1], error=f"Error de escritura: {exc}"
            )

    # ------------------------------------------------------------------
    #  Diff
    # ------------------------------------------------------------------

    def diff(self, since_version: int = 0) -> NIFDiff:
        """Retorna los cambios desde una versión dada."""
        current_version = self.version()
        patches = self.patches_since(since_version)

        fields_changed = list(set(p.field_path for p in patches))
        agents = list(set(p.agent_id for p in patches))

        # Construir resumen legible
        summary_parts = []
        agent_counts: dict[str, int] = {}
        for p in patches:
            agent_counts[p.agent_id] = agent_counts.get(p.agent_id, 0) + 1
        for agent, count in agent_counts.items():
            summary_parts.append(f"{agent}: {count} patch(es)")
        summary = "; ".join(summary_parts) if summary_parts else "Sin cambios"

        return NIFDiff(
            case_id=self.case_id,
            from_version=since_version,
            to_version=current_version,
            from_timestamp=patches[0].timestamp if patches else _now(),
            to_timestamp=patches[-1].timestamp if patches else _now(),
            patches_applied=patches,
            fields_changed=fields_changed,
            agents_involved=agents,
            summary=summary,
        )

    def patches_since(self, version: int = 0) -> list[NIFPatch]:
        """Lee patches desde una versión dada desde SQLite."""
        patches = []
        try:
            with sqlite3.connect(str(self.db_path)) as con:
                rows = con.execute(
                    """SELECT patch_id, case_id, version, agent_id, field_path,
                              operation, value_json, reason, timestamp
                       FROM nif_patches
                       WHERE version > ?
                       ORDER BY version ASC""",
                    (version,),
                ).fetchall()
                for row in rows:
                    try:
                        value = json.loads(row[6]) if row[6] else None
                    except (json.JSONDecodeError, TypeError):
                        value = None
                    from shared.schemas.nif_patch import PatchOperation
                    patches.append(NIFPatch(
                        patch_id=row[0],
                        case_id=row[1],
                        nif_version=row[2],
                        agent_id=row[3],
                        field_path=row[4],
                        operation=PatchOperation(row[5]) if row[5] else PatchOperation.replace,
                        value=value,
                        reason=row[7] or "",
                        timestamp=row[8] or "",
                    ))
        except sqlite3.Error:
            pass
        return patches

    # ------------------------------------------------------------------
    #  User edit (intervención humana)
    # ------------------------------------------------------------------

    def user_edit(self, field_path: str, value: Any, reason: str = "Edición del usuario") -> NIFPatchResult:
        """El usuario edita un campo del NIF directamente.

        Esto es el mecanismo clave para que el usuario intervenga
        cuando ve que los subagentes están fallando en encontrar
        argumentos centrales.

        Ejemplo:
            board.user_edit("hypotheses[0].evidence_for", "Sentencia Rol 1234...")
            board.user_edit("gaps", {"description": "Falta jurisprudencia sobre X", "impact": "alto"})
        """
        # Determinar operación automáticamente
        nif = self._read_nif_safe()
        if nif is None:
            return NIFPatchResult(success=False, error="NIF no existe para este caso")

        try:
            current = _get_value(nif, field_path)
            if isinstance(current, list):
                op = PatchOperation.append
            else:
                op = PatchOperation.replace
        except (KeyError, IndexError):
            op = PatchOperation.replace

        patch = NIFPatch(
            agent_id="user",
            field_path=field_path,
            operation=op,
            value=value,
            reason=reason,
            case_id=self.case_id,
        )

        return self.write(patch)

    # ------------------------------------------------------------------
    #  Fill gap (P4: Fail → Demand → Fill, Raj/IKEA)
    # ------------------------------------------------------------------

    def fill_gap(self, gap_index: int, filled_by: str, filled_with: str) -> NIFPatchResult:
        """Marca un gap como resuelto.

        Implementa el ciclo TDD-like de Raj/IKEA:
        1. Agente falla → detecta gap (status='open')
        2. Agente demanda conocimiento (scraper_ticket=True si aplica)
        3. Humano u otro agente llena el gap (status='filled')

        Args:
            gap_index: Índice del gap en la lista nif['gaps']
            filled_by: agent_id o 'user' que resolvió el gap
            filled_with: Descripción de cómo se resolvió

        Returns:
            NIFPatchResult con el patch de resolución aplicado.
        """
        nif = self.read()
        if nif is None:
            return NIFPatchResult(success=False, error="NIF no existe")

        gaps = nif.get("gaps", [])
        if gap_index < 0 or gap_index >= len(gaps):
            return NIFPatchResult(
                success=False,
                error=f"Gap índice {gap_index} no existe (total: {len(gaps)})",
            )

        gap = gaps[gap_index]
        if isinstance(gap, dict):
            previous = gap.copy()
            gap["status"] = "filled"
            gap["filled_by"] = filled_by
            gap["filled_with"] = filled_with
        else:
            return NIFPatchResult(success=False, error=f"Gap {gap_index} no es un dict válido")

        patch = NIFPatch(
            agent_id=filled_by,
            field_path=f"gaps[{gap_index}]",
            operation=PatchOperation.replace,
            value=gap,
            previous_value=previous,
            reason=f"Gap resuelto: {filled_with[:200]}",
            case_id=self.case_id,
        )
        return self.write(patch)

    # ------------------------------------------------------------------
    #  Self-diagnostics (P5: Zuben/Raindrop/Observability)
    # ------------------------------------------------------------------

    def health_check(self) -> dict:
        """Diagnóstico de salud del NIF. Detecta problemas sin intervención humana.

        Grounding: Raindrop distingue implicit signals (user frustration, task failure)
        de explicit signals (error rate, latency). health_check() implementa ambos:
        - Explicit: versión, conteos, agentes involucrados
        - Implicit: loops, stagnation, gap accumulation, agent imbalance

        Returns:
            dict con keys: status, version, total_patches, norms, gaps,
            hypotheses, confidence, issues (críticos), warnings (no críticos).
        """
        nif = self.read()
        if nif is None:
            return {"status": "error", "issues": ["NIF no existe"], "warnings": []}

        patches = self.patches_since()
        issues: list[str] = []
        warnings: list[str] = []

        # D1: Loop detection — mismo campo parcheado > 5 veces por el mismo agente
        field_agent_counts: dict[str, dict[str, int]] = {}
        for p in patches:
            field_agent_counts.setdefault(p.field_path, {})
            field_agent_counts[p.field_path][p.agent_id] = (
                field_agent_counts[p.field_path].get(p.agent_id, 0) + 1
            )
        for field, agents in field_agent_counts.items():
            for agent, count in agents.items():
                if count > 5:
                    issues.append(
                        f"LOOP: {agent} parcheó '{field}' {count} veces — posible loop"
                    )

        # D2: Stagnation — confidence no sube después de 10+ patches
        if len(patches) > 10:
            confidence_patches = [p for p in patches if p.field_path == "confidence"]
            if len(confidence_patches) >= 3:
                values = [p.value for p in confidence_patches if isinstance(p.value, (int, float))]
                if values and max(values) - min(values) < 0.1:
                    warnings.append(
                        f"STAGNATION: confidence no varía significativamente "
                        f"({min(values):.2f} - {max(values):.2f}) después de {len(patches)} patches"
                    )

        # D3: Gap accumulation — más gaps que normas
        norms_count = len(nif.get("norms", []))
        gaps_count = len(nif.get("gaps", []))
        if gaps_count > norms_count * 2 and norms_count > 0:
            warnings.append(
                f"GAP_ACCUMULATION: {gaps_count} gaps vs {norms_count} normas — "
                f"el caso puede estar subinvestigado"
            )

        # D4: Agent imbalance — un agente hizo > 80% de los patches
        if patches:
            agent_counts: dict[str, int] = {}
            for p in patches:
                agent_counts[p.agent_id] = agent_counts.get(p.agent_id, 0) + 1
            for agent, count in agent_counts.items():
                if count > len(patches) * 0.8 and len(patches) > 5:
                    warnings.append(
                        f"AGENT_IMBALANCE: {agent} hizo {count}/{len(patches)} patches "
                        f"({count * 100 // len(patches)}%) — otros agentes pueden estar bloqueados"
                    )

        # D5: No hypotheses after norms
        if norms_count > 0 and len(nif.get("hypotheses", [])) == 0:
            warnings.append(
                "NO_HYPOTHESES: Hay normas pero no hay hipótesis — "
                "case_designer puede no haber ejecutado"
            )

        return {
            "status": "healthy" if not issues else "degraded",
            "version": self.version(),
            "total_patches": len(patches),
            "norms": norms_count,
            "gaps": gaps_count,
            "hypotheses": len(nif.get("hypotheses", [])),
            "confidence": nif.get("confidence", 0),
            "issues": issues,
            "warnings": warnings,
        }

    # ------------------------------------------------------------------
    #  Context rot awareness (P6: Superlinked/Inference)
    # ------------------------------------------------------------------

    def summary_for_llm(self, max_tokens: int = 2000) -> str:
        """Resumen compacto del NIF para inyectar como contexto al LLM.

        Grounding: Context rot (Superlinked) — no inyectar todo el NIF al LLM.
        La calidad del LLM degrada a medida que el contexto aumenta.
        Este método retorna un resumen estructurado con lo esencial.

        Args:
            max_tokens: Máximo de tokens estimados (aprox 4 chars por token).

        Returns:
            String con el resumen compacto, truncado si excede max_tokens.
        """
        nif = self.read()
        if nif is None:
            return "NIF no disponible."

        parts: list[str] = []
        parts.append(f"Caso: {self.case_id} (v{self.version()})")
        parts.append(f"Pregunta: {nif.get('legal_question', 'N/A')}")
        parts.append(f"Confianza: {nif.get('confidence', 0):.2f}")

        # Normas (solo labels, no todo el objeto)
        norms = nif.get("norms", [])
        if norms:
            parts.append(f"\nNormas ({len(norms)}):")
            for n in norms[:10]:
                label = n.get("label", n.get("gid", "Sin label")) if isinstance(n, dict) else str(n)
                parts.append(f"  - {label}")
            if len(norms) > 10:
                parts.append(f"  ... y {len(norms) - 10} más")

        # Hipótesis (solo claims)
        hypotheses = nif.get("hypotheses", [])
        if hypotheses:
            parts.append(f"\nHipótesis ({len(hypotheses)}):")
            for h in hypotheses[:5]:
                claim = h.get("claim", "Sin claim") if isinstance(h, dict) else str(h)
                status = h.get("status", "?") if isinstance(h, dict) else "?"
                parts.append(f"  - [{status}] {claim}")

        # Gaps abiertos
        gaps = nif.get("gaps", [])
        open_gaps = [g for g in gaps if isinstance(g, dict) and g.get("status") == "open"]
        if open_gaps:
            parts.append(f"\nGaps abiertos ({len(open_gaps)}):")
            for g in open_gaps[:5]:
                impact = g.get("impact", "?")
                desc = g.get("description", "Sin descripción")
                parts.append(f"  - [{impact}] {desc}")

        result = "\n".join(parts)

        # Truncar si excede max_tokens (aprox 4 chars por token)
        max_chars = max_tokens * 4
        if len(result) > max_chars:
            result = result[:max_chars] + "\n... [truncado por context rot]"

        return result

    # ------------------------------------------------------------------
    #  Summary (para mostrar al usuario)
    # ------------------------------------------------------------------

    def summary(self, nif: dict | None = None) -> str:
        """Resumen legible del NIF para el usuario."""
        if nif is None:
            nif = self.read()
        if nif is None:
            return f"[NIF Board] Caso {self.case_id}: NIF no existe aún."

        lines = []
        lines.append(f"═══ NIF Board — Caso: {self.case_id} ═══")
        lines.append(f"Versión: {self.version()} | Pregunta: {nif.get('legal_question', 'N/A')}")
        lines.append(f"Tipo: {nif.get('problem_type', 'N/A')} | Confianza: {nif.get('confidence', 0):.2f}")
        lines.append("")

        facts = nif.get("facts", {})
        lines.append(f"📋 Hechos: {len(facts.get('known', []))} conocidos, "
                     f"{len(facts.get('alleged', []))} alegados, "
                     f"{len(facts.get('missing', []))} faltantes")

        lines.append(f"⚖️  Normas: {len(nif.get('norms', []))}")
        lines.append(f"👤 Sujetos: {len(nif.get('subjects', []))}")
        lines.append(f"🔗 Relaciones normativas: {len(nif.get('norm_relations', []))}")
        lines.append(f"💡 Hipótesis: {len(nif.get('hypotheses', []))}")
        lines.append(f"⚠️  Gaps: {len(nif.get('gaps', []))}")
        lines.append(f"🔴 Conflictos: {len(nif.get('conflicts', []))}")

        # Mostrar gaps abiertos (lo más importante para el usuario)
        gaps = nif.get("gaps", [])
        if gaps:
            lines.append("")
            lines.append("── Gaps abiertos ──")
            for i, gap in enumerate(gaps):
                impact = gap.get("impact", "medio")
                icon = "🔴" if impact == "alto" else "🟡" if impact == "medio" else "🟢"
                lines.append(f"  {icon} [{i}] {gap.get('description', 'Sin descripción')}")

        # Mostrar hipótesis con estado
        hypotheses = nif.get("hypotheses", [])
        if hypotheses:
            lines.append("")
            lines.append("── Hipótesis ──")
            for i, h in enumerate(hypotheses):
                if not isinstance(h, dict):
                    continue  # Saltar elementos malformados
                status_icon = {
                    "open": "❓", "supported": "✅", "rejected": "❌", "needs_more_evidence": "🔍"
                }.get(h.get("status", "open"), "❓")
                lines.append(f"  {status_icon} [{i}] {h.get('claim', 'Sin claim')}")
                lines.append(f"       Tipo: {h.get('type', 'N/A')} | Estado: {h.get('status', 'open')}")
                if h.get("evidence_for"):
                    lines.append(f"       ✅ A favor ({len(h['evidence_for'])}):")
                    for e in h["evidence_for"][:3]:
                        lines.append(f"          - {str(e)[:80]}...")
                if h.get("evidence_against"):
                    lines.append(f"       ❌ En contra ({len(h['evidence_against'])}):")
                    for e in h["evidence_against"][:3]:
                        lines.append(f"          - {str(e)[:80]}...")

        # Input del usuario
        extra = nif.get("extra", {})
        user_input = extra.get("user_input", "")
        if user_input:
            lines.append("")
            lines.append(f"🖊️  Input del usuario: {user_input[:200]}")

        lines.append("")
        lines.append(f"── Versión: {self.version()} | Patches: {len(self.patches_since())} ──")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    #  Init (crear NIF vacío para un caso)
    # ------------------------------------------------------------------

    def init_nif(self, legal_question: str, problem_type: str = "mixto",
                 source: str = "orchestrator", *, extra: dict | None = None) -> dict:
        """Inicializa un NIF vacío para este caso en SQLite.

        Valida el estado inicial contra el schema: un problem_type inválido
        (ej. pasar un área del derecho como 'laboral' en vez de un ProblemType)
        crearía un NIF que luego bloquea todas las escrituras en write(). Mejor
        fallar rápido y claro aquí.
        """
        nif = self._empty_nif(self.case_id, legal_question, problem_type, source)
        if extra:
            nif["extra"] = dict(extra)
        try:
            validated = NormativeInteractionFrame.model_validate(nif)
        except ValidationError as exc:
            raise ValueError(
                f"NIF inicial inválido para caso '{self.case_id}': {exc.errors()[:3]}"
            ) from exc
        now = _now()
        # La unicidad se decide DENTRO de la transacción. Comprobarla afuera
        # (`if board.read() is None: init()`) es un TOCTOU sin lock: dos
        # procesos que inicializan el mismo caso a la vez insertan ambos, el
        # estado materializado diverge del journal append-only y `read()`
        # devuelve None para siempre — expediente ilegible, sin reparación.
        con = sqlite3.connect(str(self.db_path), timeout=5)
        con.isolation_level = None  # control explícito de la transacción
        try:
            con.execute("PRAGMA busy_timeout=5000")
            con.execute("BEGIN IMMEDIATE")
            if con.execute("SELECT 1 FROM nif_state LIMIT 1").fetchone() is not None:
                con.execute("ROLLBACK")
                raise NIFAlreadyExists(
                    f"El caso '{self.case_id}' ya tiene un NIF inicializado"
                )
            con.execute(
                "INSERT INTO nif_state (data_json, updated_at) VALUES (?, ?)",
                (json.dumps(validated.model_dump(mode="json"), ensure_ascii=False, sort_keys=True), now),
            )
            con.execute("COMMIT")
        finally:
            con.close()
        return validated.model_dump(mode="json")

    # ------------------------------------------------------------------
    #  Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_nif(case_id: str, legal_question: str = "",
                   problem_type: str = "mixto", source: str = "orchestrator") -> dict:
        return {
            "frame_id": f"nif-{case_id}",
            "created_at": _now(),
            "source": source,
            "legal_question": legal_question,
            "problem_type": problem_type,
            "facts": {"known": [], "alleged": [], "missing": []},
            "subjects": [],
            "norms": [],
            "norm_relations": [],
            "admin_acts": [],
            "principles": [],
            "deontic_positions": [],
            "conflicts": [],
            "hypotheses": [],
            "gaps": [],
            "relevant_factors": [],
            "confidence": 0.0,
            "validated_by_human": False,
            "extra": {},
        }
