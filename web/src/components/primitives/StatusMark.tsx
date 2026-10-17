export type Status = 'SUCCESS' | 'WARN' | 'FAILED' | 'SKIPPED' | 'RUNNING'

const MARK: Record<Status, { glyph: string; word: string; tone: string }> = {
  SUCCESS: { glyph: '✓', word: 'Succeeded', tone: 'good' },
  WARN: { glyph: '!', word: 'Warning', tone: 'warning' },
  FAILED: { glyph: '✕', word: 'Failed', tone: 'critical' },
  SKIPPED: { glyph: '–', word: 'Skipped', tone: 'neutral' },
  RUNNING: { glyph: '●', word: 'Running', tone: 'running' },
}

/** Pipeline state: a coloured glyph and a word, never colour alone. */
export function StatusMark({ status, label }: { status: Status; label?: string }) {
  const mark = MARK[status]
  return <span className={`status status-${mark.tone}`}>
    <span className="status-glyph" aria-hidden="true">{mark.glyph}</span>{label ?? mark.word}
  </span>
}
