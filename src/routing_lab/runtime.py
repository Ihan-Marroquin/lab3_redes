"""Ejecución concurrente de nodos independientes sobre sockets TCP."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass
import json
import logging
from typing import Awaitable, Callable, Mapping

from routing_lab.algorithms import (
    DijkstraRouter,
    DistanceVectorRouter,
    FloodingRouter,
    LinkStateRouter,
)
from routing_lab.config import Endpoint
from routing_lab.protocol import Packet, PacketError, make_packet


LOGGER = logging.getLogger(__name__)
MAX_FRAME_BYTES = 1_048_576


class TransportError(RuntimeError):
    pass


PacketHandler = Callable[[str, Packet], Awaitable[None]]


class TcpTransport:
    """Transporte de una trama JSON por conexión TCP."""

    def __init__(
        self,
        node_id: str,
        endpoints: Mapping[str, Endpoint],
        on_packet: PacketHandler,
    ) -> None:
        if node_id not in endpoints:
            raise TransportError(f"No existe endpoint para {node_id!r}")
        self.node_id = node_id
        self.endpoints = dict(endpoints)
        self.on_packet = on_packet
        self._server: asyncio.AbstractServer | None = None

    async def start(self) -> None:
        endpoint = self.endpoints[self.node_id]
        self._server = await asyncio.start_server(
            self._handle_client,
            endpoint.host,
            endpoint.port,
            limit=MAX_FRAME_BYTES,
        )

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        await self._server.wait_closed()
        self._server = None

    async def _handle_client(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            raw = await reader.readline()
            if not raw or len(raw) > MAX_FRAME_BYTES or not raw.endswith(b"\n"):
                raise TransportError("Trama TCP vacía, incompleta o demasiado grande")
            envelope = json.loads(raw)
            if not isinstance(envelope, dict):
                raise TransportError("La trama debe ser un objeto JSON")
            sender = envelope.get("sender")
            packet_data = envelope.get("packet")
            if not isinstance(sender, str) or sender not in self.endpoints:
                raise TransportError("La trama no identifica un emisor conocido")
            if not isinstance(packet_data, dict):
                raise TransportError("La trama no contiene un paquete")
            await self.on_packet(sender, Packet.from_dict(packet_data))
        except (json.JSONDecodeError, PacketError, TransportError) as exc:
            LOGGER.warning("Trama descartada en %s: %s", self.node_id, exc)
        finally:
            writer.close()
            with suppress(ConnectionError):
                await writer.wait_closed()

    async def send(self, neighbor: str, packet: Packet, *, attempts: int = 3) -> None:
        endpoint = self.endpoints.get(neighbor)
        if endpoint is None:
            raise TransportError(f"No existe endpoint para {neighbor!r}")
        frame = json.dumps(
            {"sender": self.node_id, "packet": packet.to_dict()},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8") + b"\n"
        last_error: OSError | None = None
        for attempt in range(attempts):
            try:
                reader, writer = await asyncio.open_connection(endpoint.host, endpoint.port)
                del reader
                writer.write(frame)
                await writer.drain()
                writer.close()
                await writer.wait_closed()
                return
            except OSError as exc:
                last_error = exc
                if attempt + 1 < attempts:
                    await asyncio.sleep(0.1 * (attempt + 1))
        raise TransportError(f"No se pudo contactar a {neighbor}: {last_error}")


@dataclass(frozen=True, slots=True)
class DeliveredMessage:
    sender: str
    payload: object
    packet_id: str | None


class AsyncNode:
    """Nodo con tareas paralelas de forwarding y routing."""

    def __init__(
        self,
        node_id: str,
        algorithm: str,
        topology: Mapping[str, Mapping[str, float]],
        endpoints: Mapping[str, Endpoint],
        *,
        routing_interval: float = 5.0,
    ) -> None:
        if node_id not in topology:
            raise ValueError(f"El nodo {node_id!r} no existe en la topología")
        if routing_interval <= 0:
            raise ValueError("El intervalo de routing debe ser positivo")
        self.node_id = node_id
        self.algorithm = algorithm
        self.routing_interval = routing_interval
        self._local_links = dict(topology[node_id])
        if algorithm == "dijkstra":
            self.router = DijkstraRouter(node_id, topology)
        elif algorithm == "flooding":
            self.router = FloodingRouter(node_id, self._local_links)
        elif algorithm == "lsr":
            self.router = LinkStateRouter(node_id, self._local_links)
        elif algorithm == "dvr":
            self.router = DistanceVectorRouter(node_id, self._local_links)
        else:
            raise ValueError(f"Algoritmo no soportado: {algorithm}")

        self.transport = TcpTransport(node_id, endpoints, self._receive)
        self.delivered: asyncio.Queue[DeliveredMessage] = asyncio.Queue()
        self._forwarding_queue: asyncio.Queue[tuple[str, Packet]] = asyncio.Queue()
        self._routing_queue: asyncio.Queue[tuple[str, Packet]] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        await self.transport.start()
        self._tasks = [
            asyncio.create_task(self._forwarding_loop(), name=f"forwarding-{self.node_id}"),
            asyncio.create_task(self._routing_loop(), name=f"routing-{self.node_id}"),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await self.transport.close()

    async def _receive(self, sender: str, packet: Packet) -> None:
        if sender not in self._local_links:
            LOGGER.warning("%s descartó un paquete del no vecino %s", self.node_id, sender)
            return
        target = self._routing_queue if packet.type == "info" else self._forwarding_queue
        await target.put((sender, packet))

    async def _safe_send(self, target: str, packet: Packet) -> None:
        try:
            await self.transport.send(target, packet)
        except TransportError as exc:
            LOGGER.warning("%s", exc)

    async def _send_many(self, outgoing: tuple[tuple[str, Packet], ...]) -> None:
        if outgoing:
            await asyncio.gather(
                *(self._safe_send(target, packet) for target, packet in outgoing)
            )

    async def _forwarding_loop(self) -> None:
        while True:
            sender, packet = await self._forwarding_queue.get()
            await self._process_data(packet, sender)

    async def _process_data(self, packet: Packet, sender: str | None) -> bool:
        if self.algorithm == "dijkstra":
            if packet.proto != "dijkstra" or packet.type != "message":
                return False
            if packet.destination == self.node_id:
                await self.delivered.put(
                    DeliveredMessage(packet.sender, packet.payload, packet.packet_id)
                )
                return True
            if packet.ttl == 0:
                return False
            next_hop = self.router.next_hop(packet.destination)  # type: ignore[union-attr]
            if next_hop is None:
                return False
            await self._safe_send(next_hop, packet.forwarded())
            return True

        decision = self.router.handle(packet, sender)  # type: ignore[union-attr]
        if decision.deliver:
            await self.delivered.put(
                DeliveredMessage(packet.sender, packet.payload, packet.packet_id)
            )
        await self._send_many(decision.outgoing)
        return decision.deliver or bool(decision.outgoing)

    async def _advertise(self) -> None:
        if self.algorithm == "lsr":
            lsp = self.router.create_lsp()  # type: ignore[union-attr]
            if lsp.ttl:
                packet = lsp.forwarded()
                outgoing = tuple(
                    (neighbor, packet) for neighbor in sorted(self._local_links)
                )
                await self._send_many(outgoing)
        elif self.algorithm == "dvr":
            await self._send_many(self.router.create_updates())  # type: ignore[union-attr]

    async def _routing_loop(self) -> None:
        loop = asyncio.get_running_loop()
        next_advertisement = loop.time()
        while True:
            timeout = max(0.0, next_advertisement - loop.time())
            try:
                sender, packet = await asyncio.wait_for(
                    self._routing_queue.get(), timeout=timeout
                )
            except TimeoutError:
                await self._advertise()
                next_advertisement = loop.time() + self.routing_interval
                continue
            if self.algorithm not in {"lsr", "dvr"}:
                continue
            decision = self.router.handle(packet, sender)  # type: ignore[union-attr]
            await self._send_many(decision.outgoing)

    async def send_message(
        self, destination: str, payload: object, *, ttl: int = 16
    ) -> bool:
        if self.algorithm == "dijkstra":
            packet = make_packet(
                "dijkstra", "message", self.node_id, destination, payload, ttl=ttl
            )
        else:
            packet = self.router.create_message(destination, payload, ttl=ttl)  # type: ignore[union-attr]
        return await self._process_data(packet, None)

    def routing_table(self) -> dict[str, dict[str, object]]:
        if self.algorithm == "flooding":
            return {}
        return {
            destination: {"next_hop": route.next_hop, "cost": route.cost}
            for destination, route in self.router.table.items()  # type: ignore[union-attr]
        }

