#!/usr/bin/env python3
"""Install chile-base in the isolated Diké HOME and generate the demo signing key."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.dike_adapter import (  # noqa: E402
    VENDOR_DIKE,
    dike_paths,
    ensure_cli,
    ensure_corpus,
)
from shield.env import load_env  # noqa: E402


def lexo_mtime() -> float | None:
    lexo = Path.home() / ".lexo"
    if lexo.exists():
        return lexo.stat().st_mtime
    return None


def generate_demo_key(key_path: Path) -> str:
    if key_path.is_file():
        mode = oct(key_path.stat().st_mode & 0o777)
        return f"exists mode={mode}"
    key_path.parent.mkdir(parents=True, exist_ok=True)
    script = (
        "from pathlib import Path; "
        "from lexo_cli.content_signing import generar_content_key; "
        f"generar_content_key(Path({str(key_path)!r})); "
        "print('created')"
    )
    run = subprocess.run(
        ["uv", "run", "--directory", str(VENDOR_DIKE), "python", "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if run.returncode != 0:
        raise SystemExit("FAIL: demo key generation failed")
    key_path.chmod(0o600)
    return "created mode=0o600"


def main() -> int:
    before = lexo_mtime()
    env = load_env()
    _ = env  # secrets stay in memory; never printed
    paths = dike_paths(env)
    cmd = ensure_cli()
    marker = ensure_corpus(cmd)
    key_status = generate_demo_key(paths["key"])
    after = lexo_mtime()
    if before is not None and after is not None and before != after:
        print("FAIL: ~/.lexo mtime changed")
        return 1
    print(f"PASS corpus={marker}")
    print(f"PASS key={paths['key']} {key_status}")
    print("PASS ~/.lexo unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
