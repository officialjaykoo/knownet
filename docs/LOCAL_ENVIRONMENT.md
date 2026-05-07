# KnowNet Local Environment

KnowNet keeps source files, durable local data, and generated execution artifacts separate.

## Source

Tracked source and tests live under:

```txt
apps/
packages/
scripts/
docs/
```

Do not place virtualenvs, build outputs, packet exports, caches, or local logs inside source directories unless the tool requires that location.

## Durable Local Data

SQLite, pages, snapshots, and operator data live under:

```txt
data/
```

Generated packet exports under `data/experiment-packets/` and `data/project-snapshot-packets/` are ignored because they are runtime exchange artifacts, not source.

## Python Environment

The approved KnowNet API test environment on this workstation is global Python.

Do not create repo-local Python environments:

```txt
.venv
venv
.tox
package-local dependency folders
```

Use:

```powershell
cd apps\api
python -m pytest
```

If dependencies are missing, install them into global Python, not into the repository.

## Generated Artifacts

Repo-local generated build files use:

```txt
.local/cargo-target
```

Tool-standard generated folders remain ignored:

```txt
apps/web/node_modules
apps/web/.next
__pycache__
.pytest_cache
*.egg-info
```

Use `scripts/clean_generated.ps1` for normal cache cleanup. Use `scripts/clean_generated.ps1 -All` only when intentionally removing web dependencies and Rust build output too.

## Agent Rule

If a command fails because Python dependencies are missing, install the approved dependency set globally. Never create a local virtual environment inside `c:\knownet` as a workaround.
