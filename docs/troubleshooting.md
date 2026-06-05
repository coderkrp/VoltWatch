# Troubleshooting

## ESP8266 Hardware Issues

### 1. Readings are consistently `0.0` or `NaN`
- **Cause:** The ESP8266 cannot communicate with the INA219.
- **Fix:** Check I2C wiring (SDA to D2, SCL to D1). Verify that pull-up resistors (typically 10k) are present on the breakout board. 

### 2. Device refuses to connect to the Server
- **Cause:** Typo in the provisioning portal, or server port is blocked by firewall.
- **Fix:** Ensure the `server_host` does NOT include `http://` in the ESP's captive portal, just the raw IP or domain (e.g., `192.168.1.5`).

## Backend Issues

### 1. `422 Unprocessable Entity` on Ingest
- **Cause:** Payload formatting mismatch.
- **Fix:** Check `docs/data-flow.md` to ensure the exact JSON structure is being sent. Run `pytest` locally to validate schema compatibility.

### 2. `403 Forbidden` / Authentication Error
- **Cause:** `REQUIRE_API_KEY` is true, but the `X-API-Key` header is missing or incorrect.
- **Fix:** Double-check `.env` for both backend and dashboard. Re-provision the ESP8266 to ensure it saved the correct key.

## Dashboard Issues

### 1. "Cannot connect to backend"
- **Cause:** Backend server is not running, or `BACKEND_API_URL` is incorrect.
- **Fix:** Verify the backend is accessible manually via `curl http://localhost:8000/health`. Check CORS settings if running on separate servers without a proxy.
