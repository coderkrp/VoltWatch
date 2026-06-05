from datetime import datetime
from pathlib import Path

import pytest
from app.api import health, query, readings
from app.core import settings
from app.db import Base, get_db
from app.models import Reading, Session
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


def _sensor_payload(sensor_index: int, bus_voltage: float, shunt_voltage: float, supply_voltage: float, current: float):
    return {
        "sensor_index": sensor_index,
        "bus_voltage": bus_voltage,
        "shunt_voltage": shunt_voltage,
        "supply_voltage": supply_voltage,
        "current": current,
    }


@pytest.fixture()
def client(tmp_path: Path):
    db_file = tmp_path / "test_data_logger.db"
    engine = create_engine(
        f"sqlite:///{db_file}",
        connect_args={"check_same_thread": False},
    )
    testing_session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(health.router)
    app.include_router(readings.router, prefix="/api/v1/readings")
    app.include_router(query.router, prefix="/api/v1")

    def override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as api_client:
        yield api_client, testing_session_local


def _ingest_payload(device_id: str, seq: int, timestamp: str, sensors, boot_id: str = "boot-a"):
    return {
        "device_id": device_id,
        "boot_id": boot_id,
        "batch": [
            {
                "seq": seq,
                "timestamp": timestamp,
                "sensors": sensors,
            }
        ],
    }


def test_multisensor_same_seq_inserts_rows_without_conflict(client):
    api_client, SessionLocal = client
    payload = _ingest_payload(
        "dev-a",
        1,
        "2026-03-27T10:00:00Z",
        [
            _sensor_payload(0, 12.0, 10.0, 12.01, 1.0),
            _sensor_payload(1, 11.8, 11.0, 11.811, 0.9),
        ],
    )
    response = api_client.post("/api/v1/readings/batch", json=payload)
    assert response.status_code == 200

    with SessionLocal() as db:
        rows = db.query(Reading).filter(Reading.device_id == "dev-a", Reading.seq == 1).all()
        assert len(rows) == 2


def test_replay_same_batch_is_idempotent(client):
    api_client, SessionLocal = client
    payload = _ingest_payload(
        "dev-a",
        2,
        "2026-03-27T10:01:00Z",
        [
            _sensor_payload(0, 12.0, 10.0, 12.01, 1.1),
            _sensor_payload(1, 11.7, 9.0, 11.709, 0.8),
        ],
    )

    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    with SessionLocal() as db:
        rows = db.query(Reading).filter(Reading.device_id == "dev-a", Reading.seq == 2).all()
        assert len(rows) == 2


def test_same_seq_across_boots_inserts_new_rows(client):
    api_client, SessionLocal = client
    first_payload = _ingest_payload(
        "dev-a",
        4,
        "2026-03-27T10:03:00Z",
        [
            _sensor_payload(0, 12.0, 10.0, 12.01, 1.1),
            _sensor_payload(1, 11.7, 9.0, 11.709, 0.8),
        ],
        boot_id="boot-a",
    )
    second_payload = _ingest_payload(
        "dev-a",
        4,
        "2026-03-27T10:10:00Z",
        [
            _sensor_payload(0, 12.2, 10.0, 12.21, 1.2),
            _sensor_payload(1, 11.8, 9.0, 11.809, 0.9),
        ],
        boot_id="boot-b",
    )

    assert api_client.post("/api/v1/readings/batch", json=first_payload).status_code == 200
    assert api_client.post("/api/v1/readings/batch", json=second_payload).status_code == 200

    with SessionLocal() as db:
        rows = db.query(Reading).filter(Reading.device_id == "dev-a", Reading.seq == 4).all()
        assert len(rows) == 4
        assert {row.boot_id for row in rows} == {"boot-a", "boot-b"}


def test_replay_does_not_mutate_session_end_time(client):
    api_client, SessionLocal = client
    payload = _ingest_payload(
        "dev-replay",
        1,
        "2026-03-27T10:00:00Z",
        [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
    )

    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200
    with SessionLocal() as db:
        original = db.query(Session).filter(Session.device_id == "dev-replay").one()
        original_end = original.end_time

    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200
    with SessionLocal() as db:
        replayed = db.query(Session).filter(Session.device_id == "dev-replay").one()
        assert replayed.end_time == original_end


def test_partial_retry_fills_missing_sensor_rows(client):
    api_client, SessionLocal = client
    first_payload = _ingest_payload(
        "dev-a",
        3,
        "2026-03-27T10:02:00Z",
        [_sensor_payload(0, 12.2, 12.0, 12.212, 1.3)],
    )
    retry_payload = _ingest_payload(
        "dev-a",
        3,
        "2026-03-27T10:02:00Z",
        [
            _sensor_payload(0, 12.2, 12.0, 12.212, 1.3),
            _sensor_payload(1, 11.9, 10.0, 11.91, 1.0),
        ],
    )

    assert api_client.post("/api/v1/readings/batch", json=first_payload).status_code == 200
    assert api_client.post("/api/v1/readings/batch", json=retry_payload).status_code == 200

    with SessionLocal() as db:
        rows = db.query(Reading).filter(Reading.device_id == "dev-a", Reading.seq == 3).all()
        assert len(rows) == 2


def test_session_splits_only_after_inactivity_gap(client):
    api_client, _ = client
    payload = {
        "device_id": "dev-sessions",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:30Z",
                "sensors": [_sensor_payload(0, 12.1, 10.0, 12.11, 1.1)],
            },
            {
                "seq": 3,
                "timestamp": "2026-03-27T10:02:10Z",
                "sensors": [_sensor_payload(0, 12.2, 10.0, 12.21, 1.2)],
            },
        ],
    }

    response = api_client.post("/api/v1/readings/batch", json=payload)
    assert response.status_code == 200

    sessions_response = api_client.get("/api/v1/sessions", params={"device_id": "dev-sessions"})
    assert sessions_response.status_code == 200
    sessions = sessions_response.json()
    assert len(sessions) == 2


def test_late_reading_does_not_rewind_latest_session_end(client):
    api_client, SessionLocal = client
    payload = {
        "device_id": "dev-late",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:30Z",
                "sensors": [_sensor_payload(0, 12.1, 10.0, 12.11, 1.1)],
            },
            {
                "seq": 3,
                "timestamp": "2026-03-27T10:00:10Z",
                "sensors": [_sensor_payload(0, 12.2, 10.0, 12.21, 1.2)],
            },
        ],
    }
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    with SessionLocal() as db:
        latest = (
            db.query(Session)
            .filter(Session.device_id == "dev-late")
            .order_by(Session.start_time.desc())
            .first()
        )
        assert latest is not None
        assert latest.end_time == datetime(2026, 3, 27, 10, 0, 30)


def test_timestamp_normalization_for_naive_and_aware_input(client):
    api_client, SessionLocal = client
    payload = {
        "device_id": "dev-time",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00",
                "sensors": [_sensor_payload(0, 5.0, 5.0, 5.005, 0.5)],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:05+05:30",
                "sensors": [_sensor_payload(0, 5.1, 5.0, 5.105, 0.6)],
            },
        ],
    }
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    with SessionLocal() as db:
        seq1 = db.query(Reading).filter(Reading.device_id == "dev-time", Reading.seq == 1).one()
        seq2 = db.query(Reading).filter(Reading.device_id == "dev-time", Reading.seq == 2).one()
        assert seq1.timestamp_esp == datetime(2026, 3, 27, 10, 0, 0)
        assert seq2.timestamp_esp == datetime(2026, 3, 27, 4, 30, 5)


def test_readings_endpoint_returns_ordered_timestamps(client):
    api_client, _ = client
    payload = {
        "device_id": "dev-query",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:10Z",
                "sensors": [_sensor_payload(0, 12.2, 10.0, 12.21, 1.2)],
            },
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
            },
        ],
    }
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    sensors = api_client.get("/api/v1/sensors", params={"device_id": "dev-query"}).json()
    sessions = api_client.get("/api/v1/sessions", params={"device_id": "dev-query"}).json()
    response = api_client.get(
        "/api/v1/readings",
        params={"session_id": sessions[0]["session_id"], "sensor_id": sensors[0]["sensor_id"]},
    )

    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]["timestamp"] <= rows[1]["timestamp"]
    assert {
        "boot_id",
        "seq",
        "timestamp",
        "bus_voltage",
        "shunt_voltage",
        "supply_voltage",
        "current",
    } == set(rows[0].keys())
    assert rows[0]["seq"] == 1
    assert rows[1]["seq"] == 2


def test_readings_updates_returns_only_newer_rows_for_sensor_and_session(client):
    api_client, _ = client
    payload = {
        "device_id": "dev-updates",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [
                    _sensor_payload(0, 12.0, 10.0, 12.01, 1.0),
                    _sensor_payload(1, 9.0, 2.0, 9.002, 0.2),
                ],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:05Z",
                "sensors": [
                    _sensor_payload(0, 12.1, 10.0, 12.11, 1.1),
                    _sensor_payload(1, 9.1, 2.0, 9.102, 0.3),
                ],
            },
            {
                "seq": 3,
                "timestamp": "2026-03-27T10:02:10Z",
                "sensors": [
                    _sensor_payload(0, 12.2, 10.0, 12.21, 1.2),
                    _sensor_payload(1, 9.2, 2.0, 9.202, 0.4),
                ],
            },
        ],
    }
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    sensors = api_client.get("/api/v1/sensors", params={"device_id": "dev-updates"}).json()
    sessions = api_client.get("/api/v1/sessions", params={"device_id": "dev-updates"}).json()
    sensor_zero = next(sensor for sensor in sensors if sensor["sensor_index"] == 0)
    first_session = sessions[-1]

    response = api_client.get(
        "/api/v1/readings/updates",
        params={
            "session_id": first_session["session_id"],
            "sensor_id": sensor_zero["sensor_id"],
            "since_boot_id": "boot-a",
            "since_seq": 1,
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert [row["seq"] for row in rows] == [2]
    assert all(row["boot_id"] == "boot-a" for row in rows)


def test_readings_updates_handles_rebooted_seq_restart_in_same_session(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "SESSION_TIMEOUT_SECONDS", 3600)

    first_payload = {
        "device_id": "dev-reboot-updates",
        "boot_id": "boot-a",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:05Z",
                "sensors": [_sensor_payload(0, 12.1, 10.0, 12.11, 1.1)],
            },
        ],
    }
    second_payload = {
        "device_id": "dev-reboot-updates",
        "boot_id": "boot-b",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:10Z",
                "sensors": [_sensor_payload(0, 12.2, 10.0, 12.21, 1.2)],
            },
            {
                "seq": 2,
                "timestamp": "2026-03-27T10:00:15Z",
                "sensors": [_sensor_payload(0, 12.3, 10.0, 12.31, 1.3)],
            },
        ],
    }

    assert api_client.post("/api/v1/readings/batch", json=first_payload).status_code == 200
    assert api_client.post("/api/v1/readings/batch", json=second_payload).status_code == 200

    sensors = api_client.get("/api/v1/sensors", params={"device_id": "dev-reboot-updates"}).json()
    sessions = api_client.get("/api/v1/sessions", params={"device_id": "dev-reboot-updates"}).json()
    response = api_client.get(
        "/api/v1/readings/updates",
        params={
            "session_id": sessions[0]["session_id"],
            "sensor_id": sensors[0]["sensor_id"],
            "since_boot_id": "boot-a",
            "since_seq": 2,
        },
    )

    assert response.status_code == 200
    rows = response.json()
    assert [(row["boot_id"], row["seq"]) for row in rows] == [("boot-b", 1), ("boot-b", 2)]


def test_readings_updates_returns_empty_when_no_new_rows_exist(client):
    api_client, _ = client
    payload = _ingest_payload(
        "dev-no-updates",
        1,
        "2026-03-27T10:00:00Z",
        [_sensor_payload(0, 12.0, 10.0, 12.01, 1.0)],
    )
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    sensors = api_client.get("/api/v1/sensors", params={"device_id": "dev-no-updates"}).json()
    sessions = api_client.get("/api/v1/sessions", params={"device_id": "dev-no-updates"}).json()
    response = api_client.get(
        "/api/v1/readings/updates",
        params={
            "session_id": sessions[0]["session_id"],
            "sensor_id": sensors[0]["sensor_id"],
            "since_boot_id": "boot-a",
            "since_seq": 1,
        },
    )

    assert response.status_code == 200
    assert response.json() == []


def test_status_reports_no_active_session_after_timeout(client, monkeypatch):
    api_client, SessionLocal = client
    monkeypatch.setattr(settings, "SESSION_TIMEOUT_SECONDS", 1)
    payload = _ingest_payload(
        "dev-status",
        1,
        "2000-01-01T00:00:00Z",
        [_sensor_payload(0, 3.3, 1.0, 3.301, 0.1)],
    )
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    status = api_client.get("/api/v1/status", params={"device_id": "dev-status"})
    assert status.status_code == 200
    body = status.json()
    assert body["active_session_id"] is None
    assert body["latest_session_id"] is not None
    assert body["last_ingestion_time"] is not None


def test_status_reports_latest_session_id_when_not_active(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "SESSION_TIMEOUT_SECONDS", 1)
    payload = _ingest_payload(
        "dev-latest",
        1,
        "2000-01-01T00:00:00Z",
        [_sensor_payload(0, 3.3, 1.0, 3.301, 0.1)],
    )
    assert api_client.post("/api/v1/readings/batch", json=payload).status_code == 200

    sessions = api_client.get("/api/v1/sessions", params={"device_id": "dev-latest"})
    assert sessions.status_code == 200
    latest_session_id = sessions.json()[0]["session_id"]

    status = api_client.get("/api/v1/status", params={"device_id": "dev-latest"})
    assert status.status_code == 200
    body = status.json()
    assert body["active_session_id"] is None
    assert body["latest_session_id"] == latest_session_id


def test_ingest_requires_api_key_when_enabled(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", True)
    monkeypatch.setattr(settings, "API_KEY", "secret123")

    payload = _ingest_payload(
        "dev-auth",
        1,
        "2026-03-27T10:00:00Z",
        [_sensor_payload(0, 1.0, 1.0, 1.001, 0.1)],
    )
    no_key = api_client.post("/api/v1/readings/batch", json=payload)
    wrong_key = api_client.post(
        "/api/v1/readings/batch",
        json=payload,
        headers={"X-API-Key": "bad"},
    )
    good_key = api_client.post(
        "/api/v1/readings/batch",
        json=payload,
        headers={"X-API-Key": "secret123"},
    )

    assert no_key.status_code == 401
    assert wrong_key.status_code == 401
    assert good_key.status_code == 200


def test_ingest_requires_boot_id(client):
    api_client, _ = client
    payload = {
        "device_id": "dev-auth",
        "batch": [
            {
                "seq": 1,
                "timestamp": "2026-03-27T10:00:00Z",
                "sensors": [_sensor_payload(0, 1.0, 1.0, 1.001, 0.1)],
            }
        ],
    }

    response = api_client.post("/api/v1/readings/batch", json=payload)

    assert response.status_code == 422


def test_health_returns_ok_without_api_key_when_auth_disabled(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", False)
    monkeypatch.setattr(settings, "API_KEY", None)

    response = api_client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["server_time"] is not None


def test_health_requires_api_key_when_enabled(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", True)
    monkeypatch.setattr(settings, "API_KEY", "secret123")

    no_key = api_client.get("/health")
    wrong_key = api_client.get("/health", headers={"X-API-Key": "bad"})
    good_key = api_client.get("/health", headers={"X-API-Key": "secret123"})

    assert no_key.status_code == 401
    assert wrong_key.status_code == 401
    assert good_key.status_code == 200


def test_query_endpoints_allow_access_without_api_key_when_auth_disabled(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", False)
    monkeypatch.setattr(settings, "API_KEY", None)

    response = api_client.get("/api/v1/devices")

    assert response.status_code == 200


def test_query_endpoints_require_api_key_when_enabled(client, monkeypatch):
    api_client, _ = client
    monkeypatch.setattr(settings, "REQUIRE_API_KEY", True)
    monkeypatch.setattr(settings, "API_KEY", "secret123")

    no_key = api_client.get("/api/v1/devices")
    wrong_key = api_client.get("/api/v1/devices", headers={"X-API-Key": "bad"})
    good_key = api_client.get("/api/v1/devices", headers={"X-API-Key": "secret123"})

    assert no_key.status_code == 401
    assert wrong_key.status_code == 401
    assert good_key.status_code == 200


def test_explicit_voltage_fields_persist(client):
    api_client, SessionLocal = client
    payload = _ingest_payload(
        "dev-fields",
        1,
        "2026-03-27T10:00:00Z",
        [_sensor_payload(0, 12.5, 15.0, 12.515, 2.5)],
    )

    response = api_client.post("/api/v1/readings/batch", json=payload)
    assert response.status_code == 200

    with SessionLocal() as db:
        row = db.query(Reading).filter(Reading.device_id == "dev-fields", Reading.seq == 1).one()
        assert row.bus_voltage == 12.5
        assert row.shunt_voltage == 15.0
        assert row.supply_voltage == 12.515
        assert row.current == 2.5


def test_fresh_schema_uses_explicit_voltage_columns(client):
    _, SessionLocal = client

    with SessionLocal() as db:
        inspector = inspect(db.bind)
    columns = {column["name"] for column in inspector.get_columns("readings")}

    assert {"bus_voltage", "shunt_voltage", "supply_voltage", "current"}.issubset(columns)
    assert "boot_id" in columns
    assert "voltage" not in columns


def test_fresh_schema_uses_boot_aware_uniqueness(client):
    _, SessionLocal = client

    with SessionLocal() as db:
        inspector = inspect(db.bind)
    unique_constraints = inspector.get_unique_constraints("readings")

    assert any(
        constraint["name"] == "uq_device_boot_seq_sensor"
        and constraint["column_names"] == ["device_id", "boot_id", "seq", "sensor_id"]
        for constraint in unique_constraints
    )
