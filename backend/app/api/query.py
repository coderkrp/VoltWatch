from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import timezone

from ..db import get_db
from .. import schemas, services
from ..core.auth import verify_api_key

router = APIRouter()


def _serialize_reading(reading):
    return {
        "boot_id": reading.boot_id,
        "seq": reading.seq,
        "timestamp": (
            reading.timestamp_esp.replace(tzinfo=timezone.utc)
            if reading.timestamp_esp and reading.timestamp_esp.tzinfo is None
            else reading.timestamp_esp
        ),
        "bus_voltage": reading.bus_voltage,
        "shunt_voltage": reading.shunt_voltage,
        "supply_voltage": reading.supply_voltage,
        "current": reading.current,
    }


@router.get("/devices", response_model=List[schemas.DeviceOut])
def list_devices(
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return services.get_devices(db)


@router.get("/sensors", response_model=List[schemas.SensorOut])
def list_sensors(
    device_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return services.get_sensors(db, device_id)


@router.get("/sessions", response_model=List[schemas.SessionOut])
def list_sessions(
    device_id: str,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    return services.get_sessions(db, device_id)


@router.get("/readings", response_model=List[schemas.ReadingOut])
def list_readings(
    session_id: int,
    sensor_id: int,
    interval: Optional[int] = Query(None, ge=1),
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    readings = services.get_readings(db, session_id, sensor_id, interval)
    return [_serialize_reading(r) for r in readings]


@router.get("/readings/updates", response_model=List[schemas.ReadingOut])
def list_reading_updates(
    session_id: int,
    sensor_id: int,
    since_boot_id: str,
    since_seq: int = Query(..., ge=0),
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    readings = services.get_readings_updates(
        db=db,
        session_id=session_id,
        sensor_id=sensor_id,
        since_boot_id=since_boot_id,
        since_seq=since_seq,
    )
    return [_serialize_reading(r) for r in readings]


@router.get("/status", response_model=schemas.HealthOut)
def get_status(
    device_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    health = services.get_health(db, device_id=device_id)
    timestamp = health["last_ingestion_time"]
    if timestamp and timestamp.tzinfo is None:
        health["last_ingestion_time"] = timestamp.replace(tzinfo=timezone.utc)
    return health
