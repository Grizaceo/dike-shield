# Diseño

Este es el contrato fijo. El implementador no re-decide nada de lo que está aquí; si algo resulta
imposible, lo anota en `docs/CURSOR_LOG.md` y aplica el plan B del `HANDOFF.md`.

## 1. Topología

```text
Navegador (shield/web, estático)
   │ HTTP
   ▼
shield.api (FastAPI, Python 3.12, :8780)
   ├── shield/llm.py ─────────► Meterless Runtime (Nightshift en VM Windows, red local)
   │                               ├─ lane FAST  → Nemotron 3.5 lightning (endpoint NVIDIA)
   │                               └─ lane DEEP  → Nemotron 3.5 super     (endpoint NVIDIA)
   ├── shield/zetaris.py ─────► Zetaris local (Docker; REST :8888) ──federa──► shield-db
   ├── shield/dike_adapter.py ─► vendor/dike (CLI en subproceso, HOME aislado en .local/dike-home)
   ├── shield/engines.py ─────► engines/ (sidecar Node/TypeScript, :8790): H-MEM y Markovian
   └── shield/trace.py ───────► shield-db (Postgres, docker compose, :55432)
```

Reglas de la topología:
- **Lectura y escritura.** El agente **lee** datos por Zetaris (`run_sql`) y **escribe** directo en Postgres (`psycopg`). Zetaris es la capa de federación y consulta, no de escritura.
- **Clave de NVIDIA.** Vive solo en la pestaña Providers de Nightshift. La app solo conoce `METERLESS_BASE_URL` y `METERLESS_RUNTIME_TOKEN`.
- **Aislamiento de Diké.** Diké nunca toca el `~/.lexo` ni el `~/.dike` reales. El adaptador exporta `HOME`, `LEXO_CONFIG`, `DIKE_USER=shield`, `DIKE_USERS_ROOT`, `DIKE_BINDING_CACHE_DIR`, `DIKE_ROOTS_CACHE_DIR`, `LEXO_CASES_ROOT` y `LEXO_BCN_CACHE_DIR`, todos bajo `DIKE_HOME_DIR`.
- **Red de Docker.** El contenedor de Zetaris tiene que alcanzar `shield-db`. `docker-compose.yml` une `shield-db` a la red externa del compose de Zetaris (nombre **por verificar** con `docker network ls`; esperado `zetaris-platform_default`).

## 2. Modelo de datos (Postgres, esquema `shield`, archivo `db/schema.sql`)

```sql
CREATE SCHEMA IF NOT EXISTS shield;

CREATE TABLE shield.articulos (            -- corpus de Diké cargado desde el pack (db/load_corpus.py)
  gid             text PRIMARY KEY,         -- p. ej. cl.norma.ct:art:0168
  cuerpo          text NOT NULL,            -- nombre canónico aceptado por Diké, p. ej. "Código del Trabajo"
  numero          text NOT NULL,            -- "168", "162 bis"
  texto           text NOT NULL,
  vigencia_desde  date,
  vigencia_hasta  date,                     -- intervalo semiabierto; NULL = vigente
  pack_hash       text NOT NULL
);

CREATE TABLE shield.sesiones (
  id         uuid PRIMARY KEY,
  creada     timestamptz NOT NULL DEFAULT now(),
  escenario  text NOT NULL CHECK (escenario IN ('despido','finiquito','libre')),
  modo       text NOT NULL CHECK (modo IN ('pregunta','auditoria','banco'))
);

CREATE TABLE shield.intercepciones (
  id                uuid PRIMARY KEY,
  sesion_id         uuid NOT NULL REFERENCES shield.sesiones(id),
  entrada           text NOT NULL,
  borrador_original text NOT NULL,
  respuesta_final   text,
  decision          text NOT NULL CHECK (decision IN ('publicar','reparar','abstener','escalar')),
  iteraciones       int  NOT NULL,
  modelo_borrador   text NOT NULL,          -- campo "model" devuelto por el Runtime
  modelo_juez       text,
  commitment        jsonb,                  -- commitment.json + firma, si hubo citas verificadas
  sample_mode       boolean NOT NULL DEFAULT false,
  creada            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shield.citas (
  id               uuid PRIMARY KEY,
  intercepcion_id  uuid NOT NULL REFERENCES shield.intercepciones(id),
  iteracion        int  NOT NULL,
  cita_raw         text NOT NULL,
  cita_normalizada text NOT NULL,
  gid              text,
  estado           text NOT NULL CHECK (estado IN ('VERIFICADA','FALLO')),
  resolucion       text NOT NULL,           -- RESOLVED | AMBIGUOUS | UNRESOLVABLE | otro valor de Diké
  vigencia         text,
  accion           text NOT NULL CHECK (accion IN ('mantener','reparar','retirar')),
  reemplazo_gid    text,
  razon            text NOT NULL
);

CREATE TABLE shield.eventos_traza (
  id               bigserial PRIMARY KEY,
  intercepcion_id  uuid NOT NULL REFERENCES shield.intercepciones(id),
  paso             int  NOT NULL,
  agente           text NOT NULL,           -- router | drafter | extractor | dike | judge | repairer | memory | loop
  accion           text NOT NULL,
  lane             text,                    -- FAST | DEEP | NULL
  modelo           text,
  latencia_ms      int  NOT NULL,
  entrada_resumen  text,
  salida_resumen   text,
  creada           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shield.refutadas (            -- espejo consultable de la memoria H-MEM
  cita_normalizada text PRIMARY KEY,
  veces            int  NOT NULL,
  ultima           timestamptz NOT NULL,
  razon            text NOT NULL
);

CREATE TABLE shield.trampas (
  id               text PRIMARY KEY,
  pregunta         text NOT NULL,
  cita_ficticia    text NOT NULL,
  tipo             text NOT NULL CHECK (tipo IN ('inexistente','ambigua','derogada','cuerpo_equivocado')),
  colision_corpus  boolean NOT NULL         -- debe ser false: la norma ficticia NO existe en el corpus
);

CREATE TABLE shield.banco_corridas (
  id                 uuid PRIMARY KEY,
  creada             timestamptz NOT NULL DEFAULT now(),
  lane               text NOT NULL CHECK (lane IN ('FAST','DEEP')),
  con_escudo         boolean NOT NULL,
  n_preguntas        int NOT NULL,
  citas_total        int NOT NULL,
  citas_no_probadas  int NOT NULL,          -- tasa = citas_no_probadas / citas_total
  abstenciones       int NOT NULL,
  reparaciones       int NOT NULL,
  latencia_p50_ms    int NOT NULL,
  modelo             text NOT NULL,
  sample_mode        boolean NOT NULL
);

CREATE TABLE shield.banco_items (
  id               uuid PRIMARY KEY,
  corrida_id       uuid NOT NULL REFERENCES shield.banco_corridas(id),
  pregunta_id      text NOT NULL,
  respuesta        text NOT NULL,
  citas_total      int NOT NULL,
  citas_no_probadas int NOT NULL,
  decision         text NOT NULL
);
```

`db/load_corpus.py` lee los JSON de artículos del pack instalado por Diké (estructura **por verificar** en la fase 1, en `chile-base/articulos/*.json`) y los mapea a `shield.articulos`. Verificación de carga: 8.544 filas y `pack_hash = af1422d66d1e6eee` en todas.

## 3. Agentes y loop

| Agente | Implementación | Lane | Responsabilidad |
|---|---|---|---|
| router | `shield/agents/router.py` | FAST + reglas | Decide `responder`, `abstener` (fuera del dominio cubierto por el corpus) o `auditar` (llega un texto) |
| drafter | `shield/agents/drafter.py` | FAST | Responde la pregunta con citas en el formato que Diké reconoce. Recibe de H-MEM la lista de citas a evitar |
| extractor | `shield/extractor.py` | regex primero, FAST como respaldo | Extrae y normaliza citas a "artículo N del <cuerpo canónico>" (`shield/cuerpos.py` con los 25 nombres) |
| dike | `shield/dike_adapter.py` | — | Verifica con `dike constancia --json`; nunca reinterpreta el veredicto |
| judge | `shield/agents/judge.py` | DEEP | Con los veredictos de Diké y los artículos verificados (vía Zetaris) decide `publicar`, `reparar`, `abstener` o `escalar`, y explica por qué |
| repairer | `shield/agents/repairer.py` | DEEP | Reescribe usando SOLO artículos con `estado=VERIFICADA` o candidatos de `shield.articulos` que pasen por Diké antes de aceptarse |
| memory | `shield/engines.py` → H-MEM | — | `recall` al inicio (citas refutadas parecidas) y `remember` al final (nuevas refutadas) |
| loop | `shield/loop.py` → Markovian | — | Iteraciones acotadas (`SHIELD_MAX_ITER=3`). Cada paso recibe solo estado acotado: respuesta vigente, veredictos y candidatos |

Reglas duras del loop:
- **Toda cita pasa por Diké.** Ninguna cita llega a `respuesta_final` sin `estado=VERIFICADA` en la iteración final.
- **Agotar el límite no publica.** Si se agota `SHIELD_MAX_ITER` sin llegar a `publicar`, la decisión es `escalar` y la respuesta muestra solo lo probado más la razón.
- **Abstenerse no es fallar.** Cuenta como resultado correcto cuando el corpus no cubre la pregunta.
- **Trazabilidad.** Cada paso escribe un `eventos_traza` con lane, modelo y latencia.

## 4. Contratos externos

### Diké (observado el 2026-10-21; ver `FUENTES.md`)

- Instalación del corpus, una sola vez: `dike starter --user shield install <dir-del-pack> --name chile-base` (lo hace `scripts/setup_dike.py`).
- Verificación: `dike constancia <tmp.md> --json`. Código de salida 0 si todas las citas quedaron verificadas, 1 si alguna no. **El código 1 no es un error del adaptador.**
- Firma: `dike constancia <tmp.md> --emit-commitment <dir> --sign`, con `LEXO_CONTENT_SIGNING_KEY_PATH=$DIKE_SIGNING_KEY_PATH`. La clave es de demo, Ed25519, modo 0600, en `.local/keys/` y generada por `scripts/setup_dike.py`. **Nunca se usa la clave real de custodia del autor.**
- Salida JSON:

```json
{
  "veredicto": "CON_PROBLEMAS",
  "mensaje": "...",
  "alcance": "...",
  "citation_disclosure": {"alcance": ["..."], "verificadas": ["0168"], "no_verificadas": [], "advertencias": ["..."]},
  "problemas": ["texto explicativo por cada cita fallida"],
  "detalles": [{"cita_raw": "artículo 168 del Código del Trabajo", "gid": "cl.norma.ct:art:0168",
                "estado": "VERIFICADA", "resolucion": "RESOLVED", "cuerpo": "...", "texto_hash": "...",
                "vigencia": "IN_FORCE", "vigencia_legible": "...", "fuente_url": "...",
                "fecha_recuperacion": "...", "estado_texto_historico": "..."}],
  "meta": {"documento": "...", "origen": null, "as_of": "2026-10-21", "fecha_constancia": "...",
           "pack_hash": "af1422d66d1e6eee", "total_citas": 4, "citas_verificadas": 2, "citas_fallidas": 2}
}
```

En la prueba, "artículo 60" (sin cuerpo) dio `FALLO/AMBIGUOUS` y "artículo 9999 del Código del Trabajo" dio `FALLO/UNRESOLVABLE`.

### Meterless Runtime

- Cliente `openai` con:
  - `base_url=METERLESS_BASE_URL`;
  - `api_key=METERLESS_RUNTIME_TOKEN`;
  - `default_headers={"meterless-app": METERLESS_APP, "meterless-scope": "user"}`.
- Modelos fijados por variable: `METERLESS_MODEL_FAST` y `METERLESS_MODEL_DEEP`.
  - Son las rutas `meterless/*` con Nemotron que devuelve `GET /models` (descubrimiento en la fase 0).
  - **Prohibido usar `meterless/auto`** en el camino de evidencia del premio.
- Se guarda el campo `model` de cada respuesta en `eventos_traza.modelo`.
- Tiempo máximo por llamada: 60 s. Un solo reintento ante 5xx o timeout. Después, `SAMPLE_MODE` si está activo; si no, `escalar`.

### Zetaris

- `POST {ZETARIS_REST_URL}/sql-editor/sqls/run`
  - headers: `Authorization: Bearer ZETARIS_API_KEY`, `X-Org-ID: ZETARIS_ORG_ID`, `X-Request-ID: <uuid4>`;
  - cuerpo: `{"queryId": "<uuid4>", "sql": "<una sentencia>", "source": "SqlEditor", "limit": N}`;
  - devuelve filas en `data`.
- Una sentencia por request. Solo lectura desde la app.
- `zetaris/register.sql` contiene las sentencias Lightning SQL (una por bloque) que registran `shield-db` como fuente con el nombre `ZETARIS_SOURCE_DB`. La sintaxis exacta se toma de las recetas oficiales (por verificar).

### Sidecar de engines (`engines/`, Node + TypeScript, `127.0.0.1:8790`)

Construido desde las referencias de `meterless/meterless` (`engines/hmem` y `engines/markovian`), con su suite de conformidad en verde. API propia y fija:

| Método y ruta | Cuerpo | Respuesta |
|---|---|---|
| `GET /healthz` | — | `{"ok": true, "hmem": true, "markovian": true}` |
| `POST /hmem/remember` | `{"namespace": "refutadas"\|"trampas", "content": str, "metadata": {...}}` | `{"id": str}` |
| `POST /hmem/recall` | `{"namespace": str, "query": str, "k": int}` | `{"items": [{"id", "content", "score", "metadata"}]}` |
| `POST /markovian/start` | `{"task": str, "max_steps": int}` | `{"run_id": str, "state": {...}}` |
| `POST /markovian/step` | `{"run_id": str, "observation": {...}}` | `{"state": {...}, "done": bool}` |

El sidecar traduce esta API a la de cada referencia. La traducción es interna; la API de arriba no cambia.

### API del Shield (FastAPI)

| Método y ruta | Entrada | Salida |
|---|---|---|
| `GET /healthz` | — | `{"ok", "zetaris", "meterless", "dike", "engines", "sample_mode"}` (cada componente, bool) |
| `POST /v1/shield/answer` | `{"pregunta": str, "escenario": "despido"\|"finiquito"\|"libre", "sesion_id"?: uuid}` | `Resultado` |
| `POST /v1/shield/audit` | `{"texto": str, "escenario": ...}` | `Resultado` más `texto_reparado` |
| `GET /v1/traces/{intercepcion_id}` | — | `{"eventos": [eventos_traza...]}` (leído vía Zetaris) |
| `POST /v1/bench/run` | `{"n_preguntas": 30, "lanes": ["FAST","DEEP"], "con_escudo": [false, true]}` | `{"corrida_ids": [uuid]}` |
| `GET /v1/bench/latest` | — | Métricas por lane y condición, leídas de `banco_corridas` vía Zetaris |
| `GET /v1/commitments/{intercepcion_id}` | — | ZIP con `commitment.json`, `commitment.sig.json` y la clave pública de demo |

`Resultado` = `{"intercepcion_id", "sesion_id", "decision", "respuesta_final", "citas": [{"cita_raw", "gid", "estado", "resolucion", "vigencia", "accion", "reemplazo_gid", "razon"}], "iteraciones", "modelos": {"borrador", "juez"}, "commitment_disponible": bool, "sample_mode": bool}`.

## 5. Flujos

1. **Pregunta.**
   1. router.
   2. Si queda fuera del corpus, abstención explicada.
   3. Si no: H-MEM recall → drafter (FAST) → extractor → Diké.
   4. judge (DEEP): decide `publicar`, `reparar` (repairer DEEP, y de vuelta a Diké), `abstener` o `escalar`. Son 3 iteraciones como máximo, controladas por Markovian.
   5. Firma de las citas verificadas, H-MEM remember y respuesta.
2. **Auditoría.** Texto pegado → extractor → Diké → judge → repairer para las citas fallidas (cada reemplazo vuelve a pasar por Diké) → informe por cita, texto reparado y commitment.
3. **Banco.** Se parte de `data/samples/preguntas.jsonl` (preguntas laborales sintéticas) y `data/samples/trampas.jsonl` (preguntas con citas ficticias plausibles; `colision_corpus` debe ser `false`, verificado con Diké antes de usarlas). Por cada lane:
   - **Sin escudo:** respuesta cruda de Nemotron, y Diké solo mide.
   - **Con escudo:** el flujo 1.

   Las métricas van a `banco_corridas` y `banco_items`, y alimentan el dashboard.
4. **Memoria entre sesiones.** En una sesión, una cita queda refutada. En otra sesión, H-MEM la recupera: el drafter la evita y la traza muestra "recordado de la sesión <id>". Es la evidencia del engine.

## 6. UI (`shield/web/`, HTML/JS sin build) y etiquetas obligatorias

Pantallas:
1. Preguntar o pegar texto, con selector de escenario.
2. Resultado, con cada cita marcada: verificada, reparada, retirada o abstención.
3. Traza paso a paso (agente, lane, modelo, latencia).
4. Antes y después (borrador crudo frente a respuesta final).
5. Descarga del commitment, con la receta de verificación offline.
6. Dashboard del banco.

Etiquetas que el implementador **no puede suavizar ni eliminar**:
- Bajo cada cita verificada: "Probado por Diké: existe, tiene texto citable y estaba vigente al {as_of} en el corpus {pack_hash}".
- Fija en la pantalla de resultado: "Diké no evalúa si la norma respalda el argumento; eso es juicio del abogado".
- Opiniones del juez sobre el fondo: "Opinión del modelo {modelo}, no verificada".
- Cuando `SAMPLE_MODE=true`: "Modo muestra: respuestas grabadas de una corrida real del {fecha}".
- En el banco: "Cifras medidas sobre {n} preguntas sintéticas; no son una estimación de la tasa en producción".

## 7. Límites declarados de la plataforma

- Corpus de 25 cuerpos legales, fechado. Lo que no está se rechaza o lleva a abstenerse (ver `FUENTES.md`).
- Nightshift corre en una VM Windows (no hay edición Linux). Si la VM se cae, `SAMPLE_MODE` cubre la demo, pero la evidencia del premio debe grabarse con el Runtime vivo.
- El endpoint gratuito de NVIDIA tiene límites. El banco usa caché (`data/cache/`) y 30 preguntas por defecto.
- Zetaris pide 8 GB para Docker. Durante el hackathon hay que bajar otros servicios pesados de la máquina.
