# OVManager

OVManager is the web control panel for managing OpenVPN users, traffic, subscription links, and OVNode servers.

## Features

- User management with expiry dates, traffic quotas, and max-login limits
- Online/offline status and active connection counts per user
- Per-user disconnect and auth-error diagnostics
- Node management and bulk OVPN config download
- Subscription link generation
- Dark/light admin UI
- React frontend + FastAPI backend

## Project structure

- `backend/` — FastAPI backend, database models, routers, node API client
- `frontend/` — React/Vite UI
- `install.sh` / `installer.py` — installer entrypoints
- `data/` — runtime data directory placeholder

## Notes

Do not commit `.env`, runtime databases, logs, or generated virtualenv/node_modules directories.
