from __future__ import annotations

from typing import Any

import pandas as pd

CURSOR_COLUMNS = ["boot_id", "seq"]
READING_ID_COLUMNS = ["boot_id", "seq", "sensor_id"]


def normalize_readings(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(
            columns=[
                "boot_id",
                "seq",
                "timestamp",
                "bus_voltage",
                "shunt_voltage",
                "supply_voltage",
                "current",
                "power",
            ]
        )

    frame = df.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    if frame.empty:
        return normalize_readings(pd.DataFrame())

    if "sensor_id" not in frame.columns:
        frame["sensor_id"] = pd.NA
    frame["power"] = frame["supply_voltage"] * frame["current"]
    frame = frame.sort_values(["timestamp", "boot_id", "seq"]).reset_index(drop=True)
    return frame


def append_incremental_readings(existing_df: pd.DataFrame, updates_df: pd.DataFrame) -> pd.DataFrame:
    combined = pd.concat([existing_df, updates_df], ignore_index=True)
    combined = normalize_readings(combined)

    dedupe_columns = [column for column in READING_ID_COLUMNS if column in combined.columns]
    if dedupe_columns:
        combined = combined.drop_duplicates(subset=dedupe_columns, keep="last")
        combined = combined.sort_values(["timestamp", "boot_id", "seq"]).reset_index(drop=True)

    return combined


def latest_cursor(df: pd.DataFrame) -> tuple[str, int] | None:
    frame = normalize_readings(df)
    if frame.empty:
        return None

    latest = frame.iloc[-1]
    return str(latest["boot_id"]), int(latest["seq"])


def latest_reading(df: pd.DataFrame) -> pd.Series | None:
    frame = normalize_readings(df)
    if frame.empty:
        return None
    return frame.iloc[-1].copy()


def chart_data(df: pd.DataFrame, sample_step: int | None) -> pd.DataFrame:
    frame = normalize_readings(df)
    if frame.empty:
        return frame

    if sample_step:
        frame = frame[frame["seq"] % sample_step == 0]
        if frame.empty:
            return frame

    return frame.rename(columns={"timestamp": "time_bucket"}).reset_index(drop=True)


def compute_session_stats(df: pd.DataFrame) -> dict[str, float]:
    frame = normalize_readings(df)
    if frame.empty:
        return {
            "Supply Voltage Avg": 0.0,
            "Supply Voltage Max": 0.0,
            "Current Avg": 0.0,
            "Current Max": 0.0,
            "Charge Total": 0.0,
            "Power Avg": 0.0,
            "Power Max": 0.0,
            "Energy Total": 0.0,
        }

    charge_total, energy_total = integrate_totals(frame)
    return {
        "Supply Voltage Avg": float(frame["supply_voltage"].mean()),
        "Supply Voltage Max": float(frame["supply_voltage"].max()),
        "Current Avg": float(frame["current"].mean()),
        "Current Max": float(frame["current"].max()),
        "Charge Total": charge_total,
        "Power Avg": float(frame["power"].mean()),
        "Power Max": float(frame["power"].max()),
        "Energy Total": energy_total,
    }


def integrate_totals(df: pd.DataFrame) -> tuple[float, float]:
    frame = normalize_readings(df)
    if len(frame) < 2:
        return 0.0, 0.0

    seconds = frame["timestamp"].astype("int64").diff().div(1_000_000_000)
    avg_current = (frame["current"] + frame["current"].shift(1)) / 2
    avg_power = (frame["power"] + frame["power"].shift(1)) / 2

    charge_milliamp_hours = float((avg_current * seconds).iloc[1:].sum() / 3600)
    energy_milliwatt_hours = float((avg_power * seconds).iloc[1:].sum() / 3600)
    return charge_milliamp_hours, energy_milliwatt_hours


def reading_params(session_id: int, sensor_id: int, cursor: tuple[str, int] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {
        "session_id": session_id,
        "sensor_id": sensor_id,
    }
    if cursor is not None:
        params["since_boot_id"] = cursor[0]
        params["since_seq"] = cursor[1]
    return params
