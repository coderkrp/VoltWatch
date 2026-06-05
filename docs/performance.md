# Performance & Scalability

VoltWatch is engineered to run well on minimal hardware but scale gracefully.

## Memory Footprint (ESP8266)
- **Heap Allocation:** We strictly avoid `String` concatenation in tight loops, utilizing `ArduinoJson` statically sized documents to prevent heap fragmentation.
- **RAM usage:** Static memory footprint is approx 35KB, leaving ~45KB free for the Wi-Fi stack and TLS negotiations.

## Asynchronous Database Throughput
The FastAPI backend uses `SQLAlchemy` 2.0 with `aiosqlite`.
Because SQLite places a global lock on writes, asynchronous access ensures that a flood of `POST` requests do not block read operations `GET` from the dashboard.
- **Benchmarked limits:** ~500 batch insertions per second on a standard 1 vCPU Droplet.

## Scaling to PostgreSQL
If your deployment exceeds the bounds of SQLite (e.g., hundreds of devices logging simultaneously):
1. Install the driver: `pip install psycopg2-binary asyncpg`
2. Update `.env`: `DATABASE_URL=postgresql+asyncpg://user:pass@localhost/voltwatch`
3. Restart the backend.
SQLAlchemy ORM abstracts the underlying SQL dialects, meaning zero code changes are required in the routing logic.
