# Docker Compose evidence — 22 Aug 2026

Chain run from the repo root on Windows 11 with Docker Desktop 29.5.3:

1. `docker compose build bills-frontend bills-backend bills-db` — three images built.
2. `docker compose up -d` — `compose-ps.txt` shows all three containers up on 3005/5005/6005.
3. `curl` against each service — `curl-endpoints.txt` (health on 6005 and 5005, bills via the nginx proxy on 3005, the September calendar breakdown, a 60-day timeline, and the read-only `/upcoming` passthrough on 6005).
4. `docker compose down` — `compose-down.txt`.

Two defects were found only by this chain and fixed in the same commit: YAML parsed the unquoted `DEMO_TODAY: 2026-08-20` as a timestamp (now quoted, and `config.py` tolerates the long form), and the bills table showed ISO dates and a spurious "Confirm this?" on every unconfirmed bill rather than only on alerts-handoff rows.
