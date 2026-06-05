# Extensibility Architecture

VoltWatch is highly modular. If you want to add a new sensor (e.g., BME280 for Temperature and Humidity), follow this extensibility guide.

## 1. Modify the Firmware
Add the sensor read logic in `esp-ina219-datalogger.ino`. Append the new data to the `ArduinoJson` document:
```cpp
// Example addition
doc["readings"][i]["temperature"] = bme.readTemperature();
doc["readings"][i]["humidity"] = bme.readHumidity();
```

## 2. Update Backend Schemas
In `backend/app/schemas/reading.py`, update the Pydantic schema to accept the new fields:
```python
class ReadingCreate(BaseModel):
    timestamp: datetime
    bus_voltage: float
    current: float
    # New fields
    temperature: Optional[float] = None
    humidity: Optional[float] = None
```

## 3. Update Database Models
In `backend/app/models/reading.py`, add the SQLAlchemy columns:
```python
class Reading(Base):
    __tablename__ = "readings"
    # ... existing columns ...
    temperature = Column(Float, nullable=True)
    humidity = Column(Float, nullable=True)
```
*(If using SQLite, delete `data_logger.db` to let the engine recreate the tables, or use Alembic for migrations).*

## 4. Update the Dashboard
In `dashboard/app.py`, update the Streamlit UI to plot the new metrics by grabbing the keys from the JSON response.
