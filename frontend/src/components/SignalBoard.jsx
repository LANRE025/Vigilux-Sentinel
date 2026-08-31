import RegionRow from './RegionRow.jsx'

const RISK_WEIGHT = { Urgent: 0, Watch: 1, Stable: 2 }

// Merge region telemetry with its assessment, then order into a "watch line":
// at-risk regions first (Urgent → Watch → Stable), worsening ahead of improving,
// then unassessed targets.
function buildRows(regions, assessments) {
  const byId = new Map(assessments.map((a) => [a.region_id, a]))
  const rows = regions.map((r) => ({ ...r, ...(byId.get(r.region_id) || {}) }))
  return rows.sort((a, b) => {
    const ra = RISK_WEIGHT[a.risk_level] ?? 3
    const rb = RISK_WEIGHT[b.risk_level] ?? 3
    if (ra !== rb) return ra - rb
    const ta = a.trend?.trend_direction === 'worsening' ? 0 : 1
    const tb = b.trend?.trend_direction === 'worsening' ? 0 : 1
    if (ta !== tb) return ta - tb
    return (a.display_name || a.region_id).localeCompare(b.display_name || b.region_id)
  })
}

const COLS = ['TARGET', 'LAT', 'LON', 'AGE', 'TREND', 'CONF', 'RUN']

export default function SignalBoard({
  regions,
  assessments,
  selectedRegionId,
  setSelectedRegionId,
  selectedIds,
  toggleRegion,
}) {
  const rows = buildRows(regions, assessments)

  return (
    <div className="board" role="region" aria-label="regional signal board">
      {rows.length === 0 ? (
        <div className="empty">
          <div className="big">No regions on the board</div>
          <div>Connect the backend or run in demo mode (VITE_DEMO=true).</div>
        </div>
      ) : (
        <div className="board-grid board-header">
          {COLS.map((c) => (
            <span key={c} className={`col-${c.toLowerCase()}`}>
              {c}
            </span>
          ))}
        </div>
      )}

      {rows.map((row) => (
        <RegionRow
          key={row.region_id}
          row={row}
          selected={selectedRegionId === row.region_id}
          onSelect={() =>
            setSelectedRegionId(
              selectedRegionId === row.region_id ? null : row.region_id
            )
          }
          checked={selectedIds.has(row.region_id)}
          onToggle={() => toggleRegion(row.region_id)}
        />
      ))}
    </div>
  )
}
