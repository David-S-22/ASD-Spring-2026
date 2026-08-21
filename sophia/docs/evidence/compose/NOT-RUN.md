# Docker Compose verification — not run

Date: 22 Aug 2026.

`docker info` was checked at the start of every PR in this sequence
(PR-B through PR-F) and once more before finishing PR-F. Each time it
failed the same way:

```
failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine;
check if the path is correct and if the daemon is running: open
//./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified.
```

The Docker Desktop CLI is installed (`docker --version` reports 29.5.3), but
its daemon was never running in this environment, so `docker compose build`,
`docker compose up -d`, the health-check curls, and `docker compose down`
were not exercised on this machine.

What was verified instead, against the real local services on temp ports
(not Docker): `python -m pytest sophia/test -q` (82 passed), plus real
end-to-end HTTP calls to the `sophia/database` and `sophia/backend` Flask
apps run directly with `python`/`python -m`, including live calls to Ollama
— see `docs/evidence/ai/`. Each Dockerfile was written to the same
`pip install` / `COPY` / `CMD` shape verified working under plain `python`,
but the container build itself has not been confirmed on this machine.

If Docker Desktop's daemon is started, the verification this file
substitutes for is:

```
docker compose build bills-frontend bills-backend bills-db
docker compose up -d
curl localhost:6005/health
curl localhost:5005/health
curl localhost:3005/
curl localhost:3005/api/bills
docker compose ps
docker compose down
```
