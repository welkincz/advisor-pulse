import { NEXT_THEME, useTheme } from '../../theme/theme'

const LABEL = { system: 'System', light: 'Light', dark: 'Dark' } as const

/** Cycles system → light → dark. The icon shows the current choice; the label says what it is. */
export function ThemeToggle() {
  const [choice, setChoice] = useTheme()
  return <button type="button" className="theme-toggle" onClick={() => setChoice(NEXT_THEME[choice])}
    aria-label={`Colour scheme: ${LABEL[choice]}. Switch to ${LABEL[NEXT_THEME[choice]]}.`} title={`Colour scheme: ${LABEL[choice]}`}>
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
      {choice === 'light' && <><circle cx="8" cy="8" r="3" /><path d="M8 1.5v1.5M8 13v1.5M1.5 8H3M13 8h1.5M3.4 3.4l1 1M11.6 11.6l1 1M3.4 12.6l1-1M11.6 4.4l1-1" /></>}
      {choice === 'dark' && <path d="M13 9.5A5.5 5.5 0 0 1 6.5 3a5.5 5.5 0 1 0 6.5 6.5z" />}
      {choice === 'system' && <><circle cx="8" cy="8" r="5.5" /><path d="M8 2.5v11A5.5 5.5 0 0 0 8 2.5z" className="theme-fill" /></>}
    </svg>
    <span>{LABEL[choice]}</span>
  </button>
}
