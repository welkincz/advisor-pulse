import { useCallback, useEffect, useMemo, useState } from 'react'
import { type NodeState, type ReplayEvent, stateAt } from './timeline'

/**
 * Plays `events` once: state changes only at event times (a few dozen per run), so React
 * renders that often while the particles move in SVG. Reduced motion shows the end state.
 */
export function useReplay(events: readonly ReplayEvent[], reducedMotion: boolean) {
  const final = useMemo(() => stateAt(events, Infinity), [events])
  const [run, setRun] = useState(0)
  const [state, setState] = useState<Map<string, NodeState>>(final)
  const [replaying, setReplaying] = useState(false)

  useEffect(() => {
    if (reducedMotion || events.length === 0) {
      setState(final)
      setReplaying(false)
      return
    }
    setState(new Map())
    setReplaying(true)
    const times = [...new Set(events.map((e) => e.at))]
    const timers = times.map((at) => window.setTimeout(() => setState(stateAt(events, at)), at))
    const last = times.at(-1) ?? 0
    timers.push(window.setTimeout(() => setReplaying(false), last + 400))
    return () => timers.forEach((t) => window.clearTimeout(t))
  }, [events, final, reducedMotion, run])

  const restart = useCallback(() => setRun((n) => n + 1), [])
  return { state, replaying, restart }
}
