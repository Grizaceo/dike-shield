"""Router: rules first, FAST only when the domain is unclear."""

from __future__ import annotations

import re
from dataclasses import dataclass

from shield.jsonutil import parse_object
from shield.llm import LLMClient, LLMError, LLMResult

RUTAS = ("responder", "abstener", "auditar")

_IN_DOMAIN = re.compile(
    r"despido|finiquito|trabajador|empleador|contrato\s+de\s+trabajo|"
    r"c[oó]digo\s+del\s+trabajo|indemnizaci[oó]n|fuero|cotizaci[oó]n|"
    r"jornada|vacaciones|causal|necesidades\s+de\s+la\s+empresa|"
    r"accidente\s+(?:del|laboral)|seguro\s+de\s+(?:cesant[ií]a|desempleo)|"
    r"pensiones|datos\s+personales|c[oó]digo\s+civil|c[oó]digo\s+penal|"
    r"consumidor|sociedad(?:es)?\s+an[oó]nima",
    re.IGNORECASE,
)

_OUT_DOMAIN = re.compile(
    r"municipalidad|ordenanza\s+municipal|chilecompra|licitaci[oó]n\s+p[uú]blica|"
    r"compras\s+p[uú]blicas|ley\s+de\s+transparencia|permiso\s+de\s+circulaci[oó]n|"
    r"tr[aá]nsito|sem[aá]foro|inmigraci[oó]n|extranjer[ií]a|aduana|"
    r"plan\s+regulador|patente\s+comercial|fintech",
    re.IGNORECASE,
)


@dataclass
class Route:
    ruta: str
    razon: str
    llm: LLMResult | None


def route(
    *,
    texto: str,
    escenario: str,
    modo: str,
    llm: LLMClient | None,
) -> Route:
    if modo == "auditoria":
        return Route("auditar", "texto pegado para auditar", None)
    if _OUT_DOMAIN.search(texto) and not _IN_DOMAIN.search(texto):
        return Route(
            "abstener",
            "La pregunta cae fuera de los 25 cuerpos del corpus chile-base.",
            None,
        )
    if escenario in {"despido", "finiquito"} or _IN_DOMAIN.search(texto):
        return Route("responder", f"escenario={escenario} cubierto por el corpus", None)
    if llm is None:
        return Route(
            "abstener",
            "Sin señal de dominio cubierto y sin lane FAST para desambiguar.",
            None,
        )
    try:
        result = llm.chat(
            lane="FAST",
            agent="router",
            temperature=0,
            max_tokens=256,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Eres el router de Diké Shield. El corpus cubre 25 cuerpos "
                        "chilenos (trabajo, civil, penal, comercio, datos, pensiones, "
                        "aguas, constitución, consumidor, familia, etc.). "
                        'Responde SOLO JSON {"ruta":"responder"|"abstener","razon":"..."}. '
                        "abstener si la pregunta necesita normas que no están en ese corpus "
                        "(municipal, tránsito, compras públicas, extranjería)."
                    ),
                },
                {"role": "user", "content": texto[:3000]},
            ],
        )
        payload = parse_object(result.text)
        ruta = str(payload.get("ruta") or "abstener")
        if ruta not in RUTAS:
            ruta = "abstener"
        razon = str(payload.get("razon") or "")
        return Route(ruta, razon, result)
    except (LLMError, ValueError):
        return Route("abstener", "router FAST no desambiguó; se abstiene", None)
