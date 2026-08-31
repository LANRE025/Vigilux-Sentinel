# Vigilux Sentinel · Signal Console

A dark, early-warning command instrument for the Vigilux Sentinel agent fleet.
It watches region risk (a system of **signal lamps** — not one accent color),
surfaces trends, and triggers live fleet **sweeps** that light regions up as the
four ADK agents assess them.

Stack: **React + Vite**. Display type: **Space Grotesk** · telemetry: **IBM Plex Mono**.

## Run it

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
npm run build      # production build -> dist/
```

## Two modes

- **Demo (default)** — `VITE_DEMO=true` renders seeded mock regions and a
  simulated sweep. No backend, no CORS. Use this to demo in a video.
- **Live** — set `VITE_API_URL` to your deployed backend (e.g. the Cloud Run
  URL) and `VITE_DEMO=false`. The console then calls `/fleet/regions`,
  `/fleet/run`, and `/fleet/status`.

Copy `.env.example` → `.env` and adjust.

## What it calls

| Endpoint | Purpose |
|---|---|
| `GET /health` | connection probe |
| `GET /fleet/regions` | list regions for the board |
| `POST /fleet/run` | trigger a sweep over the selected `region_ids` |
| `GET /fleet/status` | last run + per-agent timings |

> The backend must add CORS middleware for a cross-origin frontend to reach it.
