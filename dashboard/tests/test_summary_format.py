import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from summary_format import build_summary_blocks


class SummaryFormatTests(unittest.TestCase):
    def test_build_summary_blocks_formats_each_metric_on_its_own_line(self) -> None:
        supply, current, power = build_summary_blocks(
            {
                "Supply Voltage Avg": 0.92,
                "Supply Voltage Max": 1.63,
                "Current Avg": 2.29,
                "Current Max": 3.0,
                "Charge Total": 4.56,
                "Power Avg": 7.89,
                "Power Max": 8.91,
                "Energy Total": 12.34,
            }
        )

        self.assertEqual(
            supply,
            "**Supply Voltage:**\n\n**Avg:** 0.92 V\n\n**Max:** 1.63 V",
        )
        self.assertEqual(
            current,
            "**Current:**\n\n**Avg:** 2.29 mA\n\n**Max:** 3.00 mA\n\n**Charge:** 4.56 mAh",
        )
        self.assertEqual(
            power,
            "**Power:**\n\n**Avg:** 7.89 mW\n\n**Max:** 8.91 mW\n\n**Energy:** 12.34 mWh",
        )

    def test_build_summary_blocks_handles_zero_values(self) -> None:
        supply, current, power = build_summary_blocks(
            {
                "Supply Voltage Avg": 0.0,
                "Supply Voltage Max": 0.0,
                "Current Avg": 0.0,
                "Current Max": 0.0,
                "Charge Total": 0.0,
                "Power Avg": 0.0,
                "Power Max": 0.0,
                "Energy Total": 0.0,
            }
        )

        self.assertIn("**Avg:** 0.00 V", supply)
        self.assertIn("**Charge:** 0.00 mAh", current)
        self.assertIn("**Energy:** 0.00 mWh", power)


if __name__ == "__main__":
    unittest.main()
