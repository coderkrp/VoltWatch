from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class SensorReading(BaseModel):
    sensor_index: int
    bus_voltage: float
    shunt_voltage: float
    supply_voltage: float
    current: float


class BatchItem(BaseModel):
    seq: int
    timestamp: datetime
    sensors: List[SensorReading]


class BatchRequest(BaseModel):
    device_id: str
    boot_id: str = Field(min_length=1, max_length=128)
    batch: List[BatchItem]


class BatchResponse(BaseModel):
    status: str
    last_seq: Optional[int]
    server_time: datetime

class DeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    device_id: str
    alias: Optional[str]
    created_at: datetime


class SensorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sensor_id: int
    device_id: str
    sensor_index: int
    alias: Optional[str]


class SessionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    session_id: int
    device_id: str
    start_time: datetime
    end_time: Optional[datetime]


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    boot_id: str
    seq: int
    timestamp: datetime
    bus_voltage: float
    shunt_voltage: float
    supply_voltage: float
    current: float


class HealthOut(BaseModel):
    device_id: Optional[str]
    active_session_id: Optional[int]
    latest_session_id: Optional[int]
    last_ingestion_time: Optional[datetime]
