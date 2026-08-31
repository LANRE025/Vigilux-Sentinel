import Lamp from './Lamp.jsx'

// Slide-over detail for a selected target: risk, trend, rationale, signals.
export default function DetailPanel({ region, onClose }) {
  if (!region) return null

  const trend = region.trend
  const trendDir = trend?.trend_direction
  const assessedAt = region.assessed_at

  return (
    <aside className="detail" role="complementary" aria-label="region detail">
      <div className="detail-head">
        <div className="eyebrow">Target detail</div>
        <h2>{region.display_name || region.country}</h2>
        <div className="country">{region.region_id}</div>
        <button
          className="btn btn-ghost"
          onClick={onClose}
          style={{ alignSelf: 'flex-start', marginTop: 8 }}
          aria-label="close detail"
        >
          Close
        </button>
      </div>

      <div className="detail-body">
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 12,
          }}
        >
          <Lamp risk={region.risk_level} className="lamp-lg" />
          <div>
            <div
              className="tel"
              style={{
                fontFamily: 'var(--font-display)',
                fontWeight: 700,
                fontSize: 22,
                color:
                  region.risk_level === 'Urgent'
                    ? 'var(--urgent)'
                    : region.risk_level === 'Watch'
                      ? 'var(--watch)'
                      : 'var(--stable)',
              }}
            >
              {region.risk_level || 'Unassessed'}
            </div>
            <div className="conf" style={{ marginTop: 2 }}>
              {region.confidence || 'not yet evaluated'}
            </div>
          </div>
        </div>

        <div className="metric-grid">
          <div className="metric">
            <div className="m-k">Days since survey</div>
            <div className="m-v">{region.days_since_survey ?? '–'}</div>
          </div>
          <div className="metric">
            <div className="m-k">Admissions Δ</div>
            <div className="m-v">
              {region.admissions_pct_change == null
                ? '–'
                : `${region.admissions_pct_change > 0 ? '+' : ''}${region.admissions_pct_change}%`}
            </div>
          </div>
          <div className="metric">
            <div className="m-k">Funding</div>
            <div className="m-v">{region.funding_pct_of_avg ?? '–'}% avg</div>
          </div>
          <div className="metric">
            <div className="m-k">Assessed</div>
            <div className="m-v" style={{ fontSize: 11 }}>
              {assessedAt ? new Date(assessedAt).toLocaleString() : '—'}
            </div>
          </div>
        </div>

        {trend && (
          <div className={`note ${trendDir || ''}`}>
            <div className="conf" style={{ marginBottom: 4 }}>
              trend · {trendDir?.replace('_', ' ') || '—'} · {trend.runs_compared}{' '}
              prior run{trend.runs_compared === 1 ? '' : 's'}
            </div>
            {trend.note}
          </div>
        )}

        {region.explanation && (
          <div>
            <div className="conf" style={{ marginBottom: 4 }}>
              Fleet assessment
            </div>
            <div className="tel" style={{ color: 'var(--ink-soft)' }}>
              {region.explanation}
            </div>
          </div>
        )}

        {region.signals_used && region.signals_used.length > 0 && (
          <div>
            <div className="conf" style={{ marginBottom: 6 }}>
              Signals cited
            </div>
            <div className="signal-tags">
              {region.signals_used.map((s) => (
                <span className="tag" key={s}>
                  {s}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
