"""Postgres writes (psycopg). Reads go through Zetaris."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shield.env import load_env


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class EventoTraza:
    paso: int
    agente: str
    accion: str
    lane: str | None
    modelo: str | None
    latencia_ms: int
    entrada_resumen: str | None
    salida_resumen: str | None


@dataclass
class CitaRow:
    iteracion: int
    cita_raw: str
    cita_normalizada: str
    gid: str | None
    estado: str
    resolucion: str
    vigencia: str | None
    accion: str
    reemplazo_gid: str | None
    razon: str


class Store:
    def create_sesion(self, *, escenario: str, modo: str, sesion_id: uuid.UUID | None = None) -> uuid.UUID:
        raise NotImplementedError

    def create_intercepcion(
        self,
        *,
        intercepcion_id: uuid.UUID,
        sesion_id: uuid.UUID,
        entrada: str,
        borrador_original: str,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        sample_mode: bool,
    ) -> None:
        raise NotImplementedError

    def update_intercepcion(
        self,
        intercepcion_id: uuid.UUID,
        *,
        borrador_original: str,
        respuesta_final: str | None,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        commitment: dict | None,
        sample_mode: bool,
    ) -> None:
        raise NotImplementedError

    def add_traza(self, intercepcion_id: uuid.UUID, evento: EventoTraza) -> None:
        raise NotImplementedError

    def add_cita(self, intercepcion_id: uuid.UUID, cita: CitaRow) -> None:
        raise NotImplementedError

    def list_trazas(self, intercepcion_id: uuid.UUID) -> list[EventoTraza]:
        raise NotImplementedError

    def get_intercepcion(self, intercepcion_id: uuid.UUID) -> dict | None:
        raise NotImplementedError

    def upsert_refutada(self, *, cita_normalizada: str, razon: str) -> None:
        raise NotImplementedError

    def get_refutada(self, cita_normalizada: str) -> dict | None:
        raise NotImplementedError

    def save_corrida(self, row: dict) -> None:
        raise NotImplementedError

    def save_banco_item(self, row: dict) -> None:
        raise NotImplementedError

    def latest_corridas(self, limit: int = 8) -> list[dict]:
        raise NotImplementedError


@dataclass
class MemoryStore(Store):
    sesiones: dict[uuid.UUID, dict] = field(default_factory=dict)
    intercepciones: dict[uuid.UUID, dict] = field(default_factory=dict)
    eventos: list[tuple[uuid.UUID, EventoTraza]] = field(default_factory=list)
    citas: list[tuple[uuid.UUID, CitaRow]] = field(default_factory=list)
    refutadas: dict[str, dict] = field(default_factory=dict)
    corridas: list[dict] = field(default_factory=list)
    banco_items: list[dict] = field(default_factory=list)

    def create_sesion(self, *, escenario: str, modo: str, sesion_id: uuid.UUID | None = None) -> uuid.UUID:
        sid = sesion_id or uuid.uuid4()
        self.sesiones[sid] = {"escenario": escenario, "modo": modo, "creada": _now()}
        return sid

    def create_intercepcion(
        self,
        *,
        intercepcion_id: uuid.UUID,
        sesion_id: uuid.UUID,
        entrada: str,
        borrador_original: str,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        sample_mode: bool,
    ) -> None:
        self.intercepciones[intercepcion_id] = {
            "sesion_id": sesion_id,
            "entrada": entrada,
            "borrador_original": borrador_original,
            "respuesta_final": None,
            "decision": decision,
            "iteraciones": iteraciones,
            "modelo_borrador": modelo_borrador,
            "modelo_juez": modelo_juez,
            "commitment": None,
            "sample_mode": sample_mode,
        }

    def update_intercepcion(
        self,
        intercepcion_id: uuid.UUID,
        *,
        borrador_original: str,
        respuesta_final: str | None,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        commitment: dict | None,
        sample_mode: bool,
    ) -> None:
        row = self.intercepciones[intercepcion_id]
        row.update(
            {
                "borrador_original": borrador_original,
                "respuesta_final": respuesta_final,
                "decision": decision,
                "iteraciones": iteraciones,
                "modelo_borrador": modelo_borrador,
                "modelo_juez": modelo_juez,
                "commitment": commitment,
                "sample_mode": sample_mode,
            }
        )

    def add_traza(self, intercepcion_id: uuid.UUID, evento: EventoTraza) -> None:
        self.eventos.append((intercepcion_id, evento))

    def add_cita(self, intercepcion_id: uuid.UUID, cita: CitaRow) -> None:
        self.citas.append((intercepcion_id, cita))

    def list_trazas(self, intercepcion_id: uuid.UUID) -> list[EventoTraza]:
        return [e for i, e in self.eventos if i == intercepcion_id]

    def get_intercepcion(self, intercepcion_id: uuid.UUID) -> dict | None:
        row = self.intercepciones.get(intercepcion_id)
        return dict(row) if row else None

    def upsert_refutada(self, *, cita_normalizada: str, razon: str) -> None:
        key = cita_normalizada.strip()
        if not key:
            return
        now = _now()
        prev = self.refutadas.get(key)
        if prev:
            prev["veces"] = int(prev["veces"]) + 1
            prev["ultima"] = now
            prev["razon"] = razon
        else:
            self.refutadas[key] = {"cita_normalizada": key, "veces": 1, "ultima": now, "razon": razon}

    def get_refutada(self, cita_normalizada: str) -> dict | None:
        row = self.refutadas.get(cita_normalizada.strip())
        return dict(row) if row else None

    def save_corrida(self, row: dict) -> None:
        self.corridas.append(dict(row))

    def save_banco_item(self, row: dict) -> None:
        self.banco_items.append(dict(row))

    def latest_corridas(self, limit: int = 8) -> list[dict]:
        return list(reversed(self.corridas[-limit:]))


class PostgresStore(Store):
    def __init__(self, env: dict[str, str] | None = None) -> None:
        self.env = env or load_env()

    def _connect(self):
        import psycopg

        url = self.env.get("SHIELD_DB_URL", "")
        if not url or "<" in url:
            raise RuntimeError("SHIELD_DB_URL missing")
        return psycopg.connect(url)

    def create_sesion(self, *, escenario: str, modo: str, sesion_id: uuid.UUID | None = None) -> uuid.UUID:
        sid = sesion_id or uuid.uuid4()
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO shield.sesiones (id, escenario, modo) VALUES (%s, %s, %s)",
                    (sid, escenario, modo),
                )
            conn.commit()
        return sid

    def create_intercepcion(
        self,
        *,
        intercepcion_id: uuid.UUID,
        sesion_id: uuid.UUID,
        entrada: str,
        borrador_original: str,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        sample_mode: bool,
    ) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.intercepciones (
                      id, sesion_id, entrada, borrador_original, decision,
                      iteraciones, modelo_borrador, modelo_juez, sample_mode
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        intercepcion_id,
                        sesion_id,
                        entrada,
                        borrador_original,
                        decision,
                        iteraciones,
                        modelo_borrador,
                        modelo_juez,
                        sample_mode,
                    ),
                )
            conn.commit()

    def update_intercepcion(
        self,
        intercepcion_id: uuid.UUID,
        *,
        borrador_original: str,
        respuesta_final: str | None,
        decision: str,
        iteraciones: int,
        modelo_borrador: str,
        modelo_juez: str | None,
        commitment: dict | None,
        sample_mode: bool,
    ) -> None:
        payload: Any = None if commitment is None else json.dumps(commitment)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE shield.intercepciones SET
                      borrador_original=%s, respuesta_final=%s, decision=%s,
                      iteraciones=%s, modelo_borrador=%s, modelo_juez=%s,
                      commitment=%s, sample_mode=%s
                    WHERE id=%s
                    """,
                    (
                        borrador_original,
                        respuesta_final,
                        decision,
                        iteraciones,
                        modelo_borrador,
                        modelo_juez,
                        payload,
                        sample_mode,
                        intercepcion_id,
                    ),
                )
            conn.commit()

    def add_traza(self, intercepcion_id: uuid.UUID, evento: EventoTraza) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.eventos_traza (
                      intercepcion_id, paso, agente, accion, lane, modelo,
                      latencia_ms, entrada_resumen, salida_resumen
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        intercepcion_id,
                        evento.paso,
                        evento.agente,
                        evento.accion,
                        evento.lane,
                        evento.modelo,
                        evento.latencia_ms,
                        evento.entrada_resumen,
                        evento.salida_resumen,
                    ),
                )
            conn.commit()

    def add_cita(self, intercepcion_id: uuid.UUID, cita: CitaRow) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.citas (
                      id, intercepcion_id, iteracion, cita_raw, cita_normalizada,
                      gid, estado, resolucion, vigencia, accion, reemplazo_gid, razon
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        uuid.uuid4(),
                        intercepcion_id,
                        cita.iteracion,
                        cita.cita_raw,
                        cita.cita_normalizada,
                        cita.gid,
                        cita.estado,
                        cita.resolucion,
                        cita.vigencia,
                        cita.accion,
                        cita.reemplazo_gid,
                        cita.razon,
                    ),
                )
            conn.commit()

    def list_trazas(self, intercepcion_id: uuid.UUID) -> list[EventoTraza]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT paso, agente, accion, lane, modelo, latencia_ms,
                           entrada_resumen, salida_resumen
                    FROM shield.eventos_traza
                    WHERE intercepcion_id=%s
                    ORDER BY paso
                    """,
                    (intercepcion_id,),
                )
                rows = cur.fetchall()
        return [EventoTraza(*row) for row in rows]

    def get_intercepcion(self, intercepcion_id: uuid.UUID) -> dict | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT entrada, borrador_original, respuesta_final, decision,
                           iteraciones, modelo_borrador, modelo_juez, sample_mode
                    FROM shield.intercepciones WHERE id=%s
                    """,
                    (intercepcion_id,),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "entrada": row[0],
            "borrador_original": row[1],
            "respuesta_final": row[2],
            "decision": row[3],
            "iteraciones": row[4],
            "modelo_borrador": row[5],
            "modelo_juez": row[6],
            "sample_mode": row[7],
        }

    def upsert_refutada(self, *, cita_normalizada: str, razon: str) -> None:
        key = cita_normalizada.strip()
        if not key:
            return
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.refutadas (cita_normalizada, veces, ultima, razon)
                    VALUES (%s, 1, now(), %s)
                    ON CONFLICT (cita_normalizada) DO UPDATE SET
                      veces = shield.refutadas.veces + 1,
                      ultima = now(),
                      razon = EXCLUDED.razon
                    """,
                    (key, razon),
                )
            conn.commit()

    def get_refutada(self, cita_normalizada: str) -> dict | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cita_normalizada, veces, ultima, razon
                    FROM shield.refutadas WHERE cita_normalizada=%s
                    """,
                    (cita_normalizada.strip(),),
                )
                row = cur.fetchone()
        if not row:
            return None
        return {
            "cita_normalizada": row[0],
            "veces": row[1],
            "ultima": row[2],
            "razon": row[3],
        }

    def save_corrida(self, row: dict) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.banco_corridas (
                      id, lane, con_escudo, n_preguntas, citas_total, citas_no_probadas,
                      abstenciones, reparaciones, latencia_p50_ms, modelo, sample_mode
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["id"],
                        row["lane"],
                        row["con_escudo"],
                        row["n_preguntas"],
                        row["citas_total"],
                        row["citas_no_probadas"],
                        row["abstenciones"],
                        row["reparaciones"],
                        row["latencia_p50_ms"],
                        row["modelo"],
                        row["sample_mode"],
                    ),
                )
            conn.commit()

    def save_banco_item(self, row: dict) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO shield.banco_items (
                      id, corrida_id, pregunta_id, respuesta, citas_total,
                      citas_no_probadas, decision
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        row["id"],
                        row["corrida_id"],
                        row["pregunta_id"],
                        row["respuesta"],
                        row["citas_total"],
                        row["citas_no_probadas"],
                        row["decision"],
                    ),
                )
            conn.commit()

    def latest_corridas(self, limit: int = 8) -> list[dict]:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, lane, con_escudo, n_preguntas, citas_total, citas_no_probadas,
                           abstenciones, reparaciones, latencia_p50_ms, modelo, sample_mode, creada
                    FROM shield.banco_corridas
                    ORDER BY creada DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                cols = [
                    "id", "lane", "con_escudo", "n_preguntas", "citas_total",
                    "citas_no_probadas", "abstenciones", "reparaciones",
                    "latencia_p50_ms", "modelo", "sample_mode", "creada",
                ]
                out = []
                for row in cur.fetchall():
                    item = dict(zip(cols, row))
                    item["id"] = str(item["id"])
                    item["creada"] = str(item["creada"])
                    out.append(item)
                return out
