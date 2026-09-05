import unittest

from routing_lab.algorithms import (
    DistanceVectorRouter,
    FloodingRouter,
    LinkStateRouter,
    shortest_paths,
)


GRAPH = {
    "A": {"B": 2, "C": 10},
    "B": {"A": 2, "C": 3},
    "C": {"A": 10, "B": 3},
}


class DijkstraTests(unittest.TestCase):
    def test_selects_minimum_cost_path(self) -> None:
        table = shortest_paths(GRAPH, "A")

        self.assertEqual(table["C"].path, ("A", "B", "C"))
        self.assertEqual(table["C"].next_hop, "B")
        self.assertEqual(table["C"].cost, 5)

    def test_omits_unreachable_nodes(self) -> None:
        table = shortest_paths({"A": {}, "B": {}}, "A")

        self.assertNotIn("B", table)


class FloodingTests(unittest.TestCase):
    def test_forwards_to_every_neighbor_except_sender(self) -> None:
        router = FloodingRouter("B", ["A", "C", "D"])
        packet = router.create_message("D", "hola", ttl=4)

        decision = router.handle(packet, "A")

        self.assertEqual([target for target, _ in decision.outgoing], ["C", "D"])
        self.assertTrue(all(forwarded.ttl == 3 for _, forwarded in decision.outgoing))

    def test_discards_duplicate_packet(self) -> None:
        router = FloodingRouter("B", ["A", "C"])
        packet = router.create_message("C", "hola")

        router.handle(packet, "A")
        duplicate = router.handle(packet, "A")

        self.assertEqual(duplicate.reason, "duplicate")
        self.assertFalse(duplicate.outgoing)


class LinkStateTests(unittest.TestCase):
    def test_new_lsp_updates_route_table(self) -> None:
        a = LinkStateRouter("A", {"B": 2})
        b = LinkStateRouter("B", {"A": 2, "C": 3})
        lsp = b.create_lsp().forwarded()

        decision = a.handle(lsp, "B")

        self.assertTrue(decision.topology_changed)
        self.assertEqual(a.next_hop("C"), "B")
        self.assertEqual(a.table["C"].cost, 5)

    def test_stale_lsp_is_ignored(self) -> None:
        a = LinkStateRouter("A", {"B": 1})
        b = LinkStateRouter("B", {"A": 1})
        lsp = b.create_lsp().forwarded()

        a.handle(lsp, "B")
        decision = a.handle(lsp, "B")

        self.assertEqual(decision.reason, "stale-lsp")


class DistanceVectorTests(unittest.TestCase):
    def test_learns_route_from_neighbor_vector(self) -> None:
        a = DistanceVectorRouter("A", {"B": 2})
        b = DistanceVectorRouter("B", {"A": 2, "C": 3})
        update = dict(b.create_updates())["A"]

        decision = a.handle(update, "B")

        self.assertTrue(decision.table_changed)
        self.assertEqual(a.next_hop("C"), "B")
        self.assertEqual(a.table["C"].cost, 5)

    def test_poison_reverse_hides_learned_route(self) -> None:
        a = DistanceVectorRouter("A", {"B": 1})
        b = DistanceVectorRouter("B", {"A": 1, "C": 1})
        a.handle(dict(b.create_updates())["A"], "B")

        update_to_b = dict(a.create_updates())["B"]

        self.assertEqual(update_to_b.payload["distances"]["C"], a.infinity)


if __name__ == "__main__":
    unittest.main()

