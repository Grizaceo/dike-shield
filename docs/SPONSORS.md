# Sponsor technology

English write-up of how Diké Shield uses Zetaris, Meterless, NVIDIA Nemotron and Cursor. No secrets.

## Zetaris

Zetaris is the **read path** the jury and the product share.

- Local Docker install; Lightning REST at `:8888`. The Shield Postgres (`shield-db`, `:55432`) sits on the `zetaris_default` network.
- `scripts/register_zetaris.py` registers datasource `shield_pg` and **views** (`articulos`, `sesiones`, `intercepciones`, `citas`, `eventos_traza`, `refutadas`, `trampas`, `banco_corridas`, `banco_items`). This Zetaris build does not expose schema `shield` through `REGISTER DATASOURCE TABLES` (JDBC sees `public`). Queries use `shield_pg.articulos`, never `shield_pg.shield.articulos`.
- Load check: `SELECT count(*) FROM shield_pg.articulos` → 8544; every row `pack_hash = af1422d66d1e6eee`.
- The loop **writes** with `psycopg` into `shield.*`. It **reads** article text for the judge through Lightning. That split is the federated-data requirement, not a convenience wrapper.

## Meterless

Two mandatory uses, both exercised in tests.

### Nightshift Runtime (Power)

Nightshift on a Windows VM is the **only** AI provider. The app calls `POST /v1/chat/completions` with `Authorization: Bearer <Console token>` and headers `meterless-app: dike-shield`, `meterless-scope: user`.

Prize-path lanes, taken from `GET /models` on this machine (2026-10-27):

| Lane | Model id | Role |
|---|---|---|
| FAST | `nvidia/nemotron-3.5-lightning-30b-a3b` | Router (rare), drafter |
| DEEP | `nvidia/nemotron-3-ultra-550b-a55b` | Judge, repairer |

`meterless/auto`, `meterless/fast` and `meterless/deep` are rejected in `shield/llm.py`. The NVIDIA key never appears in `.env`; it lives in the Nightshift Providers tab.

Live evidence (CURSOR_LOG Fase 2, 2026-10-27T04:36): FAST draft 26922 ms, artículo 14 AMBIGUOUS at position 391, stripped from the final text; audit of artículo 9999 in, 9999 out. At packaging time the VM did not accept TCP on `:8088`; SAMPLE_MODE replays that run.

### Engines (Build)

Vendored Apache-2.0 references under `engines/hmem/` and `engines/markovian/`. A Node sidecar on `127.0.0.1:8790` translates DESIGN HTTP onto those implementations. The Python loop is fail-closed: if the sidecar is down, recall returns empty and the intercept still finishes.

- **H-MEM:** `remember` / `recall` of refuted citations (`ns:dike-shield`). Session B of the Fase 3 script recalled `artículo 9999` from session A with the trace line `recordado de la sesión <id>`. Conformance 13/13 on both the reference and `engines/src/hmem.ts`.
- **Markovian:** `start` after the router, `step` after each judge. The run is `done` on `publicar` / `abstener` / `escalar` or `max_steps`. Conformance 8/8 on both the reference and `engines/src/markovian.ts`.

Mentioning the engines without a tested function would not count. Both are on the intercept path and in `engines` tests.

## NVIDIA Nemotron

Nemotron is not a logo. FAST Lightning 30B produces the draft the lawyer would have sent. DEEP Ultra 550B judges Diké's verdicts and rewrites. The product thesis is: a large model will invent a cite; Diké will catch it; the same family, on a slower lane, will repair it. The adversarial bank is built to show that delta per lane.

## Cursor

The shield, the sidecar, the bank, the UI and this documentation were written in Cursor during the build window. `docs/CURSOR_LOG.md` is the session record (date, model, task, command, result). The preexisting Diké engine is declared in `PREEXISTING.md` and hashed in `PREEXISTING.sha256`; it is not edited.
