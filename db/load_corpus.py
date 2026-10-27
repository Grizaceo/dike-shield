#!/usr/bin/env python3
"""Load chile-base article JSON into shield.articulos (8544 rows)."""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.cuerpos import alias_for_bcn, label_for_bcn  # noqa: E402
from shield.dike_adapter import dike_paths  # noqa: E402
from shield.env import load_env  # noqa: E402

PACK_HASH = "af1422d66d1e6eee"
EXPECTED = 8544


def article_token(eid: str) -> str:
    token = eid.removeprefix("art_").lower()
    if token.isdigit():
        return f"{int(token):04d}"
    return token.replace("-", "_")


def bcn_from_article(path: Path, payload: dict) -> str | None:
    stem = path.stem  # articulo_207436_art_0168
    if stem.startswith("articulo_"):
        rest = stem[len("articulo_") :]
        bcn, _, _eid = rest.partition("_")
        if bcn.isdigit():
            return bcn
    prov = payload.get("provenance") or {}
    derived = prov.get("wasDerivedFrom") or ""
    if "/norma/" in derived:
        return derived.rstrip("/").rsplit("/", 1)[-1]
    return None


def parse_date(value: object) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def iter_rows(articulos_dir: Path):
    files = sorted(articulos_dir.glob("articulo_*.json"))
    skipped = 0
    for path in files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        bcn = bcn_from_article(path, payload)
        alias = alias_for_bcn(bcn or "")
        label = label_for_bcn(bcn or "")
        eid = str(payload.get("eId") or "")
        texto = payload.get("text") or ""
        if not alias or not label or not eid or not texto:
            skipped += 1
            continue
        gid = f"cl.norma.{alias}:art:{article_token(eid)}"
        temporal = payload.get("temporal") or {}
        numero = str(payload.get("label") or article_token(eid).lstrip("0") or eid)
        yield (
            gid,
            label,
            numero,
            texto,
            parse_date(temporal.get("from")),
            parse_date(temporal.get("to")),
            PACK_HASH,
        )
    if skipped:
        print(f"WARN skipped={skipped}")


def articulos_dir() -> Path:
    paths = dike_paths()
    installed = paths["users"] / "shield" / "starter" / "chile-base" / "current" / "articulos"
    if installed.is_dir():
        return installed
    pack = paths["pack"] / "articulos"
    if pack.is_dir():
        return pack
    raise SystemExit("FAIL: chile-base articulos not found; run scripts/setup_dike.py")


def connect(env: dict[str, str]):
    import psycopg

    url = env.get("SHIELD_DB_URL", "")
    if not url or url.startswith("postgresql://shield:<"):
        raise SystemExit("FAIL: SHIELD_DB_URL missing")
    return psycopg.connect(url)


def main() -> int:
    env = load_env()
    source = articulos_dir()
    rows = list(iter_rows(source))
    if len(rows) != EXPECTED:
        print(f"FAIL parsed={len(rows)} expected={EXPECTED}")
        return 1
    gids = [r[0] for r in rows]
    if len(set(gids)) != len(gids):
        print("FAIL duplicate gids")
        return 1
    with connect(env) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path TO shield")
            cur.execute("TRUNCATE shield.articulos")
            with cur.copy(
                "COPY shield.articulos "
                "(gid, cuerpo, numero, texto, vigencia_desde, vigencia_hasta, pack_hash) "
                "FROM STDIN"
            ) as copy:
                for row in rows:
                    copy.write_row(row)
            cur.execute("SELECT count(*), count(*) FILTER (WHERE pack_hash = %s) FROM shield.articulos", (PACK_HASH,))
            total, hashed = cur.fetchone()
        conn.commit()
    print(f"PASS loaded={total} pack_hash={hashed} source={source}")
    if total != EXPECTED or hashed != EXPECTED:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
