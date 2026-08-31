const ARROW = { worsening: '↑', improving: '↓', unchanged: '→', first_observation: '·' }
const LABEL = {
  worsening: 'worsening',
  improving: 'improving',
  unchanged: 'unchanged',
  first_observation: 'first assessment',
}

export default function Trend({ trend }) {
  const dir = trend?.trend_direction
  const cls = dir || 'unchanged'
  return (
    <span className={`trend ${cls}`} title={trend?.note || ''}>
      <span className="arrow">{ARROW[dir] ?? ARROW.unchanged}</span>
      {LABEL[dir] ?? LABEL.unchanged}
    </span>
  )
}
