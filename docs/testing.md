# Testing Strategy

VoltWatch maintains a rigorous automated testing standard to ensure the edge, backend, and dashboard layers function correctly under pressure.

## 1. Backend Testing (`pytest`)
The backend is tested using Pytest and HTTPX (for async route testing).
Tests reside in `backend/tests/`.

### Run tests:
```bash
cd backend
pytest -v --cov=app
```

### Key coverage areas:
- **Pydantic Validation:** Ensures badly formatted JSON from a malicious or corrupted edge device is rejected cleanly.
- **API Key Middleware:** Verifies that protected routes bounce unauthorized requests.
- **Database Integrity:** Tests that batch inserts succeed and duplicates are handled correctly.

## 2. Dashboard UI Testing
The dashboard logic (API client wrapping) is tested using Pytest.

### Run tests:
```bash
cd dashboard
pytest -v
```

## 3. Hardware / Firmware Mocking
Currently, testing the ESP8266 logic relies on C++ unit testing frameworks like `AUnit` or by utilizing Wokwi (an online ESP8266 simulator) to validate logic without hardware.
For CI/CD, the `.github/workflows/ci.yml` strictly enforces that the `.ino` sketch compiles cleanly against the standard Arduino Core, preventing syntax regressions.
