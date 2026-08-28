Captured from a running service (`GET /api/contract`, `/health`, `/api/queue`),
with `libreoffice` forced to `false` so the render test exercises the warning
banner.

Refresh them when the contract changes:

```bash
uv run uvicorn main:app --port 8000 &
curl -s localhost:8000/api/contract | python3 -m json.tool > contract.json
```
