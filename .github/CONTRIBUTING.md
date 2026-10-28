# Contributing

Thanks for helping. This project stays small on purpose, so please read this
before opening a PR.

## Ground rules

- **One PR, one concern, under 300 lines.** Large dumps are closed unread.
- **No new dependencies** without prior discussion. An extra package is a
  forever cost on every install.
- **English is the source of truth** for UI strings (`web/src/lang/en.json`).
  Add the `en` key; `fa`, `ru` and `cn` may follow in the same PR or a later
  one. All four files must keep identical key sets, which `npm run check:i18n`
  enforces.

## Before you start

```bash
git clone https://github.com/anonysec/OVManager.git
cd OVManager
make setup          # go mod download + npm ci
make version        # sync version constants
cd web && npm run build
go build -o ovmanager ./cmd
```

## Checks

| Target | What it runs |
| --- | --- |
| `make setup` | `go mod download` and `npm ci`. |
| `make test` | `go test ./...` |
| `make lint` | `go vet ./...` and `gofmt` check. |
| `make verify` | `make test` + `make version` + frontend `npm run verify`. |

Run `make verify` before pushing. CI runs the same checks.

## Workflow

1. Fork, branch from `main`, keep the branch focused.
2. Change the code and add or extend a test for every behaviour change.
3. Run `make verify`.
4. Describe **what** and **why**, not what the diff already shows. Link the issue.

Commit subjects are short and imperative (`fix(node): …`, `feat(ui): …`).

## Questions

Use **Discussions** for "how do I…". Open an **issue** for a bug, with
reproduction steps: version, logs, expected versus actual.