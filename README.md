# ASD Spring 2026 — group 21

## Agentic loop

A shared terminal Plan → Act → Observe → Adapt review workflow lives in
`agentic_loop/` with per-student prompt assets under `prompts/`. With the
group app running (`docker compose up -d`):

```
pip install -r agentic_loop/requirements.txt
python -m agentic_loop.main
```

Run records land in `reports/` (gitignored). Details: `agentic_loop/README.md`.
