# OVManager agent rules

## graphify first

This repo has a persistent knowledge graph in `graphify-out/`.
For any question about the codebase (architecture, callers, data flow,
where something lives): run `graphify query "<question>"` before grepping.
For path/explain: `graphify path "<A>" "<B>"` / `graphify explain "<node>"`.
After code changes: `graphify <path> --update` (post-commit hook rebuilds
code graph automatically; run `--update` manually for doc changes).
