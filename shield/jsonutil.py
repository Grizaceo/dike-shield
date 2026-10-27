"""Pull a JSON object out of an LLM reply that may wrap it in fences or prose."""

from __future__ import annotations

import json
import re


def parse_object(text: str) -> dict:
    blob = text.strip()
    blob = re.sub(r"^```(?:json)?\s*", "", blob)
    blob = re.sub(r"\s*```$", "", blob)
    try:
        value = json.loads(blob)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = blob.find("{")
    end = blob.rfind("}")
    if start < 0 or end < start:
        raise ValueError("no JSON object")
    value = json.loads(blob[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("JSON root is not an object")
    return value
