// The signature element: an illuminated signal lamp whose color/glow
// conveys risk. `dim` renders an unassessed / awaiting-sweep lamp.
export default function Lamp({ risk, dim = false, className = '' }) {
  if (dim) {
    return <span className={`lamp dim ${className}`} aria-hidden="true" />
  }
  return (
    <span
      className={`lamp ${className}`}
      data-risk={risk ? risk.toLowerCase() : undefined}
      role="img"
      aria-label={`risk level ${risk || 'unassigned'}`}
    />
  )
}
