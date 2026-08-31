import { sortWatchLine } from '../hooks/useFleet.js'
import Severity from './Severity.jsx'
import Trend from './Trend.jsx'

function regionName(regions, a) {
  const base = regions.find((r) => r.region_id === a.region_id)
  return base?.display_name || a.country || a.region_id
}

export default function AttentionList({ assessments, regions, selectedRegionId, onSelect }) {
  // The watch line: everything that needs attention, urgent/worsening first.
  const watch = sortWatchLine(
    assessments.filter(
      (a) => a.risk_level === 'Urgent' || a.risk_level === 'Watch'
    )
  )

  if (watch.length === 0) {
    return null
  }

  return (
    <section className="section" aria-labelledby="attention-title">
      <div className="section-head">
        <span className="kicker">02 · Attention</span>
        <span className="section-title" id="attention-title">
          What needs attention
        </span>
        <span className="rule" />
      </div>
      <div className="attention">
        {watch.map((a) => (
          <article
            key={a.region_id}
            className="callout"
            data-risk={a.risk_level}
            tabIndex={0}
            role="button"
            aria-expanded={selectedRegionId === a.region_id}
            onClick={() =>
              onSelect(selectedRegionId === a.region_id ? null : a.region_id)
            }
            onKeyDown={(e) => {
              if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault()
                onSelect(selectedRegionId === a.region_id ? null : a.region_id)
              }
            }}
          >
            <div className="callout-top">
              <Severity level={a.risk_level} />
              <span className="callout-name">{regionName(regions, a)}</span>
              <span className="callout-meta">{a.region_id}</span>
              <span style={{ marginLeft: 'auto' }}>
                {a.trend ? <Trend trend={a.trend} /> : null}
              </span>
            </div>
            {a.explanation && (
              <p className="callout-explain">{a.explanation}</p>
            )}
          </article>
        ))}
      </div>
    </section>
  )
}
