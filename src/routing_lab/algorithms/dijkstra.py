"""Cálculo de rutas mínimas mediante el algoritmo de Dijkstra."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from math import inf, isfinite
from typing import Mapping


Graph = Mapping[str, Mapping[str, float]]


@dataclass(frozen=True, slots=True)
class Route:
    destination: str
    next_hop: str
    cost: float
    path: tuple[str, ...]


def _validate_graph(graph: Graph, source: str) -> set[str]:
    nodes = set(graph)
    nodes.update(neighbor for links in graph.values() for neighbor in links)
    if source not in nodes:
        raise ValueError(f"El origen {source!r} no existe en la topología")
    for node, links in graph.items():
        for neighbor, raw_cost in links.items():
            if isinstance(raw_cost, bool) or not isinstance(raw_cost, (int, float)):
                raise ValueError(f"Costo inválido en {node}->{neighbor}")
            if raw_cost < 0 or not isfinite(float(raw_cost)):
                raise ValueError(f"Dijkstra requiere costos finitos no negativos: {node}->{neighbor}")
    return nodes


def shortest_paths(graph: Graph, source: str) -> dict[str, Route]:
    """Calcula una tabla de rutas alcanzables desde ``source``.

    La cola incluye la ruta completa como criterio secundario. Esto vuelve
    determinista la selección cuando dos caminos tienen el mismo costo.
    """

    nodes = _validate_graph(graph, source)
    distances = {node: inf for node in nodes}
    best_paths: dict[str, tuple[str, ...]] = {source: (source,)}
    distances[source] = 0.0
    queue: list[tuple[float, tuple[str, ...], str]] = [(0.0, (source,), source)]

    while queue:
        distance, path, node = heapq.heappop(queue)
        if distance != distances[node] or path != best_paths.get(node):
            continue
        for neighbor, raw_cost in graph.get(node, {}).items():
            candidate_distance = distance + float(raw_cost)
            candidate_path = (*path, neighbor)
            current_path = best_paths.get(neighbor)
            if candidate_distance < distances[neighbor] or (
                candidate_distance == distances[neighbor]
                and (current_path is None or candidate_path < current_path)
            ):
                distances[neighbor] = candidate_distance
                best_paths[neighbor] = candidate_path
                heapq.heappush(queue, (candidate_distance, candidate_path, neighbor))

    table: dict[str, Route] = {}
    for destination, path in best_paths.items():
        if destination == source:
            continue
        table[destination] = Route(
            destination=destination,
            next_hop=path[1],
            cost=distances[destination],
            path=path,
        )
    return table


class DijkstraRouter:
    """Router estático que puede consultar la topología completa."""

    protocol = "dijkstra"

    def __init__(self, node_id: str, topology: Graph) -> None:
        self.node_id = node_id
        self._topology = {node: dict(links) for node, links in topology.items()}
        self._table = shortest_paths(self._topology, node_id)

    @property
    def table(self) -> dict[str, Route]:
        return dict(self._table)

    def next_hop(self, destination: str) -> str | None:
        route = self._table.get(destination)
        return route.next_hop if route else None

    def route_to(self, destination: str) -> Route | None:
        return self._table.get(destination)

    def refresh(self, topology: Graph) -> bool:
        updated = {node: dict(links) for node, links in topology.items()}
        new_table = shortest_paths(updated, self.node_id)
        changed = new_table != self._table
        self._topology = updated
        self._table = new_table
        return changed

