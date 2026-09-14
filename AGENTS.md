# Project rules

This project is a VALORANT cosmetic usage tracker.

Current phase: local Windows collector prototype.

Do not implement future phases unless explicitly requested.

Avoid:

- Tauri UI
- Spring Boot
- PostgreSQL
- Next.js
- Docker
- microservices
- ML
- overlays
- game memory reading
- DLL injection

Keep changes small.
Inspect only files relevant to the current task.
Do not create abstractions unless needed now.
Run focused tests after changes.
Never store or log Riot local API credentials.
Stop after completing the requested task.
