import asyncio
import socket
import unittest

from routing_lab.config import Endpoint
from routing_lab.runtime import AsyncNode


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_three_independent_tcp_nodes_forward_message(self) -> None:
        topology = {
            "A": {"B": 1},
            "B": {"A": 1, "C": 1},
            "C": {"B": 1},
        }
        endpoints = {
            node: Endpoint("127.0.0.1", _free_port()) for node in topology
        }
        nodes = {
            node: AsyncNode(node, "dijkstra", topology, endpoints)
            for node in topology
        }
        await asyncio.gather(*(node.start() for node in nodes.values()))
        try:
            accepted = await nodes["A"].send_message("C", "mensaje TCP")
            delivered = await asyncio.wait_for(nodes["C"].delivered.get(), timeout=2)

            self.assertTrue(accepted)
            self.assertEqual(delivered.sender, "A")
            self.assertEqual(delivered.payload, "mensaje TCP")
        finally:
            await asyncio.gather(*(node.stop() for node in nodes.values()))


if __name__ == "__main__":
    unittest.main()

