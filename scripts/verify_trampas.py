#!/usr/bin/env python3
"""Verify each trap citation is FALLO (colision_corpus=false). Isolated Diké HOME."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.dike_adapter import verificar  # noqa: E402

TRAMPAS = ROOT / "data" / "samples" / "trampas.jsonl"


def main() -> int:
    rows = [json.loads(line) for line in TRAMPAS.read_text(encoding="utf-8").splitlines() if line.strip()]
    failed = 0
    for row in rows:
        cite = str(row["cita_ficticia"])
        text = f"Según el {cite} el efecto es nulo."
        result = verificar(text)
        detalles = [d for d in (result.get("detalles") or []) if isinstance(d, dict)]
        ok = detalles and all(d.get("estado") == "FALLO" for d in detalles)
        colision = not ok
        flag = "PASS" if ok and row.get("colision_corpus") is False else "FAIL"
        if flag == "FAIL":
            failed += 1
        estados = [d.get("estado") for d in detalles]
        print(f"{flag} {row['id']} {cite} estados={estados} colision={colision}")
    print(f"{len(rows) - failed}/{len(rows)} trampas sin colisión")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
