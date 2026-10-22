"""Base de los IRI que acuña el pack (ARCH-004, 2026-10-14).

`lexo.cl` es de un tercero (Kersting S.A., según NIC Chile), y un IRI bajo ese
dominio afirma una autoridad que este proyecto no tiene. Los IRI propios van
bajo `https://dike.invalid/`: `.invalid` está reservado (RFC 6761), nunca
resuelve y no puede ser de nadie. Son nombres, no enlaces. Si algún día hay un
dominio propio, cambia la base y no la identidad: la identidad es el GID.

Los packs sellados antes de este cambio traen `https://lexo.cl/`. Se leen como
alias (el mismo camino con la otra base) y no se vuelven a emitir.
"""
from __future__ import annotations

BASE = "https://dike.invalid/"
BASE_LEGADA = "https://lexo.cl/"

# Lo que se anuncia a BCN al pedir una norma: sin dominio ajeno.
USER_AGENT = "Mozilla/5.0 (compatible; Dike-StarterGraph/1.0; +https://github.com/Grizaceo/dike)"


def iri(ruta: str) -> str:
    """IRI propio para `ruta` (sin barra inicial): `iri("eli/cl/ley/1/2000")`."""
    return BASE + ruta.lstrip("/")


def es_legado(valor: str) -> bool:
    return valor.startswith(BASE_LEGADA)


def a_base_actual(valor: str) -> str:
    """El mismo IRI con la base actual; lo que no es legado vuelve igual."""
    return BASE + valor[len(BASE_LEGADA):] if es_legado(valor) else valor


def a_base_legada(valor: str) -> str:
    """El alias legado de un IRI actual, para buscar en packs antiguos."""
    return BASE_LEGADA + valor[len(BASE):] if valor.startswith(BASE) else valor


def es_eli_propio(valor: str) -> bool:
    return valor.startswith(BASE + "eli/") or valor.startswith(BASE_LEGADA + "eli/")
