# CURSOR_LOG — registro de sesiones en Cursor

Requisito del Open Agent Hackathon 2026: cada bloque de trabajo en Cursor se anota aquí con
fecha, modelo, tarea, resultado y evidencia (comando y salida). Sin secretos.

---

## 2026-10-22 — Composer — evidencia local: hello.py

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:20:58-03:00 |
| Host | `omarchy` (local; jar JDBC presente) |
| Modelo | Composer |
| Fase | Config previa |
| Tarea | Crear y ejecutar `/tmp/cursor-check/hello.py` como evidencia de Cursor en local |
| Archivos | `/tmp/cursor-check/hello.py` (fuera del repo) |
| Resultado | PASS |

**Comando y salida:**

```text
$ mkdir -p /tmp/cursor-check && printf '%s\n' 'print("hello")' > /tmp/cursor-check/hello.py && python /tmp/cursor-check/hello.py
hello
```

---

## 2026-10-22 — Composer — JDBC Zetaris ya verificado (reconfirmado)

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:22:30-03:00 |
| Host | `omarchy` |
| Modelo | Composer |
| Fase | Config previa / fase 0 |
| Tarea | Reconfirmar `SELECT 1` y `SHOW LIGHTNING DATABASES` vía JDBC (CLI Cursor → scripts de getting-started); sin imprimir credenciales |
| Archivos | ninguno del repo (usa `~/zetaris-getting-started` + jar en `~/zetaris-platform/jdbc/`) |
| Resultado | PASS (JDBC); REST API key aún pendiente |

**Comando y salida (resumen, sin secretos):**

```text
$ .venv/bin/python scripts/preflight.py --jdbc --jar "$HOME/zetaris-platform/jdbc/ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar"
[PASS] JDBC port 10000: open
[PASS] Java (JDK 11+): ...
[PASS] jaydebeapi: importable
[PASS] driver JAR: .../ndp-jdbc-driver-2.4.3.1-7eff043-driver.jar
[PASS] JDBC SELECT 1
[INFO] lightning databases: NY_TAXI, TPCDS_DB
NOT READY: 2 check(s) failed   # solo ZETARIS_API_KEY / REST — esperado hasta que Cristóbal cree la key
```

**Nota:** la UI de Zetaris responde en http://localhost:3000; REST en `127.0.0.1:8888` (HTTP 404 en la raíz = vivo). Contenedores sanos: `zetaris-ui-1`, `zetaris-api-1`, `zetaris-driver-1`, `zetaris-postgres-1`.

---

## 2026-10-22 — Composer — Zetaris API key + SELECT 1 REST

| Campo | Valor |
|---|---|
| Fecha | 2026-10-22T01:44-03:00 |
| Modelo | Composer |
| Fase | Config previa |
| Tarea | Resolver HTTP 400 al crear token; dejar key en `.env`; verificar `SELECT 1` por REST |
| Archivos | `.env` (solo `ZETARIS_API_KEY`, no versionado); `docs/CURSOR_LOG.md` |
| Resultado | PASS |

**Causa del 400:** nombre con acento (`Diké`) / fecha manual; con nombre ASCII `dike-shield` y caducidad `+ 30 d` el create devolvió 200.

**Evidencia REST (sin secretos):**

```text
POST $ZETARIS_REST_URL/sql-editor/sqls/run  (Bearer, X-Org-ID: 1, X-Request-ID uuid)
HTTP_200
result=[["1"]]
SELECT_1_REST_OK
```

Nota: `wl-copy` al portapapeles del host falló (timeout); la key quedó en `.env` modo 600.
