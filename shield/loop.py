"""Simple shield loop (Markovian comes in phase 4)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from shield.agents import drafter, judge, repairer, router
from shield.db import CitaRow, Store
from shield.dike_adapter import emitir_commitment as _emitir
from shield.dike_adapter import verificar as _verificar
from shield.engines import Markovian, Memory
from shield.env import ROOT, load_env
from shield.extractor import extract, extract_regex
from shield.llm import LLMClient, LLMError
from shield.trace import Tracer
from shield.articles import fetch_articulos as _fetch

VerificarFn = Callable[[str], dict]
FetchFn = Callable[[list[str]], list[dict]]
EmitFn = Callable[[str, Any], dict | None]


@dataclass
class Deps:
    llm: LLMClient
    store: Store
    memory: Memory
    env: dict[str, str]
    markovian: Markovian | None = None
    verificar: VerificarFn = _verificar
    fetch_articulos: FetchFn | None = None
    emitir: EmitFn | None = None
    max_iter: int = 3
    sample_mode: bool = False


def _bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def build_deps(env: dict[str, str] | None = None, *, store: Store | None = None) -> Deps:
    cfg = env or load_env()
    from shield.db import PostgresStore

    def fetch(gids: list[str]) -> list[dict]:
        return _fetch(gids, cfg)

    return Deps(
        llm=LLMClient(cfg),
        store=store or PostgresStore(cfg),
        memory=Memory(env=cfg),
        markovian=Markovian(env=cfg),
        env=cfg,
        verificar=_verificar,
        fetch_articulos=fetch,
        emitir=lambda texto, dest: _emitir(texto, dest),
        max_iter=int(cfg.get("SHIELD_MAX_ITER") or 3),
        sample_mode=_bool_env(cfg.get("SAMPLE_MODE")),
    )


def _clip(text: str, n: int = 240) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "…"


def _fallo_needles(detalles: list[dict]) -> list[str]:
    needles: list[str] = []
    for d in detalles:
        if d.get("estado") != "FALLO":
            continue
        raw = str(d.get("cita_raw") or "")
        if raw:
            needles.append(raw)
        blob = raw if raw else ""
        for cite in extract_regex(blob) or extract_regex(f"Según el {blob}."):
            needles.append(cite.normalized)
            needles.append(f"artículo {cite.numero}")
            needles.append(f"article {cite.numero}")
    # longest first so "artículo 9999 del ..." matches before "artículo 9999"
    return sorted({n for n in needles if n}, key=len, reverse=True)


def _has_fallos(texto: str, detalles: list[dict]) -> bool:
    low = texto.lower()
    return any(n.lower() in low for n in _fallo_needles(detalles))


def _strip_needles(texto: str, needles: list[str]) -> str:
    if not needles:
        return texto.strip()
    parts = re.split(r"(?<=[.!?])\s+", texto.strip())
    keep = []
    for part in parts:
        low = part.lower()
        if any(n.lower() in low for n in needles):
            continue
        keep.append(part)
    return " ".join(keep).strip()


def _strip_fallos(texto: str, detalles: list[dict]) -> str:
    return _strip_needles(texto, _fallo_needles(detalles))


def _evitar_needles(evitar: list[str]) -> list[str]:
    needles: list[str] = []
    for raw in evitar:
        if raw:
            needles.append(raw)
        for cite in extract_regex(raw) or extract_regex(f"Según el {raw}."):
            needles.append(cite.normalized)
            needles.append(f"artículo {cite.numero}")
            needles.append(f"article {cite.numero}")
    return sorted({n for n in needles if n}, key=len, reverse=True)


def _normalize_cita(raw: str) -> str:
    cites = extract_regex(raw) or extract_regex(f"Según el {raw}.")
    return cites[0].normalized if cites else raw.strip()


def _citas_payload(juicio: judge.Juicio, detalles: list[dict]) -> list[dict]:
    by_raw = {a.cita_raw: a for a in juicio.acciones}
    out: list[dict] = []
    seen: set[str] = set()
    for d in detalles:
        raw = str(d.get("cita_raw") or "")
        key = str(d.get("gid") or raw)
        if key in seen:
            continue
        seen.add(key)
        acc = by_raw.get(raw)
        out.append(
            {
                "cita_raw": raw,
                "gid": d.get("gid"),
                "estado": d.get("estado"),
                "resolucion": d.get("resolucion"),
                "vigencia": d.get("vigencia"),
                "accion": acc.accion if acc else ("mantener" if d.get("estado") == "VERIFICADA" else "retirar"),
                "reemplazo_gid": acc.reemplazo_gid if acc else None,
                "razon": (acc.razon if acc else "") or str(d.get("resolucion") or ""),
            }
        )
    return out


def _resultado(
    *,
    intercepcion_id: uuid.UUID,
    sesion_id: uuid.UUID,
    decision: str,
    respuesta_final: str | None,
    citas: list[dict],
    iteraciones: int,
    modelo_borrador: str,
    modelo_juez: str | None,
    commitment: dict | None,
    sample_mode: bool,
    texto_reparado: str | None = None,
) -> dict:
    payload = {
        "intercepcion_id": str(intercepcion_id),
        "sesion_id": str(sesion_id),
        "decision": decision,
        "respuesta_final": respuesta_final,
        "citas": citas,
        "iteraciones": iteraciones,
        "modelos": {"borrador": modelo_borrador, "juez": modelo_juez},
        "commitment_disponible": bool(commitment),
        "sample_mode": sample_mode,
    }
    if texto_reparado is not None:
        payload["texto_reparado"] = texto_reparado
    return payload


def run(
    *,
    entrada: str,
    escenario: str,
    modo: str,
    deps: Deps,
    sesion_id: uuid.UUID | None = None,
) -> dict:
    sample_mode = deps.sample_mode
    sid = sesion_id or deps.store.create_sesion(escenario=escenario, modo=modo)
    iid = uuid.uuid4()
    deps.store.create_intercepcion(
        intercepcion_id=iid,
        sesion_id=sid,
        entrada=entrada,
        borrador_original=entrada,
        decision="escalar",
        iteraciones=0,
        modelo_borrador="pendiente",
        modelo_juez=None,
        sample_mode=sample_mode,
    )
    tracer = Tracer(deps.store, iid)

    routed = router.route(texto=entrada, escenario=escenario, modo=modo, llm=deps.llm)
    tracer.emit(
        "router",
        routed.ruta,
        lane="FAST" if routed.llm else None,
        modelo=routed.llm.model if routed.llm else None,
        latencia_ms=routed.llm.latency_ms if routed.llm else 0,
        entrada=_clip(entrada),
        salida=routed.razon,
    )
    if routed.ruta == "abstener":
        final = (
            "Me abstengo. El corpus chile-base (25 cuerpos legales, "
            "pack_hash af1422d66d1e6eee) no cubre esta pregunta. "
            f"{routed.razon} Diké no evalúa si la norma respalda el argumento; "
            "eso es juicio del abogado."
        )
        deps.store.update_intercepcion(
            iid,
            borrador_original=entrada,
            respuesta_final=final,
            decision="abstener",
            iteraciones=0,
            modelo_borrador=routed.llm.model if routed.llm else "reglas",
            modelo_juez=None,
            commitment=None,
            sample_mode=sample_mode,
        )
        return _resultado(
            intercepcion_id=iid,
            sesion_id=sid,
            decision="abstener",
            respuesta_final=final,
            citas=[],
            iteraciones=0,
            modelo_borrador=routed.llm.model if routed.llm else "reglas",
            modelo_juez=None,
            commitment=None,
            sample_mode=sample_mode,
            texto_reparado=final if modo == "auditoria" else None,
        )

    recalled = deps.memory.recall("refutadas", entrada, k=5)
    evitar = [str(item.get("content") or "") for item in recalled if item.get("content")]
    if recalled:
        for item in recalled:
            meta = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            sid_rec = str(meta.get("sesion_id") or "").strip()
            phrase = f"recordado de la sesión {sid_rec}" if sid_rec else "recall"
            tracer.emit(
                "memory",
                phrase,
                entrada=_clip(entrada),
                salida=f"{phrase}: {_clip(str(item.get('content') or ''))}",
            )
    else:
        tracer.emit("memory", "recall", entrada=_clip(entrada), salida="k=0")

    modelo_borrador = "entrada"
    texto = entrada
    if modo != "auditoria":
        try:
            drafted = drafter.draft(
                pregunta=entrada, escenario=escenario, evitar=evitar, llm=deps.llm
            )
            texto = drafted.text
            modelo_borrador = drafted.model
            tracer.emit(
                "drafter",
                "borrador",
                lane="FAST",
                modelo=drafted.model,
                latencia_ms=drafted.latency_ms,
                entrada=_clip(entrada),
                salida=_clip(texto),
            )
        except LLMError as exc:
            tracer.emit("drafter", "error", lane="FAST", salida=str(exc)[:200])
            final = (
                "No se obtuvo borrador del Runtime. Se escala a revisión humana. "
                "SAMPLE_MODE no tiene caché para esta pregunta."
                if sample_mode
                else "No se obtuvo borrador del Runtime. Se escala a revisión humana."
            )
            deps.store.update_intercepcion(
                iid,
                borrador_original=entrada,
                respuesta_final=final,
                decision="escalar",
                iteraciones=0,
                modelo_borrador="error",
                modelo_juez=None,
                commitment=None,
                sample_mode=sample_mode,
            )
            return _resultado(
                intercepcion_id=iid,
                sesion_id=sid,
                decision="escalar",
                respuesta_final=final,
                citas=[],
                iteraciones=0,
                modelo_borrador="error",
                modelo_juez=None,
                commitment=None,
                sample_mode=sample_mode,
            )
    borrador_original = texto

    decision = "escalar"
    juicio = judge.Juicio(decision="escalar", razon="sin iteraciones")
    detalles: list[dict] = []
    fallos_acum: list[dict] = []
    modelo_juez: str | None = None
    iteraciones = 0
    fetch = deps.fetch_articulos or (lambda gids: [])
    mark = deps.markovian
    mk_run: str | None = None
    if mark is not None:
        started = mark.start(entrada, deps.max_iter)
        if started and started.get("run_id"):
            mk_run = str(started["run_id"])
            tracer.emit("markovian", "start", salida=f"run_id={mk_run} max={deps.max_iter}")

    for i in range(1, deps.max_iter + 1):
        iteraciones = i
        extracted, extract_llm = extract(texto, llm=None)
        tracer.emit(
            "extractor",
            f"n={len(extracted)}",
            lane="FAST" if extract_llm else None,
            modelo=extract_llm.model if extract_llm else None,
            latencia_ms=extract_llm.latency_ms if extract_llm else 0,
            salida=", ".join(c.normalized for c in extracted)[:400],
        )
        dike_result = deps.verificar(texto)
        detalles = [d for d in (dike_result.get("detalles") or []) if isinstance(d, dict)]
        fallos_acum.extend(d for d in detalles if d.get("estado") == "FALLO")
        tracer.emit(
            "dike",
            str(dike_result.get("veredicto") or ""),
            salida=_clip(str(dike_result.get("veredicto"))),
        )
        gids = [str(d["gid"]) for d in detalles if d.get("estado") == "VERIFICADA" and d.get("gid")]
        articulos = fetch(gids)
        juicio = judge.decide(
            texto=texto,
            detalles=detalles,
            articulos=articulos,
            iteracion=i,
            max_iter=deps.max_iter,
            llm=deps.llm,
        )
        modelo_juez = juicio.llm.model if juicio.llm else modelo_juez
        decision = juicio.decision
        tracer.emit(
            "judge",
            decision,
            lane="DEEP",
            modelo=juicio.llm.model if juicio.llm else None,
            latencia_ms=juicio.llm.latency_ms if juicio.llm else 0,
            salida=_clip(juicio.razon),
        )
        for item in _citas_payload(juicio, detalles):
            deps.store.add_cita(
                iid,
                CitaRow(
                    iteracion=i,
                    cita_raw=item["cita_raw"],
                    cita_normalizada=item["cita_raw"],
                    gid=item["gid"],
                    estado=item["estado"] or "FALLO",
                    resolucion=str(item["resolucion"] or ""),
                    vigencia=item["vigencia"],
                    accion=item["accion"],
                    reemplazo_gid=item["reemplazo_gid"],
                    razon=item["razon"] or "",
                ),
            )
        if mk_run and mark is not None:
            stepped = mark.step(
                mk_run,
                {
                    "iteracion": i,
                    "decision": decision,
                    "veredicto": str(dike_result.get("veredicto") or ""),
                    "texto": _clip(texto, 400),
                },
            )
            done = bool(stepped and stepped.get("done"))
            tracer.emit(
                "markovian",
                "step",
                salida=_clip(str((stepped or {}).get("state") or {"done": done})),
            )
            if done and decision == "reparar":
                decision = "escalar"
                juicio.razon = juicio.razon + " (Markovian: max_steps)"
        if decision in {"publicar", "abstener", "escalar"}:
            break
        if decision == "reparar":
            repaired = repairer.repair(
                texto=texto, detalles=detalles, articulos=articulos, llm=deps.llm
            )
            texto = repaired.text
            tracer.emit(
                "repairer",
                "reescritura",
                lane="DEEP",
                modelo=repaired.model,
                latencia_ms=repaired.latency_ms,
                salida=_clip(texto),
            )

    if decision == "publicar":
        leftover = [d for d in detalles if d.get("estado") == "FALLO"]
        if leftover or _has_fallos(texto, fallos_acum):
            texto = _strip_fallos(texto, fallos_acum) or _strip_fallos(texto, detalles)
            if leftover or _has_fallos(texto, fallos_acum):
                decision = "escalar"
                juicio.razon = juicio.razon + " (forzado: quedaban FALLO)"
    if decision == "escalar":
        kept = _strip_fallos(texto, fallos_acum or detalles)
        texto = (
            "Se agotó el límite de iteraciones o no se pudo publicar. "
            "Solo se muestra lo verificado por Diké.\n\n"
            f"{kept}\n\nRazón: {juicio.razon}"
        ).strip()
    elif decision == "abstener":
        texto = (
            "Me abstengo. El corpus no cubre de forma verificable esta pregunta. "
            f"{juicio.razon} Diké no evalúa si la norma respalda el argumento; "
            "eso es juicio del abogado."
        )

    if evitar:
        needles = _evitar_needles(evitar)
        stripped = _strip_needles(texto, needles)
        if stripped:
            texto = stripped
        elif _has_fallos(texto, fallos_acum) or any(n.lower() in texto.lower() for n in needles):
            decision = "escalar" if decision == "publicar" else decision
            texto = (
                "Se retiraron citas recordadas de sesiones anteriores. "
                "Se escala a revisión humana."
            )

    commitment = None
    verified = [d for d in detalles if d.get("estado") == "VERIFICADA"]
    if decision == "publicar" and verified and deps.emitir is not None:
        dest = ROOT / ".local" / "dike-home" / "commitments" / str(iid)
        try:
            commitment = deps.emitir(texto, dest)
        except Exception:
            commitment = None
        tracer.emit(
            "dike",
            "commitment" if commitment else "commitment_omitido",
            salida="ok" if commitment else "none",
        )

    seen_raw: set[str] = set()
    for d in fallos_acum:
        raw = str(d.get("cita_raw") or "").strip()
        if not raw or raw in seen_raw:
            continue
        seen_raw.add(raw)
        resol = str(d.get("resolucion") or "")
        deps.memory.remember(
            "refutadas",
            raw,
            {"sesion_id": str(sid), "resolucion": resol, "razon": resol},
        )
        deps.store.upsert_refutada(cita_normalizada=_normalize_cita(raw), razon=resol)

    deps.store.update_intercepcion(
        iid,
        borrador_original=borrador_original,
        respuesta_final=texto,
        decision=decision,
        iteraciones=iteraciones,
        modelo_borrador=modelo_borrador,
        modelo_juez=modelo_juez,
        commitment=commitment,
        sample_mode=sample_mode,
    )
    tracer.emit("loop", decision, salida=f"iter={iteraciones}")
    return _resultado(
        intercepcion_id=iid,
        sesion_id=sid,
        decision=decision,
        respuesta_final=texto,
        citas=_citas_payload(juicio, detalles),
        iteraciones=iteraciones,
        modelo_borrador=modelo_borrador,
        modelo_juez=modelo_juez,
        commitment=commitment,
        sample_mode=sample_mode,
        texto_reparado=texto if modo == "auditoria" else None,
    )
