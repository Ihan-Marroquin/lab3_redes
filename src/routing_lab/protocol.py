"""Protocolo JSON común para todos los algoritmos del laboratorio."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
from typing import Any, Mapping
from uuid import uuid4


SUPPORTED_PROTOCOLS = frozenset({"dijkstra", "flooding", "lsr", "dvr"})
SUPPORTED_TYPES = frozenset({"message", "echo", "info", "hello", "ack"})


class PacketError(ValueError):
    """Señala un paquete incompleto o incompatible con el protocolo."""


@dataclass(frozen=True, slots=True)
class Packet:
    """Paquete inmutable serializable al formato definido en el enunciado."""

    proto: str
    type: str
    sender: str
    destination: str
    ttl: int = 16
    headers: tuple[Mapping[str, Any], ...] = field(default_factory=tuple)
    payload: Any = None

    def __post_init__(self) -> None:
        if self.proto not in SUPPORTED_PROTOCOLS:
            raise PacketError(f"Protocolo no soportado: {self.proto}")
        if self.type not in SUPPORTED_TYPES:
            raise PacketError(f"Tipo de paquete no soportado: {self.type}")
        if not isinstance(self.sender, str) or not self.sender.strip():
            raise PacketError("El campo 'from' debe ser una cadena no vacía")
        if not isinstance(self.destination, str) or not self.destination.strip():
            raise PacketError("El campo 'to' debe ser una cadena no vacía")
        if isinstance(self.ttl, bool) or not isinstance(self.ttl, int) or self.ttl < 0:
            raise PacketError("El TTL debe ser un entero mayor o igual a cero")
        if not all(isinstance(item, Mapping) for item in self.headers):
            raise PacketError("Cada header debe ser un objeto JSON")

    @property
    def packet_id(self) -> str | None:
        """Obtiene el identificador usado para suprimir duplicados."""

        value = self.header("packet_id")
        return str(value) if value is not None else None

    def header(self, name: str, default: Any = None) -> Any:
        for item in self.headers:
            if name in item:
                return item[name]
        return default

    def with_header(self, name: str, value: Any) -> Packet:
        remaining = tuple(item for item in self.headers if name not in item)
        return replace(self, headers=(*remaining, {name: value}))

    def forwarded(self) -> Packet:
        """Crea la copia que cruza un salto y reduce su TTL."""

        if self.ttl == 0:
            raise PacketError("No se puede reenviar un paquete con TTL agotado")
        return replace(self, ttl=self.ttl - 1)

    def to_dict(self) -> dict[str, Any]:
        return {
            "proto": self.proto,
            "type": self.type,
            "from": self.sender,
            "to": self.destination,
            "ttl": self.ttl,
            "headers": [dict(item) for item in self.headers],
            "payload": self.payload,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, separators=(",", ":"))

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Packet:
        required = {"proto", "type", "from", "to", "ttl", "headers", "payload"}
        missing = required - data.keys()
        if missing:
            raise PacketError(f"Faltan campos: {', '.join(sorted(missing))}")
        headers = data["headers"]
        if not isinstance(headers, list):
            raise PacketError("El campo 'headers' debe ser una lista")
        return cls(
            proto=data["proto"],
            type=data["type"],
            sender=data["from"],
            destination=data["to"],
            ttl=data["ttl"],
            headers=tuple(headers),
            payload=data["payload"],
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> Packet:
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PacketError("El paquete no contiene JSON válido") from exc
        if not isinstance(data, dict):
            raise PacketError("El paquete JSON debe ser un objeto")
        return cls.from_dict(data)


def make_packet(
    proto: str,
    packet_type: str,
    sender: str,
    destination: str,
    payload: Any,
    *,
    ttl: int = 16,
    headers: tuple[Mapping[str, Any], ...] = (),
) -> Packet:
    """Construye un paquete con identificador global si aún no se indicó uno."""

    if not any("packet_id" in item for item in headers):
        headers = (*headers, {"packet_id": uuid4().hex})
    return Packet(proto, packet_type, sender, destination, ttl, headers, payload)

