# Vigilux-Sentinel

A global outbreak-intelligence **agent fleet** built on [google-adk 1.x](https://google.github.io/adk-docs/).
Four focused agents - `data-steward`, `risk-assessor`, `historian`, `curator` -
run under a `SequentialAgent` orchestrator and turn irregular field survey
snapshots into a single auditable `FleetReport` per run.

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
  agents/
    main.py                 FastAPI: /health, /fleet/run, /fleet/status
    orchestrator.py         SequentialAgent root owning the four fleet agents
    config.py               pydantic-settings (env / .env)
    models/schemas.py       RegionSnapshot, SignalAssessment, TrendNote, FleetReport ...
    tools/
      firestore_tool.py     region_snapshots / fleet_runs / run_observability / run_log
      memory_bank_tool.py   Vertex AI Agent Engine Memory Bank + Firestore fallback
      observability.py      OTel spans + per-run timing records
    {agent}/agent.py        one module per fleet agent
    registry/agent_registry.yaml
    requirements.txt
  .env.example, conftest.py, pytest.ini
  data/seed_regions.py      synthetic region snapshots for a demo run
  deploy/                   Dockerfile + cloudrun_deploy.sh
  tests/                    unit tests per fleet agent
  docs/, examples/          architecture notes + sample FleetReport
  conftest.py, pytest.ini   test runner configuration
frontend/                  # API consumers / dashboards (not yet implemented)
```

## Local setup

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows; use source .venv/bin/activate on POSIX
pip install -r backend/agents/requirements.txt
copy backend\.env.example backend\.env   # and fill in what you need
```

Gemini is called through Vertex AI, so authenticate with Application Default
Credentials (no API key needed) before running locally:

```bash
gcloud auth application-default login
```

`.env` knobs that matter most:

| Var | Default | Meaning |
|---|---|---|
| `GOOGLE_CLOUD_PROJECT` | empty | Project for Firestore / Vertex / Cloud Trace |
| `FIRESTORE_REGION` | us-central1 | Firestore database region (independent of Gemini) |
| `GEMINI_VERTEX_LOCATION` | global | Vertex AI location for Gemini; `global` is required for gemini-3.5-flash |
| `GEMINI_API_KEY` | empty | Optional and UNUSED by default (legacy Developer API fallback only) |
| `SURVEY_STALENESS_THRESHOLD_DAYS` | 30 | Regions older than this are assessed |
| `USE_HEURISTIC_FALLBACK` | true | Deterministic assessment when Gemini is unavailable |
| `MEMORY_BANK_AGENT_ENGINE_ID` | empty | Real Agent Engine Memory Bank; empty = Firestore fallback |
| `OTEL_CLOUD_TRACE_ENABLED` | true | Export spans to Cloud Trace (gracefully degrades locally) |

## Run the local API

Run this from the `backend/` directory the module names resolve:

```bash
cd backend
..\venv\Scripts\python.exe -m uvicorn agents.main:app --port 8080
```

Trigger a run (requires Firestore connectivity or a mocked/dev path):

```bash
curl -X POST http://localhost:8080/fleet/run
curl http://localhost:8080/fleet/status
curl http://localhost:8080/health
```

### Seed demo data

```bash
cd backend
..\venv\Scripts\python.exe -m data.seed_regions --clear
```

seeds 10 synthetic regions spanning fresh surveys to ~90-day-old snapshots with
healthy, Watch and Urgent signal profiles.

## Tests

Run this from the `backend/` directory:

```bash
cd backend
..\venv\Scripts\python.exe -m pytest -q
```

Each fleet agent has a dedicated test module in `tests/`; the tool boundary
(Firestore / Gemini / Memory Bank) is mocked, while the agents run through the
real google-adk `Runner`.

## Deploy to Cloud Run

See [backend/deploy/cloudrun_deploy.sh](backend/deploy/cloudrun_deploy.sh)
(run from the repo root; the build context is the repo root):

```bash
export GOOGLE_CLOUD_PROJECT=my-project
export CLOUD_RUN_REGION=us-central1
./backend/deploy/cloudrun_deploy.sh
```

## License

Apache 2.0 (see [LICENSE](LICENSE)).