/**
 * A word-sized trend in plain SVG (no chart engine, so a page of tiles stays light).
 * Ink line, the latest point marked in signal; null weeks leave a gap.
 */
export function Sparkline({ values, label, width = 96, height = 24 }: { values: readonly (number | null)[]; label: string; width?: number; height?: number }) {
  const known = values.filter((v): v is number => v !== null)
  if (known.length < 2) return null
  const min = Math.min(...known)
  const span = Math.max(...known) - min || 1
  const x = (i: number) => (values.length === 1 ? width / 2 : (i / (values.length - 1)) * (width - 4) + 2)
  const y = (v: number) => height - 3 - ((v - min) / span) * (height - 6)
  let path = ''
  values.forEach((v, i) => {
    if (v === null) return
    path += `${i > 0 && values[i - 1] !== null ? 'L' : 'M'}${x(i).toFixed(1)},${y(v).toFixed(1)}`
  })
  let lastIndex = values.length - 1
  while (values[lastIndex] === null) lastIndex--
  const last = values[lastIndex] as number
  return <svg className="sparkline" role="img" aria-label={label} width={width} height={height} viewBox={`0 0 ${width} ${height}`}>
    <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    <circle cx={x(lastIndex)} cy={y(last)} r="2.5" className="sparkline-last" />
  </svg>
}
