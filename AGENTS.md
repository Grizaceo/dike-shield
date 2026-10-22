# AGENTS.md: reglas para el agente que implementa (Cursor)

Lee `HANDOFF.md` y después `DESIGN.md` antes de escribir código. Sigue las fases en orden y no
re-decidas el contrato de `DESIGN.md`.

## Comandos

```bash
uv sync                                   # dependencias Python desde uv.lock (versionado)
docker compose up -d                      # shield-db
uv run python scripts/setup_dike.py       # corpus de Diké en el HOME aislado + clave de demo
uv run python db/load_corpus.py
uv run pytest -q
(cd engines && npm ci && npm test)        # sidecar de Meterless Engines
uv run python scripts/smoke_test.py
uv run uvicorn shield.api:app --port 8780
```

## Reglas

- **No edites `vendor/dike/`.** Diké se usa solo por su CLI desde `shield/dike_adapter.py`, con el HOME aislado de `DIKE_HOME_DIR`. Al terminar, comprueba `cd vendor/dike && sha256sum -c ../../PREEXISTING.sha256`.
- **Nunca escribas en el `~/.lexo` ni en el `~/.dike` del usuario**, ni uses su clave de custodia.
- **Secretos solo en `.env`.** No los imprimas ni los pegues en el log, las trazas o los commits. La clave de NVIDIA vive solo en Nightshift.
- **Modelos.** Llama siempre a `METERLESS_MODEL_FAST` o `METERLESS_MODEL_DEEP`. No uses `meterless/auto` en el camino del premio.
- **Ninguna cita sin Diké.** Ninguna cita llega a la respuesta final sin `estado=VERIFICADA`. Las etiquetas obligatorias de `DESIGN.md` §6 no se suavizan.
- **Datos.** Solo sintéticos. Sin scraping, sin descargas de normas nuevas y sin datos reales de personas.
- **Tests.** Cada agente se prueba con un LLM falso inyectado; los tests de punta a punta corren en `SAMPLE_MODE`.
- **Idioma.** Código e identificadores en inglés; UI en español; README, `docs/SPONSORS.md`, deck y video en inglés.
- **Commits.** Pequeños, con mensaje que explique el porqué. Sin secretos. Sin push: el autor publica.
- **Registro obligatorio** (requisito del hackathon). Después de cada sesión, agrega una entrada en `docs/CURSOR_LOG.md` con fecha, modelo de Cursor (Composer o Grok), fase, tarea, archivos tocados, resultado y evidencia (comando y salida).
