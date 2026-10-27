"""DEEP repairer. May only keep VERIFICADA citations or candidates that will re-enter Diké."""

from __future__ import annotations

from shield.llm import LLMClient, LLMError, LLMResult

_SYSTEM = """Reescribes un borrador jurídico chileno.
Solo puedes citar artículos que aparezcan en la lista VERIFICADA, con el formato
exacto "artículo N del <cuerpo canónico>".
Retira o sustituye las citas en FALLO. No inventes números nuevos.
Si no hay base verificada para una afirmación, suprímela.
Prohibido explicar el proceso, pensar en voz alta o escribir en inglés.
Responde SOLO el escrito reparado en español, sin preámbulo.
"""


def looks_like_scratchpad(texto: str) -> bool:
    head = texto.lstrip()[:120].casefold()
    markers = (
        "the user",
        "i need",
        "i'll",
        "i will",
        "let me",
        "okay,",
        "sure,",
        "as an ai",
        "rewrite",
        "repaired text",
        "the original",
    )
    return any(head.startswith(m) or m in head[:80] for m in markers)


def _mechanical(texto: str, fallos: list[str]) -> str:
    out = texto
    for raw in fallos:
        if raw:
            out = out.replace(raw, "")
    out = "\n".join(line for line in out.splitlines() if line.strip())
    return out.strip() or (
        "Se retiran las citas que Diké no verificó. Queda solo lo que el corpus "
        "pudo probar; el resto se escala a revisión humana."
    )


def repair(
    *,
    texto: str,
    detalles: list[dict],
    articulos: list[dict],
    llm: LLMClient,
) -> LLMResult:
    fallos = [str(d.get("cita_raw") or "") for d in detalles if d.get("estado") == "FALLO"]
    ok = [d for d in detalles if d.get("estado") == "VERIFICADA"]
    user = (
        f"texto:\n{texto}\n\n"
        f"citas_verificadas:\n{ok}\n\n"
        f"citas_fallidas:\n{fallos}\n\n"
        f"articulos:\n{articulos}"
    )
    try:
        result = llm.chat(
            lane="DEEP",
            agent="repairer",
            temperature=0.2,
            max_tokens=2048,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user},
            ],
        )
        if looks_like_scratchpad(result.text) or any(f and f in result.text for f in fallos):
            return LLMResult(
                text=_mechanical(texto, fallos),
                model=f"{result.model}+mechanical",
                latency_ms=result.latency_ms,
                lane="DEEP",
            )
        return result
    except LLMError:
        return LLMResult(
            text=_mechanical(texto, fallos),
            model="mechanical",
            latency_ms=0,
            lane="DEEP",
        )
