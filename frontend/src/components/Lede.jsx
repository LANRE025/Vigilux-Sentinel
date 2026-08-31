export default function Lede({
  hasRun,
  urgentCount,
  watchCount,
  evaluated,
  flagged,
  live,
  isDemo,
  lastAssessed,
}) {
  // Craft the lead line from real numbers.
  let lead
  if (!hasRun) {
    lead = (
      <>
        No assessment has been run yet. Select regions and{' '}
        <span className="hl">run the fleet</span> to see what needs attention.
      </>
    )
  } else if (urgentCount > 0) {
    lead = (
      <>
        <span className="hl">{urgentCount} region{urgentCount === 1 ? '' : 's'}</span>{' '}
        need immediate attention, and{' '}
        {watchCount > 0 ? (
          <>
            another {watchCount} {watchCount === 1 ? 'is' : 'are'} on watch.
          </>
        ) : (
          <>none are on watch.</>
        )}
      </>
    )
  } else if (watchCount > 0) {
    lead = (
      <>
        No urgent regions, but <span className="hl">{watchCount}</span>{' '}
        {watchCount === 1 ? 'region is' : 'regions are'} under watch.
      </>
    )
  } else {
    lead = (
      <>
        No regions currently need attention — <span className="hl">all clear</span>.
      </>
    )
  }

  return (
    <section className="lede" aria-label="Summary">
      <p className="lead">{lead}</p>
      <div className="facts">
        <div className="fact">
          <div className="k">Regions assessed</div>
          <div className="v accent">{evaluated || '—'}</div>
          <div className="sub">{hasRun ? 'in the latest run' : 'none yet'}</div>
        </div>
        <div className="fact">
          <div className="k">Urgent</div>
          <div className="v urgent">{urgentCount || 0}</div>
          <div className="sub">need attention now</div>
        </div>
        <div className="fact">
          <div className="k">On watch</div>
          <div className="v watch">{watchCount || 0}</div>
          <div className="sub">elevated risk</div>
        </div>
        <div className="fact">
          <div className="k">Flagged</div>
          <div className="v">{flagged ?? '—'}</div>
          <div className="sub">across the fleet</div>
        </div>
        {lastAssessed && (
          <div className="fact">
            <div className="k">Last assessed</div>
            <div className="v" style={{ fontSize: '20px' }}>
              {lastAssessed}
            </div>
            <div className="sub">{isDemo ? 'demo record' : 'run record'}</div>
          </div>
        )}
      </div>
    </section>
  )
}
