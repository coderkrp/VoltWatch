# Configuration Guide

VoltWatch employs a strict 12-factor app methodology where configuration is separated from code using environment variables.

## Backend Configuration
The backend relies on `.env` (or OS environment variables). `app/core/settings.py` validates these via Pydantic `BaseSettings`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data_logger.db` | SQLAlchemy connection string. Use `postgresql+psycopg2://` for Postgres. |
| `REQUIRE_API_KEY` | `false` | Set to `true` to enable `X-API-Key` authentication on ingest routes. |
| `API_KEY` | `null` | The secret key the ESP8266 and dashboard must send. |
| `SESSION_TIMEOUT_SECONDS`| `60` | Time threshold to logically group readings into a single "Session" if a device goes offline. |

## Dashboard Configuration
| Variable | Default | Description |
|----------|---------|-------------|
| `BACKEND_API_URL` | `http://localhost:8000/api/v1` | URL of the backend API. |
| `BACKEND_API_KEY` | `null` | Must match backend `API_KEY` if auth is enabled. |

## Firmware Configuration (Dynamic)
The firmware does not hardcode configuration. Instead, it utilizes the ESP8266's internal LittleFS.
Upon connecting to the captive portal, the following variables are saved to `config.txt`:
- `ssid`: Wi-Fi Network
- `password`: Wi-Fi Password
- `server_host`: The IP/Domain of your backend API.
- `server_port`: Typically 8000 (or 80/443 for production).
- `api_key`: Used for `X-API-Key` header.
- `device_id`: A logical name (e.g., `Solar_Panel_1`).

## Hardware Calibration Settings
In the portal, you can also apply calibration:
- **INA HW Average:** Number of samples the INA219 averages internally before returning a value.
- **Software Average Window:** Number of readings the ESP averages in RAM before pushing to the payload buffer.
- **Gain/Offset:** Applied in firmware to correct systematic drift against a trusted multimeter.
