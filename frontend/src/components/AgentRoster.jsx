import { agentsOrder } from '../api.js'

const LABEL = {
  data_steward: 'Data steward — pulled region telemetry',
  risk_assessor: 'Risk assessor — scored each region',
  historian: 'Historian — compared against prior runs',
  curator: 'Curator — wrote the assessment report',
}

const DESC = {
  data_steward: 'Ingests the latest surveillance figures for each selected region.',
  risk_assessor: 'Applies the risk model and assigns Urgent / Watch / Stable.',
  historian: 'Checks each result against the region’s assessment history.',
  curator: 'Assembles the findings into a coherent situation report.',
}

function ms(s) {
  if (s == null) return '—'
  if (s < 1000) return `${Math.round(s)} ms`
  return `${(s / 1000).toFixed(1)} s`
}

export default function AgentRoster({ timings, runId, running, activeAgent, hasRun }) {
  const timing = (name) => timings.find((t) => t.agent === name)

  return (
    <section className="section" aria-labelledby="agents-title">
      <div className="section-head">
        <span className="kicker">04 · Fleet</span>
        <span className="section-title" id="agents-title">
          What the fleet did
        </span>
        <span className="rule" />
      </div>

      <div className="agents">
        {agentsOrder.map((name) => {
          const t = timing(name)
          const isActive = running && activeAgent === name
          const done = hasRun && !running && t != null
          // Steady progression estimate for the idle/placeholder state.
          const pct = isActive ? 100 : done ? 100 : running ? 25 : 0
          return (
            <div className="agent" key={name}>
              <div className="a-name">{LABEL[name]}</div>
              <div className="a-bar">
                <div
                  className="fill"
                  style={{ width: `${pct}%`, transition: 'width 0.6s var(--ease)' }}
                />
              </div>
              <div className="a-meta">
                {isActive
                  ? `working…`
                  : t?.error
                    ? <span className="err">{t.error}</span>
                    : done
                      ? `${ms(t.duration_ms)}${t.regions_processed ? ` · ${t.regions_processed} regions` : ''}`
                      : '—'}
              </div>
              <div
                className="cell"
                style={{
                  gridColumn: '2 / -1',
                  marginTop: '-6px',
                  fontSize: '12.5px',
                  color: 'var(--muted)',
                }}
              >
                {DESC[name]}
              </div>
            </div>
          )
        })}
      </div>

      {runId && (
        <div className="footer" style={{ textAlign: 'left', paddingTop: 'var(--space-4)' }}>
          Run id: {runId}
        </div>
      )}
    </section>
  )
}
