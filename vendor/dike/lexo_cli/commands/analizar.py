"""Command: lexo analizar — evalúa un documento jurídico existente."""

from __future__ import annotations

import os
import sys

from lexo_cli.agent_invoker import invoke_import_agent, resolve_document
from lexo_cli.config import load_config
from lexo_cli.grounding import gather_grounding_detailed
from lexo_cli.output import console, output_json, output_error, format_verdict
from lexo_cli.nif_studio.execution import evidence_text, execute_nif_plan


def _derive_plan(nif: dict | None, command: str = "analizar") -> dict | None:
    if not isinstance(nif, dict) or not nif:
        return None
    from lexo_cli.nif_studio.plan import resolve_plan
    return resolve_plan(nif, command=command).to_dict()


def _prepare_governed_document(
    doc_text: str,
    area: str,
    nif_override: dict | None,
    cfg: dict,
):
    """Separa el ARTEFACTO BAJO REVISIÓN del MATERIAL DE REFERENCIA.

    Antes, el contexto del NIF y la evidencia del plan se concatenaban al
    documento y el juez terminaba puntuando texto que el propio Diké había
    escrito: un escrito de cuatro líneas sin una sola cita pasaba de 2.5
    "Rechazado" a 8.8 "Aprobado" solo por el volumen inyectado. El documento
    que se evalúa es únicamente el del abogado.

    Devuelve (documento, contexto, execution, modo).
    """
    context_parts: list[str] = []
    nif_context = _nif_context_block(nif_override)
    if nif_context:
        context_parts.append(nif_context)
    if not isinstance(nif_override, dict) or not nif_override:
        return doc_text, "\n\n".join(context_parts), None, "legacy_no_nif"
    execution = execute_nif_plan(
        nif_override, command="analizar", cfg=cfg, area=area,
    )
    rendered = evidence_text(execution)
    if rendered:
        context_parts.append("EVIDENCIA EJECUTADA DEL PLAN\n" + rendered)
    return doc_text, "\n\n".join(context_parts), execution, "nif_plan"


# ---------------------------------------------------------------------------
# Gate canónico de verificación de citas (auditoría 2026-08-20 / Opus).
# El `analizar` verificaba la PROCEDENCIA del sobre pero nunca el TEXTO:
# un escrito podía citar un artículo inexistente, uno de OTRO cuerpo con el
# mismo número, o uno derogado, y el juez/contradictor lo puntuaban igual.
# Este gate corre ANTES de los agentes y abstiene fail-closed.
# ---------------------------------------------------------------------------
def _resolve_canonical_sources(
    doc_text: str,
    resolver,
    execution,
) -> tuple[list[dict], list[dict]]:
    """Evidencia canónica estructurada de las citas del documento.

    Para cada cita RESOLVED detectada con conocimiento de cuerpo
    (`extract_norm_references`) se serializa su evidencia canónica
    (`resolver.resolve(gid).to_dict()`). Se fusiona/deduplica (por GID) con la
    evidencia canónica ya presente en la ejecución completada del plan NIF.

    El grounding de la vault (texto de referencia) NUNCA cuenta como evidencia
    canónica: solo las resoluciones contra el corpus canónico indexado.

    Devuelve (canonical_sources, references):
      - canonical_sources: lista de dicts serializados (gid, eli, text,
        text_sha256, temporal_status, citation_status, ...).
      - references: resoluciones por cita (trazabilidad).
    """
    from lexo_cli.starter.norm_reference import extract_norm_references

    references = extract_norm_references(doc_text, resolver)

    # El plan puede contener resultados de índice o trabajo intermedio. La
    # certificación no reutiliza ese payload: resuelve cada GID contra el corpus
    # canónico en esta misma operación.
    canonical_sources: list[dict] = []
    seen_gids: set[str] = set()
    for ref in references:
        if ref.status != "RESOLVED" or not ref.gid:
            continue
        gid = ref.gid
        if gid in seen_gids:
            continue
        seen_gids.add(gid)
        try:
            evidence = resolver.resolve(gid)
            if hasattr(evidence, "to_dict"):
                canonical_sources.append(evidence.to_dict())
            else:
                canonical_sources.append({"gid": gid, **dict(evidence)})
        except Exception as exc:  # noqa: BLE001 — resolver.resolve puede fallar
            # P3-1: NO se anexa el gid. `verify_draft_citations` decide el
            # soporte por `gid in source_gid_set`, así que un `{gid}` desnudo
            # (o uno marcado) seguiría "soportado" y el gate lo aceptaría como
            # IN_FORCE. Omitirlo hace que la cita quede sin fuente resuelta y
            # verify abstenga fail-closed con motivo accionable.
            canonical_sources.append({
                "gid": gid,
                "citation_status": "UNRESOLVABLE",
                "temporal_status": "UNKNOWN",
                "resolve_error": str(exc),
                "_omit_from_verification": True,
            })

    return canonical_sources, references


def _citation_gate(
    doc_text: str,
    resolver,
    resolver_error: str,
    execution,
    cfg: dict,
) -> dict:
    """Gate fail-closed de verificación canónica de citas (antes de agentes).

    Se ejecuta ANTES de invocar juez/contradictor y SIEMPRE devuelve metadata
    estructurada — tanto en éxito como en fallo— para que un llamador pueda
    distinguir "citas verificadas" de "el gate nunca corrió".

    Resultados:
      * `analysis_status = "ABSTAIN_CITATION_CHECK"`: hay citas detectadas y la
        verificación falló (no soportadas, ambiguas, inexistentes, cuerpo
        equivocado, FUTURE/OUT_OF_FORCE, o resolver no disponible). El análisis
        se detiene: `abstain=true`, juez/contradictor NO deben invocarse.
      * `analysis_status = "CITATIONS_VERIFIED"`: hay citas y todas son
        exactamente soportadas e IN_FORCE. `citation_check.ok=true`, reasons
        vacío, `canonical_sources` presente, `abstain=false`.
      * `analysis_status = "NO_CITATIONS"`: no se detectaron citas. El gate no
        es obligatorio en esta capa; `abstain=false` y los agentes corren.
    """
    from lexo_cli.citation_check import (
        cited_article_numbers,
        citation_disclosure,
        citation_failure_reasons,
        verify_draft_citations,
    )

    base = {
        "analysis_status": "",
        "abstain": False,
        "citation_check": None,
        "citation_reasons": [],
        "canonical_sources": [],
        "resolver_error": resolver_error,
        "verified_count": 0,
    }

    if resolver is None:
        # Sin corpus canónico no hay contra qué verificar. Detectar citas de
        # forma ligera (token) para decidir si abstenerse.
        has_citations = bool(cited_article_numbers(doc_text))
        if not has_citations:
            base["analysis_status"] = "NO_CITATIONS"
            base["citation_check"] = verify_draft_citations(doc_text, [])
            # `NO_CITATIONS` no es «no hay nada»: es «la gramática no vio
            # nada». Si el texto citaba una norma que el detector no
            # reconoce, el estado afirma lo contrario y calla. La
            # declaración viaja con `verificadas` vacío y nombra las
            # menciones que nadie comprobó.
            base["citation_disclosure"] = citation_disclosure(
                base["citation_check"], doc_text,
            )
            return base
        reasons = [
            "Verificación canónica de citas no disponible: "
            f"{resolver_error or 'resolver canónico no configurado'}. "
            "El documento contiene citas normativas que no se pudieron "
            "verificar contra el corpus."
        ]
        base.update({
            "analysis_status": "ABSTAIN_CITATION_CHECK",
            "abstain": True,
            "citation_check": {
                "ok": False, "cited": [], "supported": [],
                "unsupported": [], "not_in_force": [],
                "references": [], "ambiguous": [],
            },
            "citation_reasons": reasons,
        })
        return base

    canonical_sources, _references = _resolve_canonical_sources(
        doc_text, resolver, execution,
    )
    # P3-1: las fuentes cuya resolución falló se marcan `_omit_from_verification`
    # y NO se pasan a verify: si se pasaran, su gid estaría en source_gid_set y
    # la cita parecería "soportada". Omitirlas hace que la cita quede sin fuente
    # resuelta y verify abstenga fail-closed.
    verification_sources = [
        item for item in canonical_sources
        if not item.get("_omit_from_verification")
    ]
    check = verify_draft_citations(
        doc_text, verification_sources, resolver=resolver,
    )

    # `verify_draft_citations` conserva un contrato legacy de comparación de
    # referencias. Pero esta ruta habilita un análisis jurídico que declara
    # citas verificadas: aquí no basta que el GID exista. Cada fuente exacta
    # debe ser a la vez citable y vigente positivamente acreditada.
    source_by_gid = {
        str(item.get("gid", "")): item
        for item in verification_sources
        if item and item.get("gid")
    }
    uncertifiable = []
    for detail in check.get("references", []):
        if detail.get("supported") is not True or not detail.get("gid"):
            continue
        source = source_by_gid.get(str(detail["gid"]))
        if source is None:
            continue
        if (
            source.get("citation_status") != "CITABLE"
            or source.get("temporal_status") != "IN_FORCE"
        ):
            uncertifiable.append(str(detail["gid"]))
    if uncertifiable:
        uncertifiable_set = set(uncertifiable)
        uncertifiable_tokens: set[str] = set()
        for index, detail in enumerate(check.get("references", [])):
            if str(detail.get("gid", "")) in uncertifiable_set:
                detail["supported"] = False
                cited = check.get("cited", [])
                if index < len(cited):
                    uncertifiable_tokens.add(str(cited[index]))
        check["supported"] = [
            token for token in check.get("supported", []) if str(token) not in uncertifiable_tokens
        ]
        check["ok"] = False
        check["uncertifiable"] = sorted(uncertifiable_set)

    # Sin citas detectadas: el gate no es obligatorio en esta capa.
    if not check.get("cited"):
        base["analysis_status"] = "NO_CITATIONS"
        base["citation_check"] = check
        # Misma razón que en la rama sin resolver: decir «no hay citas» sin
        # decir qué menciones-normas quedaron fuera del gate es el modo
        # residual del fallo P0.
        base["citation_disclosure"] = citation_disclosure(check, doc_text)
        return base

    if check.get("ok"):
        base.update({
            "analysis_status": "CITATIONS_VERIFIED",
            "citation_check": check,
            "citation_disclosure": citation_disclosure(check, doc_text),
            "canonical_sources": canonical_sources,
            "verified_count": len(check.get("supported", [])),
        })
        return base

    reasons = citation_failure_reasons(check)
    uncertifiable = check.get("uncertifiable") or []
    if uncertifiable:
        from lexo_cli.humanize import humanize_gid

        legibles = ", ".join(humanize_gid(gid) or gid for gid in uncertifiable)
        reasons.append(
            f"Diké no puede certificar la cita de: {legibles}. "
            "Su texto debe ser citable y su vigencia debe estar acreditada antes de analizarlo."
        )
    base.update({
        "analysis_status": "ABSTAIN_CITATION_CHECK",
        "abstain": True,
        "citation_check": check,
        "citation_reasons": reasons,
        # La abstención declara su alcance con la misma honestidad: no
        # acreditó ninguna cita, y decirlo forma parte del resultado.
        "citation_disclosure": citation_disclosure(check, doc_text),
        "canonical_sources": canonical_sources,
    })
    return base


def register(subparsers):
    p = subparsers.add_parser(
        "analizar",
        help="Analizar un documento jurídico",
        description="Evalúa un documento con el juez y el contradictor.",
    )
    p.add_argument("documento",
                   help="Ruta del escrito (.txt, .md, .docx, .pdf) o el texto pegado directamente")
    p.add_argument("--area", "-a", default=None, help="Área del derecho")
    p.add_argument("--json", action="store_true", dest="as_json", help="Output JSON")
    p.add_argument("--verbose", "-v", action="store_true", help="Output detallado")
    # 6.5 — explicar por qué se sugirió cada norma
    p.add_argument(
        "--explain", action="store_true", dest="explain",
        help="Explica por qué se sugirió cada norma (canal, score, evidencia)",
    )
    p.add_argument(
        "--llm",
        action="store_true",
        help="Usar LLM para análisis de mérito jurídico (requiere API key)",
    )
    p.add_argument(
        "--from-case",
        default=None,
        help="Cargar NIF desde un caso del NIF Studio (case_id) como contexto",
    )
    # 6.3 — compliance Ley 21.719: verifica el documento contra los
    # controles de la ley (depende del servidor ley21719 registrado).
    p.add_argument(
        "--compliance", default=None, choices=("ley21719",),
        help="Verifica el documento contra los controles de la Ley 21.719",
    )
    p.set_defaults(func=handle)


def handle(args):
    cfg = load_config()
    area = args.area or cfg.get("legal_area_default", "civil")

    # Read document (path or literal text — safe for long pasted documents)
    from lexo_cli.documento import DocumentoIlegible

    try:
        doc_text = resolve_document(args.documento)
    except DocumentoIlegible as exc:
        # Un documento ilegible tiene que detener el análisis. Seguir con la
        # ruta como texto produce un veredicto sobre un escrito inexistente.
        output_error(str(exc))
        return 1

    # Grounding: artículos REALES de la vault como material de referencia para
    # el LLM. Sin esto el LLM alucina números de artículo (verificado en
    # lexo-bench 2026-08-12: 2392/2405/2315... en vez de 1838/1857/1559).
    # NO se concatenan al documento: el juez debe puntuar el escrito del
    # abogado, no el texto que Diké acaba de inyectar.
    grounding = gather_grounding_detailed(doc_text, area=area, cfg=cfg)
    fuentes = grounding.text

    # 6.3 — compliance Ley 21.719: verifica el documento contra los controles
    # de la ley (depende del servidor ley21719 registrado como MCP).
    if getattr(args, "compliance", None) == "ley21719":
        try:
            from lexo_cli.mcp_compliance import verificar_compliance_ley21719

            compliance = verificar_compliance_ley21719(doc_text)
            if args.as_json:
                output_json(compliance)
                return 0
            console.print("[bold]Compliance Ley 21.719:[/bold]")
            for hallazgo in compliance.get("hallazgos", []):
                nivel = hallazgo.get("nivel", "info")
                marca = {"alto": "[red]", "medio": "[yellow]", "bajo": "[dim]"}.get(nivel, "[dim]")
                console.print(f"  {marca}{hallazgo.get('control', '?')}: {hallazgo.get('detalle', '')}[/]")
            console.print(f"[dim]{len(compliance.get('hallazgos', []))} hallazgos[/dim]")
        except Exception as exc:
            output_error(f"Compliance no disponible: {exc}")
            return 1

    if not args.as_json:
        if fuentes:
            console.print(
                f"[dim]✓ {len(fuentes)} caracteres de fuentes vigentes de la vault "
                "disponibles como referencia (no se evalúan como parte del escrito)[/dim]"
            )
        for warning in grounding.warnings:
            console.print(f"[yellow]⚠ Grounding: {warning}[/yellow]")

    nif_override = None

    if args.from_case:
        from lexo_cli.nif_studio import service

        snap = service.nif_snapshot(args.from_case)
        if not snap.get("exists"):
            output_error(f"El caso '{args.from_case}' no existe o no tiene NIF.")
            sys.exit(1)
        nif_override = snap["nif"]
        console.print(
            f"[green]✓[/green] NIF cargado desde caso '[bold]{args.from_case}[/bold]' (v{snap['version']})"
        )

    if args.as_json:
        result = _analyze_json(
            doc_text, area, nif_override=nif_override, cfg=cfg,
            sources=fuentes, use_llm=getattr(args, "llm", False),
        )
        output_json(result)
        return result.get("_exit_code", 0) if isinstance(result, dict) else 0
    else:
        return _analyze_text(
            doc_text, area, verbose=args.verbose, args=args,
            nif_override=nif_override, cfg=cfg, sources=fuentes,
        )


def _nif_context_block(nif_override: dict | None) -> str:
    """Contexto del NIF como MATERIAL DE REFERENCIA, nunca como parte del
    documento evaluado (ver `_prepare_governed_document`)."""
    if not nif_override:
        return ""

    facts = nif_override.get("facts", {}) if isinstance(nif_override, dict) else {}
    known = facts.get("known", []) if isinstance(facts, dict) else []
    alleged = facts.get("alleged", []) if isinstance(facts, dict) else []
    norms = nif_override.get("norms", []) if isinstance(nif_override, dict) else []
    subjects = nif_override.get("subjects", []) if isinstance(nif_override, dict) else []
    hypotheses = nif_override.get("hypotheses", []) if isinstance(nif_override, dict) else []

    parts = ["CONTEXTO NIF DEL STUDIO"]
    if nif_override.get("legal_question"):
        parts.append(f"Pregunta: {nif_override['legal_question']}")
    if known:
        parts.append("Hechos conocidos:")
        parts.extend(f"- {h}" for h in known[:10])
    if alleged:
        parts.append("Hechos alegados:")
        parts.extend(f"- {h}" for h in alleged[:10])
    if subjects:
        parts.append("Sujetos:")
        for s in subjects[:10]:
            parts.append(f"- {s.get('role', '?')}: {s.get('label', '?')}")
    if norms:
        parts.append("Normas:")
        for n in norms[:10]:
            parts.append(f"- {n.get('label', n.get('gid', '?'))}")
    if hypotheses:
        parts.append("Hipótesis:")
        for h in hypotheses[:10]:
            parts.append(f"- {h.get('claim', h.get('label', '?'))}")
    return "\n".join(parts)


def _analyze_text(doc_text: str, area: str, verbose: bool = False, args=None,
                  nif_override: dict | None = None, cfg: dict | None = None,
                  sources: str = ""):
    cfg = cfg if cfg is not None else load_config()
    try:
        doc_text, nif_context, execution, _ = _prepare_governed_document(
            doc_text, area, nif_override, cfg,
        )
    except Exception as exc:
        output_error(f"Error ejecutando plan NIF: {exc}")
        return 1
    if execution and execution.status != "completed":
        output_error("Análisis detenido: " + "; ".join(execution.reasons))
        return 1
    console.print(f"[bold]Analizando documento...[/bold] (área: {area})")

    # Gate canónico de verificación de citas ANTES de invocar agentes. Si el
    # documento no contiene ninguna cita, no se descubre/valida el starter: el
    # gate devuelve NO_CITATIONS sin tocar ~/.dike ni pagar el hash del corpus.
    from lexo_cli.citation_check import cited_article_numbers
    from lexo_cli.nif_studio.execution import canonical_resolver_for
    if cited_article_numbers(doc_text):
        resolver, resolver_error = canonical_resolver_for(cfg or {})
    else:
        resolver, resolver_error = None, ""
    gate = _citation_gate(doc_text, resolver, resolver_error, execution, cfg)
    if gate.get("abstain"):
        console.print(
            "\n[yellow]⚠ El análisis se detuvo: no pude verificar las citas del "
            "escrito contra tu biblioteca de leyes.[/yellow]"
        )
        for reason in gate["citation_reasons"]:
            console.print(f"  [yellow]• {reason}[/yellow]")
        console.print(
            "[bold]No se emitió veredicto estructural: las citas del escrito "
            "no se pudieron respaldar contra el corpus canónico.[/bold]"
        )
        return 1
    # Éxito: línea concisa de verificación ANTES del veredicto estructural.
    # P2-3: el gate valida existencia/citabilidad/vigencia de los GIDs citados,
    # no respaldo argumentativo independiente — las fuentes se resuelven desde
    # las propias citas. La copy no debe sobre-vender "soporte independiente".
    if gate.get("analysis_status") == "CITATIONS_VERIFIED":
        console.print(
            f"[dim]✓ {gate.get('verified_count', 0)} cita(s) verificadas contra tu "
            "biblioteca: existen, se pueden citar y están vigentes.[/dim]"
        )
    elif gate.get("analysis_status") == "NO_CITATIONS":
        console.print(
            "[dim]✓ El escrito no cita normas: no hay nada que verificar.[/dim]"
        )

    # Juez evaluation
    try:
        juez_result = invoke_import_agent(
            "juez", "evaluate_document",
            document_text=doc_text,
            legal_area=area,
            caso_id="cli-analizar",
            cases_root=os.environ.get("LEXO_CASES_ROOT") or None,
        )
        verdict_label = (
            "Análisis provisional — Requiere HITL-4"
            if execution and not execution.finalization_allowed
            else "Veredicto del Juez"
        )
        console.print(
            f"\n[bold]{verdict_label}:[/bold] {format_verdict(juez_result.get('verdict', '?'), juez_result.get('rating'))}"
        )
        if juez_result.get("weak_points"):
            console.print("\n[bold]Puntos débiles:[/bold]")
            for wp in juez_result["weak_points"][:10]:
                console.print(f"  • {wp}")
    except Exception as exc:
        output_error(f"Error en evaluación del juez: {exc}")
        juez_result = None

    # Contradictor — adversarial analysis
    try:
        contra_result = invoke_import_agent(
            "contradictor", "contradict",
            document_text=doc_text,
            legal_area=area,
            caso_id="cli-analizar",
            cases_root=os.environ.get("LEXO_CASES_ROOT") or None,
        )
        total_obj = (
            len(contra_result.get("objeciones_procesales", [])) +
            len(contra_result.get("objeciones_sustantivas", [])) +
            len(contra_result.get("objeciones_logicas", [])) +
            len(contra_result.get("objeciones_probatorias", []))
        )
        counter_docs = len(contra_result.get("counter_evidence", []))
        vuln = contra_result.get("overall_vulnerability_score", 0)
        rec = contra_result.get("recommendation", "")

        if total_obj > 0 or counter_docs > 0:
            console.print(
                f"\n[bold]Contradictor:[/bold] {total_obj} objeciones, {counter_docs} contras en vault, vulnerabilidad {vuln}/10"
            )
            if rec:
                console.print(f"  [italic]{rec}[/italic]")
            all_obj = (
                contra_result.get("objeciones_procesales", []) +
                contra_result.get("objeciones_sustantivas", []) +
                contra_result.get("objeciones_logicas", []) +
                contra_result.get("objeciones_probatorias", [])
            )
            for obj in all_obj[:5]:
                sev = obj.get("severity", "baja")
                icon = {"critica": "🔥", "alta": "⚠", "moderada": "•", "baja": "·"}.get(sev, "•")
                console.print(f"  {icon} [{sev}] {obj.get('detail', '?')[:120]}")
        else:
            console.print(
                f"\n[dim]Contradictor: sin objeciones detectadas (vulnerabilidad {vuln}/10). El contradictor revisa la estructura del escrito, no el fondo del argumento.[/dim]"
            )
    except Exception as exc:
        output_error(f"Error en contradictor: {exc}")
        contra_result = None

    # 6. Merit assessment (only with --llm and API key)
    merit_result = None
    if args and args.llm:
        try:
            from subagents.juez.scripts.merit_assessor import assess_legal_merit
            merit_result = assess_legal_merit(
                document_text=doc_text,
                # Con nif=None el validador anti-alucinación no tenía contra qué
                # anclar y marcaba como "anchored" cualquier cita.
                nif=nif_override,
                legal_area=area,
                reference_sources="\n\n".join(
                    part for part in [nif_context, sources] if part
                ),
            )
            if merit_result.get("measurable"):
                merit_outcome = merit_result.get("outcome", "?")
                merit_conf = merit_result.get("confidence", 0)
                merit_anchored = merit_result.get("anchored", False)
                anchored_tag = "" if merit_anchored else " [sin respaldo en tu biblioteca]"
                console.print(
                    f"\n[bold green]Opinión de mérito (LLM):[/bold green] {merit_outcome}{anchored_tag} (confianza: {merit_conf:.0%})"
                )
                if merit_result.get("reasoning"):
                    console.print(f"  [dim]{merit_result['reasoning'][:300]}[/dim]")
                if not merit_anchored:
                    console.print(
                        f"  [yellow]⚠ Citas no ancladas: {', '.join(merit_result.get('unanchored_citations', [])[:5])}[/yellow]"
                    )
            else:
                console.print(
                    f"\n[dim]Opinión de mérito (LLM): no disponible ({merit_result.get('reason', 'sin API key')})[/dim]"
                )
        except Exception as exc:
            if verbose:
                console.print(f"  [dim]Merit assessment skipped: {exc}[/dim]")

    # Análisis completo: éxito.
    return 0


def _analyze_json(
    doc_text: str,
    area: str,
    nif_override: dict | None = None,
    cfg: dict | None = None,
    sources: str = "",
    use_llm: bool = False,
) -> dict:
    cfg = cfg if cfg is not None else load_config()
    result = {
        "area": area,
        "juez": None,
        "contradictor": None,
        "plan": None,
        "execution": None,
        "execution_mode": None,
        "opinion_status": None,
        "merito": None,
    }
    try:
        doc_text, nif_context, execution, execution_mode = _prepare_governed_document(
            doc_text, area, nif_override, cfg,
        )
        result["execution_mode"] = execution_mode
        if execution:
            result["plan"] = execution.plan
            result["execution"] = execution.to_dict()
            result["opinion_status"] = (
                "PROVISIONAL_REQUIRES_HITL_4"
                if not execution.finalization_allowed
                else "ANALYSIS_ONLY"
            )
            if execution.status != "completed":
                # El plan no se completó: abstención. `_exit_code` 1 para que el
                # llamador distinga "análisis detenido" de "análisis completado".
                result["_exit_code"] = 1
                return result
    except Exception as exc:
        result["execution_mode"] = "nif_plan"
        result["execution"] = {
            "status": "failed", "steps": [], "evidence": [], "reasons": [str(exc)],
        }
        result["error_execution"] = str(exc)
        # Excepción durante la preparación del documento gobernado: abstención.
        result["_exit_code"] = 1
        return result
    # Gate canónico de verificación de citas ANTES de invocar agentes. Si el
    # documento no contiene ninguna cita, no se descubre/valida el starter: el
    # gate devuelve NO_CITATIONS sin tocar ~/.dike ni pagar el hash del corpus.
    from lexo_cli.citation_check import cited_article_numbers
    from lexo_cli.nif_studio.execution import canonical_resolver_for
    if cited_article_numbers(doc_text):
        resolver, resolver_error = canonical_resolver_for(cfg or {})
    else:
        resolver, resolver_error = None, ""
    gate = _citation_gate(doc_text, resolver, resolver_error, execution, cfg)
    # Se expone la metadata del gate (estado, citation_check, reasons,
    # canonical_sources) SIEMPRE —éxito o fallo— para que el llamador distinga
    # "citas verificadas" de "el gate nunca corrió". El flag interno `abstain`
    # solo se conserva en la abstención; en éxito no debe filtrarse.
    gate_status = gate.get("analysis_status")
    if gate.get("abstain"):
        result.update(gate)
        # P2-2: nunca dejar ANALYSIS_ONLY/PROVISIONAL junto a la abstención por
        # citas: el estado de opinión debe reflejar que el análisis se detuvo.
        result["opinion_status"] = "ABSTAINED_CITATION_CHECK"
        # Gate de citas fallido: abstención. `_exit_code` 1.
        result["_exit_code"] = 1
        return result
    result["analysis_status"] = gate_status
    result["citation_check"] = gate.get("citation_check")
    result["citation_reasons"] = gate.get("citation_reasons", [])
    result["canonical_sources"] = gate.get("canonical_sources", [])
    result["verified_count"] = gate.get("verified_count", 0)
    # P2-3: el gate prueba existencia/citabilidad/vigencia de los GIDs citados,
    # NO respaldo argumentativo independiente (las fuentes se resuelven desde
    # las propias citas). Se declara el alcance para no sobre-vender.
    result["citation_validation_scope"] = "existence_citability_temporal"
    try:
        result["juez"] = invoke_import_agent(
            "juez", "evaluate_document",
            document_text=doc_text, legal_area=area, caso_id="cli-analizar",
        )
    except Exception as exc:
        result["error_juez"] = str(exc)
    try:
        result["contradictor"] = invoke_import_agent(
            "contradictor", "contradict",
            document_text=doc_text, legal_area=area, caso_id="cli-analizar",
        )
    except Exception as exc:
        result["error_contradictor"] = str(exc)
    # --json ignoraba --llm en silencio: pedir la opinión de mérito y no
    # recibirla, sin aviso, es peor que no ofrecer la opción.
    if use_llm:
        try:
            from subagents.juez.scripts.merit_assessor import assess_legal_merit
            result["merito"] = assess_legal_merit(
                document_text=doc_text,
                nif=nif_override,
                legal_area=area,
                reference_sources="\n\n".join(
                    part for part in [nif_context, sources] if part
                ),
            )
        except Exception as exc:
            result["error_merito"] = str(exc)
    # Análisis completo (exitoso). `_exit_code` 0 para que el llamador
    # pueda distinguir éxito de abstención.
    result["_exit_code"] = 0
    return result
