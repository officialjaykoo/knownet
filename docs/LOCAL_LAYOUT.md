# Local Layout

KnowNet keeps source, durable project data, and generated local artifacts
separate.

## Source

Tracked source and tests live under:

```txt
apps/
packages/
scripts/
docs/
```

Do not place virtualenvs, build outputs, packet exports, caches, or local logs
inside source directories unless the tool requires that location.

## Durable Local Data

SQLite, pages, snapshots, and operator data live under:

```txt
data/
```

Generated packet exports under `data/experiment-packets/` and
`data/project-snapshot-packets/` are ignored because they are runtime exchange
artifacts, not source.

## Generated Artifacts

Repo-local generated files use:

```txt
.local/venvs/api
.local/cargo-target
```

Tool-standard generated folders remain ignored:

```txt
apps/web/node_modules
apps/web/.next
__pycache__
.pytest_cache
```

Use `scripts/clean_generated.ps1` for normal cache cleanup. Use
`scripts/clean_generated.ps1 -All` only when you intentionally want to remove
the API virtualenv, web dependencies, and Rust build output too.
