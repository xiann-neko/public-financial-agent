import unittest

from fincore.money import format_amount, parse_amount


class ParseAmountTest(unittest.TestCase):
    def test_accepts_common_formats(self):
        self.assertEqual(parse_amount("350"), 35000)
        self.assertEqual(parse_amount("₱1,299"), 129900)
        self.assertEqual(parse_amount("1299.5"), 129950)
        self.assertEqual(parse_amount(" P 2,500.75 "), 250075)
        self.assertEqual(parse_amount("php 100"), 10000)

    def test_rejects_bad_input(self):
        for bad in ["0", "-5", "12.345", "abc", "", "1,29,9"]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    parse_amount(bad)


class FormatAmountTest(unittest.TestCase):
    def test_formats(self):
        self.assertEqual(format_amount(129950), "₱1,299.50")
        self.assertEqual(format_amount(0), "₱0.00")
        self.assertEqual(format_amount(-5000), "-₱50.00")
        self.assertEqual(format_amount(123456789), "₱1,234,567.89")


if __name__ == "__main__":
    unittest.main()
