import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data_fetch import interval_to_sample_step


class IntervalToSampleStepTests(unittest.TestCase):
    def test_one_second_interval_uses_raw_readings(self) -> None:
        self.assertIsNone(interval_to_sample_step("1 sec"))

    def test_multi_second_interval_returns_sampling_step(self) -> None:
        self.assertEqual(interval_to_sample_step("5 sec"), 5)
        self.assertEqual(interval_to_sample_step("1 min"), 60)
        self.assertEqual(interval_to_sample_step("15 min"), 900)

    def test_unknown_interval_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            interval_to_sample_step("2 hours")


if __name__ == "__main__":
    unittest.main()
