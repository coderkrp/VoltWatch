from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any

import pandas as pd

SUMMARY_SHEET_NAME = "Summary"
READINGS_SHEET_NAME = "Readings"


def _utc_isoformat(value: Any) -> str:
    if value is None or value == "":
        return ""
    timestamp = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(timestamp):
        return str(value)
    return timestamp.isoformat()


def readings_export_frame(raw_df: pd.DataFrame) -> pd.DataFrame:
    if raw_df.empty:
        return pd.DataFrame(
            columns=[
                "timestamp_utc",
                "bus_voltage",
                "shunt_voltage",
                "supply_voltage",
                "current",
                "power",
            ]
        )

    frame = raw_df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    frame["power"] = frame["supply_voltage"] * frame["current"]
    frame["timestamp_utc"] = frame["timestamp"].map(lambda ts: ts.isoformat())
    return frame[
        [
            "timestamp_utc",
            "bus_voltage",
            "shunt_voltage",
            "supply_voltage",
            "current",
            "power",
        ]
    ]


def build_session_workbook(
    device_id: str,
    session_row: pd.Series | dict[str, Any],
    sensor_row: pd.Series | dict[str, Any],
    raw_df: pd.DataFrame,
    summary_stats: dict[str, Any] | None = None,
) -> bytes:
    session = dict(session_row)
    sensor = dict(sensor_row)
    readings_df = readings_export_frame(raw_df)

    summary_rows = [
        {"field": "device_id", "value": device_id},
        {"field": "session_id", "value": session.get("session_id", "")},
        {"field": "session_start_utc", "value": _utc_isoformat(session.get("start_time"))},
        {"field": "session_end_utc", "value": _utc_isoformat(session.get("end_time"))},
        {"field": "sensor_id", "value": sensor.get("sensor_id", "")},
        {"field": "sensor_index", "value": sensor.get("sensor_index", "")},
        {"field": "sensor_alias", "value": sensor.get("alias") or ""},
        {
            "field": "exported_at_utc",
            "value": datetime.now(timezone.utc).isoformat(),
        },
        {"field": "row_count", "value": len(readings_df)},
    ]

    for label, value in (summary_stats or {}).items():
        summary_rows.append({"field": label, "value": value})

    summary_df = pd.DataFrame(summary_rows)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name=SUMMARY_SHEET_NAME, index=False)
        readings_df.to_excel(writer, sheet_name=READINGS_SHEET_NAME, index=False)

    return output.getvalue()


def export_filename(session_id: int, sensor_id: int) -> str:
    return f"session_{session_id}_sensor_{sensor_id}.xlsx"
