import Lamp from './Lamp.jsx'
import { formatCoord } from '../data/mock.js'

const TREND_ARROW = {
  worsening: '▲',
  improving: '▼',
  unchanged: '–',
  first_observation: '·',
}

const CONF_CLASS = {
  High: 'high',
  Medium: 'medium',
  Low: 'low',
}

// One target row on the signal board: lamp + target + telemetry columns.
// Clicking selects it for the detail panel; the checkbox toggles the run set.
export default function RegionRow({ row, onSelect, selected, checked, onToggle }) {
  const trend = row.trend
  const trendDir = trend?.trend_direction

  return (
    <div
      className={`region-row board-grid ${selected ? 'selected' : ''}`}
      role="button"
      tabIndex={0}
      aria-pressed={selected}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
    >
      <div className="row-target">
        <Lamp risk={row.risk_level} dim={!row.risk_level} />
        <div style={{ minWidth: 0 }}>
          <div className="row-name">{row.display_name || row.country}</div>
          <div className="row-country">{row.region_id}</div>
        </div>
      </div>

      <span className="tel muted" title="latitude">
        {row.lat == null ? '—' : formatCoord(row.lat, true)}
      </span>
      <span className="tel muted" title="longitude">
        {row.lon == null ? '—' : formatCoord(row.lon, false)}
      </span>

      <span className="tel" title="days since survey">
        {row.days_since_survey == null ? '—' : `${row.days_since_survey}d`}
      </span>

      <span className={`trend ${trendDir || ''}`}>
        <span className="arrow">{TREND_ARROW[trendDir] || '·'}</span>
        <span>{trendDir ? trendDir.replace('_', ' ') : 'new'}</span>
      </span>

      <span className={`conf ${CONF_CLASS[row.confidence] || ''}`}>
        {row.confidence || '—'}
      </span>

      <label
        className="row-check"
        style={{ justifySelf: 'end', cursor: 'pointer' }}
        onClick={(e) => e.stopPropagation()}
        title="include in next run"
      >
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`include ${row.display_name || row.region_id} in run`}
          style={{ accentColor: 'var(--phosphor)', width: 15, height: 15 }}
        />
      </label>
    </div>
  )
}
