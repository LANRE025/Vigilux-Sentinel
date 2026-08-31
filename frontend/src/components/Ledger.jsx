import Severity from './Severity.jsx'
import Trend from './Trend.jsx'

const WEIGHT = { Urgent: 0, Watch: 1, Stable: 2 }

export default function Ledger({
  regions,
  assessments,
  selectedIds,
  toggleRegion,
  selectedRegionId,
  setSelectedRegionId,
}) {
  // One row per known region, merged with its latest assessment (if any).
  const rows = regions
    .map((r) => {
      const a = assessments.find((x) => x.region_id === r.region_id)
      return {
        region_id: r.region_id,
        display_name: r.display_name || r.country || r.region_id,
        days_since_survey: a?.days_since_survey ?? r.days_since_survey ?? null,
        confidence: a?.confidence ?? null,
        trend: a?.trend ?? null,
        risk: a?.risk_level ?? null,
        explanation: a?.explanation ?? null,
        signals_used: a?.signals_used ?? null,
        assessed_at: a?.assessed_at ?? null,
      }
    })
    .sort((a, b) => {
      const ra = WEIGHT[a.risk] ?? 3
      const rb = WEIGHT[b.risk] ?? 3
      if (ra !== rb) return ra - rb
      const ta = a.trend?.trend_direction === 'worsening' ? 0 : 1
      const tb = b.trend?.trend_direction === 'worsening' ? 0 : 1
      if (ta !== tb) return ta - tb
      return a.display_name.localeCompare(b.display_name)
    })

  const open = rows.find((r) => r.region_id === selectedRegionId)

  return (
    <section className="section" aria-labelledby="ledger-title">
      <div className="section-head">
        <span className="kicker">03 · Ledger</span>
        <span className="section-title" id="ledger-title">
          Region risk &amp; change
        </span>
        <span className="rule" />
      </div>

      <div className="ledger">
        <div className="ledger-row ledger-head">
          <span>Region</span>
          <span>Status</span>
          <span>Trend</span>
          <span className="hide-sm">Days since survey</span>
          <span className="hide-sm">Confidence</span>
          <span />
        </div>

        {rows.map((r) => {
          const isOpen = open?.region_id === r.region_id
          const checked = selectedIds.has(r.region_id)
          return (
            <div key={r.region_id}>
              <div
                className="ledger-row"
                role="button"
                tabIndex={0}
                aria-expanded={isOpen}
                onClick={() =>
                  setSelectedRegionId(isOpen ? null : r.region_id)
                }
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setSelectedRegionId(isOpen ? null : r.region_id)
                  }
                }}
              >
                <span
                  className="lg-name"
                  onClick={(e) => {
                    // Select toggle must not also expand the row.
                    e.stopPropagation()
                    toggleRegion(r.region_id)
                  }}
                  onKeyDown={(e) => {
                    if (e.key === ' ' || e.key === 'Enter') {
                      e.preventDefault()
                      e.stopPropagation()
                      toggleRegion(r.region_id)
                    }
                  }}
                  role="checkbox"
                  aria-checked={checked}
                  tabIndex={0}
                >
                  <span
                    style={{
                      display: 'inline-flex',
                      width: 14,
                      height: 14,
                      marginRight: 10,
                      border: '1.5px solid var(--line-strong)',
                      borderRadius: 2,
                      verticalAlign: '-2px',
                      background: checked ? 'var(--accent)' : 'transparent',
                    }}
                  />
                  {r.display_name}
                  <div className="lg-id">{r.region_id}</div>
                </span>
                <span className="cell">
                  <Severity level={r.risk} />
                </span>
                <span className="cell">
                  {r.trend ? <Trend trend={r.trend} /> : '—'}
                </span>
                <span className="cell num hide-sm">
                  {r.days_since_survey ?? '—'}
                </span>
                <span className="cell hide-sm">{r.confidence ?? '—'}</span>
                <span className="chev">{isOpen ? '−' : '+'}</span>
              </div>

              {isOpen && r.risk && (
                <div className="ledger-expanded">
                  {r.trend?.note && (
                    <p className={`exp-note ${r.trend.trend_direction || ''}`}>
                      {r.trend.note}
                    </p>
                  )}
                  {r.explanation && (
                    <p className="exp-explain">{r.explanation}</p>
                  )}
                  <div className="exp-facts">
                    <div className="fact">
                      <div className="k">Confidence</div>
                      <div className="v" style={{ fontSize: '20px' }}>
                        {r.confidence ?? '—'}
                      </div>
                    </div>
                    <div className="fact">
                      <div className="k">Days since survey</div>
                      <div className="v" style={{ fontSize: '20px' }}>
                        {r.days_since_survey ?? '—'}
                      </div>
                    </div>
                  </div>
                  {r.signals_used?.length ? (
                    <div className="signal-tags">
                      {r.signals_used.map((s) => (
                        <span key={s} className="tag">
                          {s.replace(/_/g, ' ')}
                        </span>
                      ))}
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
