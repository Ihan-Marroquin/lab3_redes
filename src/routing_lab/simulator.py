"""Simulador determinista que conecta routers sin revelarles la topología global."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any, Mapping

from routing_lab.algorithms import (
    DijkstraRouter,
    DistanceVectorRouter,
    FloodingRouter,
    LinkStateRouter,
)
from routing_lab.protocol import Packet, make_packet


@dataclass(frozen=True, slots=True)
class TraceEvent:
    sender: str
    receiver: str
    packet_type: str
    packet_id: str | None
    path: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationResult:
    delivered: bool
    path: tuple[str, ...]
    payload: Any
    transmissions: int
    drops: tuple[str, ...]
    trace: tuple[TraceEvent, ...]


@dataclass(slots=True)
class _QueuedPacket:
    sender: str
    receiver: str
    packet: Packet
    path: tuple[str, ...]


class NetworkSimulator:
    """Red en memoria con una instancia independiente de router por nodo."""

    def __init__(self, topology: Mapping[str, Mapping[str, float]], algorithm: str) -> None:
        if algorithm not in {"dijkstra", "flooding", "lsr", "dvr"}:
            raise ValueError(f"Algoritmo no soportado: {algorithm}")
        self.topology = {
            node: {neighbor: float(cost) for neighbor, cost in links.items()}
            for node, links in topology.items()
        }
        self.algorithm = algorithm
        self.routers: dict[str, object] = {}
        for node, links in self.topology.items():
            if algorithm == "dijkstra":
                router = DijkstraRouter(node, self.topology)
            elif algorithm == "flooding":
                router = FloodingRouter(node, links)
            elif algorithm == "lsr":
                router = LinkStateRouter(node, links)
            else:
                router = DistanceVectorRouter(node, links)
            self.routers[node] = router
        self._control_queue: deque[_QueuedPacket] = deque()

    def set_link(
        self,
        source: str,
        destination: str,
        cost: float | None,
        *,
        bidirectional: bool = True,
    ) -> None:
        """Crea, modifica o elimina un enlace y notifica a los routers locales."""

        if source == destination:
            raise ValueError("No se permiten enlaces de un nodo hacia sí mismo")
        if source not in self.topology or destination not in self.topology:
            raise ValueError("Los extremos del enlace deben existir")
        if cost is not None and cost <= 0:
            raise ValueError("El costo del enlace debe ser positivo")

        directions = [(source, destination)]
        if bidirectional:
            directions.append((destination, source))
        for origin, neighbor in directions:
            if cost is None:
                self.topology[origin].pop(neighbor, None)
            else:
                self.topology[origin][neighbor] = float(cost)
        self._refresh_local_knowledge()

    def remove_node(self, node_id: str) -> None:
        """Simula la caída de un nodo y de todos sus enlaces."""

        if node_id not in self.topology:
            raise ValueError(f"El nodo {node_id!r} no existe")
        del self.topology[node_id]
        self.routers.pop(node_id)
        for links in self.topology.values():
            links.pop(node_id, None)
        self._refresh_local_knowledge()

    def _refresh_local_knowledge(self) -> None:
        for node, router in self.routers.items():
            if self.algorithm == "dijkstra":
                router.refresh(self.topology)  # type: ignore[attr-defined]
            elif self.algorithm == "flooding":
                router.set_neighbors(self.topology[node])  # type: ignore[attr-defined]
            else:
                router.update_local_links(self.topology[node])  # type: ignore[attr-defined]

    def _enqueue(
        self,
        queue: deque[_QueuedPacket],
        sender: str,
        target: str,
        packet: Packet,
        path: tuple[str, ...],
    ) -> None:
        if target not in self.topology.get(sender, {}):
            return
        queue.append(_QueuedPacket(sender, target, packet, (*path, target)))

    def converge(self, *, max_events: int = 100_000) -> int:
        """Distribuye LSP o vectores hasta vaciar la cola de control."""

        if self.algorithm in {"dijkstra", "flooding"}:
            return 0
        queue = self._control_queue
        if self.algorithm == "lsr":
            for node, router in self.routers.items():
                assert isinstance(router, LinkStateRouter)
                lsp = router.create_lsp()
                if lsp.ttl == 0:
                    continue
                forwarded = lsp.forwarded()
                for neighbor in sorted(router.neighbors):
                    self._enqueue(queue, node, neighbor, forwarded, (node,))
        else:
            for node, router in self.routers.items():
                assert isinstance(router, DistanceVectorRouter)
                for neighbor, packet in router.create_updates():
                    self._enqueue(queue, node, neighbor, packet, (node,))

        processed = 0
        while queue:
            if processed >= max_events:
                raise RuntimeError("La red no convergió dentro del límite de eventos")
            event = queue.popleft()
            router = self.routers[event.receiver]
            decision = router.handle(event.packet, event.sender)  # type: ignore[attr-defined]
            processed += 1
            for target, packet in decision.outgoing:
                self._enqueue(queue, event.receiver, target, packet, event.path)
        return processed

    def route_message(
        self,
        source: str,
        destination: str,
        payload: Any,
        *,
        ttl: int = 16,
        max_events: int = 100_000,
    ) -> SimulationResult:
        if source not in self.routers or destination not in self.routers:
            raise ValueError("El origen y el destino deben existir en la red")
        router = self.routers[source]
        if self.algorithm == "dijkstra":
            packet = make_packet("dijkstra", "message", source, destination, payload, ttl=ttl)
        else:
            packet = router.create_message(destination, payload, ttl=ttl)  # type: ignore[attr-defined]

        if source == destination:
            return SimulationResult(True, (source,), payload, 0, (), ())

        queue: deque[_QueuedPacket] = deque()
        drops: list[str] = []
        trace: list[TraceEvent] = []
        if self.algorithm == "dijkstra":
            first_hop = router.next_hop(destination)  # type: ignore[attr-defined]
            if first_hop is None or packet.ttl == 0:
                reason = "unreachable" if first_hop is None else "ttl-expired"
                return SimulationResult(False, (), None, 0, (f"{source}:{reason}",), ())
            self._enqueue(queue, source, first_hop, packet.forwarded(), (source,))
        else:
            decision = router.handle(packet, None)  # type: ignore[attr-defined]
            for target, outgoing in decision.outgoing:
                self._enqueue(queue, source, target, outgoing, (source,))
            if not decision.outgoing:
                drops.append(f"{source}:{decision.reason}")

        processed = 0
        while queue:
            if processed >= max_events:
                raise RuntimeError("Se excedió el límite de eventos de datos")
            event = queue.popleft()
            processed += 1
            trace.append(
                TraceEvent(
                    event.sender,
                    event.receiver,
                    event.packet.type,
                    event.packet.packet_id,
                    event.path,
                )
            )
            if self.algorithm == "dijkstra":
                if event.receiver == destination:
                    return SimulationResult(
                        True, event.path, payload, processed, tuple(drops), tuple(trace)
                    )
                if event.packet.ttl == 0:
                    drops.append(f"{event.receiver}:ttl-expired")
                    continue
                current = self.routers[event.receiver]
                next_hop = current.next_hop(destination)  # type: ignore[attr-defined]
                if next_hop is None:
                    drops.append(f"{event.receiver}:unreachable")
                    continue
                self._enqueue(
                    queue,
                    event.receiver,
                    next_hop,
                    event.packet.forwarded(),
                    event.path,
                )
                continue

            current = self.routers[event.receiver]
            decision = current.handle(event.packet, event.sender)  # type: ignore[attr-defined]
            if decision.deliver:
                return SimulationResult(
                    True, event.path, payload, processed, tuple(drops), tuple(trace)
                )
            if not decision.outgoing:
                drops.append(f"{event.receiver}:{decision.reason}")
            for target, outgoing in decision.outgoing:
                self._enqueue(queue, event.receiver, target, outgoing, event.path)

        return SimulationResult(False, (), None, processed, tuple(drops), tuple(trace))

    def routing_tables(self) -> dict[str, dict[str, dict[str, object]]]:
        output: dict[str, dict[str, dict[str, object]]] = {}
        for node, router in self.routers.items():
            if self.algorithm == "flooding":
                output[node] = {}
                continue
            table = router.table  # type: ignore[attr-defined]
            output[node] = {
                destination: {
                    "next_hop": route.next_hop,
                    "cost": route.cost,
                }
                for destination, route in table.items()
            }
        return output
