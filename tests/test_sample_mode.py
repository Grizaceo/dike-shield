"""SAMPLE_MODE serves recorded Nemotron replies without Nightshift."""

from __future__ import annotations

import pytest

from shield.llm import LLMClient, LLMError, sample_manifest, sample_recorded_at

FAST = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEEP = "nvidia/nemotron-3-ultra-550b-a55b"

SAMPLE_ENV = {
    "SAMPLE_MODE": "true",
    "METERLESS_BASE_URL": "http://127.0.0.1:1",
    "METERLESS_RUNTIME_TOKEN": "not-a-real-token",
    "METERLESS_MODEL_FAST": FAST,
    "METERLESS_MODEL_DEEP": DEEP,
}

LIVE_ENV = {
    **SAMPLE_ENV,
    "SAMPLE_MODE": "false",
}


def test_manifest_is_the_live_fase2_date() -> None:
    man = sample_manifest()
    assert man.get("recorded_at") == "2026-10-27"
    assert sample_recorded_at() == "2026-10-27"
    assert man["models"]["FAST"] == FAST
    assert man["models"]["DEEP"] == DEEP


def test_sample_mode_drafter_replays_art14_trace() -> None:
    llm = LLMClient(env=SAMPLE_ENV)
    draft = llm.chat(
        lane="FAST",
        agent="drafter",
        messages=[
            {"role": "system", "content": "Eres un asistente jurídico chileno."},
            {"role": "user", "content": "¿Qué plazo hay para reclamar un despido por necesidades de la empresa?"},
        ],
        timeout=1,
    )
    assert draft.model == FAST
    assert draft.lane == "FAST"
    assert draft.latency_ms == 26922
    assert draft.text.find("artículo 14") == 391
    assert "artículo 161" in draft.text
    assert "artículo 168" in draft.text


def test_sample_mode_judge_branches_on_user_verdict() -> None:
    llm = LLMClient(env=SAMPLE_ENV)
    bad = llm.chat(
        lane="DEEP",
        agent="judge",
        messages=[
            {"role": "system", "content": "Eres el juez. FALLO is a word in the system prompt."},
            {
                "role": "user",
                "content": "veredicto CON_PROBLEMAS estado FALLO resolucion AMBIGUOUS artículo 14",
            },
        ],
        timeout=1,
    )
    assert bad.model == DEEP
    assert "reparar" in bad.text

    ok = llm.chat(
        lane="DEEP",
        agent="judge",
        messages=[
            {"role": "system", "content": "Eres el juez. FALLO is a word in the system prompt."},
            {"role": "user", "content": "veredicto TODAS_VERIFICADAS todas las citas VERIFICADA"},
        ],
        timeout=1,
    )
    assert "publicar" in ok.text
    assert "reparar" not in ok.text.split("decision")[1][:40]


def test_sample_mode_repairer_drops_invented_cites() -> None:
    llm = LLMClient(env=SAMPLE_ENV)
    repaired = llm.chat(
        lane="DEEP",
        agent="repairer",
        messages=[{"role": "user", "content": "quita artículo 9999 y artículo 14"}],
        timeout=1,
    )
    assert repaired.model == DEEP
    assert "9999" not in repaired.text
    assert "artículo 14" not in repaired.text
    assert "artículo 161" in repaired.text
    assert "artículo 168" in repaired.text


def test_sample_mode_off_does_not_read_cache() -> None:
    llm = LLMClient(env=LIVE_ENV)
    with pytest.raises(LLMError):
        llm.chat(
            lane="FAST",
            agent="drafter",
            messages=[{"role": "user", "content": "hi"}],
            timeout=1,
        )
