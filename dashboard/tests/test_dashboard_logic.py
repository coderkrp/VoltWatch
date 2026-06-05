import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dashboard_logic import (  # noqa: E402
    append_incremental_readings,
    chart_data,
    compute_session_stats,
    latest_cursor,
    latest_reading,
    normalize_readings,
    reading_params,
)


class DashboardLogicTests(unittest.TestCase):
    def test_latest_cursor_uses_boot_aware_position(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": 1,
                    "sensor_id": 7,
                    "timestamp": "2026-04-04T10:00:00Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 4.2,
                    "current": 90.0,
                },
                {
                    "boot_id": "boot-b",
                    "seq": 2,
                    "sensor_id": 7,
                    "timestamp": "2026-04-04T10:00:05Z",
                    "bus_voltage": 4.1,
                    "shunt_voltage": 1.1,
                    "supply_voltage": 4.3,
                    "current": 100.0,
                },
            ]
        )

        self.assertEqual(latest_cursor(df), ("boot-b", 2))
        self.assertEqual(latest_reading(df)["power"], 430.0)

    def test_append_incremental_readings_deduplicates_same_boot_seq_sensor(self) -> None:
        existing_df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": 1,
                    "sensor_id": 3,
                    "timestamp": "2026-04-04T10:00:00Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 4.2,
                    "current": 90.0,
                }
            ]
        )
        updates_df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": 1,
                    "sensor_id": 3,
                    "timestamp": "2026-04-04T10:00:00Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 4.2,
                    "current": 90.0,
                },
                {
                    "boot_id": "boot-b",
                    "seq": 1,
                    "sensor_id": 3,
                    "timestamp": "2026-04-04T10:00:03Z",
                    "bus_voltage": 4.1,
                    "shunt_voltage": 1.1,
                    "supply_voltage": 4.4,
                    "current": 100.0,
                },
            ]
        )

        combined = append_incremental_readings(existing_df, updates_df)

        self.assertEqual(len(combined), 2)
        self.assertEqual(list(combined["boot_id"]), ["boot-a", "boot-b"])

    def test_chart_data_applies_existing_seq_sampling_behavior(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": seq,
                    "sensor_id": 3,
                    "timestamp": f"2026-04-04T10:00:0{seq}Z",
                    "bus_voltage": 4.0 + seq,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 4.0 + seq,
                    "current": 10.0 * seq,
                }
                for seq in range(1, 6)
            ]
        )

        sampled = chart_data(df, 2)

        self.assertEqual(list(sampled["seq"]), [2, 4])
        self.assertIn("time_bucket", sampled.columns)

    def test_compute_session_stats_uses_charge_and_energy_totals(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": 1,
                    "sensor_id": 5,
                    "timestamp": "2026-04-04T10:00:00Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 5.0,
                    "current": 3600.0,
                },
                {
                    "boot_id": "boot-a",
                    "seq": 2,
                    "sensor_id": 5,
                    "timestamp": "2026-04-04T10:00:01Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 5.0,
                    "current": 3600.0,
                },
            ]
        )

        stats = compute_session_stats(df)

        self.assertAlmostEqual(stats["Charge Total"], 1.0)
        self.assertAlmostEqual(stats["Energy Total"], 5.0)
        self.assertAlmostEqual(stats["Power Avg"], 18000.0)

    def test_normalize_readings_produces_power_column(self) -> None:
        df = pd.DataFrame(
            [
                {
                    "boot_id": "boot-a",
                    "seq": 9,
                    "sensor_id": 2,
                    "timestamp": "2026-04-04T10:00:00Z",
                    "bus_voltage": 4.0,
                    "shunt_voltage": 1.0,
                    "supply_voltage": 4.5,
                    "current": 2.0,
                }
            ]
        )

        normalized = normalize_readings(df)

        self.assertAlmostEqual(normalized.iloc[0]["power"], 9.0)

    def test_reading_params_include_cursor_when_present(self) -> None:
        self.assertEqual(
            reading_params(11, 4, ("boot-a", 8)),
            {
                "session_id": 11,
                "sensor_id": 4,
                "since_boot_id": "boot-a",
                "since_seq": 8,
            },
        )


if __name__ == "__main__":
    unittest.main()
