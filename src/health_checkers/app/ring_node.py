from __future__ import annotations
import asyncio, json, socket, contextlib, time
from typing import Optional, List, Dict
from .models import Config, Peer, Message
from .election import Election
from .dood import DockerReviver

NOW = lambda: time.monotonic()

class RingNode:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((cfg.listen_host, cfg.listen_port))
        self.sock.setblocking(False)

        # Peers sorted by id, excluding myself
        self._peers: List[Peer] = [p for p in cfg.peers if p.id != cfg.node_id]
        self._peers.sort(key=lambda x: x.id)

        # Successor/predecessor bookkeeping
        self._successor_index = self._compute_successor_index()

        # Leader election + DooD
        self.election = Election(cfg, self._send_to_successor)
        self.reviver = DockerReviver(cfg.docker_host)

        # Last heartbeat time per neighbor (peer_id -> monotonic seconds)
        self._last_hb_from: Dict[int, float] = {}

        # Boot timestamp to apply startup grace before pruning never-heard peers
        self._boot_ts = NOW()

    # ---------- Topology ----------
    def _compute_successor_index(self) -> int:
        """Choose the peer with the smallest id greater than mine; otherwise the smallest id."""
        higher = [i for i, p in enumerate(self._peers) if p.id > self.cfg.node_id]
        if higher:
            return higher[0]
        return 0 if self._peers else -1

    def successor(self) -> Optional[Peer]:
        """Return current successor in the ring (or None if I am alone)."""
        if not self._peers or self._successor_index < 0:
            return None
        return self._peers[self._successor_index]

    def predecessor(self) -> Optional[Peer]:
        """Return current predecessor in the ring (or None if I am alone)."""
        if not self._peers:
            return None
        lower = [p for p in self._peers if p.id < self.cfg.node_id]
        return lower[-1] if lower else self._peers[-1]

    def _remove_peer(self, peer_id: int):
        """Remove a peer from the local view and recompute topology."""
        self._peers = [p for p in self._peers if p.id != peer_id]
        self._peers.sort(key=lambda x: x.id)
        self._successor_index = self._compute_successor_index()
        self._last_hb_from.pop(peer_id, None)

    # ---------- Leader state ----------
    def is_leader(self) -> bool:
        """True if my node id matches the known leader id."""
        return (self.election.leader_id == self.cfg.node_id)

    # ---------- IO ----------
    async def _send_to(self, peer: Peer, msg: Message):
        """Send a JSON message via UDP to a specific peer."""
        data = msg.model_dump_json().encode("utf-8")
        loop = asyncio.get_running_loop()
        try:
            await loop.sock_sendto(self.sock, data, (peer.host, peer.port))
        except Exception as e:
            print(f"[send] Error enviando a {peer.name}@{peer.host}:{peer.port}: {e}")

    async def _send_to_successor(self, msg: Message):
        """Helper to send to current successor (if any)."""
        suc = self.successor()
        if suc:
            await self._send_to(suc, msg)

    # ---------- Run ----------
    async def run(self):
        """Start receiver and heartbeat tasks and keep them running."""
        recv_task = asyncio.create_task(self._recv_loop())
        hb_task = asyncio.create_task(self._heartbeat_loop())
        try:
            await asyncio.gather(recv_task, hb_task)
        finally:
            with contextlib.suppress(Exception):
                recv_task.cancel()
                hb_task.cancel()

    async def _recv_loop(self):
        """Receive UDP packets and dispatch to the message handler."""
        loop = asyncio.get_running_loop()
        while True:
            data, addr = await loop.sock_recvfrom(self.sock, 65535)
            try:
                msg = Message.model_validate_json(data)
            except Exception:
                continue
            await self._handle_message(msg)

    async def _handle_message(self, msg: Message):
        """Handle protocol messages (heartbeat/election/coordinator/probe...)."""
        kind = msg.kind
        src = msg.src_id

        if kind == "heartbeat":
            # Record last heartbeat time from this neighbor
            self._last_hb_from[src] = NOW()
            return

        elif kind == "election":
            await self.election.handle_election(msg)

        elif kind == "coordinator":
            await self.election.handle_coordinator(msg)
            lid = self.election.leader_id
            print(f"[ring] Nuevo líder: {lid}")

        elif kind == "probe":
            # Leader global ping placeholder: just ack around the ring
            ack = Message(kind="probe_ack", src_id=self.cfg.node_id, src_name=self.cfg.node_name)
            await self._send_to_successor(ack)

        # Future message kinds can be added here

    # ---------- Bidirectional heartbeats with startup grace ----------
    async def _heartbeat_loop(self):
        """
        On each interval:
          - Send heartbeat to SUCCESSOR and PREDECESSOR (if present).
          - Check SUCCESSOR silence as the primary failure signal.
          - Do not prune peers that we've NEVER heard from until startup grace elapses.
          - If SUCCESSOR exceeds timeout (after grace or after having heard it at least once):
              try revive (DooD), remove from ring, and trigger election if it was the leader
              or if leader is unknown.
        """
        interval_s = self.cfg.heartbeat_interval_ms / 1000.0
        timeout_ms = self.cfg.heartbeat_timeout_ms
        startup_grace_ms = getattr(self.cfg, "suspect_grace_ms", 1200)
        # Give some extra slack on first contact: allow 2x timeout during grace
        first_contact_multiplier = 2.0

        while True:
            suc = self.successor()
            pred = self.predecessor()

            # 1) Send heartbeat to both neighbors (if they exist)
            hb = Message(kind="heartbeat", src_id=self.cfg.node_id, src_name=self.cfg.node_name)

            if suc:
                await self._send_to(suc, hb)
            if pred and (not suc or pred.id != suc.id):
                await self._send_to(pred, hb)

            now = NOW()
            elapsed_ms_since_boot = (now - self._boot_ts) * 1000.0

            # 2) Evaluate SUCCESSOR silence
            if suc:
                last = self._last_hb_from.get(suc.id, 0.0)
                never_heard = (suc.id not in self._last_hb_from)
                silence_ms = (now - last) * 1000.0 if not never_heard else float("inf")

                # During startup grace, do not prune never-heard successors.
                if never_heard and elapsed_ms_since_boot < startup_grace_ms:
                    # Just log (optional) to help debugging; do not rewire yet
                    # print(f"[debug] In grace: waiting to hear from sucesor {suc.id}...")
                    pass
                else:
                    # Past grace or we've heard it before: apply timeout logic.
                    effective_timeout = timeout_ms
                    if never_heard:
                        # If we NEVER heard them, be a bit more lenient once grace elapsed
                        effective_timeout = int(timeout_ms * first_contact_multiplier)

                    if silence_ms > effective_timeout:
                        print(f"[ring] Sucesor {suc.id} ({suc.name}) en silencio {silence_ms:.0f}ms (> {effective_timeout}ms). Reacomodando anillo…")

                        # Attempt to revive via DooD
                        container = self.cfg.revive_targets.get(suc.name)
                        if container:
                            ok = self.reviver.revive_container(container)
                            print(f"[ring] revive({suc.name} -> {container}) = {ok}")

                        # Election conditions
                        was_leader = (self.election.leader_id == suc.id)

                        # Remove successor and recompute topology
                        self._remove_peer(suc.id)

                        if was_leader:
                            print("[ring] El sucesor caído era líder → inicio elección")
                            await self.election.start_election()
                        elif self.election.leader_id is None:
                            print("[ring] No conozco líder → inicio elección")
                            await self.election.start_election()

            # 3) (Optional) Log predecessor silence (informative)
            if pred:
                lastp = self._last_hb_from.get(pred.id, 0.0)
                never_heard_p = (pred.id not in self._last_hb_from)
                silencep_ms = (now - lastp) * 1000.0 if not never_heard_p else float("inf")
                if not never_heard_p and silencep_ms > timeout_ms:
                    print(f"[ring] Predecesor {pred.id} ({pred.name}) en silencio {silencep_ms:.0f}ms.")

            # 4) If I'm alone in the ring -> self-elect as leader
            if not self._peers:
                if self.election.leader_id != self.cfg.node_id:
                    self.election.set_leader(self.cfg.node_id)
                    print(f"[ring] Soy líder (único en el anillo)")

            await asyncio.sleep(interval_s)
