# KnowNet Release Checklist

Run this before tagging a local MVP release.

```txt
1. git status is clean
2. cargo test passes in apps/core
3. API pytest suite passes in apps/api
4. smoke test passes: pytest tests/smoke/ -m smoke
5. npm audit reports 0 vulnerabilities in apps/web
6. npm run build passes in apps/web
7. GET /health/summary is not attention_required
8. Create a tar.gz snapshot
9. Restore from that snapshot in an isolated test data directory
10. Run verify-index after restore
11. README and RUNBOOK are up to date
```

Do not tag a release if restore has not been tested.
