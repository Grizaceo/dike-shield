"""Canonical names of the 25 chile-base statutes Diké accepts."""

from __future__ import annotations

import unicodedata

# alias UMJ -> canonical Spanish label (materias_catalog.v1.json)
ALIAS_TO_LABEL: dict[str, str] = {
    "cc": "Código Civil",
    "cpc": "Código de Procedimiento Civil",
    "cot": "Código Orgánico de Tribunales",
    "cp": "Código Penal",
    "cpp": "Código Procesal Penal",
    "ct": "Código del Trabajo",
    "ccom": "Código de Comercio",
    "ctrib": "Código Tributario",
    "cpr": "Constitución Política de la República",
    "dfl_1122": "Código de Aguas",
    "dl_3500": "DL 3.500 — Sistema de Pensiones",
    "ley_16744": "Ley 16.744 — Accidentes del Trabajo",
    "ley_17322": "Ley 17.322 — Cobranza de Cotizaciones",
    "ley_19728": "Ley 19.728 — Seguro de Desempleo",
    "ley_19496": "Ley 19.496 — Protección al Consumidor",
    "ley_19628": "Ley 19.628 — Vida Privada",
    "ley_21719": "Ley 21.719 — Datos Personales",
    "ley_19968": "Ley 19.968 — Tribunales de Familia",
    "ley_20066": "Ley 20.066 — Violencia Intrafamiliar",
    "ley_20000": "Ley 20.000 — Estupefacientes",
    "ley_18216": "Ley 18.216 — Penas Sustitutivas",
    "ley_18046": "Ley 18.046 — Sociedades Anónimas",
    "ley_18092": "Ley 18.092 — Letra de Cambio y Pagaré",
    "ley_20720": "Ley 20.720 — Reorganización y Liquidación",
    "ley_19828": "Ley 19.828 — Servicio Nacional del Adulto Mayor",
}

# Ley Chile idNorma (pack.json includedLeychileCodes) -> alias
BCN_TO_ALIAS: dict[str, str] = {
    "172986": "cc",
    "22740": "cpc",
    "25563": "cot",
    "1984": "cp",
    "176595": "cpp",
    "207436": "ct",
    "1974": "ccom",
    "6374": "ctrib",
    "242302": "cpr",
    "5605": "dfl_1122",
    "7147": "dl_3500",
    "28650": "ley_16744",
    "28919": "ley_17322",
    "184979": "ley_19728",
    "61438": "ley_19496",
    "141599": "ley_19628",
    "1209272": "ley_21719",
    "229557": "ley_19968",
    "242648": "ley_20066",
    "235507": "ley_20000",
    "29636": "ley_18216",
    "29473": "ley_18046",
    "29517": "ley_18092",
    "1058072": "ley_20720",
    "202950": "ley_19828",
}

CANONICAL_NAMES: tuple[str, ...] = tuple(ALIAS_TO_LABEL[a] for a in ALIAS_TO_LABEL)


def _fold(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch)).casefold()


_FOLDED_TO_CANONICAL: dict[str, str] = {}
for _alias, _label in ALIAS_TO_LABEL.items():
    _FOLDED_TO_CANONICAL[_fold(_alias)] = _label
    _FOLDED_TO_CANONICAL[_fold(_label)] = _label
    _FOLDED_TO_CANONICAL[_fold(_label.split("—")[0].strip())] = _label

# Extra phrases Diké's extractor already maps onto these 25 bodies.
_FOLDED_TO_CANONICAL.update(
    {
        _fold("codigo civil"): ALIAS_TO_LABEL["cc"],
        _fold("codigo de procedimiento civil"): ALIAS_TO_LABEL["cpc"],
        _fold("codigo del trabajo"): ALIAS_TO_LABEL["ct"],
        _fold("codigo de comercio"): ALIAS_TO_LABEL["ccom"],
        _fold("codigo comercial"): ALIAS_TO_LABEL["ccom"],
        _fold("codigo tributario"): ALIAS_TO_LABEL["ctrib"],
        _fold("codigo penal"): ALIAS_TO_LABEL["cp"],
        _fold("codigo procesal penal"): ALIAS_TO_LABEL["cpp"],
        _fold("codigo organico de tribunales"): ALIAS_TO_LABEL["cot"],
        _fold("codigo de aguas"): ALIAS_TO_LABEL["dfl_1122"],
        _fold("caguas"): ALIAS_TO_LABEL["dfl_1122"],
        _fold("dfl 1122"): ALIAS_TO_LABEL["dfl_1122"],
        _fold("constitucion"): ALIAS_TO_LABEL["cpr"],
        _fold("constitucion politica"): ALIAS_TO_LABEL["cpr"],
        _fold("constitucion politica de la republica"): ALIAS_TO_LABEL["cpr"],
    }
)


def canonicalize(name: str) -> str | None:
    """Return the canonical body name Diké accepts, or None if unknown."""
    if not name or not name.strip():
        return None
    return _FOLDED_TO_CANONICAL.get(_fold(name.strip()))


def label_for_bcn(bcn_id: str) -> str | None:
    alias = BCN_TO_ALIAS.get(str(bcn_id))
    if not alias:
        return None
    return ALIAS_TO_LABEL[alias]


def alias_for_bcn(bcn_id: str) -> str | None:
    return BCN_TO_ALIAS.get(str(bcn_id))
