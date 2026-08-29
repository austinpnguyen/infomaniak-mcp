"""Encoding helpers. No network, so these run without credentials."""
import unittest

from infomaniak_mcp.dav import carddav_unsafe, double_encoded, unfold


class TestCarddavUnsafe(unittest.TestCase):
    def test_flags_a_known_trigger(self):
        self.assertEqual(carddav_unsafe("Bạn"), ["ạ"])

    def test_plain_ascii_is_clean(self):
        self.assertEqual(carddav_unsafe("Jane Doe"), [])

    def test_characters_that_survive_are_not_flagged(self):
        for safe in ("ậ", "ử", "ộ", "ề", "ị", "đ", "à"):
            self.assertEqual(carddav_unsafe(safe), [], safe)

    def test_empty_input(self):
        self.assertEqual(carddav_unsafe(""), [])
        self.assertEqual(carddav_unsafe(None), [])


class TestDoubleEncoded(unittest.TestCase):
    def _corrupt(self, text):
        """Reproduce exactly what the server does to a string."""
        return text.encode("utf-8").decode("latin-1")

    def test_repairs_real_corruption(self):
        original = "Đặng Nhật Anh"
        self.assertEqual(double_encoded(self._corrupt(original)), original)

    def test_clean_text_returns_none(self):
        self.assertIsNone(double_encoded("Đặng Nhật Anh"))
        self.assertIsNone(double_encoded("Jane Doe"))

    def test_round_trip_for_every_trigger(self):
        for ch in ("ạ", "ả", "ầ", "ặ", "ỷ"):
            self.assertEqual(double_encoded(self._corrupt(ch)), ch, ch)


class TestUnfold(unittest.TestCase):
    def test_joins_folded_lines(self):
        self.assertEqual(unfold("SUMMARY:one\r\n  two"), "SUMMARY:one two")

    def test_leaves_normal_lines_alone(self):
        self.assertEqual(unfold("A:1\r\nB:2"), "A:1\r\nB:2")


if __name__ == "__main__":
    unittest.main()
