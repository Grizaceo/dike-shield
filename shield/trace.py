"""Trace writer: one eventos_traza row per agent step."""

from __future__ import annotations

import uuid

from shield.db import EventoTraza, Store


class Tracer:
    def __init__(self, store: Store, intercepcion_id: uuid.UUID) -> None:
        self.store = store
        self.intercepcion_id = intercepcion_id
        self.paso = 0

    def emit(
        self,
        agente: str,
        accion: str,
        *,
        lane: str | None = None,
        modelo: str | None = None,
        latencia_ms: int = 0,
        entrada: str = "",
        salida: str = "",
    ) -> None:
        self.paso += 1
        self.store.add_traza(
            self.intercepcion_id,
            EventoTraza(
                paso=self.paso,
                agente=agente,
                accion=accion,
                lane=lane,
                modelo=modelo,
                latencia_ms=latencia_ms,
                entrada_resumen=(entrada or "")[:400] or None,
                salida_resumen=(salida or "")[:400] or None,
            ),
        )
