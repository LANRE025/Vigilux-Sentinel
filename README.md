# Vigilux-Sentinel

A global outbreak-intelligence **agent fleet** built on [google-adk 1.x](https://google.github.io/adk-docs/).
Four focused agents - `data-steward`, `risk-assessor`, `historian`, `curator` -
run under a `SequentialAgent` orchestrator and turn irregular field survey
snapshots into a single auditable `FleetReport` per run.

> **Python**: 3.10+ required (the code uses modern typing such as `list[str]`
> and `X | None`). 3.12 is recommended and matches the Cloud Run image.

## What the fleet does

1. **data-steward** reads every region snapshot from Firestore (no LLM).
2. **risk-assessor** sends regions* whose survey is older than
   `SURVEY_STALENESS_THRESHOLD_DAYS` (default 30) to Gemini, one structured
   `SignalAssessment` call per region; fresh regions are skipped entirely.
   A deterministic heuristic keeps the run alive when Gemini is unavailable.
3. **historian** recalls each region's previous assessment from the **Memory
   Bank**, writes a `TrendNote` (first_observation / improving / worsening /
   unchanged), and stores this run's assessment for the next run.
4. **curator** merges everything into the `FleetReport`, persists it along with
   per-agent telemetry and the registry log, and returns it as JSON.

Every agent runs inside an OpenTelemetry span; timings are persisted per run
and exposed through `GET /fleet/status`.

## Architecture

See [backend/docs/architecture.md](backend/docs/architecture.md) for the
topology, the real roles of the Memory Bank and Observability, and an explicit
list of what is **not** implemented (Identity/Gateway, dynamic registry API,
Model Armor).

## Repository layout

```
backend/                   # everything that runs the agent fleet
  main.py                  FastAPI app (/health, /fleet/regions, /fleet/run, /fleet/status)
  requirements.txt         runtime dependencies (everything needed to boot & run)
  requirements-dev.txt     test-only dependencies (pytest, pytest-asyncio)
  .env.example             template for .env; copy to .env and fill in
  pytest.ini, conftest.py  test runner configuration + shared harness
  agents/
    orchestrator.py         SequentialAgent root owning the four fleet agents
    config.py               pydantic-settings (env / .env)
    models/schemas.py       RegionSignal, SignalAssessment, TrendNote, FleetReport ...
    tools/
      firestore_tool.py     region_snapshots / fleet_runs / run_observability / run_log
      memory_bank_tool.py   Vertex AI Agent Engine Memory Bank + Firestore fallback
      observability.py      OTel spans + per-run timing records
    {agent}/agent.py        one module per fleet agent
    registry/agent_registry.yaml
  data/seed_regions.py      synthetic region snapshots for a demo run
  scripts/                  live-check helpers (data_steward, full_fleet, firestore smoke)
  deploy/                   Dockerfile + cloudrun_deploy.sh
  tests/                    unit tests per fleet agent
  docs/, examples/          architecture notes + sample FleetReport
frontend/                  # API consumers / dashboards (not yet implemented)
```

## Local setup

### 1. Create a virtual environment

From the repository root:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate
```

### 2. Install dependencies

Install the **runtime** dependencies first, then the **dev/test** ones so you
can run the test suite:

```bash
# runtime (everything needed to boot the API and run the agents)
python -m pip install -r backend/requirements.txt

# dev/test (pytest + pytest-asyncio) — only needed if you run the tests
python -m pip install -r backend/requirements-dev.txt
```

> `httpx` is in the runtime requirements because the FastAPI endpoint tests
> (the ASGI `TestClient`) and the risk assessor both rely on it.

Everything the project needs is declared in
[`backend/requirements.txt`](backend/requirements.txt) (and
[`backend/requirements-dev.txt`](backend/requirements-dev.txt) for tests). If
you prefer a completely reproducible install you can pin exact versions in
either file.

### 3. Configure `.env`

```bash
copy backend\.env.example backend\.env    # Windows
# cp backend/.env.example backend/.env     # macOS / Linux
```

Then edit `backend/.env` (see the table below). The app reads `.env` from the
`backend/` working directory, so always run uvicorn/pytest from there.

### 4. Authenticate with Google Cloud (ADC)

Gemini is reached through **Vertex AI** and Firestore through **Cloud
Firestore**, both authenticated with Application Default Credentials (ADC) -
**no API key** is needed or read by the fleet:

```bash
gcloud auth application-default login
```

If you do not need live Firestore/Gemini for local exploration, you can skip
this step - the unit-test suite mocks the tool layer and runs offline.

`.env` knobs that matter most:

| Var | Default | Meaning |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | empty | Project for Firestore / Vertex / Cloud Trace |
| `FIRESTORE_REGION` | us-central1 | Firestore database region (independent of Gemini) |
| `GEMINI_VERTEX_LOCATION` | global | Vertex AI location for Gemini; `global` is required for gemini-3.5-flash |
| `GEMINI_API_KEY` | empty | Optional and UNUSED by default (legacy Developer API fallback only) |
| `SURVEY_STALENESS_THRESHOLD_DAYS` | 30 | Regions older than this are assessed |
| `DATA_STEWARD_STALENESS_THRESHOLD_DAYS` | 30 | Data-steward flagging threshold (inclusive) |
| `USE_HEURISTIC_FALLBACK` | true | Deterministic assessment when Gemini is unavailable |
| `MEMORY_BANK_AGENT_ENGINE_ID` | empty | Real Agent Engine Memory Bank; empty = Firestore fallback |
| `OTEL_CLOUD_TRACE_ENABLED` | true | Export spans to Cloud Trace (gracefully degrades locally) |

## Run the local API

Run from the `backend/` directory so the `agents` package, `main:app` and
`.env` all resolve:

```bash
cd backend
..\venv\Scripts\python.exe -m uvicorn main:app --port 8080
```

Trigger a run (requires Firestore connectivity or a seeded dev dataset):

```bash
# region_ids is REQUIRED - pick the subset of regions to look through this run.
# Omit it and FastAPI returns 422. Grab candidate ids from /fleet/regions.
curl -X POST http://localhost:8080/fleet/run \
  -H "Content-Type: application/json" \
  -d '{"region_ids": ["region-nigeria-covid19-01", "region-accra-01"]}'
# Requested ids not found in the data source appear in missing_region_ids
# (the run still completes rather than failing).
curl http://localhost:8080/fleet/status
curl http://localhost:8080/health

# Fast, cheap list of available regions for a frontend picker (no pipeline):
curl http://localhost:8080/fleet/regions   # -> [{"region_id": "...", "display_name": "..."}, ...]
```

The API is also self-documenting: open `http://localhost:8080/docs` (Swagger UI).
Try it quickly with the live checks below.

### Seed demo data

```bash
cd backend
..\venv\Scripts\python.exe -m data.seed_regions --clear      # wipe + reseed
..\venv\Scripts\python.exe -m data.seed_regions              # upsert only
```

This seeds 10 synthetic regions plus the packaged survey dataset, spanning
fresh surveys to ~90-day-old snapshots with healthy, Watch and Urgent signal
profiles.

## Live checks (real Firestore + real Gemini)

These are **not** part of the pytest suite - they hit the real Firestore
collection and real Vertex/Gemini, and each `full_fleet` run writes rows to
`fleet_runs` / `run_observability` / `run_log` in Firestore. Run them from
`backend/` with ADC configured. Note the CLI's `region_ids` are optional
here, but **scoping a run to a small subset is strongly recommended** - a
full-fleet run over every region takes on the order of 20-35 minutes and
spends real Vertex tokens, one Gemini call per region:

```bash
cd backend
..\.venv\Scripts\python.exe scripts\data_steward_live_check.py
..\.venv\Scripts\python.exe scripts\full_fleet_live_check.py region-accra-01   # scoped (fast)
..\.venv\Scripts\python.exe scripts\full_fleet_live_check.py region-accra-01 region-lagos-01
..\.venv\Scripts\python.exe scripts\smoke_test_firestore.py
```

## Tests

Run from the `backend/` directory:

```bash
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Each fleet agent has a dedicated test module in `tests/`; the tool boundary
(Firestore / Gemini / Memory Bank) is mocked, while the agents run through the
real google-adk `Runner`. `pytest.ini` sets `asyncio_mode = auto`, so the async
tests run without extra decorators (requires `pytest-asyncio`, in
`requirements-dev.txt`).

## Deploy to Cloud Run

See [backend/deploy/cloudrun_deploy.sh](backend/deploy/cloudrun_deploy.sh)
(run from the repo root; the build context is the repo root):

```bash
export GOOGLE_CLOUD_PROJECT=my-project
export CLOUD_RUN_REGION=us-central1
./backend/deploy/cloudrun_deploy.sh
```

The included [Dockerfile](backend/deploy/Dockerfile) installs only the runtime
`requirements.txt` (no dev/test deps) and starts `uvicorn main:app`.

## License

Apache 2.0 (see [LICENSE](LICENSE)).