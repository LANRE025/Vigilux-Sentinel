// Bottom telemetry rail: last run outcome + per-agent timing.
export default function StatusRail({ timings, runId }) {
  const segs = timings?.length
    ? timings.map((t) => ({
        k: t.agent.replace('_', ' '),
        v: `${(t.duration_ms / 1000).toFixed(2)}s`,
        extra: `${t.regions_processed ?? 0} regions`,
        ok: !t.error,
      }))
    : []

  return (
    <footer className="statusrail" role="region" aria-label="run telemetry">
      <div className="rail-seg">
        <span className="r-k">last run</span>
        <span className="r-v">{runId ? runId.slice(0, 8) : 'none yet'}</span>
      </div>
      {segs.map((s) => (
        <div className="rail-seg" key={s.k}>
          <span className="r-k">{s.k}</span>
          <span className={`r-v ${s.ok ? 'ok' : 'err'}`}>
            {s.v} <span style={{ color: 'var(--muted)' }}>· {s.extra}</span>
          </span>
        </div>
      ))}
    </footer>
  )
}
