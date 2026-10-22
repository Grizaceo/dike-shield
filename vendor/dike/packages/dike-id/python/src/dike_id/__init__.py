"""dike-id: identificadores GID v2 de Diké (especificación 2.0.0).

La gramática es `spec/dike-id.abnf`; el regex y la gramática serializada de `_generated/` salen
de ella. Esta biblioteca y la de TypeScript (`ts/`) pasan la misma suite y la prueba
diferencial compara sus AST.

- `sintaxis_ok(s)`: la cadena pertenece al lenguaje (consumo total, largo ≤ 256).
- `parse(s)`: cadena canónica → AST de identidad (dict). Falla si hay dos derivaciones.
- `render(ast)`: AST → cadena canónica. `render(parse(x)) == x` para toda x válida.
- `violaciones(s, slugs=…, tribunales=…)`: reglas semánticas (spec/semantics.md) que el
  regex no expresa. Sin registros, solo se revisan las reglas que no dependen de ellos.
- `etiqueta_articulo(...)`: identidad de artículo → etiqueta v2.
- `desde_legado(...)`: dialectos heredados (v1, runtime) → hipótesis v2 con su clase de
  migración. Nunca decide con el id solo lo que exige evidencia.

Formato no es identidad: un GID bien formado no acredita existencia, vigencia ni
aplicabilidad. Eso lo deciden los registros y la revisión humana.
"""
from __future__ import annotations

import datetime as _dt
import re

from ._generated.regex import GRAMMAR_SHA256, MAX_LENGTH, SPEC_VERSION, full_match
from ._parser import PARSER

__all__ = ["SPEC_VERSION", "GRAMMAR_SHA256", "MAX_LENGTH", "LATINOS", "ErrorGID", "sintaxis_ok", "parse",
           "render", "violaciones", "es_valido", "etiqueta_articulo", "leer_etiqueta_legada", "desde_legado"]

LATINOS = ("bis", "ter", "quater", "quinquies", "sexies", "septies", "octies", "nonies", "decies",
           "undecies", "duodecies", "terdecies", "quaterdecies", "quindecies")
ENIE = "enie"                     # S19, decisión T: la Ñ se escribe «enie»; el AST guarda «ñ»
_ESPECIALES = ("prelim", "unico", "final", "trans")


class ErrorGID(ValueError):
    pass


# ── Sintaxis ────────────────────────────────────────────────────────────────
def sintaxis_ok(s: object) -> bool:
    """Pertenencia al lenguaje. Nunca confiar solo en `^…$`: Python acepta un \\n final."""
    return full_match(s) is not None


# ── parse: cadena → AST de identidad ────────────────────────────────────────
def _letra(tok: str) -> str:
    return "ñ" if tok == ENIE else tok


def _sufijos(nodo, s) -> list:
    out: list = []
    for t in nodo.todos("suffix-tok"):
        v = t.texto(s)
        out.append(int(v) if t.hijo("subnum") is not None else _letra(v))
    return out


def _etiqueta(nodo, s) -> dict:
    """art-label o hier-label → {"especial": x} | {"num": n, "suf": [...]} | {"letra": x}."""
    p4 = nodo.buscar("positive-4")
    if p4 is not None:
        suf = nodo.buscar("suffixes")
        return {"num": int(p4.texto(s)), "suf": _sufijos(suf, s) if suf is not None else []}
    le = nodo.hijo("letter")
    if le is not None:
        return {"letra": _letra(le.texto(s))}
    return {"especial": nodo.texto(s)}


def _x(nodo, s):
    d = nodo.hijo("disambig")
    return d.hijo("local-key").texto(s) if d is not None else None


def parse(s: str) -> dict:
    if not sintaxis_ok(s):
        raise ErrorGID("SINTAXIS")
    ders = PARSER.derivaciones(s, limite=2)
    if len(ders) != 1:
        raise ErrorGID("AMBIGUEDAD")     # dos derivaciones: la gramática no es inequívoca aquí
    raiz = ders[0]
    n = raiz.hijo("norm-id")
    if n is not None:
        ast = {"kind": "norm", "slug": n.buscar("norm-slug").texto(s), "ver": None, "unit": None}
        v = n.buscar("norm-ver-date")
        if v is not None:
            ast["ver"] = v.texto(s)
        u = n.hijo("norm-unit")
        if u is not None:
            ast["unit"] = _unidad(u, s)
        return ast
    j = raiz.hijo("judgment-id")
    ast = {"kind": "judgment", "court": j.hijo("court-slug").texto(s), "year": int(j.hijo("jud-year").texto(s)),
           "rol_tipo": None, "num": None, "x": _x(j, s), "par": None}
    k = j.hijo("jud-key")
    ast["rol_tipo"], ast["num"] = k.hijo("rol-tipo").texto(s), int(k.hijo("jud-num").texto(s))
    p = j.hijo("jud-par")
    if p is not None:
        ast["par"] = {"ord": int(p.hijo("small-ord").texto(s)), "x": _x(p, s)}
    return ast


def _unidad(u, s) -> dict:
    a = u.hijo("article-path")
    if a is not None:
        seg = a.hijo("article-seg")
        cls = seg.hijo("art-class")
        out = {"type": "art", "label": _etiqueta(seg.hijo("art-label"), s),
               "class": cls.texto(s) if cls is not None else None, "x": _x(seg, s),
               "inc": None, "num": None, "lit": None}
        inc = a.hijo("inc-seg")
        if inc is not None:
            out["inc"] = {"ord": int(inc.hijo("small-ord").texto(s)), "x": _x(inc, s)}
        num = a.hijo("num-seg")
        if num is not None:
            lat = num.hijo("latin")
            out["num"] = {"ord": int(num.hijo("small-ord").texto(s)), "lat": lat.texto(s) if lat else None,
                          "x": _x(num, s)}
        lit = a.hijo("lit-seg")
        if lit is not None:
            lat = lit.hijo("latin")
            out["lit"] = {"letra": _letra(lit.hijo("letter").texto(s)), "lat": lat.texto(s) if lat else None,
                          "x": _x(lit, s)}
        return out
    h = u.hijo("hierarchy-path")
    if h is not None:
        return {"type": "hier", "path": [{"t": x.hijo("hier-type").texto(s),
                                          "label": _etiqueta(x.hijo("hier-label"), s), "x": _x(x, s)}
                                         for x in h.todos("hier-seg")]}
    un = u.hijo("unnumbered")
    if un is not None:
        return {"type": "unn", "kind": un.hijo("unn-kind").texto(s), "key": un.hijo("local-key").texto(s)}
    ur = u.hijo("unresolved")
    return {"type": "unres", "key": ur.hijo("local-key").texto(s)}


# ── render: AST → cadena canónica ───────────────────────────────────────────
def _tok(t) -> str:
    if isinstance(t, int):
        return str(t)
    return ENIE if t == "ñ" else t


def _render_etiqueta(lab: dict) -> str:
    if "especial" in lab:
        return lab["especial"]
    if "letra" in lab:
        return _tok(lab["letra"])
    return f"{lab['num']:04d}" + "".join("_" + _tok(t) for t in lab.get("suf", []))


def _rx(d: dict) -> str:
    return f":x:{d['x']}" if d.get("x") else ""


def render(ast: dict) -> str:
    """AST → cadena canónica; falla si el resultado no pertenece al lenguaje."""
    if ast["kind"] == "judgment":
        s = f"cl.v2.sentencia.{ast['court']}.{ast['year']:04d}.{ast['rol_tipo']}_{ast['num']}" + _rx(ast)
        if ast.get("par"):
            s += f":par:{ast['par']['ord']:02d}" + _rx(ast["par"])
    else:
        s = f"cl.v2.norma.{ast['slug']}"
        if ast.get("ver"):
            s += f":ver:{ast['ver']}"
        u = ast.get("unit")
        if u:
            if u["type"] == "art":
                s += ":art:" + _render_etiqueta(u["label"])
                if u.get("class"):
                    s += ":" + u["class"]
                s += _rx(u)
                if u.get("inc"):
                    s += f":inc:{u['inc']['ord']:02d}" + _rx(u["inc"])
                if u.get("num"):
                    s += f":num:{u['num']['ord']:02d}" + (f"_{u['num']['lat']}" if u["num"].get("lat") else "")
                    s += _rx(u["num"])
                if u.get("lit"):
                    s += f":lit:{_tok(u['lit']['letra'])}" + (f"_{u['lit']['lat']}" if u["lit"].get("lat") else "")
                    s += _rx(u["lit"])
            elif u["type"] == "hier":
                s += ":" + ":".join(f"{p['t']}:{_render_etiqueta(p['label'])}" + _rx(p) for p in u["path"])
            elif u["type"] == "unn":
                s += f":unn:{u['kind']}:{u['key']}"
            else:
                s += f":unres:{u['key']}"
    if not sintaxis_ok(s):
        raise ErrorGID("RENDER: el AST no produce un GID válido")
    return s


# ── Reglas semánticas (spec/semantics.md) ───────────────────────────────────
def _fecha_ok(d8: str) -> bool:
    try:
        _dt.date(int(d8[:4]), int(d8[4:6]), int(d8[6:]))
        return True
    except ValueError:
        return False


def _clase_tok(t) -> str:
    return "num" if isinstance(t, int) else ("lat" if t in LATINOS else "letra")


def _s15(lab: dict) -> list[str]:
    clases = [_clase_tok(t) for t in lab.get("suf", [])]
    out = []
    if any(a == b for a, b in zip(clases, clases[1:])):
        out.append("S15: dos tokens contiguos de la misma clase")
    if clases.count("num") > 1:
        out.append("S15: más de un subnúmero")
    return out


def violaciones(s: str, slugs=None, tribunales=None) -> list[str]:
    """Reglas violadas por una cadena. `slugs`: slugs canónicos registrados (S2).
    `tribunales`: {court_slug: {rol_tipo, …}} (S26). Si falta un registro, su regla no se revisa."""
    try:
        ast = parse(s)
    except ErrorGID as e:
        return [str(e)]
    out = []
    if ast["kind"] == "norm" and ast["ver"] and not _fecha_ok(ast["ver"]):
        out.append("S1: fecha inexistente")
    if ast["kind"] == "judgment":
        if tribunales is not None:
            if ast["court"] not in tribunales:
                out.append("S26: tribunal no registrado")
            elif ast["rol_tipo"] not in tribunales[ast["court"]]:
                out.append("S26: tipo de rol no registrado para el tribunal")
        return out
    if slugs is not None and ast["slug"] not in slugs:
        out.append("S2: slug no registrado")
    u = ast.get("unit") or {}
    if u.get("type") == "art":
        out += _s15(u["label"])
        if u["label"].get("especial") == "final" and u.get("class") == "final":
            out.append("S8b: final:final")
    elif u.get("type") == "hier":
        for p in u["path"]:
            out += _s15(p["label"])
        if any(p["t"] == "lib" for p in u["path"][1:]):
            out.append("S16a: lib solo puede ir primero")
    return out


def es_valido(s: str, slugs=None, tribunales=None) -> bool:
    return sintaxis_ok(s) and not violaciones(s, slugs, tribunales)


# ── Identidad de artículo → etiqueta v2 ─────────────────────────────────────
def etiqueta_articulo(numero: int | None, sufijos=(), transitorio=False, unico=False) -> str:
    lab = "unico" if unico else f"{numero:04d}" + "".join("_" + _tok(t) for t in sufijos)
    return "art:" + lab + (":trans" if transitorio else "")


# ── Dialectos heredados → v2 ────────────────────────────────────────────────
# Solo ASCII (`\d` de Python acepta dígitos Unicode y el de ECMAScript no) y enteros acotados
# (los de ECMAScript pierden precisión sobre 2^53): así la biblioteca TS da lo mismo.
_LEG = re.compile(r"cl\.norma\.(?P<slug>[^:]+)(?::art:(?P<lab>[^:]+))?(?P<resto>:.*)?")
_RUNTIME = re.compile(r"(?P<t>t_)?(?P<n>[0-9]{4})(?P<suf>(?:_[a-zñ]+)*)")
_SIN_RELLENO = re.compile(r"[0-9]{1,3}(?:_[a-zñ]+)*")
_POLICY = re.compile(r"(?P<n>[0-9]{4,9})(?P<lat>bis|ter|quater|quinquies|sexies|septies|octies)?")
_TRUNCADO = re.compile(r"[0-9]{4}(qua|qui|sex|sep|oct)")
_SEG = re.compile(r":([a-z]+):([^:]+)|:([0-9a-f]{7})(?=:|$)")
_ENTERO = re.compile(r"[0-9]{1,4}")
_FECHA8 = re.compile(r"[0-9]{8}")
_PROHIBIDOS = ("\r", "\n", " ", " ", "\x00")
CLAVE_PENDIENTE = "<clave-minteada>"


def leer_etiqueta_legada(lab: str):
    """→ ((numero, sufijos, transitorio, dialecto), None) o (None, motivo)."""
    m = _RUNTIME.fullmatch(lab)
    if not m and _SIN_RELLENO.fullmatch(lab):
        cabeza, _, cola = lab.partition("_")
        m = _RUNTIME.fullmatch(cabeza.zfill(4) + ("_" + cola if cola else ""))
    if m:
        n = int(m.group("n"))
        if n == 0:
            return None, "art_0000"
        suf = tuple({"novies": "nonies"}.get(p, p) for p in m.group("suf").split("_") if p)
        return (n, suf, bool(m.group("t")), "runtime"), None
    m = _POLICY.fullmatch(lab)
    if m:
        n = int(m.group("n"))
        if n == 0:
            return None, "art_0000"
        return (n, (m.group("lat"),) if m.group("lat") else (), False, "policy_v1"), None
    if _TRUNCADO.fullmatch(lab):
        return None, "sufijo_v1_truncado"
    return None, "ilegible"


def _representable(v2: str) -> bool:
    return sintaxis_ok(v2.replace(CLAVE_PENDIENTE, "uaaaaaaaaaa"))


def desde_legado(gid: str, alias_slug: dict | None = None, identidad=None) -> dict:
    """Un GID heredado (y, si la hay, la identidad verificada de su unidad) → hipótesis v2.

    `identidad` = (numero, sufijos, transitorio, unico) derivada de EVIDENCIA (encabezado o
    estructura de la fuente). Sin evidencia, un sufijo de letra final no se da por bueno si el
    dialecto no lo distingue de un artefacto: se marca `requiere_evidencia`.

    Devuelve {clase, v2, motivo, requiere_evidencia} con clase ∈ {igual, cambia, ambiguo, unres,
    chunk, no_representable, invalido}. La clase `split` se decide por almacén (un id legado →
    varias identidades v2), no aquí.
    """
    def r(clase, v2, motivo, req=False):
        return {"clase": clase, "v2": v2, "motivo": motivo, "requiere_evidencia": req}

    if not isinstance(gid, str) or len(gid) > 1024 or any(c in gid for c in _PROHIBIDOS):
        return r("invalido", None, "no es cl.norma.*")
    m = _LEG.fullmatch(gid)
    if not m:
        return r("invalido", None, "no es cl.norma.*")
    slug = (alias_slug or {}).get(m.group("slug"), m.group("slug"))
    raiz = f"cl.v2.norma.{slug}"
    cola, resto = "", m.group("resto") or ""
    notas: list[str] = []
    segs = _SEG.findall(resto)
    if resto and "".join(f":{a}:{b}" if a else f":{h}" for a, b, h in segs) != resto:
        return r("ambiguo", None, f"subunidad heredada «{resto}» sin regla")
    for a, b, h in segs:
        if h:                                   # desambiguador v1 = hash de 7 del contenido (S12)
            cola += f":x:{CLAVE_PENDIENTE}"
            notas.append("hash v1 → clave minteada")
        elif a == "ver" and _FECHA8.fullmatch(b):
            raiz += f":ver:{b}"                 # la versión pasa tras la raíz (expresión)
            notas.append("ver tras la raíz")
        elif a == "inc" and _ENTERO.fullmatch(b) and int(b) > 0:
            cola += f":inc:{int(b):02d}"
            if b != f"{int(b):02d}":
                notas.append("inc sin relleno")
        elif a == "chunk" and _ENTERO.fullmatch(b):
            return r("chunk", None, "S24: un chunk no es identidad jurídica; su id es del índice y se "
                                    "enlaza al GID por un campo")
        else:
            return r("ambiguo", None, f"segmento heredado :{a}:{b} sin regla")
    if m.group("lab") is None:
        if cola:
            return r("ambiguo", None, "subunidad sin artículo")
        if not _representable(raiz):
            return r("no_representable", None, f"la raíz «{raiz}» no pertenece al lenguaje v2")
        return r("igual" if not notas else "cambia", raiz, "raíz")
    leido, motivo = leer_etiqueta_legada(m.group("lab"))
    if leido is None:
        if motivo == "art_0000":
            v2 = f"{raiz}:unres:{CLAVE_PENDIENTE}"
            if not _representable(v2):
                return r("no_representable", None, f"la raíz «{raiz}» no pertenece al lenguaje v2")
            return r("unres", v2, "art:0000 no es identidad")
        if motivo == "sufijo_v1_truncado":
            return r("ambiguo", None, "sufijo v1 truncado (qua/qui…): no se adivina")
        return r("invalido", None, motivo)
    n, suf, tra, dialecto = leido
    if identidad is not None:
        en, es, et, eu = identidad
        if eu:
            return r("cambia", f"{raiz}:{etiqueta_articulo(None, (), et, True)}", "evidencia: artículo único")
        v2 = f"{raiz}:{etiqueta_articulo(en, es, et or tra, False)}"
        if (en, tuple(es)) != (n, suf):
            v2 += cola
            if not _representable(v2):
                return r("no_representable", None, f"«{v2}» no pertenece al lenguaje v2")
            return r("cambia", v2, "evidencia corrige la etiqueta heredada")
    else:
        v2 = f"{raiz}:{etiqueta_articulo(n, suf, tra, False)}"
    v2 += cola
    if not _representable(v2):
        return r("no_representable", None, f"«{v2}» no pertenece al lenguaje v2")
    lab_v2 = v2.split(":art:", 1)[1]
    lab_v2 = lab_v2[:len(lab_v2) - len(cola)] if cola else lab_v2
    aviso = ""
    if identidad is None and suf and len(suf[-1]) == 1:
        aviso = "; letra final sin evidencia: confirmar con el encabezado (en el starter, 20 de 214 son artefactos)"
    if lab_v2 == m.group("lab") and not notas:
        return r("igual", v2, dialecto + aviso, bool(aviso))
    return r("cambia", v2, f"{dialecto}: {m.group('lab')}{resto} → {lab_v2}{cola}"
             + (f" [{', '.join(notas)}]" if notas else "") + aviso, bool(aviso))
