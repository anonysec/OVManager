# OVManager

OVManager is the web control panel for managing OpenVPN users, traffic, subscription links, and OVNode servers.

## Features

- User management with expiry, traffic quota, max-login limits
- Online/offline status and active connection counts
- Per-user disconnect and auth-error diagnostics
- Node management and bulk OVPN config download
- Subscription link generation
- Dark/light admin UI

## Components

- `panel/` — FastAPI backend + React frontend
- Connects to OVNode agents over authenticated HTTP APIs

## License

Private project source published by repository owner.
