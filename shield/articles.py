"""Read verified articles through Zetaris (never through direct SELECT in the agent path)."""

from __future__ import annotations

from shield.env import load_env
from shield.zetaris import run_sql


def fetch_articulos(gids: list[str], env: dict[str, str] | None = None) -> list[dict]:
    if not gids:
        return []
    cfg = env or load_env()
    source = cfg.get("ZETARIS_SOURCE_DB", "shield_pg")
    quoted = ",".join("'" + gid.replace("'", "''") + "'" for gid in gids)
    sql = (
        f"SELECT gid, cuerpo, numero, texto FROM {source}.articulos "
        f"WHERE gid IN ({quoted})"
    )
    rows = run_sql(sql, limit=max(10, len(gids)), env=cfg)
    out: list[dict] = []
    for row in rows:
        if isinstance(row, (list, tuple)) and len(row) >= 4:
            out.append(
                {
                    "gid": row[0],
                    "cuerpo": row[1],
                    "numero": row[2],
                    "texto": row[3],
                }
            )
    return out
