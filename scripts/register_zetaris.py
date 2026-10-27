#!/usr/bin/env python3
"""Apply zetaris/register.sql (one statement per request) and verify 8544 rows."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shield.env import load_env, redact, secret_values  # noqa: E402
from shield.zetaris import ZetarisError, run_sql  # noqa: E402

EXPECTED = 8544
SQL_PATH = ROOT / "zetaris" / "register.sql"


def statements(sql: str, source: str, password: str) -> list[str]:
    filled = (
        sql.replace("__ZETARIS_SOURCE_DB__", source).replace("__SHIELD_DB_PASSWORD__", password)
    )
    chunks: list[str] = []
    buf: list[str] = []
    for raw in filled.splitlines():
        line = raw.strip()
        if not line or line.startswith("--"):
            continue
        buf.append(raw)
        if line.endswith(";"):
            stmt = "\n".join(buf).strip().rstrip(";").strip()
            buf = []
            if stmt:
                chunks.append(stmt)
    if buf:
        stmt = "\n".join(buf).strip().rstrip(";").strip()
        if stmt:
            chunks.append(stmt)
    return chunks


def datasource_names(rows: list) -> set[str]:
    names: set[str] = set()
    for row in rows:
        if isinstance(row, (list, tuple)) and row:
            names.add(str(row[0]))
        elif isinstance(row, dict):
            for key in ("name", "datasource", "NAME"):
                if key in row:
                    names.add(str(row[key]))
    return names


def count_queries(source: str) -> list[str]:
    # Spark on this Zetaris build is single-part: <fuente>.articulos, not
    # <fuente>.shield.articulos (see zetaris/register.sql).
    return [
        f"SELECT count(*) FROM {source}.articulos",
    ]


def as_int(rows: list) -> int | None:
    if not rows:
        return None
    cell = rows[0]
    if isinstance(cell, (list, tuple)) and cell:
        cell = cell[0]
    try:
        return int(cell)
    except (TypeError, ValueError):
        return None


def main() -> int:
    env = load_env()
    secrets = secret_values(env)
    source = env.get("ZETARIS_SOURCE_DB", "shield_pg")
    password = env.get("SHIELD_DB_PASSWORD", "")
    if not password or password.startswith("<"):
        print("FAIL missing SHIELD_DB_PASSWORD")
        return 1
    sql = SQL_PATH.read_text(encoding="utf-8")
    stmts = statements(sql, source, password)

    try:
        existing = datasource_names(run_sql("SHOW DATASOURCES", limit=100, env=env))
    except ZetarisError as exc:
        print(f"FAIL SHOW DATASOURCES {redact(str(exc), secrets)}")
        return 1

    if source in existing:
        try:
            run_sql(f"DROP DATASOURCE {source}", env=env)
            print(f"PASS dropped existing datasource {source}")
        except ZetarisError as exc:
            print(f"FAIL DROP DATASOURCE {redact(str(exc), secrets)}")
            return 1

    for stmt in stmts:
        kind = stmt.split()[0:3]
        label = " ".join(kind)
        try:
            run_sql(stmt, limit=10, timeout=90, env=env)
        except ZetarisError as exc:
            print(f"FAIL {label} {redact(str(exc), secrets)}")
            return 1
        print(f"PASS {label}")

    try:
        tables = run_sql(f"SHOW DATASOURCE TABLES {source}", limit=50, env=env)
        print(f"PASS tables n={len(tables)}")
    except ZetarisError as exc:
        print(f"FAIL SHOW DATASOURCE TABLES {redact(str(exc), secrets)}")
        return 1

    last_err = ""
    for query in count_queries(source):
        try:
            rows = run_sql(query, limit=10, env=env)
        except ZetarisError as exc:
            last_err = redact(str(exc), secrets)
            continue
        total = as_int(rows)
        print(f"PASS count query={query} -> {total}")
        if total == EXPECTED:
            hashed = as_int(
                run_sql(
                    f"SELECT count(*) FROM {source}.articulos WHERE pack_hash = 'af1422d66d1e6eee'",
                    limit=10,
                    env=env,
                )
            )
            print(f"PASS pack_hash={hashed}")
            if hashed != EXPECTED:
                print("FAIL pack_hash mismatch")
                return 1
            return 0
        last_err = f"count={total}"
    print(f"FAIL count != {EXPECTED} {last_err}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
