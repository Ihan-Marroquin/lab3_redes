"""Carga y validación de los archivos de configuración del laboratorio."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any, Mapping


class ConfigError(ValueError):
    """Indica que un archivo no cumple el formato esperado."""


def _read_document(path: str | Path, expected_type: str) -> Mapping[str, Any]:
    source = Path(path)
    try:
        document = json.loads(source.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"No se pudo leer {source}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"JSON inválido en {source}: {exc}") from exc
    if not isinstance(document, dict):
        raise ConfigError("La raíz del archivo debe ser un objeto JSON")
    if document.get("type") != expected_type:
        raise ConfigError(f"Se esperaba type='{expected_type}'")
    config = document.get("config")
    if not isinstance(config, dict):
        raise ConfigError("El campo 'config' debe ser un objeto")
    return config


@dataclass(frozen=True, slots=True)
class Topology:
    """Grafo dirigido ponderado; una lista de vecinos implica costo 1."""

    links: Mapping[str, Mapping[str, float]]

    @classmethod
    def load(cls, path: str | Path) -> Topology:
        raw = _read_document(path, "topo")
        links: dict[str, dict[str, float]] = {}
        for node, neighbors in raw.items():
            if not isinstance(node, str) or not node:
                raise ConfigError("Cada identificador de nodo debe ser una cadena")
            if isinstance(neighbors, list):
                if not all(isinstance(value, str) and value for value in neighbors):
                    raise ConfigError(f"Vecinos inválidos para {node}")
                links[node] = {neighbor: 1.0 for neighbor in neighbors}
            elif isinstance(neighbors, dict):
                parsed: dict[str, float] = {}
                for neighbor, raw_cost in neighbors.items():
                    if not isinstance(neighbor, str) or not neighbor:
                        raise ConfigError(f"Vecino inválido para {node}")
                    if isinstance(raw_cost, bool) or not isinstance(raw_cost, (int, float)):
                        raise ConfigError(f"Costo inválido para {node}->{neighbor}")
                    cost = float(raw_cost)
                    if cost <= 0:
                        raise ConfigError(f"El costo de {node}->{neighbor} debe ser positivo")
                    parsed[neighbor] = cost
                links[node] = parsed
            else:
                raise ConfigError(f"La configuración de {node} debe ser lista u objeto")

        unknown = {
            neighbor
            for neighbors in links.values()
            for neighbor in neighbors
            if neighbor not in links
        }
        if unknown:
            raise ConfigError(f"Vecinos sin definición: {', '.join(sorted(unknown))}")
        return cls(links)

    def neighbors(self, node_id: str) -> dict[str, float]:
        """Entrega únicamente los enlaces que el nodo puede conocer al iniciar."""

        if node_id not in self.links:
            raise ConfigError(f"El nodo {node_id!r} no existe en la topología")
        return dict(self.links[node_id])


@dataclass(frozen=True, slots=True)
class NodeNames:
    values: Mapping[str, str]

    @classmethod
    def load(cls, path: str | Path) -> NodeNames:
        raw = _read_document(path, "names")
        if not all(
            isinstance(node, str)
            and node
            and isinstance(address, str)
            and address
            for node, address in raw.items()
        ):
            raise ConfigError("Los nombres y direcciones deben ser cadenas no vacías")
        if len(set(raw.values())) != len(raw):
            raise ConfigError("Cada dirección debe pertenecer a un solo nodo")
        return cls(dict(raw))

    def address(self, node_id: str) -> str:
        try:
            return self.values[node_id]
        except KeyError as exc:
            raise ConfigError(f"No hay dirección asignada a {node_id!r}") from exc


@dataclass(frozen=True, slots=True)
class Endpoint:
    host: str
    port: int


def load_endpoints(path: str | Path) -> dict[str, Endpoint]:
    """Carga direcciones TCP locales sin mezclarlas con la topología lógica."""

    raw = _read_document(path, "endpoints")
    endpoints: dict[str, Endpoint] = {}
    for node, value in raw.items():
        if not isinstance(node, str) or not isinstance(value, dict):
            raise ConfigError("Cada endpoint debe ser un objeto asociado a un nodo")
        host, port = value.get("host"), value.get("port")
        if not isinstance(host, str) or not host:
            raise ConfigError(f"Host inválido para {node}")
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ConfigError(f"Puerto inválido para {node}")
        endpoints[node] = Endpoint(host, port)
    return endpoints

