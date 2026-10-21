/**
 * The site's light palette (web/src/theme/tokens.css), copied because the video bundle cannot
 * read CSS variables. tests/export/test_recap.py fails if the two drift apart.
 */
export const COLORS = {
  paper: '#F6F7F5',
  ink: '#1B222B',
  muted: '#586371',
  rule: '#D9DDD8',
  signal: '#8A6A1C',
  'better-1': '#85B9D8',
  'better-2': '#548AAF',
  'better-3': '#2A5C84',
  'worse-1': '#DDA187',
  'worse-2': '#B66D56',
  'worse-3': '#893F30',
  'diverging-mid': '#E4E3DF',
} as const

export const FPS = 30
export const WIDTH = 1280
export const HEIGHT = 720
