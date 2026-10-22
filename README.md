# Diké Shield

> **Estado: blueprint (no implementado).** Este repo contiene dos cosas:
> - el motor previo de Diké en `vendor/dike/`, declarado en `PREEXISTING.md`;
> - el plan completo para construir Diké Shield en Cursor durante el Open Agent Hackathon 2026.
>
> Empieza por `HANDOFF.md`.

## Qué será

Diké Shield es un escudo agéntico entre NVIDIA Nemotron y un abogado laboral chileno. Funciona así:
- Nemotron responde una pregunta o revisa un borrador de demanda por despido.
- Cada cita normativa se prueba con Diké contra una copia fechada de 25 cuerpos legales chilenos.
- Lo que no se puede probar se repara con un artículo verificado, se retira explicando por qué o lleva a abstenerse.
- Cada respuesta final trae un commitment firmado que cualquiera puede comprobar offline.
- Un banco adversarial mide cuántas citas inventaba cada lane de Nemotron sin el escudo y con él.

Track del hackathon: **The Agent That Can Explain Why**.

## Mapa del repo

| Ruta | Qué es | Estado |
|---|---|---|
| `HANDOFF.md` | Fases, verificación exigida, plan B, entregables | listo |
| `DESIGN.md` | Topología, contrato fijo (API, esquemas, tablas), flujos, límites | listo |
| `SCOPE.md` | Qué entra y qué queda fuera, con su porqué | listo |
| `FUENTES.md` | Hechos externos con URL y fecha de verificación | listo |
| `AGENTS.md` | Reglas para el agente de Cursor que implementa | listo |
| `PREEXISTING.md`, `PREEXISTING.sha256` | Declaración y huella del componente previo | listo |
| `.env.example` | Variables de entorno (solo placeholders) | listo |
| `vendor/dike/` | Motor de Diké (previo; no se edita) | importado |
| `shield/`, `engines/`, `db/`, `zetaris/`, `data/`, `scripts/`, `tests/`, `docs/` | Implementación | por construir |

## Arranque rápido (objetivo de la fase 5)

```bash
cp .env.example .env            # completar con los valores reales; nunca versionar
docker compose up -d            # Postgres del Shield
uv sync && (cd engines && npm ci)
uv run python scripts/setup_dike.py && uv run python db/load_corpus.py
uv run python scripts/smoke_test.py   # 5 líneas PASS
uv run uvicorn shield.api:app --port 8780
```
