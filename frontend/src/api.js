// ============================================================
// API client. Reads VITE_API_URL + VITE_DEMO from .env (Vite
// exposes import.meta.env.VITE_*). In demo mode everything is
// served from ./data/mock.js so the console demos with no live
// backend (and no CORS wiring).
// ============================================================

import {
  AGENTS_ORDER,
  MOCK_REGIONS,
  MOCK_REPORT,
  MOCK_TIMINGS,
  displayName,
} from './data/mock.js'

const PROXY = import.meta.env.VITE_PROXY === 'true'
// When proxying, the base is '' (same-origin; the dev server forwards /fleet
// and /health to VITE_API_URL). Otherwise use VITE_API_URL directly.
const API_URL = (PROXY ? '' : import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
// Demo mode is on when VITE_DEMO=true OR no backend URL is configured (in
// which case there's nothing to call, so we serve mock data).
const DEMO = import.meta.env.VITE_DEMO === 'true' || (!PROXY && !API_URL)

export const isDemo = DEMO
export const agentsOrder = AGENTS_ORDER

const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

async function req(path, options) {
  // Only attach a JSON Content-Type when there's a body. A stray
  // Content-Type on a GET (as before) made the dev proxy's http-proxy
  // wait for a request body that never comes, hanging every read.
  const withBody = Boolean(options?.body)
  const res = await fetch(`${API_URL}${path}`, {
    ...(withBody ? { headers: { 'Content-Type': 'application/json' } } : {}),
    ...options,
  })
  if (!res.ok) {
    throw new Error(`${res.status} ${res.statusText} (${path})`)
  }
  return res.json()
}

// Build a live-region row. The backend's /fleet/regions returns only
// {region_id, display_name}; enrich with coordinates + signals from the
// seeded mock set (keyed by region_id) when they match, otherwise leave the
// telemetry columns empty so the board renders "—" rather than fabricated 0s.
function toRegionRow(r) {
  const m = MOCK_REGIONS.find((x) => x.region_id === r.region_id)
  return {
    region_id: r.region_id,
    display_name: r.display_name || displayName(m) || r.region_id,
    country: m?.country || r.region_id,
    lat: m?.lat ?? null,
    lon: m?.lon ?? null,
    days_since_survey: m?.days_since_survey ?? null,
    admissions_pct_change: m?.admissions_pct_change ?? null,
    funding_pct_of_avg: m?.funding_pct_of_avg ?? null,
  }
}

export async function getRegions() {
  if (DEMO) {
    return MOCK_REGIONS.map((r) => ({ ...toRegionRow(r), display_name: displayName(r) }))
  }
  const list = await req('/fleet/regions')
  return list.map(toRegionRow)
}

export async function getStatus() {
  if (DEMO) {
    return {
      run_id: MOCK_REPORT.run_id,
      latest_run: MOCK_REPORT,
      agent_timings: MOCK_TIMINGS,
      registry_entry: {
        run_id: MOCK_REPORT.run_id,
        outcome: 'pass',
        regions_evaluated: MOCK_REPORT.regions_evaluated,
        regions_flagged: MOCK_REPORT.regions_flagged,
      },
    }
  }
  return req('/fleet/status')
}

// Run the fleet. In both modes we drive the sweep animation forward as the
// four agents "report", then resolve to a FleetReport. Demo mode resolves to
// the mock report; live mode POSTs and returns the real report.
export async function runFleet(regionIds, onAgent) {
  const step = 620 // ms per agent in the sweep
  for (let i = 0; i < AGENTS_ORDER.length; i += 1) {
    onAgent?.(AGENTS_ORDER[i], i)
    await sleep(step)
  }

  if (DEMO) {
    return MOCK_REPORT
  }

  return req('/fleet/run', {
    method: 'POST',
    body: JSON.stringify({ region_ids: regionIds }),
  })
}

export async function ping() {
  if (DEMO) return true
  try {
    const d = await req('/health')
    return d?.status === 'ok'
  } catch {
    return false
  }
}
