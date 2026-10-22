import type { ReactNode } from 'react'
import type { Status } from '../../components/primitives'

const TONE: Record<Status, string> = { SUCCESS: 'good', WARN: 'warning', FAILED: 'critical', SKIPPED: 'neutral', RUNNING: 'running' }
const WORD: Record<Status, string> = { SUCCESS: 'Succeeded', WARN: 'Warning', FAILED: 'Failed', SKIPPED: 'Skipped', RUNNING: 'Running' }

/** Drawn icons, so the mark is the same weight on every platform instead of a font's ✓. */
const ICON: Record<Status, ReactNode> = {
  SUCCESS: <path d="M3.5 8.5l3 3 6-7" />,
  WARN: <><path d="M8 3.5v5.5" /><path d="M8 12.2v.3" /></>,
  FAILED: <path d="M4 4l8 8M12 4l-8 8" />,
  SKIPPED: <path d="M4 8h8" />,
  RUNNING: <circle cx="8" cy="8" r="3" />,
}

/** StatusMark's coloured mark and word, with a drawn icon. */
export function QualityMark({ status, label }: { status: Status; label?: string }) {
  return <span className={`status status-${TONE[status]} quality-mark`}>
    <svg className="status-glyph" viewBox="0 0 16 16" aria-hidden="true" focusable="false">{ICON[status]}</svg>{label ?? WORD[status]}
  </span>
}
