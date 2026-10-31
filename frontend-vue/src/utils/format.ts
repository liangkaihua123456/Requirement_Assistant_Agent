export function formatTokens(value?: number | null): string {
  if (value == null) return '-'
  if (value >= 1_000_000) return (value / 1_000_000).toFixed(2) + 'M'
  if (value >= 1_000) return (value / 1_000).toFixed(1) + 'k'
  return String(Math.round(value))
}

export function formatSeconds(value?: number | null): string {
  if (value == null) return '-'
  return value >= 10 ? value.toFixed(0) + 's' : value.toFixed(1) + 's'
}
