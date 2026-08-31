import { useCallback, useEffect, useMemo, useState } from 'react'
import { getRegions, getStatus, runFleet, ping, isDemo } from '../api.js'

const RISK_WEIGHT = { Urgent: 0, Watch: 1, Stable: 2 }

// Severity ordering for the "watch line": urgent/worsening first.
export function sortWatchLine(assessments) {
  return [...assessments].sort((a, b) => {
    const ra = RISK_WEIGHT[a.risk_level] ?? 3
    const rb = RISK_WEIGHT[b.risk_level] ?? 3
    if (ra !== rb) return ra - rb
    const ta = a.trend?.trend_direction === 'worsening' ? 0 : 1
    const tb = b.trend?.trend_direction === 'worsening' ? 0 : 1
    return ta - tb
  })
}

export function useFleet() {
  const [regions, setRegions] = useState([])
  const [report, setReport] = useState(null)
  const [status, setStatus] = useState(null)
  const [phase, setPhase] = useState('idle') // idle | running | error
  const [activeAgent, setActiveAgent] = useState(null)
  const [error, setError] = useState(null)
  const [live, setLive] = useState(false)
  const [selectedRegionId, setSelectedRegionId] = useState(null)
  const [selectedIds, setSelectedIds] = useState(() => new Set())

  const loadRegions = useCallback(async () => {
    try {
      const rows = await getRegions()
      setRegions(rows)
      return rows
    } catch (e) {
      setError(`Could not reach the fleet: ${e.message}`)
      return []
    }
  }, [])

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await getStatus())
    } catch {
      /* non-fatal */
    }
  }, [])

  // Initial load + connection probe.
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      const ok = await ping()
      if (cancelled) return
      // "live" means a real backend is reachable — never in demo mode.
      setLive(!isDemo && ok)
      const rows = await loadRegions()
      if (cancelled) return
      // Pre-select a small scoped set so a single click can run the sweep.
      if (rows.length) {
        setSelectedIds(new Set(rows.slice(0, 5).map((r) => r.region_id)))
      }
      await refreshStatus()
    })()
    return () => {
      cancelled = true
    }
  }, [loadRegions, refreshStatus])

  const toggleRegion = useCallback((id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const run = useCallback(async () => {
    if (phase === 'running') return
    setPhase('running')
    setError(null)
    setActiveAgent(null)
    const ids = [...selectedIds]
    try {
      const res = await runFleet(ids, (agent) => setActiveAgent(agent))
      setReport(res)
      setPhase('idle')
      setActiveAgent(null)
      await refreshStatus()
    } catch (e) {
      setError(`Fleet run failed: ${e.message}`)
      setPhase('error')
      setActiveAgent(null)
    }
  }, [phase, selectedIds, refreshStatus])

  const summary = useMemo(() => {
    const a = report?.assessments || status?.latest_run?.assessments || []
    const flagged = (report?.regions_flagged ?? status?.latest_run?.regions_flagged ?? 0)
    const evaluated = (report?.regions_evaluated ?? status?.latest_run?.regions_evaluated ?? a.length)
    return {
      evaluated,
      flagged,
      assessments: a,
      runId: report?.run_id || status?.latest_run?.run_id || null,
    }
  }, [report, status])

  const selectedRegion = useMemo(() => {
    if (!selectedRegionId) return null
    const assessment = summary.assessments.find(
      (a) => a.region_id === selectedRegionId
    )
    const base = regions.find((r) => r.region_id === selectedRegionId)
    // Merge telemetry with its assessment so the detail panel shows risk/trend.
    return { ...(base || {}), ...(assessment || {}) }
  }, [regions, summary.assessments, selectedRegionId])

  return {
    regions,
    report,
    status,
    phase,
    activeAgent,
    error,
    live,
    summary,
    selectedIds,
    toggleRegion,
    run,
    selectedRegionId,
    setSelectedRegionId,
    selectedRegion,
  }
}
