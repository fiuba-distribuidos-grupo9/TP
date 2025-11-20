# src/health_checkers/app/leader.py
from __future__ import annotations
import threading
import time
from typing import Optional
from .models import Config


class LeaderLoop:
    """
    Loop sencillo basado en hilos:
      - Corre en un hilo dedicado.
      - Sólo cuando este nodo es líder ejecuta la lógica de validación.
    Por ahora, la "validación" es únicamente un print + sleep(5s).
    """

    def __init__(self, cfg: Config, is_leader_callable):
        self.cfg = cfg
        self.is_leader = is_leader_callable
        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()

    def start(self):
        if self._thread is not None:
            return
        self._running.set()
        self._thread = threading.Thread(
            target=self._loop,
            name=f"LeaderLoop-{self.cfg.node_id}",
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running.clear()
        # No bloqueamos fuerte: el hilo se terminará solo al próximo ciclo.
        self._thread = None

    def _loop(self):
        while self._running.is_set():
            if self.is_leader():
                # Lugar central donde el líder valida al resto del sistema.
                print(f"[leader] Nodo líder {self.cfg.node_id} validando nodos del sistema (placeholder)…")
                time.sleep(5.0)
            else:
                # Si no soy líder, sólo descanso un poco y vuelvo a chequear.
                time.sleep(1.0)
