CREATE SCHEMA IF NOT EXISTS shield;

CREATE TABLE shield.articulos (
  gid             text PRIMARY KEY,
  cuerpo          text NOT NULL,
  numero          text NOT NULL,
  texto           text NOT NULL,
  vigencia_desde  date,
  vigencia_hasta  date,
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
  modelo_borrador   text NOT NULL,
  modelo_juez       text,
  commitment        jsonb,
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
  resolucion       text NOT NULL,
  vigencia         text,
  accion           text NOT NULL CHECK (accion IN ('mantener','reparar','retirar')),
  reemplazo_gid    text,
  razon            text NOT NULL
);

CREATE TABLE shield.eventos_traza (
  id               bigserial PRIMARY KEY,
  intercepcion_id  uuid NOT NULL REFERENCES shield.intercepciones(id),
  paso             int  NOT NULL,
  agente           text NOT NULL,
  accion           text NOT NULL,
  lane             text,
  modelo           text,
  latencia_ms      int  NOT NULL,
  entrada_resumen  text,
  salida_resumen   text,
  creada           timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE shield.refutadas (
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
  colision_corpus  boolean NOT NULL
);

CREATE TABLE shield.banco_corridas (
  id                 uuid PRIMARY KEY,
  creada             timestamptz NOT NULL DEFAULT now(),
  lane               text NOT NULL CHECK (lane IN ('FAST','DEEP')),
  con_escudo         boolean NOT NULL,
  n_preguntas        int NOT NULL,
  citas_total        int NOT NULL,
  citas_no_probadas  int NOT NULL,
  abstenciones       int NOT NULL,
  reparaciones       int NOT NULL,
  latencia_p50_ms    int NOT NULL,
  modelo             text NOT NULL,
  sample_mode        boolean NOT NULL
);

CREATE TABLE shield.banco_items (
  id                uuid PRIMARY KEY,
  corrida_id        uuid NOT NULL REFERENCES shield.banco_corridas(id),
  pregunta_id       text NOT NULL,
  respuesta         text NOT NULL,
  citas_total       int NOT NULL,
  citas_no_probadas int NOT NULL,
  decision          text NOT NULL
);
