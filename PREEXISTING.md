# Componentes preexistentes

El Open Agent Hackathon 2026 exige declarar el código y los datos anteriores a la ventana de
construcción (22-oct-2026, 00:00 UTC). Este archivo es esa declaración. Lo que no figura aquí se
construye dentro de la ventana y aparece en la historia git **después** del commit de importación.
El commit de importación tiene fecha dentro de la ventana, pero su contenido es previo y está
declarado aquí.

## 1. Motor de Diké

| Campo | Valor |
|---|---|
| Qué es | Motor offline que verifica citas normativas chilenas (`dike constancia`, `dike starter`) y emite commitments Ed25519 verificables por terceros |
| Dónde está | `vendor/dike/`. No se edita: se usa solo a través de su CLI (`shield/dike_adapter.py`) |
| Origen | Repositorio del autor `Grizaceo/dike`, rama `limpieza-lexocl`, commit `da31d1694fd60415937c01461556a308dea3e97a` (14-oct-2026) |
| Qué se copió | Los 101 archivos versionados de `lexo_cli/`, `shared/`, `packages/`, `corpus/`, `pyproject.toml`, `LICENSE`, `conftest.py` y `.origen.json` |
| Cómo se copió | `git archive` de esa ref: solo archivos versionados, sin historia |
| Prueba de fidelidad | `PREEXISTING.sha256` trae el sha256 de cada archivo. Todos coinciden con la ref de origen (verificado el 2026-10-21) |
| Licencia | MIT (`vendor/dike/LICENSE`). El corpus se rige por las condiciones de Ley Chile/BCN (`vendor/dike/corpus/README.md`) |
| Qué NO se copió | El kit de la postulación de Diké a otro hackathon (`docs/hackathon/`), el plugin para el agente Hermes (`hermes-plugin/`) y `scripts/`. No forman parte del motor |

Para comprobarlo: `cd vendor/dike && sha256sum -c ../../PREEXISTING.sha256`.

Seis archivos de prueba del motor dependen del kit excluido y fallan aquí por diseño:
`lexo_cli/tests/_kit_commitment.py`, `test_constancia_emit_commitment.py`, `test_content_signing.py`,
`test_demo_bli_e2e.py`, `test_keys_md_ejecutable.py` y `test_verificar_tercero.py`.

El motor nació de un código más grande y conserva algunos residuos: valores por defecto que apuntan a
servicios que esta distribución no incluye (un índice de búsqueda, un runtime de agentes, una ruta de
perfil local) e identificadores `lexo.cl` aceptados solo como legado. `dike constancia` no usa nada de eso.

## 2. Datos previos

- Corpus `chile-base`, `pack_hash` `af1422d66d1e6eee`: snapshot de 25 cuerpos legales chilenos
  (8.544 artículos) descargado de Ley Chile (BCN) el 2026-08-18, con ventanas de vigencia corregidas el
  2026-09-27. Detalle y lista de normas en `vendor/dike/corpus/README.md` y en `FUENTES.md`.

## 3. Lo nuevo

Todo lo demás se construye en la ventana:
- el paquete `shield/`, los agentes y el loop;
- la integración con Zetaris, Meterless (Nightshift y Engines) y NVIDIA Nemotron;
- el banco adversarial;
- la UI;
- los datos sintéticos de demo;
- los tests y la documentación.

Se desarrolla en Cursor, con registro en `docs/CURSOR_LOG.md`.

## 4. Texto para el formulario de envío (en inglés, para el jurado)

> Pre-existing component: the Diké citation-verification engine (MIT), vendored unmodified in
> `vendor/dike/` from Grizaceo/dike@da31d16, with a 25-statute Chilean corpus snapshot
> (pack af1422d66d1e6eee). A file-level SHA-256 manifest is in `PREEXISTING.sha256`. Everything else in
> this repository was built in Cursor during the build window: the agents, the Zetaris data layer, the
> Meterless Engines and Nightshift runtime integration, the NVIDIA Nemotron lanes, the adversarial
> benchmark, the UI and the tests. See the git history after the import commit.
