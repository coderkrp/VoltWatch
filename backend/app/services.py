from sqlalchemy.orm import Session
from datetime import datetime, timezone
from . import models
from .core import settings
from .core.time import utc_now_naive

def get_or_create_device(db: Session, device_id: str):
    device = db.query(models.Device).filter_by(device_id=device_id).first()
    if not device:
        device = models.Device(device_id=device_id)
        db.add(device)
        db.flush()
    return device


def get_or_create_sensor(db: Session, device_id: str, sensor_index: int):
    sensor = db.query(models.Sensor).filter_by(
        device_id=device_id, sensor_index=sensor_index
    ).first()

    if not sensor:
        sensor = models.Sensor(
            device_id=device_id,
            sensor_index=sensor_index,
        )
        db.add(sensor)
        db.flush()

    return sensor


def get_active_session(db: Session, device_id: str):
    return (
        db.query(models.Session)
        .filter(models.Session.device_id == device_id)
        .order_by(models.Session.start_time.desc())
        .first()
    )


def get_device_sessions(db: Session, device_id: str):
    return (
        db.query(models.Session)
        .filter(models.Session.device_id == device_id)
        .order_by(models.Session.start_time.asc())
        .all()
    )


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _get_last_session_reading_time(db: Session, session_id: int):
    return (
        db.query(models.Reading.timestamp_esp)
        .filter(models.Reading.session_id == session_id)
        .order_by(models.Reading.timestamp_esp.desc())
        .limit(1)
        .scalar()
    )


def normalize_to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        # Contract: naive timestamps from device are treated as UTC.
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _session_bounds(session: models.Session) -> tuple[datetime, datetime]:
    start = session.start_time
    end = session.end_time or session.start_time
    return start, end


def get_session_for_timestamp(db: Session, device_id: str, timestamp: datetime):
    event_time = _utc_naive(timestamp)
    sessions = get_device_sessions(db, device_id)
    if not sessions:
        return None

    containing = None
    for session in sessions:
        start, end = _session_bounds(session)
        if start <= event_time <= end:
            containing = session
            break
    if containing:
        return containing

    latest_before = None
    for session in sessions:
        if session.start_time <= event_time:
            latest_before = session
        else:
            break

    if latest_before:
        return latest_before
    return sessions[0]


def should_split_latest_session(latest_session: models.Session | None, event_time: datetime) -> bool:
    if not latest_session:
        return False

    _, latest_end = _session_bounds(latest_session)
    if event_time <= latest_end:
        return False

    gap = (event_time - latest_end).total_seconds()
    return gap >= settings.SESSION_TIMEOUT_SECONDS


def ensure_session_for_event(db: Session, device_id: str, timestamp: datetime):
    event_time = _utc_naive(timestamp)
    latest_session = get_active_session(db, device_id)

    if not latest_session:
        created = models.Session(
            device_id=device_id,
            start_time=event_time,
            end_time=event_time,
        )
        db.add(created)
        db.flush()
        return created, True

    if should_split_latest_session(latest_session, event_time):
        new_session = models.Session(
            device_id=device_id,
            start_time=event_time,
            end_time=event_time,
        )
        db.add(new_session)
        db.flush()
        return new_session, True

    target_session = get_session_for_timestamp(db, device_id, event_time)
    return target_session, False


def update_session_bounds_monotonic(session: models.Session, event_time: datetime) -> bool:
    updated = False
    if session.start_time is None or event_time < session.start_time:
        session.start_time = event_time
        updated = True

    current_end = session.end_time or session.start_time
    if current_end is None or event_time > current_end:
        session.end_time = event_time
        updated = True

    return updated


def get_devices(db: Session):
    return db.query(models.Device).order_by(models.Device.created_at.desc()).all()


def get_sensors(db: Session, device_id: str):
    return (
        db.query(models.Sensor)
        .filter(models.Sensor.device_id == device_id)
        .order_by(models.Sensor.sensor_index)
        .all()
    )


def get_sessions(db: Session, device_id: str):
    return (
        db.query(models.Session)
        .filter(models.Session.device_id == device_id)
        .order_by(models.Session.start_time.desc())
        .all()
    )


def get_readings(
    db: Session,
    session_id: int,
    sensor_id: int,
    interval: int | None = None,
):
    query = db.query(models.Reading).filter(
        models.Reading.session_id == session_id,
        models.Reading.sensor_id == sensor_id,
    )

    if interval:
        # Downsampling using modulo on seq
        query = query.filter(models.Reading.seq % interval == 0)

    return query.order_by(models.Reading.timestamp_esp, models.Reading.boot_id, models.Reading.seq).all()


def get_readings_updates(
    db: Session,
    session_id: int,
    sensor_id: int,
    since_boot_id: str,
    since_seq: int,
):
    query = db.query(models.Reading).filter(
        models.Reading.session_id == session_id,
        models.Reading.sensor_id == sensor_id,
    )
    query = query.filter(
        (models.Reading.boot_id > since_boot_id)
        | (
            (models.Reading.boot_id == since_boot_id)
            & (models.Reading.seq > since_seq)
        )
    )
    return query.order_by(models.Reading.timestamp_esp, models.Reading.boot_id, models.Reading.seq).all()


def get_health(db: Session, device_id: str | None = None):
    session_query = db.query(models.Session)
    reading_query = db.query(models.Reading)

    if device_id:
        session_query = session_query.filter(models.Session.device_id == device_id)
        reading_query = reading_query.filter(models.Reading.device_id == device_id)

    latest_session = session_query.order_by(models.Session.start_time.desc()).first()
    last_ingestion = reading_query.order_by(models.Reading.timestamp_server.desc()).first()

    active_session_id = None
    latest_session_id = latest_session.session_id if latest_session else None
    if latest_session and latest_session.end_time:
        now_utc_naive = utc_now_naive()
        idle_seconds = (now_utc_naive - latest_session.end_time).total_seconds()
        if idle_seconds <= settings.SESSION_TIMEOUT_SECONDS:
            active_session_id = latest_session.session_id

    return {
        "device_id": device_id,
        "active_session_id": active_session_id,
        "latest_session_id": latest_session_id,
        "last_ingestion_time": last_ingestion.timestamp_server if last_ingestion else None,
    }
