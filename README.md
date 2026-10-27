# Diké Shield

An agentic interceptor between NVIDIA Nemotron and a Chilean labor lawyer.

Nemotron drafts a dismissal or severance answer. Every statutory citation is proven with Diké against a dated snapshot of 25 Chilean codes. What cannot be proven is repaired with a verified article, withdrawn with a reason, or escalated. The final answer ships an Ed25519 commitment that anyone can check offline. An adversarial bank measures invented citations per Nemotron lane with and without the shield.

Hackathon track: **The Agent That Can Explain Why**.

Pre-existing component: the Diké engine in `vendor/dike/` (see `PREEXISTING.md`). Everything else in this repository was built in Cursor during the Open Agent Hackathon 2026 window.

## What it does

1. **Question or audit.** FAST Nemotron drafts, or the lawyer pastes a brief.
2. **Prove.** Diké returns `VERIFICADA` or `FALLO` (AMBIGUOUS / UNRESOLVABLE). The loop never reinterprets that verdict.
3. **Repair.** DEEP Nemotron rewrites using only verified articles, then Diké runs again.
4. **Remember.** H-MEM stores refuted cites so the next session does not repeat them.
5. **Commit.** Signed proof of the citations that survived.
6. **Measure.** Four bank runs: FAST/DEEP × with/without the shield.

## Architecture

```text
Browser (shield/web, Spanish UI)
   │ HTTP
   ▼
shield.api  FastAPI :8780
   ├── shield/llm.py      → Meterless Nightshift Runtime (Windows VM)
   │                         FAST  nvidia/nemotron-3.5-lightning-30b-a3b
   │                         DEEP  nvidia/nemotron-3-ultra-550b-a55b
   ├── shield/zetaris.py  → Zetaris Lightning SQL :8888  →  shield-db
   ├── shield/dike_adapter.py → vendor/dike CLI (HOME isolated under .local/dike-home)
   ├── shield/engines.py  → Node sidecar :8790  (H-MEM + Markovian)
   └── shield/trace.py    → Postgres shield-db :55432
```

Writes go to Postgres (`psycopg`). Reads that the jury and the UI care about go through Zetaris views (`shield_pg.articulos`, not `shield_pg.shield.articulos`). The NVIDIA API key never enters this repo: it lives only in the Nightshift Providers tab.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 20+ and npm
- Docker, with the local Zetaris compose already up (`zetaris_default` network)
- Meterless Nightshift Runtime on a Windows VM on the LAN, **or** `SAMPLE_MODE=true` for the recorded demo
- Do not use `meterless/auto`, `meterless/fast`, or `meterless/deep` on the prize path

## Setup (from a clean copy of this repo)

Timed from a folder that contains only the repository files (no `.venv`, no `node_modules`, no `.env`, no `.local/`):

```bash
cp .env.example .env
# Fill ZETARIS_API_KEY, SHIELD_DB_PASSWORD, SHIELD_DB_URL.
# For a live Runtime: fill METERLESS_BASE_URL and METERLESS_RUNTIME_TOKEN from the Nightshift Console.
# For the recorded demo: SAMPLE_MODE=true (replies from data/cache/, labeled in the UI).
chmod 600 .env

docker compose up -d          # shield-db on :55432, attached to zetaris_default

uv sync
(cd engines && npm ci)
(cd engines/hmem/reference && npm ci)
(cd engines/markovian/reference && npm ci)

uv run python scripts/setup_dike.py     # isolated Diké HOME + demo signing key
uv run python db/load_corpus.py         # 8544 rows, pack_hash af1422d66d1e6eee
uv run python scripts/register_zetaris.py
```

Sidecar and API (two terminals):

```bash
(cd engines && npm start)               # http://127.0.0.1:8790
uv run uvicorn shield.api:app --host 127.0.0.1 --port 8780
```

Open `http://127.0.0.1:8780`. The UI is Spanish. Code and this README are English.

Eligibility smoke (needs live Zetaris, Diké corpus, and Nightshift unless you skip the Meterless checks):

```bash
uv run python scripts/smoke_test.py     # 5 lines PASS
```

## SAMPLE_MODE

`data/cache/` holds recorded FAST/DEEP replies from the live Nightshift run of 2026-10-27 (Lightning 30B drafter, Ultra 550B judge/repairer). When `SAMPLE_MODE=true`, `shield/llm.py` serves those files and never needs the Runtime. The UI banner reads:

> Modo muestra: respuestas grabadas de una corrida real del 2026-10-27

That is a demo path, not a substitute for the NVIDIA prize receipt. The live receipt (model ids, latency, token hidden) is in `docs/CURSOR_LOG.md` (Fase 2, 2026-10-27T04:36) and in `docs/video/`.

## Tests

```bash
uv run pytest -q
(cd engines && npm test)
HMEM_IMPL=$PWD/engines/src/hmem.ts npx tsx engines/hmem/conformance/runner.ts
MARKOVIAN_IMPL=$PWD/engines/src/markovian.ts npx tsx engines/markovian/conformance/runner.ts
(cd vendor/dike && sha256sum -c ../../PREEXISTING.sha256)
```

Unit tests inject fakes. They never call Nightshift.

## Usage

| Action | Endpoint |
|---|---|
| Health | `GET /healthz` |
| Ask | `POST /v1/shield/answer` `{"pregunta","escenario"}` |
| Audit pasted text | `POST /v1/shield/audit` |
| Trace | `GET /v1/shield/trace/{id}` |
| Commitment ZIP | `GET /v1/commitments/{id}` |
| Run bank | `POST /v1/bench/run` |
| Latest bank | `GET /v1/bench/latest` |

Scenarios: `despido`, `finiquito`, `libre`. Synthetic fixtures: `data/samples/despido_01.md`, `finiquito_01.md`, 30 questions, 20 traps (all `FALLO`, none collide with the corpus).

## Dependencies

| Piece | Role |
|---|---|
| FastAPI, uvicorn, psycopg, httpx | API, Postgres writes, tests |
| Node + tsx | Meterless engine sidecar |
| Meterless H-MEM + Markovian (Apache-2.0 reference, vendored) | Cross-session memory; bounded loop |
| Zetaris Lightning | Federated reads of `shield.*` |
| Nightshift Runtime | Only AI provider; Nemotron FAST/DEEP |
| Diké CLI (`vendor/dike`, MIT) | Citation proof + commitments |
| Postgres 16 | `shield-db` |

Sponsor write-up: [`docs/SPONSORS.md`](docs/SPONSORS.md).

## Limits

- Corpus is 25 Chilean statutes, dated 2026-08-18 (`pack_hash` `af1422d66d1e6eee`). Municipal, procurement, transparency, traffic and Fintech law are out of scope: the router abstains.
- Diké proves existence, citable text and force-in-time. It does not prove that the article supports the lawyer's argument.
- Nightshift has no Linux x86_64 build. If the Windows VM is down, SAMPLE_MODE covers the demo; the prize path needs a live Runtime.
- Bank figures on the dashboard are measured on synthetic items. The label says so and must stay.
- Do not run `sudo`. Do not write `~/.lexo`, `~/.dike` or `~/dike`. Secrets stay in `.env` mode 600.

## Deliverables

- Deck: `docs/deck/dike-shield.pptx`
- Video: `docs/video/dike-shield.mp4` (storyboard in `docs/video/README.md`)
- Cursor log: `docs/CURSOR_LOG.md`
- Jury preexisting text: `PREEXISTING.md` §4

## Map

| Path | What |
|---|---|
| `HANDOFF.md` | Phases, verification, plan B |
| `DESIGN.md` | Fixed contract |
| `shield/` | Agents, loop, API, UI |
| `engines/` | H-MEM + Markovian sidecar |
| `data/cache/` | SAMPLE_MODE recordings (versioned) |
| `data/samples/` | Synthetic questions, traps, briefs |
| `vendor/dike/` | Pre-existing engine (do not edit) |
