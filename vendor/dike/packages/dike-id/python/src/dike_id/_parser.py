"""Parser estructural derivado de la gramática serializada (`_generated/grammar.json`).

Intérprete con retroceso sobre el AST del ABNF. Enumera las derivaciones: si una cadena tiene
más de una, la gramática es ambigua para esa cadena y el parse no es función. Solo se llama
después de que el regex generado aceptó la cadena (largo ≤ 256), así que el costo está acotado.
El mismo algoritmo está en `ts/src/parser.ts`; la prueba diferencial compara sus AST.
"""
from __future__ import annotations

import json
import pathlib

_GRAMATICA = json.loads((pathlib.Path(__file__).resolve().parent / "_generated" / "grammar.json")
                        .read_text(encoding="utf-8"))


class Nodo:
    __slots__ = ("regla", "i", "j", "hijos")

    def __init__(self, regla: str, i: int, j: int, hijos: list["Nodo"]):
        self.regla, self.i, self.j, self.hijos = regla, i, j, hijos

    def texto(self, s: str) -> str:
        return s[self.i:self.j]

    def buscar(self, regla: str) -> "Nodo | None":
        """Primer descendiente (preorden) con esa regla."""
        for h in self.hijos:
            if h.regla == regla:
                return h
            r = h.buscar(regla)
            if r is not None:
                return r
        return None

    def hijo(self, regla: str) -> "Nodo | None":
        """Hijo directo con esa regla."""
        for h in self.hijos:
            if h.regla == regla:
                return h
        return None

    def todos(self, regla: str) -> list["Nodo"]:
        out = []
        for h in self.hijos:
            if h.regla == regla:
                out.append(h)
            else:
                out += h.todos(regla)
        return out


class Parser:
    def __init__(self, gramatica: dict = _GRAMATICA):
        self.reglas = gramatica["rules"]
        self.inicio = gramatica["start"]

    def _m(self, n, s, i):
        t = n[0]
        if t == "lit":
            L = len(n[1])
            seg = s[i:i + L]
            if (seg == n[1]) if n[2] else (len(seg) == L and seg.lower() == n[1].lower()):
                yield i + L, []
        elif t == "range":
            if i < len(s) and n[1] <= ord(s[i]) <= n[2]:
                yield i + 1, []
        elif t == "ref":
            for j, hs in self._m(self.reglas[n[1]], s, i):
                yield j, [Nodo(n[1], i, j, hs)]
        elif t == "alt":
            for x in n[1]:
                yield from self._m(x, s, i)
        elif t == "seq":
            yield from self._seq(n[1], 0, s, i)
        elif t == "rep":
            yield from self._rep(n, 0, s, i)
        else:
            raise ValueError(f"nodo desconocido {t}")

    def _seq(self, ops, k, s, i):
        if k == len(ops):
            yield i, []
            return
        for j, hs in self._m(ops[k], s, i):
            for j2, hs2 in self._seq(ops, k + 1, s, j):
                yield j2, hs + hs2

    def _rep(self, n, cuenta, s, i):
        lo, hi, hijo = n[1], n[2], n[3]
        if hi is None or cuenta < hi:
            for j, hs in self._m(hijo, s, i):
                if j == i:
                    continue  # sin progreso: evita bucles
                for j2, hs2 in self._rep(n, cuenta + 1, s, j):
                    yield j2, hs + hs2
        if cuenta >= lo:
            yield i, []

    def derivaciones(self, s: str, limite: int = 2) -> list[Nodo]:
        out = []
        for j, hs in self._m(["ref", self.inicio], s, 0):
            if j == len(s):
                out.append(hs[0])
                if len(out) >= limite:
                    break
        return out


PARSER = Parser()
