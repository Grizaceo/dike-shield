"""Extract citations. Regex first; FAST LLM only if the text looks like it cites and regex is empty."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from shield.cuerpos import CANONICAL_NAMES, canonicalize
from shield.llm import LLMClient, LLMError, LLMResult

_CITE = re.compile(
    r"(?P<raw>(?:art(?:[íi]culos?)?|arts?)\.?\s+"
    r"(?P<num>\d+)(?:\s*(?P<suf>bis|ter|qu[aá]ter|quinquies))?"
    r"(?:\s+(?:del?|de\s+la|de\s+los)\s+(?P<body>[A-ZÁÉÍÓÚÑa-záéíóúñ0-9\s]{3,80}))?)",
    re.IGNORECASE,
)

_LOOKS_LIKE_CITE = re.compile(r"\bart(?:[íi]culo)?s?\.?\s+\d+", re.IGNORECASE)


@dataclass
class ExtractedCite:
    raw: str
    normalized: str
    numero: str
    cuerpo: str | None


def _clip_body(body: str) -> str:
    body = re.split(r"[,.;:\n]|(\s+el\s+|\s+la\s+|\s+los\s+|\s+las\s+|\s+y\s+)", body, maxsplit=1)[0]
    return re.sub(r"\s+", " ", body).strip(" .")


def _canonical_body(body: str | None) -> str | None:
    if not body:
        return None
    words = re.sub(r"\s+", " ", body).strip().split()
    for n in range(min(len(words), 12), 0, -1):
        cand = " ".join(words[:n]).strip(" .,;:")
        hit = canonicalize(cand)
        if hit:
            return hit
    for name in CANONICAL_NAMES:
        if name.casefold() in body.casefold():
            return name
    return canonicalize(_clip_body(body))


def _normalize(num: str, suf: str | None, body: str | None) -> tuple[str, str | None]:
    numero = num
    if suf:
        numero = f"{num} {suf.lower().replace('á', 'a')}"
    canon = _canonical_body(body)
    if canon:
        return f"artículo {numero} del {canon}", canon
    if body:
        clipped = _clip_body(body)
        return f"artículo {numero} del {clipped}", clipped
    return f"artículo {numero}", None


def extract_regex(text: str) -> list[ExtractedCite]:
    found: list[ExtractedCite] = []
    seen: set[str] = set()
    for match in _CITE.finditer(text):
        raw = re.sub(r"\s+", " ", match.group("raw")).strip()
        body = match.group("body")
        normalized, canon = _normalize(match.group("num"), match.group("suf"), body)
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        found.append(
            ExtractedCite(
                raw=raw,
                normalized=normalized,
                numero=match.group("num"),
                cuerpo=canon,
            )
        )
    return found


def _parse_llm_cites(blob: str) -> list[ExtractedCite]:
    start = blob.find("[")
    end = blob.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        data = json.loads(blob[start : end + 1])
    except json.JSONDecodeError:
        return []
    out: list[ExtractedCite] = []
    seen: set[str] = set()
    if not isinstance(data, list):
        return out
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = str(item.get("raw") or item.get("cita") or "").strip()
        if not raw:
            continue
        parsed = extract_regex(raw) or extract_regex(f"Según el {raw}.")
        if not parsed:
            continue
        cite = parsed[0]
        if cite.normalized.casefold() in seen:
            continue
        seen.add(cite.normalized.casefold())
        out.append(cite)
    return out


def extract(text: str, llm: LLMClient | None = None) -> tuple[list[ExtractedCite], LLMResult | None]:
    cites = extract_regex(text)
    if cites or llm is None or not _LOOKS_LIKE_CITE.search(text):
        return cites, None
    try:
        result = llm.chat(
            lane="FAST",
            agent="extractor",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extrae citas normativas chilenas. Responde SOLO un JSON array "
                        '[{"raw": "artículo N del <cuerpo>"}]. Cuerpos canónicos; sin inventar.'
                    ),
                },
                {"role": "user", "content": text[:4000]},
            ],
            max_tokens=512,
            temperature=0,
        )
    except LLMError:
        return cites, None
    return _parse_llm_cites(result.text) or cites, result
