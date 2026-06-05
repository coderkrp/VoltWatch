# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- GitHub Actions CI/CD workflow for fully automated validation of hardware firmware, backend APIs, and frontend UI.
- Comprehensive technical documentation (`docs/` folder) detailing data-flow, architecture, setup, and deployment.
- Initial public release formatting including `ARCHITECTURE.md`, `ROADMAP.md`, and issue templates.

### Changed
- Major refactoring of the README to reflect the transition from a personal tool to a robust full-stack pipeline.
- Migrated code style to utilize `Ruff` and `Black` for standardized Python development.

## [1.0.0] - 2024-02-10
### Added
- Complete ESP8266 + INA219 + DS3231 telemetry system.
- FastAPI backend for high-performance async batch ingestion.
- Streamlit dashboard for real-time visualization of bus voltage, shunt voltage, and current.
- On-device Wi-Fi provisioning via Captive Portal.
- SQLite persistence layer with SQLAlchemy ORM.
