"""FAST drafter. Citations must use the format Diké recognizes."""

from __future__ import annotations

from shield.llm import LLMClient, LLMResult

# Lightning 30B returns empty_response (HTTP 502) on longer legal system prompts.
# This wording is the one that completes with max_tokens>=2048 on Nightshift.
_SYSTEM = (
    "Eres un asistente jurídico chileno. Cita como artículo N del Código del Trabajo. "
    "Responde en español, 4 oraciones."
)


def draft(
    *,
    pregunta: str,
    escenario: str,
    evitar: list[str],
    llm: LLMClient,
) -> LLMResult:
    del escenario
    user = pregunta.strip()
    if evitar:
        user += "\nNo uses: " + "; ".join(evitar[:5])
    return llm.chat(
        lane="FAST",
        agent="drafter",
        max_tokens=2048,
        temperature=0.2,
        timeout=90,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    )
