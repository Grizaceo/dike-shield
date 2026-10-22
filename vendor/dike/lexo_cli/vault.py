"""Shared vault search logic — used by preguntar, buscar, and status."""

from __future__ import annotations

import subprocess
import re
import unicodedata
import os
from dataclasses import dataclass, field
from pathlib import Path

from lexo_cli.output import output_warning


@dataclass(frozen=True)
class SearchOutcome:
    results: list[dict]
    backend: str
    degraded: bool
    errors: list[str]
    filters_applied: dict[str, str] = field(default_factory=dict)
    candidate_count: int = 0
    post_filter_count: int = 0


_MATERIA_ALIASES = {
    "administrativo": "administrativo",
    "ambiental": "ambiental",
    "civil": "civil",
    "comercial": "comercial",
    "constitucional": "constitucional",
    "datos_personales": "datos_personales",
    "derecho_administrativo": "administrativo",
    "derecho_ambiental": "ambiental",
    "derecho_civil": "civil",
    "derecho_comercial": "comercial",
    "derecho_constitucional": "constitucional",
    "derecho_del_trabajo": "laboral",
    "derecho_laboral": "laboral",
    "derecho_penal": "penal",
    "derecho_procesal": "procesal",
    "derecho_tributario": "tributario",
    "familia": "civil",
    "laboral": "laboral",
    "penal": "penal",
    "previsional": "laboral",
    "procesal": "procesal",
    "proteccion_de_datos": "datos_personales",
    "seguridad_social": "laboral",
    "trabajo": "laboral",
    "tributario": "tributario",
}


def _materia_token(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char)).lower().strip()
    return re.sub(r"[^a-z0-9]+", "_", text).strip("_")


def _canonical_materia(value: object) -> str:
    token = _materia_token(value)
    if not token:
        # Fail closed: un valor vacío/ausente no puede matchear ningún alias
        # (antes, '' in 'administrativo' era True y todo resultado sin materia
        # se clasificaba como administrativo, rompiendo el filtro fail-closed).
        return ""
    if token in _MATERIA_ALIASES:
        return _MATERIA_ALIASES[token]
    for alias, canonical in _MATERIA_ALIASES.items():
        if alias in token or token in alias:
            return canonical
    return ""


def _result_materia(result: dict) -> str:
    raw_metadata = result.get("metadata")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    direct = result.get("materia") or metadata.get("materia")
    if direct:
        return _canonical_materia(direct)
    for field_name in ("category", "path", "filename", "source_path"):
        value = _canonical_materia(result.get(field_name, ""))
        if value:
            return value
    return ""


def _filter_by_materia(results: list[dict], materia: str) -> list[dict]:
    """Fail closed: unknown/unclassified candidates cannot satisfy a filter."""
    return [item for item in results if _result_materia(item) == materia]


# ── Autostart de IndexO ──────────────────────────────────────────────────────
# IndexO no tiene systemd ni auto-restart: después de un reboot el server queda
# caído y `dike buscar` degradaba a grep local sin avisar. Con indexo_autostart
# (default True), el cliente intenta levantarlo una vez y reintenta la query.


def _indexo_health_ok(indexo_url: str, timeout: float = 3.0) -> bool:
    """Health check rápido: True si el server responde 200 con status ok."""
    try:
        import requests
        resp = requests.get(indexo_url + "/health", timeout=timeout)
        if resp.status_code != 200:
            return False
        data = resp.json()
        return data.get("status") == "ok" and bool(data.get("faiss", {}).get("available"))
    except Exception:
        return False


def _puerto_de(url: str, default: int = 7861) -> int:
    """Puerto de la URL configurada de IndexO.

    Estaba escrito `env["PORT"] = "7861"` mientras la URL se leía de la
    configuración: cambiar `indexo_url` a otro puerto levantaba el server en
    7861 y luego lo buscaba en otro lado.
    """
    from urllib.parse import urlparse

    try:
        return urlparse(url).port or default
    except ValueError:
        return default


def _start_indexo(cfg: dict) -> tuple[bool, str]:
    """Levanta IndexO vía start.sh con el PATH de miniconda (requisito: el
    python3 del PATH por defecto no tiene faiss/torch).

    Returns: (ok, mensaje). Espera hasta indexo_start_timeout segundos a que
    /health responda con FAISS disponible.
    """
    vault_cfg = cfg.get("vault", {})
    script = vault_cfg.get("indexo_start_script", "")
    conda_bin = vault_cfg.get("indexo_conda_bin") or ""
    timeout_s = int(vault_cfg.get("indexo_start_timeout", 90))
    indexo_url = vault_cfg.get("indexo_url", "http://localhost:7861")

    if not script or not Path(script).exists():
        return False, f"start script no existe: {script}"

    try:
        import subprocess
        env = dict(os.environ)
        # Sin conda_bin configurado no se antepone nada: inyectar un
        # directorio inexistente al PATH solo cambia un fallo claro por uno
        # confuso.
        if conda_bin and Path(conda_bin).is_dir():
            env["PATH"] = f"{conda_bin}:{env.get('PATH', '')}"
        env["PORT"] = str(_puerto_de(indexo_url))
        proc = subprocess.run(
            ["bash", script],
            capture_output=True, text=True, timeout=30,
            env=env,
        )
        if proc.returncode != 0:
            return False, f"start.sh falló (exit {proc.returncode}): {proc.stderr[-300:]}"
    except Exception as exc:
        return False, f"start.sh no ejecutable: {exc}"

    # Esperar health (el server tarda ~30-60s en cargar modelo e5 + FAISS)
    import time
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _indexo_health_ok(indexo_url):
            return True, "IndexO levantado"
        time.sleep(3)
    return False, f"IndexO no respondió health en {timeout_s}s (revisar {Path(script).parent / 'server.log'})"


def search_vault_detailed(
    query: str,
    top_k: int,
    cfg: dict,
    area: str = "",
    *,
    strict: bool = False,
) -> SearchOutcome:
    """Search with explicit backend/error provenance and optional strict mode."""
    indexo_url = cfg.get("vault", {}).get("indexo_url", "http://localhost:7861")
    indexo_enabled = cfg.get("vault", {}).get("indexo_enabled", True)
    indexo_hybrid = cfg.get("vault", {}).get("indexo_hybrid", True)
    indexo_autostart = cfg.get("vault", {}).get("indexo_autostart", True)
    errors: list[str] = []
    # La materia no se concatena a la consulta: desplazaría sus términos en el
    # embedding. Pedimos candidatos amplios y filtramos por metadata ANTES de
    # truncar al top_k final. Es un contrato explícito mientras IndexO no
    # exponga el filtro server-side (server.py:630 solo acepta q/top_k/raw).
    requested_materia = _canonical_materia(area) if area else ""
    if area and not requested_materia:
        return SearchOutcome(
            [], "indexo", False, [f"Materia no reconocida para filtro: {area}"],
            {"materia": str(area), "mode": "rejected"}, 0, 0,
        )
    filters_applied = (
        {"materia": requested_materia, "mode": "client_post_retrieval"}
        if requested_materia else {}
    )
    candidate_k = min(20, max(top_k, top_k * 6)) if requested_materia else top_k
    if indexo_enabled:
        import requests
        # Ranking híbrido (semántica FAISS + BM25, RRF) cuando está
        # disponible: benchmark 2026-08-17 mostró +19.5pp sobre el
        # semántico puro (22/41 vs 14/41). El server degrada fail-open a
        # solo semántica si BM25 no está listo; el backend reportado
        # distingue ambos casos para no mentir sobre la procedencia.
        endpoint = "/search_hybrid" if indexo_hybrid else "/search"
        # Autostart: si la primera request falla por conexión y el flag está
        # activo, se levanta IndexO una vez y se reintenta. Evita que `dike
        # buscar` degrade silenciosamente a grep tras un reboot.
        for attempt in range(2):
            try:
                response = requests.get(
                    indexo_url + endpoint,
                    # El servidor espera `top_k` e `include_raw` (ver
                    # indexo-retriever-prod/server.py:632). Enviar `k` hacía que
                    # ignorara el límite, y omitir `include_raw` devolvía la
                    # evidencia SIN texto: las fuentes llegaban al juez vacías.
                    params={"q": query, "top_k": candidate_k, "include_raw": "true"},
                    timeout=10,
                )
                response.raise_for_status()
                data = response.json()
                raw_results = data if isinstance(data, list) else data.get("results") if isinstance(data, dict) else None
                if isinstance(raw_results, list):
                    candidates = [item for item in raw_results if isinstance(item, dict)]
                    filtered = _filter_by_materia(candidates, requested_materia) if requested_materia else candidates
                    # Etiqueta honesta: solo "indexo_hybrid" cuando el server
                    # realmente fusionó ambos rankings (RRF con 2 listas).
                    fusion = data.get("fusion") if isinstance(data, dict) else None
                    backend = "indexo_hybrid" if (indexo_hybrid and fusion == "rrf") else "indexo"
                    return SearchOutcome(
                        filtered[:top_k], backend, False, [], filters_applied,
                        len(candidates), len(filtered),
                    )
                errors.append("IndexO devolvió un contrato no reconocido")
                break
            except Exception as exc:
                if attempt == 0 and indexo_autostart:
                    ok, msg = _start_indexo(cfg)
                    if ok:
                        errors.append(f"IndexO autostart: {msg}")
                        continue  # reintentar la query
                    errors.append(f"IndexO autostart falló: {msg}")
                errors.append(f"IndexO: {exc}")
                break
    else:
        errors.append("IndexO deshabilitado")
    if strict:
        return SearchOutcome([], "indexo", False, errors, filters_applied, 0, 0)

    # Sin carpeta configurada, `Path("")` es `Path(".")`: existe siempre, así
    # que el fallback se ponía a hacer grep sobre el directorio de trabajo
    # completo y devolvía código fuente del propio repositorio presentado como
    # documento jurídico. Un vault sin definir es un error de configuración con
    # reparación conocida, no una carpeta vacía.
    configured_path = str(cfg.get("vault", {}).get("path", "") or "").strip()
    if not configured_path:
        return SearchOutcome(
            [], "local_rg", True,
            errors + ["No hay carpeta de documentos configurada: define `vault.path` "
                      "en ~/.lexo/config.yaml o ejecuta `dike onboard`."],
            filters_applied, 0, 0,
        )
    vault_path = Path(configured_path).expanduser()
    if not vault_path.is_dir():
        return SearchOutcome(
            [], "local_rg", True,
            errors + [f"La carpeta de tus documentos no existe: {vault_path}"],
            filters_applied, 0, 0,
        )
    results = []
    try:
        grep_out = subprocess.run(
            ["rg", "-l", "-i", query[:40], str(vault_path)],
            capture_output=True, text=True, timeout=10,
        )
        # Igual que con IndexO: se traen candidate_k candidatos amplios y se
        # filtra por materia DESPUÉS. Truncar a top_k antes del filtro hacía
        # que el fallback local devolviera 0 resultados con área cuando los
        # hits laborales caían más allá del corte (ej. despido injustificado).
        grep_hits = [line for line in grep_out.stdout.strip().split("\n") if line]
        for line in grep_hits[:candidate_k]:
            path = Path(line)
            results.append({"filename": path.name, "path": str(path), "score": 0.0})
    except Exception as exc:
        errors.append(f"local_rg: {exc}")
    filtered = _filter_by_materia(results, requested_materia) if requested_materia else results
    return SearchOutcome(
        filtered[:top_k], "local_rg", True, errors, filters_applied,
        len(results), len(filtered),
    )


def search_vault(
    query: str,
    top_k: int,
    cfg: dict,
    area: str = "",
) -> list[dict]:
    """Search the vault via IndexO (semantic) or local grep fallback.

    Single source of truth for vault search across all CLI commands.
    Handles IndexO returning either a list or {"results": [...]}.

    Args:
        query: Search query string.
        top_k: Maximum results to return.
        cfg: Config dict (from load_config()).
        area: Optional legal area to append to query.

    Returns:
        List of result dicts, each with at minimum 'filename' and 'score' keys.
    """
    outcome = search_vault_detailed(query, top_k, cfg, area)
    if outcome.degraded and not outcome.results:
        output_warning("; ".join(outcome.errors) or "Búsqueda degradada sin resultados")
    return outcome.results
