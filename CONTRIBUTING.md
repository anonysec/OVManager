# Contributing

Thanks for helping. This project stays small on purpose — please read this
before opening a PR.

## Ground rules

- **One PR = one concern, < 300 lines.** Large dumps are closed unread.
- **No new dependencies** without prior discussion (an extra package is a
  forever cost on every install). Redis/Alembic/passlib were evaluated and
  rejected — check history before proposing.
- **No new features during freeze.** Bug, security, test, and translation
  PRs are welcome; features wait for the roadmap issue.
- **English is the source of truth** for UI strings (`en.json`). Add the
  `en` key; `fa/ru/cn` translations may follow in the same or a later PR.
  CI fails if a locale drifts beyond budget (`npm run check:i18n`).

## Workflow

1. Fork, branch from `main`, keep the branch focused.
2. Backend: `uv sync && uv run pytest -q` green with
   `filterwarnings = error` (a warning fails the run — fix it, don't mute it).
3. Lint: `ruff check .` (Python). Frontend: `npm run lint -- --max-warnings 10`,
   `npm test`, `npm run build`.
4. Add or extend a test for every behavior change. New endpoints need a
   contract test; new UI copy needs the `en` key.
5. Describe **what/why**, not what the diff already shows. Link the issue.

## Commit style

Short imperative subject (`fix(node): ...`, `feat(bot): ...`), body only
when the reason isn't obvious. Never commit secrets (`.env`, `*.db`,
`data/`) — push protection is on and will block you.

## Questions?

Use **Discussions** for "how do I…". Open an **issue** only for a bug with
reproduction steps (version, logs, expected vs actual).
