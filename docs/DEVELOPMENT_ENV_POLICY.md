# Development Environment Policy

KnowNet keeps source files and local execution environments separate.

## Hard Rules

Do not:

- Create `.venv`, `venv`, `.tox`, or package environment folders inside this
  repository.
- Run `pip install` into the global Python interpreter while working on
  KnowNet.
- Generate or keep `*.egg-info`, `.pytest_cache`, `__pycache__`, `.next`,
  `node_modules`, `target`, or other build/cache folders as source artifacts.
- Install dependencies just to satisfy a one-off verification command without
  operator approval.

Do:

- Prefer Docker or an already prepared external environment.
- If Python dependencies are missing, stop and report the missing dependency
  instead of installing it globally.
- Keep any local Python environment outside the repo, for example:

  ```txt
  C:\knownet-local\venvs\api
  ```

- Use ignored/generated paths only as disposable local artifacts.

## Verification Rule For Agents

If a test command requires missing Python dependencies, the agent must report:

```txt
Skipped: Python test dependencies are not installed in the approved external
environment.
```

The agent must not run:

```txt
python -m pip install ...
```

unless the operator explicitly asks for dependency installation in that turn.

## Cleanup

Safe generated directories to remove when they appear in the source tree:

```txt
apps/api/.pytest_cache
apps/api/*.egg-info
**/__pycache__
.next
node_modules
target
```

These are not source and should not be used as evidence that the implementation
changed.
