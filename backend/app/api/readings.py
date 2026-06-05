import logging

from fastapi import APIRouter, Depends
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from ..db import get_db
from .. import schemas, models, services
from ..core import settings
from ..core.auth import verify_api_key
from ..core.time import utc_now

router = APIRouter()
logger = logging.getLogger(__name__)


@router.post("/batch", response_model=schemas.BatchResponse)
def ingest_batch(
    payload: schemas.BatchRequest,
    db: Session = Depends(get_db),
    _: None = Depends(verify_api_key),
):
    services.get_or_create_device(db, payload.device_id)
    last_seq = None
    inserted_rows = 0
    duplicate_rows = 0
    late_rows = 0
    session_transitions = 0

    try:
        for item in payload.batch:
            normalized_timestamp = services.normalize_to_utc_naive(item.timestamp)
            latest_session = services.get_active_session(db, payload.device_id)
            latest_end = None
            if latest_session:
                latest_end = latest_session.end_time or latest_session.start_time

            rows = []
            new_rows = []
            for sensor_data in item.sensors:
                if abs(sensor_data.bus_voltage) > settings.MAX_ABS_VOLTAGE or abs(sensor_data.current) > settings.MAX_ABS_CURRENT:
                    logger.warning(
                        "Out-of-range reading observed device=%s seq=%s sensor_index=%s bus_voltage=%s current=%s",
                        payload.device_id,
                        item.seq,
                        sensor_data.sensor_index,
                        sensor_data.bus_voltage,
                        sensor_data.current,
                    )

                sensor = services.get_or_create_sensor(
                    db, payload.device_id, sensor_data.sensor_index
                )

                base_row = {
                    "device_id": payload.device_id,
                    "boot_id": payload.boot_id,
                    "sensor_id": sensor.sensor_id,
                    "seq": item.seq,
                    "timestamp_esp": normalized_timestamp,
                    "timestamp_server": services.utc_now_naive(),
                    "bus_voltage": sensor_data.bus_voltage,
                    "shunt_voltage": sensor_data.shunt_voltage,
                    "supply_voltage": sensor_data.supply_voltage,
                    "current": sensor_data.current,
                }
                rows.append(base_row)

                exists = (
                    db.query(models.Reading.id)
                    .filter_by(
                        device_id=payload.device_id,
                        boot_id=payload.boot_id,
                        seq=item.seq,
                        sensor_id=sensor.sensor_id,
                    )
                    .first()
                )
                if not exists:
                    new_rows.append(base_row)

            if not rows:
                continue

            if not new_rows:
                duplicate_rows += len(rows)
                last_seq = item.seq
                continue

            session, transitioned = services.ensure_session_for_event(
                db, payload.device_id, normalized_timestamp
            )
            if transitioned:
                session_transitions += 1

            if latest_end and normalized_timestamp < latest_end:
                late_rows += len(new_rows)

            rows_with_session = []
            for row in new_rows:
                row_copy = dict(row)
                row_copy["session_id"] = session.session_id
                rows_with_session.append(row_copy)

            stmt = sqlite_insert(models.Reading).values(rows_with_session)
            stmt = stmt.on_conflict_do_nothing(
                index_elements=["device_id", "boot_id", "seq", "sensor_id"]
            )
            result = db.execute(stmt)
            row_count = result.rowcount if result.rowcount is not None else 0
            inserted_rows += max(row_count, 0)
            duplicate_rows += max(len(rows) - max(row_count, 0), 0)
            last_seq = item.seq

            if row_count > 0:
                services.update_session_bounds_monotonic(session, normalized_timestamp)

        db.commit()
    except Exception:
        db.rollback()
        raise

    logger.info(
        "Batch ingest complete device=%s boot_id=%s batch_items=%s inserted_rows=%s duplicate_rows=%s late_rows=%s session_transitions=%s last_seq=%s",
        payload.device_id,
        payload.boot_id,
        len(payload.batch),
        inserted_rows,
        duplicate_rows,
        late_rows,
        session_transitions,
        last_seq,
    )

    return {
        "status": "ok",
        "last_seq": last_seq,
        "server_time": utc_now(),
    }
