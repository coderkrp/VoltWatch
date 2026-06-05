# VoltWatch Roadmap

This document outlines the planned technical direction and future architectural additions for the VoltWatch telemetry pipeline. 

## Phase 1: Foundational Robustness (Completed)
- [x] Establish strict decoupling between Edge, Backend, and Presentation layers.
- [x] Implement hardware-level time stamping (DS3231) to prevent latency artifacts.
- [x] Provide a zero-configuration SQLite onboarding experience.
- [x] Standardize CI/CD pipelines via GitHub Actions.

## Phase 2: Observability & Profiling (Current Focus)
- [ ] **Metrics Collection:** Integrate Prometheus hooks into the FastAPI backend to expose API latency and DB commit timings.
- [ ] **Benchmarking Suite:** Build an automated load testing script (using `Locust` or `wrk`) to validate ingestion throughput under high concurrency.
- [ ] **Grafana Dashboard:** Provide an optional Grafana configuration for users who prefer it over Streamlit for deep historical analysis.

## Phase 3: Advanced Data Streaming
- [ ] **WebSocket Integration:** Transition the Streamlit dashboard from HTTP polling to WebSockets for sub-second UI updates without hammering the DB.
- [ ] **TimescaleDB Migration Guide:** Document a smooth transition path for deploying VoltWatch on a VPS using TimescaleDB for millions of rows of time-series data.
- [ ] **Alerting System:** Add an async worker (e.g., Celery or native FastAPI BackgroundTasks) to trigger email/webhooks if voltage/current exceeds user-defined limits.

## Phase 4: Edge Autonomy
- [ ] **Over-The-Air (OTA) Updates:** Allow firmware updates via the Streamlit dashboard.
- [ ] **Plugin Architecture:** Design an extensible interface on the ESP8266 to easily add other sensors (e.g., BME280 for temperature/humidity) without rewriting the core HTTP retry logic.
