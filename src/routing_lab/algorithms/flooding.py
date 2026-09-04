"""Enrutamiento por inundación con TTL y supresión de duplicados."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

from routing_lab.protocol import Packet, PacketError, make_packet


class DuplicateCache:
    """Conjunto acotado que evita ciclos sin crecer indefinidamente."""

    def __init__(self, capacity: int = 4096) -> None:
        if capacity <= 0:
            raise ValueError("La capacidad debe ser positiva")
        self.capacity = capacity
        self._items: OrderedDict[str, None] = OrderedDict()

    def remember(self, packet_id: str) -> bool:
        """Devuelve ``True`` únicamente la primera vez que observa un ID."""

        if packet_id in self._items:
            self._items.move_to_end(packet_id)
            return False
        self._items[packet_id] = None
        if len(self._items) > self.capacity:
            self._items.popitem(last=False)
        return True


@dataclass(frozen=True, slots=True)
class FloodDecision:
    deliver: bool
    outgoing: tuple[tuple[str, Packet], ...]
    reason: str


class FloodingRouter:
    protocol = "flooding"

    def __init__(
        self,
        node_id: str,
        neighbors: Iterable[str],
        *,
        cache_capacity: int = 4096,
    ) -> None:
        self.node_id = node_id
        self._neighbors = set(neighbors)
        if node_id in self._neighbors:
            raise ValueError("Un nodo no puede ser vecino de sí mismo")
        self._seen = DuplicateCache(cache_capacity)

    @property
    def neighbors(self) -> frozenset[str]:
        return frozenset(self._neighbors)

    def set_neighbors(self, neighbors: Iterable[str]) -> None:
        updated = set(neighbors)
        if self.node_id in updated:
            raise ValueError("Un nodo no puede ser vecino de sí mismo")
        self._neighbors = updated

    def create_message(self, destination: str, payload: object, *, ttl: int = 16) -> Packet:
        return make_packet(
            "flooding", "message", self.node_id, destination, payload, ttl=ttl
        )

    def handle(self, packet: Packet, incoming_neighbor: str | None = None) -> FloodDecision:
        if packet.proto != self.protocol:
            raise PacketError(f"Flooding no acepta paquetes {packet.proto!r}")
        if incoming_neighbor is not None and incoming_neighbor not in self._neighbors:
            raise PacketError(f"El paquete llegó desde un no vecino: {incoming_neighbor}")
        if packet.packet_id is None:
            raise PacketError("Flooding requiere el header 'packet_id'")
        if not self._seen.remember(packet.packet_id):
            return FloodDecision(False, (), "duplicate")

        deliver = packet.destination in {self.node_id, "*"}
        if packet.ttl == 0 or (deliver and packet.destination != "*"):
            reason = "delivered" if deliver else "ttl-expired"
            return FloodDecision(deliver, (), reason)

        forwarded = packet.forwarded()
        targets = tuple(sorted(self._neighbors - {incoming_neighbor}))
        outgoing = tuple((neighbor, forwarded) for neighbor in targets)
        return FloodDecision(deliver, outgoing, "forwarded" if outgoing else "dead-end")

