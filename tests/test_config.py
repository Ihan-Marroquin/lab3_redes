from pathlib import Path
import tempfile
import unittest

from routing_lab.config import ConfigError, NodeNames, Topology, load_endpoints


ROOT = Path(__file__).resolve().parents[1]


class ConfigTests(unittest.TestCase):
    def test_loads_weighted_topology(self) -> None:
        topology = Topology.load(ROOT / "examples" / "topo-demo.txt")

        self.assertEqual(topology.neighbors("A")["I"], 1.0)
        self.assertEqual(len(topology.links), 9)

    def test_loads_names_and_endpoints(self) -> None:
        names = NodeNames.load(ROOT / "examples" / "names-demo.txt")
        endpoints = load_endpoints(ROOT / "examples" / "endpoints-demo.txt")

        self.assertEqual(names.address("A"), "a@lab.local")
        self.assertEqual(endpoints["I"].port, 9109)

    def test_list_neighbors_default_to_unit_cost(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topo.txt"
            path.write_text(
                '{"type":"topo","config":{"A":["B"],"B":["A"]}}',
                encoding="utf-8",
            )

            topology = Topology.load(path)

        self.assertEqual(topology.neighbors("A"), {"B": 1.0})

    def test_unknown_neighbor_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "topo.txt"
            path.write_text(
                '{"type":"topo","config":{"A":["B"]}}', encoding="utf-8"
            )
            with self.assertRaises(ConfigError):
                Topology.load(path)


if __name__ == "__main__":
    unittest.main()

