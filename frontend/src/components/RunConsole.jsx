import { agentsOrder } from '../api.js'

// Control strip: run the fleet over the selected set, and show the live
// sweep progressing through the four agents. The count stats update from the
// latest report.
export default function RunConsole({ summary, phase, activeAgent, running, onRun, live }) {
  const { evaluated, flagged, runId } = summary

  const agentIndex = activeAgent ? agentsOrder.indexOf(activeAgent) : -1
  const isRunning = phase === 'running'

  return (
    <div className="runconsole">
      <div className="summary">
        <span className="stat">
          <span className="k">evaluated</span>
          <span className="v accent">{evaluated}</span>
        </span>
        <span className="stat">
          <span className="k">flagged</span>
          <span className="v urgent">{flagged}</span>
        </span>
        {runId && (
          <span className="stat">
            <span className="k">run</span>
            <span className="v" style={{ fontSize: 12 }}>
              {runId.slice(0, 8)}
            </span>
          </span>
        )}
        <span className="stat">
          <span className="k">mode</span>
          <span className="v" style={{ fontSize: 12, color: 'var(--phosphor)' }}>
            {live ? 'live' : 'demo'}
          </span>
        </span>
      </div>

      {isRunning && (
        <div className="sweep" role="status" aria-live="polite">
          <span>{activeAgent || '…'}</span>
          <span className="seq">
            {agentsOrder.map((a, i) => (
              <span key={a} className={`sq ${i <= agentIndex ? 'on' : ''}`} />
            ))}
          </span>
        </div>
      )}

      <button
        className="btn btn-primary"
        onClick={onRun}
        disabled={isRunning}
        aria-busy={isRunning}
      >
        {isRunning ? (
          <span>SWEEP…</span>
        ) : (
          <span>
            RUN <span className="label">FLEET</span> ▸
          </span>
        )}
      </button>
    </div>
  )
}
