"""Command: dike constancia <escrito> — verificación de citas para el socio.

La constancia es la VISTA LEGIBLE del gate CITABLE: un anexo que un socio
entiende en 30 segundos y puede adjuntar al escrito. No es un segundo
cálculo — es la misma verificación que ya corre en `analizar`, presentada
como un documento independiente.

Estructura:
  - Portada con hash del MANIFEST del pack (trazabilidad)
  - Una fila por cita detectada
  - Veredicto: TODAS_VERIFICADAS / CON_PROBLEMAS

`--emit-commitment DIR [--sign]` escribe además el commitment PUBLICABLE: solo
las normas verificadas, sin texto del escrito, sin ruta, sin `origen` y sin la
huella del escrito. Las citas que no se pudieron verificar no entran; queda su
número. Con `--sign` se firma con la llave de contenido.

Código de salida:
  0  todas las citas verificadas
  1  hay citas sin verificar (si se pidió, el commitment de las verificadas
     se escribe igual)
  2  se pidió un commitment y NO se pudo emitir. No queda ningún archivo:
     si la escritura falla o se interrumpe (disco lleno, Ctrl-C), se borra lo
     escrito, también el archivo que quedó a medias. Lo que esto no cubre es
     que el proceso muera sin poder limpiar (`kill -9`, un corte de energía).
"""
from __future__ import annotations

import hashlib
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from lexo_cli.agent_invoker import resolve_document
from lexo_cli.commands.useropt import add_user_flags, resolve_user, resolve_users_root
from lexo_cli.config import load_config
from lexo_cli.citation_check import (
    cited_article_numbers,
    citation_disclosure,
    citation_failure_reasons,
    verify_draft_citations,
)
from lexo_cli.documento import DocumentoIlegible
from lexo_cli.humanize import humanize_gid, vigencia_legible
from lexo_cli.nif_studio.execution import canonical_resolver_for
from lexo_cli.output import (
    console,
    output_error,
    output_info,
    output_json,
    output_success,
    output_warning,
)

#: Archivos que escribe `--emit-commitment`. Son los nombres que usa
#: `docs/hackathon/KEYS.md`: productor y documento no pueden discrepar.
COMMITMENT_FILE = "commitment.json"
SIGNATURE_FILE = "commitment.sig.json"
PUBKEY_FILE = "content-signing-key.pub"

#: Salida cuando se pidió un commitment y no se emitió.
EXIT_COMMITMENT_NO_EMITIDO = 2


def register(subparsers):
    p = subparsers.add_parser(
        "constancia",
        help="Genera una constancia de verificación de citas",
        description=(
            "Verifica las citas del escrito contra tu biblioteca de leyes "
            "y genera un anexo que puedes adjuntar. Es la misma verificación "
            "que ya corre en `dike analizar`, presentada como constancia."
        ),
    )
    add_user_flags(p)
    p.add_argument(
        "documento",
        help="Ruta del escrito (.txt, .md, .docx, .pdf) o texto pegado",
    )
    p.add_argument(
        "--as-of",
        dest="as_of",
        default=None,
        help="Fecha de referencia para vigencia (YYYY-MM-DD). Default: hoy.",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="Output JSON (para integración)",
    )
    p.add_argument(
        "--origen",
        default=None,
        help="Descripción del origen del documento (ej: 'demanda de Juan Pérez')",
    )
    p.add_argument(
        "--emit-commitment",
        dest="emit_commitment",
        metavar="DIR",
        default=None,
        help=(
            f"Escribe en DIR el commitment publicable ({COMMITMENT_FILE}): solo las "
            "normas verificadas, sin texto del escrito ni su huella. No sobrescribe."
        ),
    )
    p.add_argument(
        "--sign",
        action="store_true",
        dest="sign",
        help=(
            "Con --emit-commitment: firma el commitment con la llave de contenido "
            f"(LEXO_CONTENT_SIGNING_KEY_PATH) y escribe {SIGNATURE_FILE} y {PUBKEY_FILE}."
        ),
    )
    p.set_defaults(func=handle)


def _manifest_hash(cfg: dict, *, as_of: date | None = None) -> str:
    """Hash del MANIFEST del mismo snapshot y fecha usados por el resolver.

    Devuelve 16 hexadecimales, o una etiqueta que NO lo es cuando no hay un
    corpus que nombrar: `sin-corpus`, `sin-manifest`, `varios-corpus`. Con una
    etiqueta la constancia se puede mostrar, pero no sale ningún commitment:
    `validar_publicable` exige un `pack_hash` de 16 hexadecimales. Antes un
    fallo aquí terminaba en un commitment firmado que decía `sin-corpus`.
    """
    try:
        resolver, _ = canonical_resolver_for(cfg, as_of=as_of)
        if resolver is None:
            return "sin-corpus"
        corpora = list(resolver.binding().get("corpora") or [])
    except Exception:
        return "sin-corpus"
    if not corpora:
        return "sin-corpus"
    if len(corpora) > 1:
        # Un solo `pack_hash` no puede nombrar dos corpus, y el primero de la
        # lista no es «el» corpus contra el que se verificó.
        return "varios-corpus"
    unico = corpora[0]
    return str((unico.get("snapshot_hash") if isinstance(unico, dict) else None) or "sin-manifest")[:16]


def _format_fecha_iso(fecha: date | None = None) -> str:
    if fecha is None:
        fecha = date.today()
    return fecha.isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _archivos_commitment(directorio: Path, *, firmar: bool) -> list[Path]:
    nombres = [COMMITMENT_FILE] + ([SIGNATURE_FILE, PUBKEY_FILE] if firmar else [])
    return [directorio / n for n in nombres]


def _precheck_commitment(cfg: dict, directorio: Path, *, firmar: bool) -> str | None:
    """Lo que se puede saber ANTES de verificar nada. Devuelve el error o None.

    Mira los tres nombres aunque no se firme: un `commitment.json` nuevo junto
    a un `commitment.sig.json` viejo sería un par que no verifica.
    """
    if directorio.exists() and not directorio.is_dir():
        return f"--emit-commitment: {directorio} existe y no es una carpeta."
    ya = [p.name for p in _archivos_commitment(directorio, firmar=True) if p.exists() or p.is_symlink()]
    if ya:
        return (
            f"--emit-commitment: en {directorio} ya existe {', '.join(ya)}. "
            "No se sobrescribe un commitment: elige otra carpeta."
        )
    if firmar:
        from lexo_cli import content_signing as cs

        try:
            cs.comprobar_llave_de_contenido(cfg)
        except cs.ContentSigningError as exc:
            return str(exc)
    return None


def _emitir_commitment(result: dict, cfg: dict, directorio: Path, *, firmar: bool) -> bool:
    """Escribe el commitment publicable de `result`. True si quedó escrito.

    Todo se arma y se verifica en memoria antes de crear un solo archivo; si
    algo falla o se interrumpe al escribir, se borra lo escrito, también el
    archivo que quedó a medias. O queda el juego completo y verificado, o no
    queda nada (salvo que el proceso muera sin poder limpiar).
    """
    from lexo_cli import content_signing as cs
    from lexo_cli.commitment import (
        CommitmentIncoherenteError,
        CommitmentPIIError,
        commitment_de_constancia,
        compromiso_publico,
    )

    if result.get("veredicto") in ("SIN_CITAS", "SIN_CORPUS"):
        output_error(
            f"COMMITMENT_UNAVAILABLE: veredicto {result.get('veredicto')}. "
            "No se verificó ninguna cita: no hay nada que comprometer."
        )
        return False
    try:
        # Sin `documento`: la huella del escrito ni siquiera se calcula.
        publico = compromiso_publico(commitment_de_constancia(result))
    except (CommitmentPIIError, CommitmentIncoherenteError) as exc:
        output_error(f"COMMITMENT_UNAVAILABLE: {exc}")
        return False
    if not publico["normas_verificadas"]:
        output_error(
            "COMMITMENT_UNAVAILABLE: ninguna cita quedó verificada. Diké no emite "
            "un commitment que no acredita nada."
        )
        return False

    contenidos: dict[Path, bytes] = {
        directorio / COMMITMENT_FILE: (
            json.dumps(publico, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }
    sobre = None
    if firmar:
        try:
            ruta = cs.content_key_path(cfg)
            sobre = cs.firmar_commitment(publico, cfg=cfg, key_path=ruta)
            # La pubkey sale de la MISMA ruta con que se firmó.
            pub_pem = cs.content_public_pem(key_path=ruta)
        except cs.ContentSigningError as exc:
            output_error(str(exc))
            return False
        except (CommitmentPIIError, CommitmentIncoherenteError) as exc:
            # El firmador vuelve a validar lo que firma. Si discrepa de la
            # validación de arriba, no se firma: se dice y se sale.
            output_error(f"COMMITMENT_UNAVAILABLE: {exc}")
            return False
        contenidos[directorio / SIGNATURE_FILE] = (
            json.dumps(sobre.to_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        contenidos[directorio / PUBKEY_FILE] = pub_pem

    creado = not directorio.exists()
    escritos: list[Path] = []
    try:
        directorio.mkdir(parents=True, exist_ok=True)
        for ruta_archivo, datos in contenidos.items():
            # "xb": falla si el archivo apareció entre el precheck y ahora, y
            # no sigue un enlace simbólico que alguien haya dejado ahí.
            with open(ruta_archivo, "xb") as f:
                # Desde aquí el archivo es nuestro. Se anota ANTES de escribir:
                # si la escritura se corta, el que quedó a medias también se borra.
                escritos.append(ruta_archivo)
                f.write(datos)
        if firmar:
            # Se verifica lo que quedó EN DISCO, con los lectores estrictos.
            pubkey = cs.leer_clave_publica(directorio / PUBKEY_FILE)
            if cs.verificar_archivos(directorio / COMMITMENT_FILE, directorio / SIGNATURE_FILE, pubkey) is not True:
                raise cs.ContentSigningError("lo escrito no verifica contra su propia firma")
    except BaseException as exc:
        # BaseException: un Ctrl-C a mitad de la escritura dejaba un
        # commitment.json completo sin firma válida al lado.
        for ruta_archivo in escritos:
            ruta_archivo.unlink(missing_ok=True)
        if creado and directorio.is_dir() and not any(directorio.iterdir()):
            directorio.rmdir()
        if not isinstance(exc, (OSError, ValueError, cs.ContentSigningError)):
            raise  # la interrupción sigue su curso, pero sin dejar nada atrás
        output_error(f"COMMITMENT_UNAVAILABLE: no se pudo escribir el commitment ({exc}).")
        return False

    n = len(publico["normas_verificadas"])
    fuera = publico.get("citas_fallidas") or 0
    output_success(
        f"{COMMITMENT_FILE} escrito en {directorio}: {n} "
        f"{'cita verificada' if n == 1 else 'citas verificadas'}."
    )
    if fuera:
        output_info(
            f"  {fuera} {'cita no se pudo verificar y quedó' if fuera == 1 else 'citas no se pudieron verificar y quedaron'} "
            "fuera del commitment; solo viaja su número."
        )
    if sobre is not None:
        output_success(
            f"{SIGNATURE_FILE} y {PUBKEY_FILE}: firmado con la llave de contenido "
            f"{sobre.key_id}, rol {sobre.role}."
        )
    else:
        output_info("  Sin firma. Para firmarlo: --emit-commitment DIR --sign.")
    return True


def handle(args):
    cfg = load_config()

    # 0. Commitment: lo que se puede rechazar sin verificar nada, se rechaza ya.
    emitir_en = getattr(args, "emit_commitment", None)
    firmar = bool(getattr(args, "sign", False))
    if firmar and not emitir_en:
        output_error("--sign solo tiene sentido con --emit-commitment DIR.")
        return EXIT_COMMITMENT_NO_EMITIDO
    directorio = Path(emitir_en).expanduser() if emitir_en else None
    if directorio is not None:
        problema = _precheck_commitment(cfg, directorio, firmar=firmar)
        if problema:
            output_error(problema)
            return EXIT_COMMITMENT_NO_EMITIDO

    # 1. Leer documento
    try:
        doc_text = resolve_document(args.documento)
    except DocumentoIlegible as exc:
        output_error(str(exc))
        return 1

    # 2. Parsear as_of
    as_of = None
    if args.as_of:
        try:
            as_of = date.fromisoformat(args.as_of)
        except ValueError:
            output_error(f"Fecha inválida: '{args.as_of}'. Use YYYY-MM-DD.")
            return 1

    # 3. Resolver citas
    resolver, resolver_error = canonical_resolver_for(cfg, as_of=as_of)
    has_citations = bool(cited_article_numbers(doc_text))

    if not has_citations:
        # Sin citas: constancia positiva (nada que verificar)
        #
        # AUDITORÍA 2026-09-27. Antes esta ruta no declaraba nada y el
        # renderer cerraba con «No se requiere verificación adicional». Es el
        # punto ciego del P0 en su forma más legible: el socio lee esa frase,
        # adjunta el anexo y cree que el escrito fue revisado. `SIN_CITAS`
        # significa «la gramática no vio citas», no «no hay citas»; si el
        # texto mencionaba una norma sin pinpoint, la declaración lo nombra.
        check = verify_draft_citations(doc_text, [])
        result = {
            "veredicto": "SIN_CITAS",
            "mensaje": "El escrito no contiene citas normativas. Nada que verificar.",
            "detalles": [],
            "citation_disclosure": citation_disclosure(check, doc_text),
            "meta": {
                "documento": args.documento,
                "origen": args.origen,
                "as_of": _format_fecha_iso(as_of),
                "fecha_constancia": _now_iso(),
                "pack_hash": _manifest_hash(cfg, as_of=as_of),
            },
        }
        if args.as_json:
            output_json(result)
        else:
            _render_constancia_sin_citas(result, doc_text)
        if directorio is not None:
            _emitir_commitment(result, cfg, directorio, firmar=firmar)  # siempre se niega
            return EXIT_COMMITMENT_NO_EMITIDO
        return 0

    if resolver is None:
        # Sin corpus no se puede verificar
        #
        # No verificar nada también es un resultado, y se declara como tal:
        # el veredicto SIN_CORPUS no debe leerse como «no había nada que
        # verificar» sino como «no había con qué verificar».
        check = verify_draft_citations(doc_text, [])
        result = {
            "veredicto": "SIN_CORPUS",
            "mensaje": (
                f"No se pueden verificar las citas: {resolver_error}. "
                "El escrito contiene citas normativas pero no hay corpus "
                "canónico instalado para contrastarlas."
            ),
            "detalles": [],
            "citation_disclosure": citation_disclosure(check, doc_text),
            "meta": {
                "documento": args.documento,
                "origen": args.origen,
                "as_of": _format_fecha_iso(as_of),
                "fecha_constancia": _now_iso(),
                "pack_hash": "sin-corpus",
            },
        }
        if args.as_json:
            output_json(result)
        else:
            _render_constancia_sin_corpus(result, doc_text, resolver_error)
        if directorio is not None:
            _emitir_commitment(result, cfg, directorio, firmar=firmar)  # siempre se niega
            return EXIT_COMMITMENT_NO_EMITIDO
        return 1

    # 4. Verificar citas con resolver canónico
    from lexo_cli.commands.analizar import _resolve_canonical_sources, _citation_gate
    from lexo_cli.nif_studio.execution import execute_nif_plan

    # Construir un execution mínimo (sin NIF) para reutilizar la lógica
    class _EmptyExecution:
        evidence = []
        status = "completed"
        reasons = []
        finalization_allowed = True

    execution = _EmptyExecution()
    gate = _citation_gate(doc_text, resolver, resolver_error, execution, cfg)

    # 5. Construir resultado
    check = gate.get("citation_check", {})
    canonical_sources = gate.get("canonical_sources", [])

    detalles = []
    reasons = list(gate.get("citation_reasons", []))
    not_in_force = {str(gid) for gid in check.get("not_in_force", [])}
    temporal_uncertain = {str(gid) for gid in check.get("temporal_uncertain", [])}
    for ref in check.get("references", []):
        gid = ref.get("gid", "")
        raw = ref.get("raw", "")
        status = ref.get("status", "")
        supported = bool(ref.get("supported"))

        # Buscar evidencia canónica correspondiente.
        evidencia = next(
            (src for src in canonical_sources if src.get("gid") == gid),
            None,
        )
        source_url = evidencia.get("source_url", "") if evidencia else ""
        retrieved_at = evidencia.get("retrieved_at", "") if evidencia else ""
        historical_status = (
            evidencia.get("historical_text_status", "CURRENT_VERSION_APPLIES")
            if evidencia
            else "EVIDENCE_UNAVAILABLE"
        )
        verification_problem = ""
        if supported and not source_url:
            verification_problem = "PROVENANCE_INCOMPLETE"
            reasons.append(f"{raw}: la fuente oficial no registra URL verificable.")
        elif supported and not retrieved_at:
            verification_problem = "PROVENANCE_INCOMPLETE"
            reasons.append(f"{raw}: la fuente oficial no registra fecha de recuperación.")
        elif supported and gid in not_in_force:
            # La fuente se resolvió e identifica el artículo, pero su ventana
            # temporal lo excluye de la fecha de constancia. No puede contar
            # como cita verificada ni diluir el veredicto con los contadores.
            verification_problem = "NOT_IN_FORCE"
        elif supported and gid in temporal_uncertain:
            verification_problem = "TEMPORAL_UNKNOWN"
        elif supported and historical_status == "HISTORICAL_TEXT_UNAVAILABLE":
            verification_problem = "HISTORICAL_TEXT_UNAVAILABLE"
            reasons.append(
                f"{raw}: no hay texto histórico verificable para {_format_fecha_iso(as_of)}; "
                "no se certifica el texto consolidado actual como histórico."
            )

        detalle = {
            "cita_raw": raw,
            "gid": gid,
            "estado": "VERIFICADA" if supported and not verification_problem else "FALLO",
            "resolucion": verification_problem or status,
            "cuerpo": humanize_gid(gid) if gid else None,
            "texto_hash": evidencia.get("text_sha256") if evidencia else None,
            "vigencia": evidencia.get("temporal_status", "DESCONOCIDO") if evidencia else "DESCONOCIDO",
            "vigencia_legible": vigencia_legible(
                evidencia.get("temporal_status") if evidencia else None,
                None,
                evidencia.get("out_of_force_reason") if evidencia else None,
            ),
            "fuente_url": source_url,
            "fecha_recuperacion": retrieved_at,
            "estado_texto_historico": historical_status,
        }
        detalles.append(detalle)

    veredicto = (
        "TODAS_VERIFICADAS"
        if gate.get("analysis_status") == "CITATIONS_VERIFIED"
        and all(detalle["estado"] == "VERIFICADA" for detalle in detalles)
        else "CON_PROBLEMAS"
    )

    # AUDITORÍA 2026-09-27. `constancia` ya declaraba un `alcance`, pero era
    # un string fijo que no computaba los puntos ciegos del texto: la constancia
    # podía decir «todas verificadas» sin nombrar la mención de una ley que
    # el gate no cubrió. `citation_disclosure` se calcula sobre el TEXTO real,
    # no sobre la lista de detalles, para que herede los `no_verificados`.
    disclosure = citation_disclosure(check, doc_text)

    result = {
        "veredicto": veredicto,
        "mensaje": (
            "Todas las referencias normativas del escrito tienen fuente, integridad y vigencia verificables."
            if veredicto == "TODAS_VERIFICADAS"
            else "El escrito tiene citas que no se pudieron verificar de forma completa."
        ),
        "alcance": (
            "La constancia acredita identidad de la referencia, integridad del texto fuente, "
            "provenance y vigencia; no certifica la corrección de interpretaciones o paráfrasis."
        ),
        "citation_disclosure": disclosure,
        "problemas": reasons,
        "detalles": detalles,
        "meta": {
            "documento": args.documento,
            "origen": args.origen,
            "as_of": _format_fecha_iso(as_of),
            "fecha_constancia": _now_iso(),
            "pack_hash": _manifest_hash(cfg, as_of=as_of),
            "total_citas": len(detalles),
            "citas_verificadas": sum(1 for d in detalles if d["estado"] == "VERIFICADA"),
            "citas_fallidas": sum(1 for d in detalles if d["estado"] == "FALLO"),
        },
    }

    if args.as_json:
        output_json(result)
    else:
        _render_constancia(result, doc_text)

    if directorio is not None and not _emitir_commitment(result, cfg, directorio, firmar=firmar):
        return EXIT_COMMITMENT_NO_EMITIDO

    # Código de retorno: 0 si todas verificadas, 1 si hay problemas
    return 0 if veredicto == "TODAS_VERIFICADAS" else 1


def _imprime_declaracion(declaracion: dict | None):
    """Imprime la declaración de alcance de la verificación.

    Es el mismo bloque en las tres vistas: la constancia es lo que el socio
    lee y adjunta, así que el alcance y los puntos ciegos tienen que estar en
    la vista legible, no solo en el `--json`.

    Las advertencias las emite `citation_disclosure` —incluida la que nombra
    las menciones no verificadas—, así que aquí no se vuelven a listar: el
    texto es el mismo y duplicarlo solo alarga el anexo.
    """
    if not declaracion:
        return
    for advertencia in declaracion.get("advertencias") or []:
        console.print(f"[dim]{advertencia}[/dim]")
    if declaracion.get("alcance"):
        console.print(
            "[dim]Alcance verificado: "
            + "; ".join(declaracion["alcance"]) + ".[/dim]"
        )
    if declaracion.get("no_verificadas"):
        console.print(
            "[dim]Menciones no verificadas: "
            + ", ".join(declaracion["no_verificadas"]) + ".[/dim]"
        )
    console.print()


def _render_constancia(result: dict, doc_text: str):
    """Renderiza la constancia en formato legible (Rich)."""
    from rich.panel import Panel
    from rich.table import Table

    meta = result["meta"]
    veredicto = result["veredicto"]

    # Título con veredicto
    if veredicto == "TODAS_VERIFICADAS":
        titulo = "[bold green]✓ CONSTANCIA DE VERIFICACIÓN — TODAS LAS CITAS VERIFICADAS[/bold green]"
    else:
        titulo = "[bold red]✕ CONSTANCIA DE VERIFICACIÓN — CON PROBLEMAS[/bold red]"

    console.print(titulo)
    console.print(f"[dim]Documento: {meta['documento']}[/dim]")
    if meta.get("origen"):
        console.print(f"[dim]Origen: {meta['origen']}[/dim]")
    console.print(
        f"[dim]Fecha: {meta['fecha_constancia']} · "
        f"Pack: {meta['pack_hash']}[/dim]"
    )
    console.print()

    # Tabla de citas
    if result["detalles"]:
        table = Table(show_lines=False)
        table.add_column("Cita")
        table.add_column("Norma")
        table.add_column("Vigencia")
        table.add_column("Estado")

        for d in result["detalles"]:
            estado = (
                "[green]✓ Verificada[/green]"
                if d["estado"] == "VERIFICADA"
                else "[red]✕ Falló[/red]"
            )
            table.add_row(
                d["cita_raw"],
                d["cuerpo"] or "—",
                d["vigencia_legible"],
                estado,
            )
        console.print(table)
        console.print()

    # Resumen
    console.print(
        f"[bold]Resumen:[/bold] {meta['citas_verificadas']}/{meta['total_citas']} citas verificadas"
    )

    # Problemas
    if result.get("problemas"):
        console.print()
        console.print("[bold yellow]Problemas detectados:[/bold yellow]")
        for problema in result["problemas"]:
            console.print(f"  [yellow]• {problema}[/yellow]")

    console.print()
    # El mensaje de cierre refleja el veredicto real (no siempre "verificadas").
    # El texto honesto ya existe en el campo `alcance` del JSON.
    alcance = result.get("alcance", "")
    veredicto_msg = (
        "Todas las citas del escrito fueron verificadas contra el corpus "
        "canónico instalado. El hash del pack garantiza la trazabilidad de "
        "las fuentes utilizadas."
        if veredicto == "TODAS_VERIFICADAS"
        else "El escrito tiene citas que no se pudieron verificar de forma "
        "completa. Revise los problemas detectados antes de presentarlo."
    )
    console.print(f"[dim]{veredicto_msg}[/dim]")
    if alcance:
        console.print(f"[dim]{alcance}[/dim]")
    console.print()
    _imprime_declaracion(result.get("citation_disclosure"))


def _render_constancia_sin_citas(result: dict, doc_text: str):
    """Renderiza cuando no hay citas."""
    console.print("[bold blue]ℹ CONSTANCIA — SIN CITAS[/bold blue]")
    console.print(f"[dim]Documento: {result['meta']['documento']}[/dim]")
    console.print(f"[dim]Fecha: {result['meta']['fecha_constancia']}[/dim]")
    console.print()
    console.print("[dim]El escrito no contiene citas normativas detectables.[/dim]")
    # La frase anterior es sobre el DETECTOR, no sobre el escrito. Decirlo sin
    # más convertía la constancia en un aval de algo que nadie comprobó.
    console.print(
        "[dim]La verificación no detectó citas, pero eso no equivale a que "
        "el escrito no cite nada: el alcance real se declara abajo.[/dim]"
    )
    _imprime_declaracion(result.get("citation_disclosure"))


def _render_constancia_sin_corpus(result: dict, doc_text: str, error: str):
    """Renderiza cuando no hay corpus."""
    console.print("[bold red]✕ CONSTANCIA — SIN CORPUS[/bold red]")
    console.print(f"[dim]Documento: {result['meta']['documento']}[/dim]")
    console.print(f"[dim]Fecha: {result['meta']['fecha_constancia']}[/dim]")
    console.print()
    console.print(f"[yellow]No se pueden verificar las citas: {error}[/yellow]")
    console.print(
        "[yellow]El escrito contiene citas normativas pero no hay corpus "
        "canónico instalado para contrastarlas.[/yellow]"
    )
    _imprime_declaracion(result.get("citation_disclosure"))
