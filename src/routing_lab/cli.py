"""Interfaz de línea de comandos para simulación y nodos TCP."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import json
import logging
from pathlib import Path
from typing import Sequence

from routing_lab.config import Topology, load_endpoints
from routing_lab.runtime import AsyncNode
from routing_lab.simulator import NetworkSimulator


ALGORITHMS = ("dijkstra", "flooding", "lsr", "dvr")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="routing-lab", description="Laboratorio de algoritmos de enrutamiento"
    )
    parser.add_argument("--verbose", action="store_true", help="mostrar eventos de red")
    commands = parser.add_subparsers(dest="command", required=True)

    simulate = commands.add_parser("simulate", help="enviar un mensaje en memoria")
    simulate.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    simulate.add_argument("--topology", type=Path, required=True)
    simulate.add_argument("--source", required=True)
    simulate.add_argument("--destination", required=True)
    simulate.add_argument("--message", required=True)
    simulate.add_argument("--ttl", type=int, default=16)
    simulate.add_argument("--show-tables", action="store_true")

    tables = commands.add_parser("tables", help="calcular todas las tablas")
    tables.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    tables.add_argument("--topology", type=Path, required=True)

    node = commands.add_parser("node", help="levantar un nodo TCP interactivo")
    node.add_argument("--id", required=True, dest="node_id")
    node.add_argument("--algorithm", choices=ALGORITHMS, required=True)
    node.add_argument("--topology", type=Path, required=True)
    node.add_argument("--endpoints", type=Path, required=True)
    node.add_argument("--routing-interval", type=float, default=5.0)
    return parser


def _print_json(value: object) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def _simulate(args: argparse.Namespace) -> int:
    topology = Topology.load(args.topology)
    network = NetworkSimulator(topology.links, args.algorithm)
    control_events = network.converge()
    result = network.route_message(
        args.source, args.destination, args.message, ttl=args.ttl
    )
    output = {
        "algorithm": args.algorithm,
        "control_events": control_events,
        "delivered": result.delivered,
        "path": list(result.path),
        "transmissions": result.transmissions,
        "drops": list(result.drops),
        "payload": result.payload,
    }
    if args.show_tables:
        output["routing_tables"] = network.routing_tables()
    _print_json(output)
    return 0 if result.delivered else 2


def _tables(args: argparse.Namespace) -> int:
    topology = Topology.load(args.topology)
    network = NetworkSimulator(topology.links, args.algorithm)
    control_events = network.converge()
    _print_json(
        {
            "algorithm": args.algorithm,
            "control_events": control_events,
            "routing_tables": network.routing_tables(),
        }
    )
    return 0


async def _display_deliveries(node: AsyncNode) -> None:
    while True:
        message = await node.delivered.get()
        print(
            f"\n[RECIBIDO de {message.sender}] {message.payload}\n{node.node_id}> ",
            end="",
            flush=True,
        )


async def _interactive_node(args: argparse.Namespace) -> int:
    topology = Topology.load(args.topology)
    endpoints = load_endpoints(args.endpoints)
    node = AsyncNode(
        args.node_id,
        args.algorithm,
        topology.links,
        endpoints,
        routing_interval=args.routing_interval,
    )
    await node.start()
    printer = asyncio.create_task(_display_deliveries(node))
    print(f"Nodo {args.node_id} activo con {args.algorithm}.")
    print("Comandos: send <destino> <mensaje> | table | help | quit")
    try:
        while True:
            try:
                line = (await asyncio.to_thread(input, f"{args.node_id}> ")).strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not line:
                continue
            command, *rest = line.split(maxsplit=2)
            command = command.lower()
            if command in {"quit", "exit"}:
                break
            if command == "help":
                print("send <destino> <mensaje> | table | help | quit")
                continue
            if command == "table":
                _print_json(node.routing_table())
                continue
            if command == "send" and len(rest) == 2:
                accepted = await node.send_message(rest[0], rest[1])
                print("Mensaje encolado." if accepted else "No existe una ruta disponible.")
                continue
            print("Comando inválido. Escriba 'help' para ver las opciones.")
    finally:
        printer.cancel()
        with suppress(asyncio.CancelledError):
            await printer
        await node.stop()
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    if args.command == "simulate":
        return _simulate(args)
    if args.command == "tables":
        return _tables(args)
    if args.command == "node":
        return asyncio.run(_interactive_node(args))
    parser.error("Comando desconocido")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

