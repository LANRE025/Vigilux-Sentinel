# Vigilux Sentinel - Architecture

## Problem

Field teams across regions submit snapshots on irregular cadences. Vigilux
Sentinel runs a **fleet** that turns those snapshots into a single, auditable
outbreak-intelligence report per run: which regions are at risk, why, whether a
region is getting better or worse compared to its own history, and what the
fleet spent its LLM budget on.

## Fleet topology

Everything is google-adk 1.x. The root is a plain `SequentialAgent`; it does
**no inference of its own**. It owns four fleet agents, each with a single
responsibility, its own bounded tools and instructions, and strict sequential
hand-off of state:

```
GET /fleet/regions (FastAPI - read-only, no fleet run)
   │
   ▼
region_snapshots (Firestore) → [{region_id, display_name}]

POST /fleet/run  (FastAPI)
   │
   ▼
vigilux_orchestrator  (SequentialAgent - deterministic pass-through)
   │
   ├─ data-steward     read region_snapshots (Firestore) ─────────────┐ no LLM
   │                                                                   │
   ├─ risk-assessor    per stale region: one Gemini call              ┐ │ LLM per
   │                   (response_schema=SignalAssessment) +           │ │ stale
   │                   deterministic heuristic fallback                │ │ region
   │                                                                   │ │
   ├─ historian        Memory Bank: recall prev assessment →          ┐ │ no LLM
   │                   TrendNote → store this assessment               │ │
   │                                                                   │ │
   ├─ curator          merge → FleetReport ─→ fleet_runs              ┐ │ no LLM
   │                   telemetry    ─→ run_observability              │ │
   │                   registry log ─→ run_log                        │ │
   │                                                                   │ │
   └──────────────────────────────► JSON FleetReport ◄────────────────┘ ┘
```

Data flows between agents through ADK session state under the ephemeral
`temp:` namespace (`temp:region_snapshots`, `temp:assessments`,
`temp:trend_notes`, `temp:fleet_report`). Run metadata (`temp:run_id`,
`temp:started_at`) is seeded by the API through
`Runner.run_async(state_delta=...)`.

## The four agents

| Agent | Responsibility | LLM? | Tools |
|---|---|---|---|
| data-steward | Read all region snapshots, hand structured data to the fleet | No | `firestore_tool.read_region_snapshots` |
| risk-assessor | A structured `SignalAssessment` per stale region (1 call each), skip fresh ones | Yes, one structured call per stale region | `assess_region` |
| historian | Cross-run baselines: read history -> TrendNote -> append back | No | `compute_trend`, `firestore_tool.read_assessment_history`, `firestore_tool.write_assessment_history` |
| curator | Assemble + persist the FleetReport and return it | No | `build_fleet_report`, `firestore_tool.write_*`, `append_run_log_entry` |

## Region picker (GET /fleet/regions)

`GET /fleet/regions` is a fast, cheap, read-only listing of available regions
for the frontend region picker. It reads the same ``region_snapshots``
collection the data steward pulls from (so region identity is always in sync
with the pipeline), and composes a human-readable ``display_name`` from the
snapshot's ``country`` plus optional ``disease`` (e.g. "Nigeria / COVID-19"),
mirroring how ``data/seed_regions.py`` labels rows. It performs **no**
staleness calculation, **no** Gemini call, and critically does **not** start a
fleet run - it cannot trigger the assessment pipeline.

## Historian runtime memory (assessment_history)

The historian is the only agent that reads and writes cross-run memory. Each
assessment is scoped per region; the region's history document is read *before*
this run's assessment is written (read-before-write for the same region), the
last entry becomes the trend baseline, and the new assessment is appended for
the next run.

- **Real implementation**: the Firestore collection `assessment_history`, one
  document per region (`assessment_history/<region_id>`), with an `entries`
  array holding full SignalAssessments (most recent last). Entries are trimmed
  to the last 5, so trends compare against at most 5 prior observations.
  `runs_compared` counts how many prior entries existed (0 = first
  observation). The same document is never compared against itself within a
  run: two assessments for one region in a single fleet run both trend against
  the same pre-run baseline.

## Observability (real role)

Every agent executes inside `observability.agent_span`:

1. An OpenTelemetry span (`agent.<name>`, attributes for `run_id` and
   `regions_processed`, `record_exception` on failure). Exported to **Cloud
   Trace** via `opentelemetry-exporter-gcp-trace` on Cloud Run.
2. A per-run JSON timing record (agent, started/ended, duration_ms,
   regions_processed, error). The curator persists these to
   `run_observability/<run_id>`; `GET /fleet/status` surfaces them.

## What is deliberately NOT implemented

These were out of scope and are called out explicitly:

- **Identity and Gateway (Agent Engine)**: no `/session/*`, model-gateway or
  identity endpoints. The fleet is driven through the FastAPI surface in
  `backend/main.py`.
- **Dynamic registry API**: the registry is the static YAML catalog in
  `backend/agents/registry/agent_registry.yaml` plus the `run_log` collection
  written by the curator, not a live registry service.
- **Model Armor**: no integration. Gemini calls go directly through
  google-genai.

## Data flow (mermaid)

```mermaid
flowchart LR
  API[POST /fleet/run] --> ORCH[vigilux_orchestrator<br/>SequentialAgent]
  ORCH --> DS[data-steward]
  DS -->|temp:region_snapshots| RA[risk-assessor]
  RA -->|temp:assessments| HI[historian]
  HI --> AH[(assessment_history<br/>read-before-write)]
  HI -->|temp:trend_notes| CU[curator]
  CU --> F[(Firestore<br/>fleet_runs/run_observability/run_log)]
  CU -->|FleetReport JSON| API
  DS -.-> SRC[(region_snapshots)]
  RA -.-> GEMINI[(Gemini<br/>structured)]
```