# Contributing

Thanks for helping. This project stays small on purpose, so please read this
before opening a PR.

## Ground rules

- **One PR, one concern, under 300 lines.** Large dumps are closed unread.
- **No new dependencies** without prior discussion. An extra package is a
  forever cost on every install. Redis and Alembic were evaluated and rejected;
  check the history before proposing one.
- **No new features during the freeze.** Bug, security, test and translation PRs
  are welcome. Features wait for an agreed issue.
- **English is the source of truth** for UI strings (`frontend/src/lang/en.json`).
  Add the `en` key; `fa`, `ru` and `cn` may follow in the same PR or a later one.
  All four files must keep identical key sets, which `npm run check:i18n`
  enforces.

## Conduct

Be kind and direct. Harassment, hate speech, spam and trolling are not welcome
in issues, discussions or PRs; technical disagreement is. Maintainers may hide
or remove violating content and, for repeat or serious violations, block the
account. Report harassment through GitHub private vulnerability reporting or the
maintainer address on the repository profile.

## Before you start: a manual install

The installer is the supported path for users. To work on the code, run it
yourself:

```bash
git clone https://github.com/anonysec/OVManager.git /opt/ovmanager
cd /opt/ovmanager
cp .env.example .env                      # set PUBLIC_URL for shareable links
pip install uv && uv sync
cd frontend && npm ci && npm run build
uv run main.py                            # first run creates the schema
```

The first run creates the owner row with no password. Set one with the Python
CLI directly (this is the CLI's own spelling, `--admin-pass`; the `-p/--pass`
short form belongs to the installed `ovm` command, not to this one):

```bash
.venv/bin/python -m cli.main reset-password --admin-pass 'a-strong-password'
```

## Checks

`make` wraps them, so you do not have to remember the incantations or run them
one at a time:

| Target | What it runs |
| --- | --- |
| `make setup` | `uv sync --frozen` and `npm ci`: exactly what the lock files pin. |
| `make test` | The backend suite, `pytest -n auto`. Parallel is safe because each xdist worker imports `conftest`, which allocates its own throwaway data directory. |
| `make lint` | `ruff check` and `ruff format --check` over backend, bot, cli, tests and bench; `bash -n` on the shell entrypoints; `git diff --check`; and `eslint src/` in the frontend. |
| `make verify` | `lint`, then the frontend's `npm run verify` (build, design tokens, i18n key parity, RTL, eslint, types, vitest), then regenerates `scripts/openapi.json`. |
| `make bench` | The node fan-out benchmarks in `scripts/bench/`. Not a test: the figures depend on the machine's core count. |

`make verify` does **not** run the backend suite; that is `make test`. Run both
before pushing. CI runs the same checks in three parallel jobs (`backend`,
`frontend`, `frontend-dist`) rather than one target.

Two project rules the warnings will catch you on:

- Warnings are errors. The backend suite runs with `filterwarnings = error`, so
  a new `DeprecationWarning` fails the run. Fix it rather than muting it.
- `frontend/src/tokens.css` is the only file allowed to declare `:root` or
  `html[data-theme=...]`, and Persian is right-to-left: use logical CSS
  (`margin-inline`, `inset-inline`, `text-align: start`) rather than
  `margin-left` or `left:`.

## Workflow

1. Fork, branch from `main`, keep the branch focused.
2. Change the code and add or extend a test for every behaviour change. New
   endpoints need a contract test; new UI copy needs the `en` key.
3. Run `make test` and `make verify`.
4. Describe **what** and **why**, not what the diff already shows. Link the
   issue.

Commit subjects are short and imperative (`fix(node): …`, `feat(bot): …`), with a
body only when the reason is not obvious. Never commit secrets: `.env`, `*.db`
and `data/` are push-protected and will block you.

## Release freeze

`main` is frozen at **1.0.0** until explicit owner sign-off. Version bumps,
features and fixes land only through a pull request the owner has reviewed.

Two things the release process depends on, since there is no tag yet:

- `install.sh` fetches `scripts/lib/*.sh` from the `v${VERSION}` tag, and the
  install and update paths download `ovmanager-${VERSION}.tar.gz` with its
  `.sha256` from that release. A published `v1.0.0` release is therefore a
  prerequisite for the documented one-liner, not a side effect of it.
- `tests/test_version_parity.py` pins every place the version is written, the
  changelog heading included. A bump that misses one fails the suite.

## Questions

Use **Discussions** for "how do I…". Open an **issue** for a bug, with
reproduction steps: version, logs, expected versus actual.
