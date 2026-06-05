# Security Policy

## Supported Versions

Currently, VoltWatch is in active development. Only the `main` branch is supported with security updates.

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |
| < 1.0   | :x:                |

## Reporting a Vulnerability

If you discover a security vulnerability within VoltWatch (especially concerning API Key exposure or the captive portal provisioning on the ESP8266), please send an e-mail to the maintainer via the contact info provided on the GitHub profile. 

**Do NOT report security vulnerabilities through public GitHub issues.**

### Important Security Considerations
- **API Keys**: The backend supports basic token-based authentication via `X-API-Key`. This is transmitted in plaintext if not using HTTPS. Always deploy the backend behind a reverse proxy (like Nginx or Caddy) with TLS/SSL enabled in production.
- **Captive Portal**: The ESP8266 provisioning portal operates over an open Wi-Fi network by default. Do not provision devices in highly untrusted public environments.
- **SQL Injection**: We use SQLAlchemy ORM to prevent SQL injection. Avoid executing raw SQL queries if extending the backend.
