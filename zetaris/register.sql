-- Lightning SQL: register shield-db as ZETARIS_SOURCE_DB (shield_pg).
-- One statement per REST request. Placeholders are filled from .env at runtime
-- by scripts/register_zetaris.py — never commit the password.
-- JDBC host `shield-db` resolves on Docker network zetaris_default.
--
-- CREATE DATASOURCE does not accept accented DESCRIBE BY on this build.
-- REGISTER DATASOURCE TABLES lists zero tables: JDBC metadata sees `public`,
-- while the contract lives in schema `shield`. Plan B: datasource views that
-- run native Postgres `SELECT * FROM shield.<table>`. Query as
-- `<fuente>.articulos` (Spark rejects `<fuente>.shield.articulos`).

CREATE DATASOURCE __ZETARIS_SOURCE_DB__ OPTIONS (jdbcdriver "org.postgresql.Driver", jdbcurl "jdbc:postgresql://shield-db:5432/shield?currentSchema=shield", username "shield", password "__SHIELD_DB_PASSWORD__", fetchsize "1000");

CREATE DATASOURCE VIEW articulos FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.articulos;

CREATE DATASOURCE VIEW sesiones FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.sesiones;

CREATE DATASOURCE VIEW intercepciones FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.intercepciones;

CREATE DATASOURCE VIEW citas FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.citas;

CREATE DATASOURCE VIEW eventos_traza FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.eventos_traza;

CREATE DATASOURCE VIEW refutadas FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.refutadas;

CREATE DATASOURCE VIEW trampas FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.trampas;

CREATE DATASOURCE VIEW banco_corridas FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.banco_corridas;

CREATE DATASOURCE VIEW banco_items FROM __ZETARIS_SOURCE_DB__ AS SELECT * FROM shield.banco_items;
