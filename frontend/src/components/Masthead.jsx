import { agentsOrder } from '../api.js'
import { displayName } from '../data/mock.js'

export default function Masthead({
  running,
  activeAgent,
  error,
  live,
  selectedCount,
  onRun,
  canRun,
}) {
  return (
    <header className="masthead">
      <div className="brand">
        <div className="kicker">Outbreak Intelligence Fleet</div>
        <h1>
          <span className="brand-vigilux">Vigilux</span>{' '}
          <span className="brand-sentinel">Sentinel</span>
        </h1>
        <div className="pubdate">
          {live ? 'Live fleet assessment' : 'Demonstration data'}
          <span className="sep">·</span>
          {selectedCount} region{selectedCount === 1 ? '' : 's'} selected
          <span className="sep">·</span>
          {live ? (
            <span className="live-dot" title="Backend online" />
          ) : null}
          {live ? 'backend online' : 'offline mode'}
        </div>
      </div>

      <div className="masthead-actions">
        <button
          className="btn btn-primary"
          onClick={onRun}
          disabled={!canRun || selectedCount === 0}
        >
          {running ? 'Fleet assessing…' : 'Run fleet assessment'}
        </button>
        <div className="runstate" role="status" aria-live="polite">
          {running ? (
            <>
              <span className="agents">
                {agentsOrder.map((a) => (
                  <span key={a} className={`ag ${activeAgent === a ? 'on' : ''}`}>
                    {displayName({ country: a.replace(/_/g, ' ') })}
                  </span>
                ))}
              </span>
              <span>assessing</span>
            </>
          ) : error ? (
            <span style={{ color: 'var(--urgent)' }}>{error}</span>
          ) : (
            <span>{live ? 'fleet ready' : 'ready to demonstrate'}</span>
          )}
        </div>
      </div>
    </header>
  )
}
