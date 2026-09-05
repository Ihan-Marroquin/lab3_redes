import unittest

from routing_lab.protocol import Packet, PacketError, make_packet


class PacketTests(unittest.TestCase):
    def test_json_round_trip_preserves_standard_fields(self) -> None:
        original = make_packet("lsr", "message", "A", "B", "áéí", ttl=7)

        restored = Packet.from_json(original.to_json())

        self.assertEqual(restored, original)
        self.assertIsNotNone(restored.packet_id)
        self.assertEqual(restored.to_dict()["from"], "A")
        self.assertEqual(restored.to_dict()["to"], "B")

    def test_forwarding_reduces_ttl_without_mutating_packet(self) -> None:
        packet = make_packet("dvr", "message", "A", "B", "hola", ttl=2)

        forwarded = packet.forwarded()

        self.assertEqual(packet.ttl, 2)
        self.assertEqual(forwarded.ttl, 1)
        self.assertEqual(forwarded.packet_id, packet.packet_id)

    def test_forwarding_rejects_expired_packet(self) -> None:
        packet = make_packet("flooding", "message", "A", "B", "hola", ttl=0)

        with self.assertRaises(PacketError):
            packet.forwarded()

    def test_missing_wire_fields_are_rejected(self) -> None:
        with self.assertRaises(PacketError):
            Packet.from_dict({"proto": "dvr"})


if __name__ == "__main__":
    unittest.main()

