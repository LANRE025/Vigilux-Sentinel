export default function Severity({ level }) {
  return <span className={`sev ${level || 'none'}`}>{level || 'Unassessed'}</span>
}
