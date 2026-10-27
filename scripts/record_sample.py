#!/usr/bin/env python3
"""Record live Nightshift replies into data/cache/ when the Runtime is up."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.env import load_env  # noqa: E402
from shield.llm import LLMClient, LLM_CACHE_DIR, MANIFEST_PATH  # noqa: E402


def main() -> int:
    env = dict(load_env())
    env["SAMPLE_MODE"] = "false"
    llm = LLMClient(env=env)
    LLM_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    pregunta = (
        "¿Qué plazo hay para reclamar un despido por necesidades de la empresa "
        "según el Código del Trabajo?"
    )
    draft = llm.chat(
        lane="FAST",
        agent="drafter",
        max_tokens=2048,
        timeout=90,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres un asistente jurídico chileno. Cita como artículo N del "
                    "Código del Trabajo. Responde en español, 4 oraciones."
                ),
            },
            {"role": "user", "content": pregunta},
        ],
    )
    (LLM_CACHE_DIR / "drafter_FAST.json").write_text(
        json.dumps(
            {
                "text": draft.text,
                "model": draft.model,
                "lane": draft.lane,
                "latency_ms": draft.latency_ms,
                "agent": "drafter",
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    man = {
        "recorded_at": __import__("time").strftime("%Y-%m-%d"),
        "source": "scripts/record_sample.py live Nightshift",
        "models": {"FAST": draft.model, "DEEP": env.get("METERLESS_MODEL_DEEP", "")},
    }
    MANIFEST_PATH.write_text(json.dumps(man, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"PASS recorded drafter model={draft.model} latency_ms={draft.latency_ms} chars={len(draft.text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
