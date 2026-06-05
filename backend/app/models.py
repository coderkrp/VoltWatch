
from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from .core.time import utc_now_naive
from .db import Base


class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)
    alias = Column(String, nullable=True)
    created_at = Column(DateTime, default=utc_now_naive)

    sensors = relationship("Sensor", back_populates="device")


class Sensor(Base):
    __tablename__ = "sensors"

    sensor_id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"))
    sensor_index = Column(Integer)
    alias = Column(String, nullable=True)
    calibration_params = Column(JSON, nullable=True)

    device = relationship("Device", back_populates="sensors")

    __table_args__ = (
        UniqueConstraint("device_id", "sensor_index", name="uq_sensor_device_index"),
    )


class Session(Base):
    __tablename__ = "sessions"

    session_id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, ForeignKey("devices.device_id"))
    start_time = Column(DateTime)
    end_time = Column(DateTime, nullable=True)


class Reading(Base):
    __tablename__ = "readings"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String, index=True)
    boot_id = Column(String, nullable=False, index=True)
    sensor_id = Column(Integer, ForeignKey("sensors.sensor_id"))
    session_id = Column(Integer, ForeignKey("sessions.session_id"))
    seq = Column(Integer)
    timestamp_esp = Column(DateTime)
    timestamp_server = Column(DateTime)
    bus_voltage = Column(Float)
    shunt_voltage = Column(Float)
    supply_voltage = Column(Float)
    current = Column(Float)

    __table_args__ = (
        UniqueConstraint("device_id", "boot_id", "seq", "sensor_id", name="uq_device_boot_seq_sensor"),
        Index("idx_session_sensor_time", "session_id", "sensor_id", "timestamp_esp"),
    )
