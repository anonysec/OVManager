# OVManager Frontend

React SPA for the OVManager panel: user/node management, server stats, audit log, settings, and the Telegram bot configuration UI.

## Stack

- React 19 + Vite 8
- react-router-dom for routing
- i18next (en, fa, ru, cn)
- axios for the panel API
- Vitest for unit tests

## Development

```bash
npm ci
npm run dev        # dev server on http://localhost:5173
npm run lint       # eslint
npm test           # vitest
npm run build      # production build -> dist/
```

## Notes

- The panel serves at a configurable URL prefix (e.g. `/dashboard/`). The
  backend injects a `<base href>` tag into the served `index.html` at
  runtime, so the build itself is prefix-agnostic (`base: './'`).
- The production build is served by the backend from `dist/`; it is also
  published to GitHub Pages as a static showcase along with the `install.sh`
  installer script.
