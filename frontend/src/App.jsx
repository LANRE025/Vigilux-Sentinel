import { useMemo } from 'react'
import { useFleet } from './hooks/useFleet.js'
import { isDemo } from './api.js'
import Masthead from './components/Masthead.jsx'
import Lede from './components/Lede.jsx'
import AttentionList from './components/AttentionList.jsx'
import Ledger from './components/Ledger.jsx'
import AgentRoster from './components/AgentRoster.jsx'

function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const date = d.toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
  const time = d.toLocaleTimeString('en-US', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  })
  return `${date} · ${time}`
}

export default function App() {
  const {
    regions,
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
  } = useFleet()

  const assessments = summary.assessments
  const urgentCount = assessments.filter((a) => a.risk_level === 'Urgent').length
  const watchCount = assessments.filter((a) => a.risk_level === 'Watch').length
  const hasRun = assessments.length > 0

  const lastAssessed = useMemo(() => {
    const ts = assessments.map((a) => a.assessed_at).filter(Boolean).sort().pop()
    return formatDateTime(ts) || formatDateTime(summary.runId)
  }, [assessments, summary.runId])

  return (
    <div className="report">
      <Masthead
        running={phase === 'running'}
        activeAgent={activeAgent}
        error={error}
        live={live}
        selectedCount={selectedIds.size}
        onRun={run}
        canRun={phase !== 'running'}
      />

      <Lede
        hasRun={hasRun}
        urgentCount={urgentCount}
        watchCount={watchCount}
        evaluated={summary.evaluated}
        flagged={summary.flagged}
        live={live}
        isDemo={isDemo}
        lastAssessed={lastAssessed}
      />

      <AttentionList
        assessments={assessments}
        regions={regions}
        selectedRegionId={selectedRegionId}
        onSelect={setSelectedRegionId}
      />

      <Ledger
        regions={regions}
        assessments={assessments}
        selectedIds={selectedIds}
        toggleRegion={toggleRegion}
        selectedRegionId={selectedRegionId}
        setSelectedRegionId={setSelectedRegionId}
      />

      <AgentRoster
        timings={status?.agent_timings || []}
        runId={summary.runId}
        running={phase === 'running'}
        activeAgent={activeAgent}
        hasRun={hasRun}
      />

      <footer className="footer">
        Vigilux Sentinel · outbreak-intelligence fleet ·{' '}
        {live ? 'live backend' : 'demo data'}
      </footer>
    </div>
  )
}
