import { useFleet } from './hooks/useFleet.js'
import SignalBoard from './components/SignalBoard.jsx'
import RunConsole from './components/RunConsole.jsx'
import DetailPanel from './components/DetailPanel.jsx'
import StatusRail from './components/StatusRail.jsx'

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
    selectedRegion,
  } = useFleet()

  const timings = status?.agent_timings || []
  const lastRunId = status?.latest_run?.run_id || summary.runId

  return (
    <div className="console">
      <header className="topbar">
        <div className="wordmark">
          <span className="mark">VIGILUX</span>
          <span className="sub">signal console</span>
        </div>
        <div className="spacer" />
        {error && (
          <span
            className="conn"
            style={{ color: 'var(--urgent)' }}
            role="alert"
          >
            <span className="dot" style={{ background: 'var(--urgent)', boxShadow: 'var(--glow-urgent)' }} />
            {error}
          </span>
        )}
        <span className={`conn ${live ? 'live' : ''}`}>
          <span className="dot" />
          {live ? 'backend online' : 'demo mode'}
        </span>
      </header>

      <div className={`body ${selectedRegion ? 'has-detail' : ''}`}>
        <div className="board-wrap">
          <RunConsole
            summary={summary}
            phase={phase}
            activeAgent={activeAgent}
            onRun={run}
            live={live}
          />
          <SignalBoard
            regions={regions}
            assessments={summary.assessments}
            selectedRegionId={selectedRegionId}
            setSelectedRegionId={setSelectedRegionId}
            selectedIds={selectedIds}
            toggleRegion={toggleRegion}
          />
        </div>
        {selectedRegion && (
          <DetailPanel
            region={selectedRegion}
            onClose={() => setSelectedRegionId(null)}
          />
        )}
      </div>

      <StatusRail timings={timings} runId={lastRunId} />
    </div>
  )
}
