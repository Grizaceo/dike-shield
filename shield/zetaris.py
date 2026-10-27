"""Read-only Lightning SQL client (Zetaris REST). One statement per request."""

from __future__ import annotations

import json
import uuid
from typing import Any
from urllib import error, request

from shield.env import load_env, redact, secret_values


class ZetarisError(RuntimeError):
    pass


def _post(url: str, headers: dict[str, str], body: dict[str, Any], timeout: int) -> tuple[int, object]:
    data = json.dumps(body).encode()
    req = request.Request(url, data=data, method="POST", headers=headers)
    req.add_header("Content-Type", "application/json")
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            try:
                parsed: object = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                parsed = {"_text": raw[:400]}
            return resp.status, parsed
    except error.HTTPError as exc:
        raw = exc.read().decode()[:800]
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = {"_text": raw}
        return exc.code, parsed


def run_sql(sql: str, *, limit: int = 100, timeout: int = 60, env: dict[str, str] | None = None) -> list[Any]:
    """Execute one Lightning SQL statement. Returns the `data` rows."""
    if ";" in sql.strip().rstrip(";"):
        raise ZetarisError("one statement per request")
    cfg = env or load_env()
    secrets = secret_values(cfg)
    base = cfg.get("ZETARIS_REST_URL", "").rstrip("/")
    key = cfg.get("ZETARIS_API_KEY", "")
    org = cfg.get("ZETARIS_ORG_ID", "1")
    if not base or not key or key.startswith("<"):
        raise ZetarisError("missing ZETARIS_REST_URL or ZETARIS_API_KEY")
    url = f"{base}/sql-editor/sqls/run"
    headers = {
        "Authorization": f"Bearer {key}",
        "X-Org-ID": str(org),
        "X-Request-ID": str(uuid.uuid4()),
    }
    body = {
        "queryId": str(uuid.uuid4()),
        "sql": sql,
        "source": "SqlEditor",
        "limit": limit,
    }
    code, payload = _post(url, headers, body, timeout)
    if code != 200:
        summary = redact(str(payload)[:300], secrets)
        raise ZetarisError(f"HTTP {code} {summary}")
    if not isinstance(payload, dict):
        raise ZetarisError("unexpected payload")
    data = payload.get("data")
    if data is None:
        # DDL often returns empty data; treat as success with no rows.
        return []
    if not isinstance(data, list):
        raise ZetarisError(redact(f"unexpected data: {data!r}"[:300], secrets))
    return data
