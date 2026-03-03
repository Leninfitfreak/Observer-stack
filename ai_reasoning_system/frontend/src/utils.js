export function severityClasses(severity) {
  if (severity === 'critical') return 'bg-critical/15 text-critical border-critical/40'
  if (severity === 'warning') return 'bg-warning/15 text-warning border-warning/40'
  return 'bg-info/15 text-info border-info/40'
}
