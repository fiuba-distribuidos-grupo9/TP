# src/health_checkers/app/ring_node.py
from __future__ import annotations
import json
import socket
import time
from typing import Optional, List
from .models import Config, Peer, Message
from .election import Election
from .dood import DockerReviver

NOW = lambda: time.monotonic()


class RingNode:
    """
    Nodo del anillo:
      - Mantiene la topología (peers, sucesor, predecesor).
      - Envia y recibe mensajes vía UDP (bloqueante, con timeout).
      - Integra la lógica de elección de líder (Election) y el reviver de Docker.
    """

    def __init__(self, cfg: Config):
        self.cfg = cfg

        # Socket UDP en modo bloqueante con timeout para poder interrumpir con Ctrl+C.
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((cfg.listen_host, cfg.listen_port))
        self.sock.settimeout(1.0)

        # Peers ordenados por id, excluyéndome a mí.
        self._peers: List[Peer] = [p for p in cfg.peers if p.id != cfg.node_id]
        self._peers.sort(key=lambda x: x.id)

        # Índice de sucesor dentro de _peers.
        self._successor_index = self._compute_successor_index()

        # Lógica de elección + reviver de contenedores.
        self.election = Election(cfg, self._send_to_successor)
        self.reviver = DockerReviver(cfg.docker_host)

    # ---------- Topología ----------

    def _compute_successor_index(self) -> int:
        """Elijo el peer con id más chico mayor al mío; si no, el más chico de todos."""
        if not self._peers:
            return 0
        higher = [i for i, p in enumerate(self._peers) if p.id > self.cfg.node_id]
        if higher:
            return higher[0]
        return 0

    def successor(self) -> Optional[Peer]:
        """Devuelve el sucesor actual en el anillo (o None si estoy solo)."""
        if not self._peers:
            return None
        return self._peers[self._successor_index]

    def predecessor(self) -> Optional[Peer]:
        """Devuelve el predecesor actual en el anillo (o None si estoy solo)."""
        if not self._peers:
            return None
        lower = [p for p in self._peers if p.id < self.cfg.node_id]
        return lower[-1] if lower else self._peers[-1]

    def _remove_peer(self, peer_id: int):
        """Remueve un peer de la vista local y recalcula la topología."""
        self._peers = [p for p in self._peers if p.id != peer_id]
        self._peers.sort(key=lambda x: x.id)
        self._successor_index = self._compute_successor_index()

    # ---------- Estado de líder ----------

    def is_leader(self) -> bool:
        return self.election.leader_id == self.cfg.node_id

    # ---------- IO ----------

    def _send_to(self, peer: Peer, msg: Message):
        """Envía un mensaje JSON vía UDP a un peer específico (bloqueante)."""
        data = msg.model_dump_json().encode("utf-8")
        try:
            self.sock.sendto(data, (peer.host, peer.port))
        except Exception as e:
            print(f"[send] Error enviando a {peer.name}@{peer.host}:{peer.port}: {e}")

    def _send_to_successor(self, msg: Message):
        """Helper para enviar al sucesor actual (si existe)."""
        suc = self.successor()
        if suc is not None:
            self._send_to(suc, msg)

    # ---------- Loop principal ----------

    def run(self):
        """
        Loop bloqueante de recepción de mensajes.
        Se queda en recvfrom() con timeout y despacha según el tipo de mensaje.
        """
        print("[ring] Loop principal iniciado.")
        while True:
            try:
                data, addr = self.sock.recvfrom(64 * 1024)
            except socket.timeout:
                # No llegó nada en este intervalo; vuelvo a intentar.
                continue
            except OSError as e:
                print(f"[ring] Error de socket: {e}")
                break

            try:
                msg = Message.model_validate_json(data.decode("utf-8"))
            except Exception as e:
                print(f"[ring] Mensaje inválido recibido: {e}")
                continue

            self._handle_message(msg)

    def _handle_message(self, msg: Message):
        """Manejo de mensajes de protocolo (election/coordinator/probe...)."""
        kind = msg.kind

        if kind == "election":
            self.election.handle_election(msg)

        elif kind == "coordinator":
            self.election.handle_coordinator(msg)
            lid = self.election.leader_id
            print(f"[ring] Nuevo líder: {lid}")

        elif kind == "probe":
            # Placeholder de ping global: respondemos con un ack al sucesor.
            ack = Message(kind="probe_ack", src_id=self.cfg.node_id, src_name=self.cfg.node_name)
            self._send_to_successor(ack)

        # Otros tipos de mensaje (heartbeat, whois, iam, probe_ack, etc.)
        # se pueden implementar más adelante cuando haga falta.
