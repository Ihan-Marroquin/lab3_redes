"""Distance Vector Routing con Bellman-Ford y poison reverse."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import time
from typing import Callable, Mapping

from routing_lab.protocol import Packet, PacketError, make_packet


@dataclass(frozen=True, slots=True)
class DistanceRoute:
    destination: str
    next_hop: str
    cost: float


@dataclass(frozen=True, slots=True)
class NeighborVector:
    sequence: int
    distances: Mapping[str, float]
    received_at: float


@dataclass(frozen=True, slots=True)
class DistanceVectorDecision:
    deliver: bool
    outgoing: tuple[tuple[str, Packet], ...]
    table_changed: bool
    reason: str


class DistanceVectorRouter:
    protocol = "dvr"

    def __init__(
        self,
        node_id: str,
        local_links: Mapping[str, float],
        *,
        infinity: float = 1_000_000.0,
        vector_max_age: float = 45.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if infinity <= 0 or not isfinite(infinity):
            raise ValueError("El valor de infinito debe ser positivo y finito")
        self.node_id = node_id
        self.infinity = float(infinity)
        self.vector_max_age = vector_max_age
        self._clock = clock
        self._sequence = 0
        self._local_links = self._validate_links(local_links)
        self._neighbor_vectors: dict[str, NeighborVector] = {}
        self._table: dict[str, DistanceRoute] = {}
        self._recompute()

    def _validate_links(self, raw: Mapping[str, object]) -> dict[str, float]:
        links: dict[str, float] = {}
        for neighbor, raw_cost in raw.items():
            if not isinstance(neighbor, str) or not neighbor or neighbor == self.node_id:
                raise ValueError(f"Vecino inválido: {neighbor!r}")
            if (
                isinstance(raw_cost, bool)
                or not isinstance(raw_cost, (int, float))
                or not 0 < float(raw_cost) < self.infinity
            ):
                raise ValueError(f"Costo inválido hacia {neighbor!r}")
            links[neighbor] = float(raw_cost)
        return links

    @property
    def neighbors(self) -> frozenset[str]:
        return frozenset(self._local_links)

    @property
    def table(self) -> dict[str, DistanceRoute]:
        return dict(self._table)

    @property
    def distances(self) -> dict[str, float]:
        values = {self.node_id: 0.0}
        values.update({destination: route.cost for destination, route in self._table.items()})
        return values

    def next_hop(self, destination: str) -> str | None:
        route = self._table.get(destination)
        return route.next_hop if route else None

    def _recompute(self) -> bool:
        destinations = set(self._local_links)
        for vector in self._neighbor_vectors.values():
            destinations.update(vector.distances)
        destinations.discard(self.node_id)

        updated: dict[str, DistanceRoute] = {}
        for destination in destinations:
            candidates: list[tuple[float, str]] = []
            direct = self._local_links.get(destination)
            if direct is not None:
                candidates.append((direct, destination))
            for neighbor, link_cost in self._local_links.items():
                advertised = self._neighbor_vectors.get(neighbor)
                if advertised is None:
                    continue
                remaining = advertised.distances.get(destination, self.infinity)
                candidate = min(self.infinity, link_cost + remaining)
                if candidate < self.infinity:
                    candidates.append((candidate, neighbor))
            if candidates:
                cost, next_hop = min(candidates)
                updated[destination] = DistanceRoute(destination, next_hop, cost)

        changed = updated != self._table
        self._table = updated
        return changed

    def update_local_links(self, links: Mapping[str, float]) -> bool:
        updated = self._validate_links(links)
        removed = set(self._local_links) - set(updated)
        for neighbor in removed:
            self._neighbor_vectors.pop(neighbor, None)
        self._local_links = updated
        return self._recompute()

    def _advertisement_for(self, neighbor: str) -> dict[str, float]:
        advertised = self.distances
        for destination, route in self._table.items():
            if destination != neighbor and route.next_hop == neighbor:
                advertised[destination] = self.infinity
        return advertised

    def create_updates(self) -> tuple[tuple[str, Packet], ...]:
        """Genera una versión por vecino para aplicar poison reverse."""

        self._sequence += 1
        outgoing = []
        for neighbor in sorted(self.neighbors):
            packet = make_packet(
                "dvr",
                "info",
                self.node_id,
                neighbor,
                {
                    "origin": self.node_id,
                    "sequence": self._sequence,
                    "distances": self._advertisement_for(neighbor),
                },
                ttl=1,
            )
            outgoing.append((neighbor, packet))
        return tuple(outgoing)

    def create_message(self, destination: str, payload: object, *, ttl: int = 16) -> Packet:
        return make_packet("dvr", "message", self.node_id, destination, payload, ttl=ttl)

    def expire(self) -> set[str]:
        now = self._clock()
        expired = {
            neighbor
            for neighbor, vector in self._neighbor_vectors.items()
            if now - vector.received_at > self.vector_max_age
        }
        for neighbor in expired:
            del self._neighbor_vectors[neighbor]
        if expired:
            self._recompute()
        return expired

    def handle(
        self, packet: Packet, incoming_neighbor: str | None = None
    ) -> DistanceVectorDecision:
        if packet.proto != self.protocol:
            raise PacketError(f"DVR no acepta paquetes {packet.proto!r}")
        if packet.type == "info":
            return self._handle_vector(packet, incoming_neighbor)
        if packet.type == "message":
            return self._handle_message(packet)
        return DistanceVectorDecision(False, (), False, "unsupported-type")

    def _handle_vector(
        self, packet: Packet, incoming_neighbor: str | None
    ) -> DistanceVectorDecision:
        if incoming_neighbor is None or incoming_neighbor not in self._local_links:
            raise PacketError("Un vector de distancia debe llegar desde un vecino")
        if not isinstance(packet.payload, dict):
            raise PacketError("El payload DVR debe ser un objeto")
        origin = packet.payload.get("origin")
        sequence = packet.payload.get("sequence")
        raw_distances = packet.payload.get("distances")
        if origin != incoming_neighbor:
            raise PacketError("El origen del vector no coincide con el vecino emisor")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise PacketError("La secuencia DVR no es válida")
        if not isinstance(raw_distances, dict):
            raise PacketError("El vector DVR no contiene distancias")

        current = self._neighbor_vectors.get(incoming_neighbor)
        if current is not None and sequence <= current.sequence:
            return DistanceVectorDecision(False, (), False, "stale-vector")
        distances: dict[str, float] = {}
        for destination, raw_cost in raw_distances.items():
            if not isinstance(destination, str) or not destination:
                raise PacketError("Destino inválido en el vector")
            if (
                isinstance(raw_cost, bool)
                or not isinstance(raw_cost, (int, float))
                or float(raw_cost) < 0
            ):
                raise PacketError(f"Distancia inválida hacia {destination!r}")
            distances[destination] = min(float(raw_cost), self.infinity)
        self._neighbor_vectors[incoming_neighbor] = NeighborVector(
            sequence, distances, self._clock()
        )
        changed = self._recompute()
        outgoing = self.create_updates() if changed else ()
        return DistanceVectorDecision(False, outgoing, changed, "vector-installed")

    def _handle_message(self, packet: Packet) -> DistanceVectorDecision:
        if packet.destination == self.node_id:
            return DistanceVectorDecision(True, (), False, "delivered")
        if packet.ttl == 0:
            return DistanceVectorDecision(False, (), False, "ttl-expired")
        next_hop = self.next_hop(packet.destination)
        if next_hop is None:
            return DistanceVectorDecision(False, (), False, "unreachable")
        return DistanceVectorDecision(
            False, ((next_hop, packet.forwarded()),), False, "forwarded"
        )

