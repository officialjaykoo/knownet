# Development Environment Policy

KnowNet keeps source files and generated/local execution artifacts separate.
For Python API work, the approved test environment is the global Python
interpreter on this workstation.

## Hard Rules

Do not:

- Create `.venv`, `venv`, `.tox`, or package environment folders inside this
  repository.
- Generate or keep `*.egg-info`, `.pytest_cache`, `__pycache__`, `.next`,
  `node_modules`, `target`, or other build/cache folders as source artifacts.
- Create local dependency folders inside the repo to work around missing
  packages.

Do:

- Use global Python for API dependencies and test execution:

  ```powershell
  cd apps\api
  python -m pytest
  ```

- If dependencies are missing, install them into the global Python interpreter,
  not into the repository.
- Use ignored/generated paths only as disposable local artifacts.

## Verification Rule For Agents

If a test command requires missing Python dependencies, install the approved
global API dependency set:

```powershell
python -m pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2.8" "pydantic-settings>=2.4" "aiosqlite>=0.20" "httpx>=0.27" "pytest>=8.0" "python-frontmatter>=1.1" "PyYAML>=6.0" "sentence-transformers>=2.7"
```

Do not create a repo-local virtual environment as part of this fallback.

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
