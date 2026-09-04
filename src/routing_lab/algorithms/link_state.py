"""Link State Routing: anuncios LSP, flooding y Dijkstra reutilizable."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
import time
from typing import Callable, Mapping

from routing_lab.algorithms.dijkstra import Route, shortest_paths
from routing_lab.protocol import Packet, PacketError, make_packet


@dataclass(frozen=True, slots=True)
class LinkStateRecord:
    sequence: int
    links: Mapping[str, float]
    received_at: float


@dataclass(frozen=True, slots=True)
class LinkStateDecision:
    deliver: bool
    outgoing: tuple[tuple[str, Packet], ...]
    topology_changed: bool
    reason: str


class LinkStateRouter:
    protocol = "lsr"

    def __init__(
        self,
        node_id: str,
        local_links: Mapping[str, float],
        *,
        lsp_ttl: int = 64,
        max_age: float = 120.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if node_id in local_links:
            raise ValueError("Un nodo no puede anunciar un enlace a sí mismo")
        self.node_id = node_id
        self.lsp_ttl = lsp_ttl
        self.max_age = max_age
        self._clock = clock
        self._sequence = 0
        self._local_links = self._validate_links(local_links)
        self._database: dict[str, LinkStateRecord] = {}
        self._table: dict[str, Route] = {}
        self._install_local_record()

    @staticmethod
    def _validate_links(raw: Mapping[str, object]) -> dict[str, float]:
        links: dict[str, float] = {}
        for neighbor, raw_cost in raw.items():
            if not isinstance(neighbor, str) or not neighbor:
                raise PacketError("Los vecinos LSP deben ser cadenas no vacías")
            if (
                isinstance(raw_cost, bool)
                or not isinstance(raw_cost, (int, float))
                or float(raw_cost) <= 0
                or not isfinite(float(raw_cost))
            ):
                raise PacketError(f"Costo LSP inválido hacia {neighbor!r}")
            links[neighbor] = float(raw_cost)
        return links

    @property
    def neighbors(self) -> frozenset[str]:
        return frozenset(self._local_links)

    @property
    def database(self) -> dict[str, LinkStateRecord]:
        return dict(self._database)

    @property
    def table(self) -> dict[str, Route]:
        return dict(self._table)

    def _install_local_record(self) -> None:
        self._database[self.node_id] = LinkStateRecord(
            self._sequence, dict(self._local_links), self._clock()
        )
        self._recompute()

    def _recompute(self) -> None:
        graph = {origin: dict(record.links) for origin, record in self._database.items()}
        graph.setdefault(self.node_id, dict(self._local_links))
        self._table = shortest_paths(graph, self.node_id)

    def update_local_links(self, links: Mapping[str, float]) -> bool:
        updated = self._validate_links(links)
        if updated == self._local_links:
            return False
        self._local_links = updated
        self._sequence += 1
        self._install_local_record()
        return True

    def create_lsp(self) -> Packet:
        self._sequence += 1
        self._install_local_record()
        return make_packet(
            "lsr",
            "info",
            self.node_id,
            "*",
            {
                "origin": self.node_id,
                "sequence": self._sequence,
                "links": dict(self._local_links),
            },
            ttl=self.lsp_ttl,
        )

    def create_message(self, destination: str, payload: object, *, ttl: int = 16) -> Packet:
        return make_packet("lsr", "message", self.node_id, destination, payload, ttl=ttl)

    def next_hop(self, destination: str) -> str | None:
        route = self._table.get(destination)
        return route.next_hop if route else None

    def expire(self) -> set[str]:
        """Retira anuncios remotos viejos y recalcula las rutas."""

        now = self._clock()
        expired = {
            origin
            for origin, record in self._database.items()
            if origin != self.node_id and now - record.received_at > self.max_age
        }
        for origin in expired:
            del self._database[origin]
        if expired:
            self._recompute()
        return expired

    def handle(self, packet: Packet, incoming_neighbor: str | None = None) -> LinkStateDecision:
        if packet.proto != self.protocol:
            raise PacketError(f"LSR no acepta paquetes {packet.proto!r}")
        if incoming_neighbor is not None and incoming_neighbor not in self._local_links:
            raise PacketError(f"El paquete llegó desde un no vecino: {incoming_neighbor}")
        if packet.type == "info":
            return self._handle_lsp(packet, incoming_neighbor)
        if packet.type == "message":
            return self._handle_message(packet)
        return LinkStateDecision(False, (), False, "unsupported-type")

    def _handle_lsp(
        self, packet: Packet, incoming_neighbor: str | None
    ) -> LinkStateDecision:
        if not isinstance(packet.payload, dict):
            raise PacketError("El payload de un LSP debe ser un objeto")
        origin = packet.payload.get("origin")
        sequence = packet.payload.get("sequence")
        raw_links = packet.payload.get("links")
        if not isinstance(origin, str) or not origin:
            raise PacketError("El LSP no contiene un origen válido")
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise PacketError("El LSP no contiene una secuencia válida")
        if not isinstance(raw_links, dict):
            raise PacketError("El LSP no contiene enlaces válidos")
        links = self._validate_links(raw_links)

        current = self._database.get(origin)
        if current is not None and sequence <= current.sequence:
            return LinkStateDecision(False, (), False, "stale-lsp")
        self._database[origin] = LinkStateRecord(sequence, links, self._clock())
        self._recompute()

        if packet.ttl == 0:
            return LinkStateDecision(False, (), True, "ttl-expired")
        forwarded = packet.forwarded()
        targets = tuple(sorted(self.neighbors - {incoming_neighbor}))
        outgoing = tuple((neighbor, forwarded) for neighbor in targets)
        return LinkStateDecision(False, outgoing, True, "lsp-installed")

    def _handle_message(self, packet: Packet) -> LinkStateDecision:
        if packet.destination == self.node_id:
            return LinkStateDecision(True, (), False, "delivered")
        if packet.ttl == 0:
            return LinkStateDecision(False, (), False, "ttl-expired")
        next_hop = self.next_hop(packet.destination)
        if next_hop is None or next_hop not in self._local_links:
            return LinkStateDecision(False, (), False, "unreachable")
        return LinkStateDecision(
            False, ((next_hop, packet.forwarded()),), False, "forwarded"
        )

