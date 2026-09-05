from pathlib import Path
import unittest

from routing_lab.config import Topology
from routing_lab.simulator import NetworkSimulator


ROOT = Path(__file__).resolve().parents[1]


class SimulatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.topology = Topology.load(ROOT / "examples" / "topo-demo.txt").links

    def test_every_algorithm_delivers(self) -> None:
        for algorithm in ("dijkstra", "flooding", "lsr", "dvr"):
            with self.subTest(algorithm=algorithm):
                network = NetworkSimulator(self.topology, algorithm)
                network.converge()

                result = network.route_message("A", "H", "hola")

                self.assertTrue(result.delivered)
                self.assertEqual(result.path[0], "A")
                self.assertEqual(result.path[-1], "H")

    def test_lsr_and_dvr_converge_to_dijkstra_costs(self) -> None:
        expected = NetworkSimulator(self.topology, "dijkstra")
        expected_tables = expected.routing_tables()

        for algorithm in ("lsr", "dvr"):
            with self.subTest(algorithm=algorithm):
                network = NetworkSimulator(self.topology, algorithm)
                network.converge()

                self.assertEqual(network.routing_tables(), expected_tables)

    def test_ttl_can_stop_a_message(self) -> None:
        network = NetworkSimulator(self.topology, "dijkstra")

        result = network.route_message("A", "H", "hola", ttl=2)

        self.assertFalse(result.delivered)
        self.assertTrue(any("ttl-expired" in reason for reason in result.drops))

    def test_routes_adapt_after_link_failure(self) -> None:
        topology = {
            "A": {"B": 1, "C": 10},
            "B": {"A": 1, "C": 1},
            "C": {"A": 10, "B": 1},
        }
        for algorithm in ("dijkstra", "lsr", "dvr"):
            with self.subTest(algorithm=algorithm):
                network = NetworkSimulator(topology, algorithm)
                network.converge()
                self.assertEqual(network.routing_tables()["A"]["C"]["cost"], 2)

                network.set_link("B", "C", None)
                network.converge()

                self.assertEqual(network.routing_tables()["A"]["C"]["cost"], 10)
                self.assertEqual(
                    network.route_message("A", "C", "recuperado").path,
                    ("A", "C"),
                )


if __name__ == "__main__":
    unittest.main()
