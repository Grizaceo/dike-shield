# Fuentes

Cada hecho externo que usa este blueprint, con su fuente y fecha de verificación. Lo que no se
pudo leer directamente queda marcado **por verificar** y se resuelve en la fase 0 del `HANDOFF.md`.

## Hackathon

| Hecho | Fuente | Verificado |
|---|---|---|
| Ventana: 22-oct-2026 00:00 UTC a 27-oct-2026 23:45 UTC; envío por HackOS; plazo duro | Official Rules, https://hackathon.genai.works/event/open-agent-hackathon-2026 | 2026-10-21 |
| Tracks; el envío elige uno (cambiable hasta el cierre) | ídem | 2026-10-21 |
| Rúbrica: Impact 30, Technical 20, Innovation 15, Demo 15, Product & UX 10, Sponsor tech 10; desempate por Impact y luego hora de envío | ídem | 2026-10-21 |
| Obligatorio: integrar Zetaris y Meterless; desarrollar en Cursor; NVIDIA donde aporte | ídem | 2026-10-21 |
| Lo commiteado antes de la ventana no es elegible salvo componentes previos declarados; el código de producto previo se declara en el formulario | ídem | 2026-10-21 |
| Entregables: video de 1-4 min, slide deck, repo GitHub con README (setup, uso, dependencias), explicación del uso de Zetaris, Meterless, Cursor y NVIDIA | ídem | 2026-10-21 |
| Premio "Best use of NVIDIA Nemotron": NVIDIA DGX Spark | ídem | 2026-10-21 |
| Elegibilidad: "Zetaris and Meterless must be running on your machine to be eligible" | Participant Setup Guide (PDF distribuido en HackOS, "Last updated 21 October 2026"), p. 2 | 2026-10-21 |
| Build rule: al menos un Meterless Engine implementado en una función real y probada; mencionarlo o dejar una dependencia sin uso no cuenta | Setup Guide, sección 3.2 | 2026-10-21 |
| Power rule: Meterless Nightshift como proveedor principal de IA de la app; Nemotron vía Nightshift para optar al premio NVIDIA | Setup Guide, sección 4 | 2026-10-21 |

## Zetaris

| Hecho | Fuente | Verificado |
|---|---|---|
| Instalación local en Docker: 8 GB y 4 CPU para Docker, 15 GB de disco, imágenes amd64 | https://zetaris.github.io/getting-started/docs/install/choose-install.html | 2026-10-21 |
| Bundle `zetaris-platform.zip` y credenciales del registro desde la página Run locally de Zetaris Cloud; `./preflight.sh`, `docker compose up -d`, `./verify.sh` (9 checks) | https://zetaris.github.io/getting-started/docs/install/updated_zetaris_installation_guide.html y Setup Guide, 1.1-1.6 | 2026-10-21 |
| Endpoints locales: UI `:3000`, REST `:8888/api/v1.0`, JDBC `:10000` | Setup Guide, 1.9 | 2026-10-21 |
| REST: `POST /sql-editor/sqls/run` con `Authorization: Bearer <API key>`, `X-Org-ID` (1 en instalación local) y `X-Request-ID` (UUID nuevo); cuerpo `{"queryId","sql","source":"SqlEditor","limit"}`; filas en `data` | Setup Guide, 1.9 y smoke_test.py (p. 24) | 2026-10-21 |
| Zetaris no lee archivos del laptop: hay que servirlos como base de datos, API REST o bucket tipo S3 | Setup Guide, "Files on your laptop" (p. 22) | 2026-10-21 |
| Recetas y reglas para agentes (Lightning SQL, una sentencia por request, no imprimir credenciales) | https://github.com/zetaris/getting-started (README, AGENTS.md) | 2026-10-21 |
| Sintaxis Lightning SQL para registrar una base Postgres como fuente | `~/zetaris-getting-started/docs/guides/zetaris-lightning-sql-commands.md` §4.1–4.3: `CREATE DATASOURCE <name> DESCRIBE BY '…' OPTIONS (jdbcdriver 'org.postgresql.Driver', jdbcurl 'jdbc:postgresql://…', username '…', password '…', fetchsize '1000')`; luego `REGISTER DATASOURCE TABLE '<table>' FROM <datasource>` o `REGISTER DATASOURCE TABLES FROM <datasource>`. Ejemplo oficial `crm_pg`. Dry-run obligatorio antes de crear objetos en vivo. | 2026-10-22 |
| Red Docker del compose local de Zetaris | `docker network ls`: nombre real `zetaris_default` (no `zetaris-platform_default`) | 2026-10-27 |

## Meterless

| Hecho | Fuente | Verificado |
|---|---|---|
| Nightshift existe para Windows, Mac (M1+ y M5+), DGX (AppImage aarch64) y web; no hay edición Linux x86_64 | https://meterless.ai/ | 2026-10-21 |
| La edición web no expone el Runtime local que necesita la app | Setup Guide, 4.2 | 2026-10-21 |
| Runtime compatible con OpenAI: `POST /v1/chat/completions`, `GET /v1/models`, `/healthz`; `Authorization: Bearer <token de la Console>`; headers `meterless-app` y `meterless-scope: user` | Setup Guide, 4.5-4.6 | 2026-10-21 |
| `meterless/auto` es un modo de ruteo y puede usar un modelo no NVIDIA: para el premio hay que fijar un lane con Nemotron | Setup Guide, 4.6 | 2026-10-21 |
| Engines: H-MEM, World Model, Markovian y Scout Intent; cada uno es una spec AGENTS.md con referencia ejecutable y suite de conformidad | https://github.com/meterless/meterless (README) | 2026-10-21 |
| La conformidad de H-MEM corre en TypeScript: `HMEM_IMPL=<build> npx tsx conformance/runner.ts` | https://github.com/meterless/meterless/blob/main/engines/hmem/AGENTS.md | 2026-10-21 |
| Comando de conformidad de Markovian | `MARKOVIAN_IMPL=/abs/path/to/your/index.ts npx tsx conformance/runner.ts` | https://github.com/meterless/meterless/blob/main/engines/markovian/AGENTS.md (raw, 2026-10-27) | 2026-10-27 |
| Prompts IDEATE / IMPLEMENT / COMBINE / HARDEN / POWER (incluye "Add Meterless as a provider") | https://meterless.ai/engines.html (sección de prompts; POWER incluye el contrato de provider) | 2026-10-27 |

## NVIDIA

| Hecho | Fuente | Verificado |
|---|---|---|
| Endpoints de Nemotron en build.nvidia.com/models (algunos "Free Endpoint" para prototipos, con límites) | Setup Guide, 4.3 | 2026-10-21 |
| Lanes sugeridos: `nvidia/nemotron-3.5-lightning-30b-a3b` (rápido) y `nvidia/nemotron-3.5-super-vl-120b-a12b` (profundo) | Setup Guide, 4.4 ("examples, not guaranteed entitlements") | 2026-10-21 |
| Nombres exactos en Nightshift GET /models (esta máquina) | Cloud: `nvidia/nemotron-3.5-lightning-30b-a3b`, `nvidia/nemotron-3-ultra-550b-a55b` (más Bolt/Embed/Rerank). Super VL 120B no aparece; DEEP asentado = Ultra 550B. 86 ids, HTTP 200 | 2026-10-27 |

## Corpus de Diké (dato previo)

| Hecho | Fuente | Verificado |
|---|---|---|
| Snapshot de Ley Chile (BCN) del 2026-08-18; `pack_hash` `af1422d66d1e6eee`; 25 cuerpos legales y 8.544 artículos | `vendor/dike/corpus/README.md` e instalación de prueba (`dike starter install`) | 2026-10-21 |
| Cuerpos incluidos: Constitución; Códigos del Trabajo, Civil, de Comercio, Penal, Procesal Penal, de Procedimiento Civil, Orgánico de Tribunales, Tributario y de Aguas; leyes 16.744, 17.322, 18.046, 18.092, 18.216, 19.496, 19.628, 19.728, 19.828, 19.968, 20.000, 20.066, 20.720 y 21.719; DL 3.500 | `includedLeychileCodes` del pack y los `@id` ELI de sus artículos | 2026-10-21 |
| No incluidos (fuera de alcance): ley de municipalidades, Ley 19.886 de compras públicas, Ley 20.285 de transparencia, Ley Fintech, ley de tránsito | misma lista | 2026-10-21 |
| Fuente oficial usada al construir el corpus: `https://nuevo.leychile.cl/servicios/Navegar/get_norma_json` (no se consulta en runtime) | `vendor/dike/corpus/README.md` | 2026-10-21 |

## Contrato observado del motor (no es externo, se fija aquí por trazabilidad)

`dike constancia <archivo.md> --json`, ejecutado el 2026-10-21 sobre un escrito sintético con 4 citas:
- devolvió `veredicto: CON_PROBLEMAS`, `detalles[].estado` en `VERIFICADA|FALLO`, `resolucion` en `RESOLVED|AMBIGUOUS|UNRESOLVABLE` y `vigencia: IN_FORCE` para las verificadas;
- terminó con código de salida 1 porque había citas no verificadas.

El esquema completo está en `DESIGN.md`.
