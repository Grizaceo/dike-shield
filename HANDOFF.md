# HANDOFF: implementar Diké Shield

## Estado

- **Blueprint listo; nada implementado.**
- El motor de Diké está importado y verificado: `vendor/dike/`, con su declaración en `PREEXISTING.md`.
- El contrato fijo está en `DESIGN.md`, el alcance en `SCOPE.md` y los hechos externos en `FUENTES.md`.

## Objetivo

Entregar en HackOS, antes del **27-oct-2026 23:45 UTC** (apuntar al lunes 26 en la noche), una
demo reproducible de Diké Shield en el track **The Agent That Can Explain Why**, que además compita
por el premio **Best use of NVIDIA Nemotron**.

## Restricciones (no negociables)

1. **Se implementa en Cursor**, con Composer o Grok. Es requisito del hackathon. Cada sesión se registra en `docs/CURSOR_LOG.md` con fecha, modelo, tarea, archivos y resultado.
2. **`vendor/dike/` no se edita.** Se usa solo vía `shield/dike_adapter.py` (CLI en subproceso). Si aparece un bug del motor, se documenta y se rodea en el adaptador.
3. **Diké nunca toca el `~/.lexo` ni el `~/.dike` reales** ni la clave de custodia del autor (aislamiento descrito en `DESIGN.md` §1).
4. **Secretos solo en `.env`**, que está ignorado. La clave de NVIDIA va solo en Nightshift. Nunca se imprimen tokens en logs, trazas ni capturas.
5. **Solo datos sintéticos o anonimizados.** Nada de scraping ni descargas de normas nuevas sin autorización del autor.
6. **El repo `Grizaceo/dike` y su postulación a otro hackathon no se tocan.** Nada se publica ni se pushea sin el autor.
7. **El contrato de `DESIGN.md` no se re-decide.** Si algo es imposible, se anota en el log y se aplica el plan B.

## Fases

Cada fase termina solo con su evidencia real (comando y salida), anotada en `docs/CURSOR_LOG.md`.

### Fase 0: entorno y hechos por verificar (jue 22 y vie 23 por la mañana)

1. **Zetaris local.** Bundle desde Zetaris Cloud, `./preflight.sh`, `docker compose up -d` y `./verify.sh` con 9/9. El autor crea la cuenta de administrador y la API key de Zetaris; el agente nunca las crea.
2. **VM Windows con Nightshift** (receta en las notas locales del autor):
   - proveedor NVIDIA configurado en Providers;
   - un lane FAST y uno DEEP con Nemotron;
   - el token y la URL del Runtime copiados de la Console a `.env`.
3. **Descubrir rutas.** `GET {METERLESS_BASE_URL}/models` para elegir las rutas `meterless/*` de cada lane y escribirlas en `METERLESS_MODEL_FAST` y `METERLESS_MODEL_DEEP`.
4. **Cerrar los "por verificar" de `FUENTES.md`:**
   - sintaxis Lightning SQL para registrar Postgres;
   - comando de conformidad de Markovian;
   - página de prompts de engines;
   - nombres de modelos del catálogo;
   - red de Docker de Zetaris.
5. **`scripts/smoke_test.py` en verde**, con 5 PASS: Zetaris web, Zetaris SQL, Meterless `/models`, un chat con la ruta FAST y Diké verificando una cita conocida.

**Hecho cuando:** smoke con 5 PASS y `FUENTES.md` actualizado, sin ningún "por verificar".

### Fase 1: capa de datos y Diké (vie 23 por la tarde)

1. `docker-compose.yml` con `shield-db` (Postgres 16, puerto 55432, unido a la red de Zetaris) y `db/schema.sql`.
2. `scripts/setup_dike.py`: instala el corpus en el HOME aislado y genera la clave de demo.
3. `db/load_corpus.py` y `zetaris/register.sql`.
4. `shield/zetaris.py` (`run_sql`), `shield/dike_adapter.py` y `shield/cuerpos.py`.
5. `tests/test_dike_adapter.py` reproduce el caso observado: 2 VERIFICADA, 1 AMBIGUOUS y 1 UNRESOLVABLE.

**Hecho cuando:**
- `SELECT count(*) FROM <fuente>.shield.articulos` vía Zetaris devuelve 8544;
- los tests del adaptador pasan;
- `ls ~/.lexo` del usuario sigue sin cambios (comparar la fecha de modificación antes y después).

### Fase 2: el escudo de punta a punta (sáb 24 por la mañana)

1. Implementar `shield/llm.py`, el router, el drafter, el extractor, el judge y el repairer.
2. Implementar el loop simple (sin Markovian todavía) y `shield/trace.py`.
3. Exponer `POST /v1/shield/answer` y `/v1/shield/audit`.
4. Agregar `tests/test_loop.py` con un LLM falso (inyectado) que cubra publicar, reparar, abstener y escalar.

**Hecho cuando:**
- una pregunta real de despido con el Runtime vivo pasa por todo el flujo;
- la traza tiene modelos Nemotron en `eventos_traza.modelo`;
- el borrador traía una cita no probada y la respuesta final no la contiene.

> **PUERTA del sábado 24 a las 12:00 (hora de Chile):** si Zetaris y Nemotron vía Nightshift no responden de verdad, **se abandona**. Sin ellos no hay elegibilidad. El autor protege su otra postulación.

### Fase 3: H-MEM (sáb 24 por la tarde)

1. Crear `engines/` desde la referencia de H-MEM y dejar su conformidad en verde.
2. Implementar el servidor HTTP del sidecar (rutas `hmem/*` y `healthz`) y `shield/engines.py`.
3. Integrar recall y remember en el loop, más el espejo en `shield.refutadas`.
4. Agregar `tests/test_memory.py`: refutar en la sesión A y anticipar en la sesión B.

**Hecho cuando:** la conformidad de H-MEM está en verde (salida pegada en el log) y la demo de dos sesiones muestra "recordado de la sesión <id>".

### Fase 4: Markovian, banco y UI (dom 25)

1. Agregar el Markovian del sidecar (conformidad en verde) y conectar `shield/loop.py` a `markovian/start` y `markovian/step`.
2. Preparar los datos del banco: `data/samples/preguntas.jsonl` (30 preguntas) y `trampas.jsonl` (20 trampas, todas con `colision_corpus=false` verificado por Diké).
3. Implementar `shield/bench/` y los endpoints del banco.
4. Construir la UI completa con las etiquetas obligatorias, el segundo escenario (finiquito) y `data/samples/despido_01.md` y `finiquito_01.md`.

**Hecho cuando:**
- el banco produce 4 corridas (FAST/DEEP × sin/con escudo) con la tasa de citas no probadas por condición;
- la UI muestra traza, antes y después y el dashboard;
- `pytest` pasa completo.

### Fase 5: endurecer y documentar (lun 26)

1. `SAMPLE_MODE` con respuestas grabadas de corridas reales en `data/cache/`, etiquetado en la UI.
2. Instalación desde cero en una carpeta limpia siguiendo solo el README, cronometrada.
3. README en inglés (setup, uso, dependencias, arquitectura y límites), `docs/SPONSORS.md` en inglés y `docs/CURSOR_LOG.md` completo.
4. Revisar `PREEXISTING.md` y comprobar `sha256sum -c`.
5. Deck y video:
   - **Deck:** problema y usuario; solución; arquitectura; stack; uso de Zetaris y Meterless; qué tuvo de único; visuales; futuro.
   - **Video (1-4 min):** pregunta → cita inventada atrapada → reparación verificada → commitment comprobado offline → memoria entre sesiones → cifra del banco por lane. Debe mostrar la conexión al Runtime y, ocultando las claves, el recibo de Nightshift con el modelo Nemotron.

**Hecho cuando:** la instalación limpia funciona, el escaneo de secretos (`gitleaks` o `rg`) está limpio y el video y el deck están listos.

### Fase 6: envío (lun 26 en la noche o mar 27 temprano)

- **El autor:** crea el remoto y hace push, publica el repo tras el escaneo y completa el formulario de HackOS (track, video, deck, repo, explicación de sponsors y declaración de componentes previos copiada de `PREEXISTING.md` §4).
- **El agente** no hace push ni publica.

## Plan B

| Falla | Respuesta |
|---|---|
| Nightshift no corre en la VM o Meterless no acepta la VM | Preguntar en Help Meterless (fase 0). Si no hay solución antes de la puerta del sábado, abandonar |
| Endpoint de NVIDIA limitado o lento | Caché de respuestas, banco de 15 preguntas y lane DEEP solo para el juez |
| La conformidad de Markovian no pasa | Entregar con H-MEM (basta un engine) y loop simple; documentarlo con honestidad |
| La conformidad de H-MEM no pasa | Cambiar a Markovian como engine principal; si ninguno pasa, no hay elegibilidad: abandonar |
| Extractor frágil con texto libre | Pedir al drafter el formato canónico y limitar la auditoría a ese formato |
| Zetaris no alcanza `shield-db` | `host.docker.internal` con `extra_hosts: host-gateway`; si falla, Postgres dentro de la red del compose de Zetaris |
| Falta tiempo | Recortar en este orden: segundo escenario, modo auditoría, Markovian, dashboard. Nunca recortar el banco ni las etiquetas |

## Verificación de cierre

Evidencia, no prosa:

```bash
uv run pytest -q
(cd engines && npm test) && <comandos de conformidad H-MEM y Markovian>
uv run python scripts/smoke_test.py
(cd vendor/dike && sha256sum -c --quiet ../../PREEXISTING.sha256)
rg -n -i '(api[_-]?key|token|secret)\s*[:=]\s*\S{12,}' --glob '!.env.example' .
git status --short
```
