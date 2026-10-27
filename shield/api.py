"""FastAPI surface for Diké Shield."""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from typing import Literal
from urllib import error, request

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from shield.bench import run_bench
from shield.dike_adapter import dike_paths
from shield.engines import engines_healthy
from shield.env import ROOT, load_env, redact, secret_values
from shield.llm import sample_recorded_at
from shield.loop import Deps, build_deps, run
from shield.zetaris import ZetarisError, run_sql

WEB = Path(__file__).resolve().parent / "web"
SAMPLES = ROOT / "data" / "samples"
PACK_HASH = "af1422d66d1e6eee"

Escenario = Literal["despido", "finiquito", "libre"]


class AnswerIn(BaseModel):
    pregunta: str
    escenario: Escenario
    sesion_id: uuid.UUID | None = None


class AuditIn(BaseModel):
    texto: str
    escenario: Escenario = "libre"


class CitaOut(BaseModel):
    cita_raw: str
    gid: str | None = None
    estado: str | None = None
    resolucion: str | None = None
    vigencia: str | None = None
    accion: str
    reemplazo_gid: str | None = None
    razon: str


class BenchIn(BaseModel):
    n_preguntas: int = 30
    lanes: list[Literal["FAST", "DEEP"]] = ["FAST", "DEEP"]
    con_escudo: list[bool] = [False, True]


class ResultadoOut(BaseModel):
    intercepcion_id: str
    sesion_id: str
    decision: str
    respuesta_final: str | None
    citas: list[CitaOut]
    iteraciones: int
    modelos: dict[str, str | None]
    commitment_disponible: bool
    sample_mode: bool
    texto_reparado: str | None = None


def _meterless_ok(env: dict[str, str]) -> bool:
    base = env.get("METERLESS_BASE_URL", "").rstrip("/")
    token = env.get("METERLESS_RUNTIME_TOKEN", "")
    if not base or not token or token.startswith("<"):
        return False
    req = request.Request(
        f"{base}/models",
        method="GET",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with request.urlopen(req, timeout=8) as resp:
            return 200 <= resp.status < 300
    except (error.URLError, error.HTTPError, TimeoutError, OSError):
        return False


def _dike_ok() -> bool:
    marker = dike_paths()["users"] / "shield" / "starter" / "chile-base" / "STATE.json"
    return marker.is_file()


def create_app(deps: Deps | None = None) -> FastAPI:
    app = FastAPI(title="Diké Shield", version="0.1.0")
    app.state.deps = deps

    def _deps() -> Deps:
        if app.state.deps is None:
            app.state.deps = build_deps()
        return app.state.deps

    @app.get("/healthz")
    def healthz() -> dict:
        env = load_env()
        zetaris = False
        try:
            zetaris = run_sql("SELECT 1", limit=1, env=env) == [["1"]]
        except ZetarisError:
            zetaris = False
        meterless = _meterless_ok(env)
        dike = _dike_ok()
        engines = engines_healthy(env)
        sample_mode = (env.get("SAMPLE_MODE") or "").lower() in {"1", "true", "yes", "on"}
        return {
            "ok": zetaris and meterless and dike,
            "zetaris": zetaris,
            "meterless": meterless,
            "dike": dike,
            "engines": engines,
            "sample_mode": sample_mode,
            "sample_recorded_at": sample_recorded_at() if sample_mode else None,
        }

    @app.post("/v1/shield/answer", response_model=ResultadoOut)
    def answer(body: AnswerIn) -> dict:
        return run(
            entrada=body.pregunta,
            escenario=body.escenario,
            modo="pregunta",
            deps=_deps(),
            sesion_id=body.sesion_id,
        )

    @app.post("/v1/shield/audit", response_model=ResultadoOut)
    def audit(body: AuditIn) -> dict:
        return run(
            entrada=body.texto,
            escenario=body.escenario,
            modo="auditoria",
            deps=_deps(),
        )

    @app.get("/v1/traces/{intercepcion_id}")
    def traces(intercepcion_id: uuid.UUID) -> dict:
        deps = _deps()
        env = deps.env
        secrets = secret_values(env)
        source = env.get("ZETARIS_SOURCE_DB", "shield_pg")
        sql = (
            f"SELECT paso, agente, accion, lane, modelo, latencia_ms, "
            f"entrada_resumen, salida_resumen FROM {source}.eventos_traza "
            f"WHERE intercepcion_id = '{intercepcion_id}' ORDER BY paso"
        )
        try:
            rows = run_sql(sql, limit=200, env=env)
        except ZetarisError as exc:
            raise HTTPException(status_code=502, detail=redact(str(exc), secrets)) from exc
        eventos = []
        for row in rows:
            if not isinstance(row, (list, tuple)) or len(row) < 8:
                continue
            eventos.append(
                {
                    "paso": row[0],
                    "agente": row[1],
                    "accion": row[2],
                    "lane": row[3],
                    "modelo": row[4],
                    "latencia_ms": row[5],
                    "entrada_resumen": row[6],
                    "salida_resumen": row[7],
                }
            )
        if not eventos:
            local = deps.store.list_trazas(intercepcion_id)
            eventos = [
                {
                    "paso": e.paso,
                    "agente": e.agente,
                    "accion": e.accion,
                    "lane": e.lane,
                    "modelo": e.modelo,
                    "latencia_ms": e.latencia_ms,
                    "entrada_resumen": e.entrada_resumen,
                    "salida_resumen": e.salida_resumen,
                }
                for e in local
            ]
        return {"eventos": eventos}

    @app.post("/v1/bench/run")
    def bench_run(body: BenchIn) -> dict:
        ids = run_bench(
            deps=_deps(),
            n_preguntas=body.n_preguntas,
            lanes=list(body.lanes),
            con_escudo=list(body.con_escudo),
        )
        return {"corrida_ids": ids}

    @app.get("/v1/bench/latest")
    def bench_latest() -> dict:
        deps = _deps()
        env = deps.env
        secrets = secret_values(env)
        rows: list[dict] = []

        def _from_store() -> list[dict]:
            out = []
            for row in deps.store.latest_corridas(8):
                total = int(row.get("citas_total") or 0)
                bad = int(row.get("citas_no_probadas") or 0)
                item = {k: (str(v) if k in {"id", "creada"} else v) for k, v in row.items()}
                item["tasa"] = (bad / total) if total else 0
                out.append(item)
            return out

        rows = _from_store()
        if not rows:
            source = env.get("ZETARIS_SOURCE_DB", "shield_pg")
            sql = (
                f"SELECT id, lane, con_escudo, n_preguntas, citas_total, citas_no_probadas, "
                f"abstenciones, reparaciones, latencia_p50_ms, modelo, sample_mode "
                f"FROM {source}.banco_corridas ORDER BY creada DESC"
            )
            try:
                raw = run_sql(sql, limit=8, env=env)
                for row in raw:
                    if not isinstance(row, (list, tuple)) or len(row) < 11:
                        continue
                    n = int(row[3] or 0)
                    total = int(row[4] or 0)
                    bad = int(row[5] or 0)
                    rows.append(
                        {
                            "id": str(row[0]),
                            "lane": row[1],
                            "con_escudo": row[2],
                            "n_preguntas": n,
                            "citas_total": total,
                            "citas_no_probadas": bad,
                            "tasa": (bad / total) if total else 0,
                            "abstenciones": row[6],
                            "reparaciones": row[7],
                            "latencia_p50_ms": row[8],
                            "modelo": row[9],
                            "sample_mode": row[10],
                        }
                    )
            except ZetarisError as exc:
                _ = redact(str(exc), secrets)
                rows = []
        n_label = rows[0]["n_preguntas"] if rows else 0
        return {
            "corridas": rows,
            "pack_hash": PACK_HASH,
            "etiqueta": (
                f"Cifras medidas sobre {n_label} preguntas sintéticas; "
                "no son una estimación de la tasa en producción"
            ),
        }

    @app.get("/v1/commitments/{intercepcion_id}")
    def commitment_zip(intercepcion_id: uuid.UUID) -> Response:
        dest = ROOT / ".local" / "dike-home" / "commitments" / str(intercepcion_id)
        names = ["commitment.json", "commitment.sig.json", "content-signing-key.pub"]
        buf = io.BytesIO()
        found = 0
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name in names:
                path = dest / name
                if path.is_file():
                    zf.write(path, name)
                    found += 1
            demo_pub = ROOT / ".local" / "keys" / "demo-content-signing-key.pub"
            if "content-signing-key.pub" not in zf.namelist() and demo_pub.is_file() and found:
                zf.write(demo_pub, "content-signing-key.pub")
                found += 1
        if not found:
            raise HTTPException(status_code=404, detail="commitment no disponible")
        return Response(
            content=buf.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f"attachment; filename=commitment-{intercepcion_id}.zip"
            },
        )

    @app.get("/")
    def ui() -> FileResponse:
        index = WEB / "index.html"
        if not index.is_file():
            raise HTTPException(status_code=404, detail="UI missing")
        return FileResponse(index)

    if WEB.is_dir():
        app.mount("/web", StaticFiles(directory=str(WEB)), name="web")
    if SAMPLES.is_dir():
        app.mount("/samples", StaticFiles(directory=str(SAMPLES)), name="samples")

    return app


app = create_app()
