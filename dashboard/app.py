import time
from datetime import datetime

import pandas as pd
import plotly.graph_objs as go
import streamlit as st
from api_client import fetch_json, get_api_base_url
from data_fetch import interval_to_sample_step
from dashboard_logic import (
    append_incremental_readings,
    chart_data,
    compute_session_stats,
    latest_cursor,
    latest_reading,
    normalize_readings,
    reading_params,
)
from export_excel import build_session_workbook, export_filename
from session_selection import resolve_selected_session
from summary_format import build_summary_blocks

API_BASE_URL = get_api_base_url()
CACHED_READINGS_KEY = "cached_raw_readings"
CACHED_CURSOR_KEY = "cached_readings_cursor"
BOOTSTRAP_COMPLETE_KEY = "cached_readings_bootstrap_complete"
SELECTION_SIGNATURE_KEY = "cached_readings_selection_signature"


@st.cache_data(ttl=5)
def fetch_devices():
    return pd.DataFrame(fetch_json("/devices"))


@st.cache_data(ttl=5)
def fetch_sessions(device_id: str):
    return pd.DataFrame(fetch_json("/sessions", params={"device_id": device_id}))


@st.cache_data(ttl=5)
def fetch_sensors(device_id: str):
    return pd.DataFrame(fetch_json("/sensors", params={"device_id": device_id}))


@st.cache_data(ttl=3)
def fetch_status(device_id: str):
    return fetch_json("/status", params={"device_id": device_id})


@st.cache_data(ttl=3)
def fetch_readings(session_id: int, sensor_id: int, interval: int | None = None):
    params = {"session_id": session_id, "sensor_id": sensor_id}
    if interval is not None:
        params["interval"] = interval
    payload = fetch_json(
        "/readings",
        params=params,
    )
    return pd.DataFrame(payload)


def safe_fetch_sessions(device_id: str) -> pd.DataFrame:
    try:
        return fetch_sessions(device_id)
    except Exception as exc:
        st.warning(f"Could not load sessions right now: {exc}")
        return pd.DataFrame()


def safe_fetch_sensors(device_id: str) -> pd.DataFrame:
    try:
        return fetch_sensors(device_id)
    except Exception as exc:
        st.warning(f"Could not load sensors right now: {exc}")
        return pd.DataFrame()


def safe_fetch_status(device_id: str) -> dict:
    try:
        return fetch_status(device_id)
    except Exception as exc:
        st.warning(f"Could not load device status right now: {exc}")
        return {}


def safe_fetch_readings(
    session_id: int,
    sensor_id: int,
    interval: int | None = None,
) -> pd.DataFrame:
    try:
        return fetch_readings(session_id, sensor_id, interval)
    except Exception as exc:
        st.warning(f"Could not load readings right now: {exc}")
        return pd.DataFrame()


def fetch_reading_updates(session_id: int, sensor_id: int, cursor: tuple[str, int]) -> pd.DataFrame:
    payload = fetch_json(
        "/readings/updates",
        params=reading_params(session_id, sensor_id, cursor),
    )
    return pd.DataFrame(payload)


def safe_fetch_reading_updates(
    session_id: int,
    sensor_id: int,
    cursor: tuple[str, int],
) -> pd.DataFrame:
    try:
        return fetch_reading_updates(session_id, sensor_id, cursor)
    except Exception as exc:
        st.warning(f"Could not load new readings right now: {exc}")
        return pd.DataFrame()


def _reset_cached_readings(selection_signature: tuple[str, int, int]) -> None:
    if st.session_state.get(SELECTION_SIGNATURE_KEY) == selection_signature:
        return

    st.session_state[SELECTION_SIGNATURE_KEY] = selection_signature
    st.session_state[CACHED_READINGS_KEY] = pd.DataFrame()
    st.session_state[CACHED_CURSOR_KEY] = None
    st.session_state[BOOTSTRAP_COMPLETE_KEY] = False


def _prepare_readings(df: pd.DataFrame, sensor_id: int) -> pd.DataFrame:
    if df.empty:
        return normalize_readings(df)
    frame = df.copy()
    frame["sensor_id"] = sensor_id
    return normalize_readings(frame)


def _ensure_bootstrap_readings(session_id: int, sensor_id: int) -> pd.DataFrame:
    if st.session_state.get(BOOTSTRAP_COMPLETE_KEY):
        return st.session_state.get(CACHED_READINGS_KEY, pd.DataFrame())

    bootstrap_df = _prepare_readings(safe_fetch_readings(session_id, sensor_id), sensor_id)
    st.session_state[CACHED_READINGS_KEY] = bootstrap_df
    st.session_state[CACHED_CURSOR_KEY] = latest_cursor(bootstrap_df)
    st.session_state[BOOTSTRAP_COMPLETE_KEY] = True
    return bootstrap_df


def _get_cached_readings(session_id: int, sensor_id: int, live_mode: bool) -> pd.DataFrame:
    cached_df = _ensure_bootstrap_readings(session_id, sensor_id)
    if not live_mode:
        return cached_df

    cursor = st.session_state.get(CACHED_CURSOR_KEY)
    if cursor is None:
        refreshed_df = _prepare_readings(safe_fetch_readings(session_id, sensor_id), sensor_id)
        st.session_state[CACHED_READINGS_KEY] = refreshed_df
        st.session_state[CACHED_CURSOR_KEY] = latest_cursor(refreshed_df)
        return refreshed_df

    updates_df = _prepare_readings(
        safe_fetch_reading_updates(session_id, sensor_id, cursor),
        sensor_id,
    )
    if updates_df.empty:
        return cached_df

    cached_df = append_incremental_readings(cached_df, updates_df)
    st.session_state[CACHED_READINGS_KEY] = cached_df
    st.session_state[CACHED_CURSOR_KEY] = latest_cursor(cached_df)
    return cached_df


def plot_chart(df: pd.DataFrame, y_col: str, title: str):
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df["time_bucket"],
            y=df[y_col],
            mode="lines",
            name=title,
        )
    )
    fig.update_layout(
        title=title,
        xaxis_title="Time (UTC)",
        yaxis_title=title,
        height=300,
    )
    return fig
def render_dashboard(session_df: pd.DataFrame, selected_session: int, raw_df: pd.DataFrame, agg_df: pd.DataFrame):
    if raw_df.empty or agg_df.empty:
        st.warning("No data available for the current selection.")
        return

    session_row = session_df[session_df["session_id"] == selected_session].iloc[0]
    st.write(f"**Start (UTC):** {session_row['start_time']}")
    st.write(f"**End (UTC):** {session_row['end_time']}")

    live = latest_reading(raw_df)
    if live is not None:
        st.subheader("Live")
        live_cols = st.columns(3)
        live_cols[0].metric("Latest Timestamp (UTC)", live["timestamp"].isoformat())
        live_cols[1].metric("Live Supply Voltage (V)", f"{live['supply_voltage']:.3f}")
        live_cols[2].metric("Live Current (mA)", f"{live['current']:.3f}")
        st.metric("Live Power (mW)", f"{live['power']:.3f}")

    st.subheader("Summary")
    stats = compute_session_stats(raw_df)
    col1, col2, col3 = st.columns(3)
    supply_summary, current_summary, power_summary = build_summary_blocks(stats)
    col1.markdown(supply_summary)
    col2.markdown(current_summary)
    col3.markdown(power_summary)

    st.plotly_chart(plot_chart(agg_df, "supply_voltage", "Supply Voltage vs Time"), use_container_width=True)
    st.plotly_chart(plot_chart(agg_df, "current", "Current vs Time"), use_container_width=True)
    st.plotly_chart(plot_chart(agg_df, "power", "Power vs Time"), use_container_width=True)


st.title("Data Logger Dashboard")
st.sidebar.title("Controls")
st.sidebar.caption(f"Backend: {API_BASE_URL}")

try:
    devices = fetch_devices()
except Exception as exc:
    st.error(f"Unable to reach backend API: {exc}")
    st.stop()

if devices.empty:
    st.info("No devices are registered yet. Start your ESP8266 sender first.")
    st.stop()

device_map = {
    f"{(row.get('alias') or 'Device')} ({row['device_id']})": row["device_id"]
    for _, row in devices.iterrows()
}
selected_device_label = st.sidebar.selectbox("Device", list(device_map.keys()))
selected_device = device_map[selected_device_label]

status = safe_fetch_status(selected_device)
sessions = safe_fetch_sessions(selected_device)
if sessions.empty:
    st.info("No sessions found for this device yet.")
    st.stop()

active_session_id = status.get("active_session_id")
latest_session_id = status.get("latest_session_id")
session_ids = sessions["session_id"].tolist()
live_mode = st.sidebar.checkbox("Live Mode", value=False)
selected_session_id, session_message = resolve_selected_session(
    session_ids=session_ids,
    prior_selected_session_id=st.session_state.get("selected_session_id"),
    active_session_id=active_session_id,
    latest_session_id=latest_session_id,
    live_mode=live_mode,
)
st.session_state["selected_session_id"] = selected_session_id
if session_message:
    st.info(session_message)

default_index = session_ids.index(st.session_state["selected_session_id"])
selected_session = st.sidebar.selectbox("Session", session_ids, index=default_index)
st.session_state["selected_session_id"] = selected_session

sensors = safe_fetch_sensors(selected_device)
if sensors.empty:
    st.info("No sensors are mapped for this device yet.")
    st.stop()

sensor_map = {
    f"{(row.get('alias') or 'Sensor')} (idx {row['sensor_index']})": row["sensor_id"]
    for _, row in sensors.iterrows()
}
selected_sensor_label = st.sidebar.selectbox("Sensor", list(sensor_map.keys()))
selected_sensor = sensor_map[selected_sensor_label]

interval = st.sidebar.selectbox(
    "Aggregation Interval",
    ["1 sec", "5 sec", "30 sec", "1 min", "5 min", "15 min"],
)
refresh_rate = st.sidebar.slider("Refresh (sec)", 2, 30, 3)

status_col1, status_col2, status_col3, status_col4 = st.columns(4)
status_col1.metric("Active Session", active_session_id or "N/A")
status_col2.metric("Latest Session", latest_session_id or "N/A")
status_col3.metric("Selected Session", selected_session)
status_col4.metric("Last Ingestion (UTC)", status.get("last_ingestion_time") or "N/A")

_reset_cached_readings((selected_device, selected_session, selected_sensor))
raw_df = _get_cached_readings(selected_session, selected_sensor, live_mode)
chart_interval = interval_to_sample_step(interval)
agg_df = chart_data(raw_df, chart_interval)
latest_selected_reading = latest_reading(raw_df)
if latest_selected_reading is not None:
    st.caption(f"Latest reading in selected session: {latest_selected_reading['timestamp'].isoformat()}")

selected_session_row = sessions[sessions["session_id"] == selected_session].iloc[0]
selected_sensor_row = sensors[sensors["sensor_id"] == selected_sensor].iloc[0]
if raw_df.empty:
    st.caption("Export unavailable until readings exist for the selected session and sensor.")
else:
    export_stats = compute_session_stats(raw_df)
    workbook_bytes = build_session_workbook(
        device_id=selected_device,
        session_row=selected_session_row,
        sensor_row=selected_sensor_row,
        raw_df=raw_df,
        summary_stats=export_stats,
    )
    st.download_button(
        "Export Session to Excel",
        data=workbook_bytes,
        file_name=export_filename(selected_session, selected_sensor),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
render_dashboard(sessions, selected_session, raw_df, agg_df)

if live_mode:
    st.caption(f"Live mode enabled. Next refresh at {datetime.utcnow().isoformat()}Z + {refresh_rate}s")
    time.sleep(refresh_rate)
    st.rerun()
