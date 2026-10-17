# Advisor Pulse design system

Advisor Pulse should read like a well-made annual report from a careful bank: paper, ink,
and one colour that means "look here". It extends charliebuild's language: paper, ink,
signal gold, Avenir Next. It is not a SaaS dashboard. Every rule below exists so that an
agent who is not a designer can build a new view that still looks like it belongs.

Everything here is implemented in `web/src/theme/` (tokens, ECharts theme) and
`web/src/components/primitives/` (Section, Figure, Stat, Delta, Sparkline, Breadcrumb,
Chart, StatusMark). Run `make web-dev` and open `/_kitchen-sink` to see all of it in your
current colour scheme.

## 1. Principles

1. **The number is the hero, and the sentence explains it.** Lead with the value. Then
   say how it moved and why it matters, in plain words. A chart is the evidence, not the headline.
2. **Paper and ink do the work.** Colour is scarce. Signal gold marks one thing per view:
   the stat the page leads with, the selected node, the latest point.
3. **Structure is information.** Rules, margins and type size show hierarchy. No
   decoration that does not encode something.
4. **Calm under failure.** A missing week or a failed fetch gets a plain sentence and
   the last run time, never a blank page or an alarming red banner.
5. **Weekly, not live.** Nothing pulses, ticks, or claims to be real-time. Copy says
   "weekly report" and "last weekly run".

## 2. Banned looks

If a design matches any of these, it is wrong:

- Neon or saturated gradients, gradient text, glowing accents.
- Glassmorphism: blurred translucent cards, frosted panels.
- The generic hero dashboard: a dark hero with a giant number, four identical rounded
  KPI cards with drop shadows, and a donut chart.
- Cards as the default container. Content sits on the paper, separated by hairline rules
  and space. No box shadows anywhere.
- Pie and donut charts, 3D charts, dual-axis charts, rainbow colour scales.
- Tracked-out ALL-CAPS labels. Labels are sentence case.
- Pulsing dots, tickers, or "live" badges.
- Raw hex colours outside `web/src/theme/tokens.css` (CI rejects them).

## 3. Type

One family: **Avenir Next** (falls back to Avenir, Segoe UI, then the system sans).
Weight and size carry the hierarchy. There is no second display face.

The scale is the classic one from *The Elements of Typographic Style*:

| Token | Size | Use |
|---|---|---|
| `--text-display` | 48 to 72 (fluid) | Page title (`h1`), one per page |
| `--text-3xl` | 48 | The leading stat (`Stat emphasis`) |
| `--text-2xl` | 36 | Other stat values |
| `--text-xl` | 24 | Section headings (`h2`) |
| `--text-lg` | 21 | Intro and lead paragraphs |
| `--text-md` | 16 | Body, figure titles (`h3`, weight 600) |
| `--text-sm` | 14 | Labels, deltas, breadcrumb, legends |
| `--text-xs` | 12 | Source notes, axis labels |

Rules:

- **Figures:** numbers use tabular lining figures (`.figure-num`, `td.num`) so they line up
  and do not jitter when a value tweens. This is what "mono figures" means here: monospaced
  digits in Avenir Next, not a monospace typeface.
- Body text stays under `--measure` (38rem, about 70 characters).
- Weights: 400 body, 500 stat values, 600 headings. Never 700+ except the status glyph.
- Sentence case everywhere, including buttons and table headers.
- Write numbers the same way everywhere: one decimal for rates as percentages (`84.4%`),
  thousands separators (`1,284`), a real minus sign (`−7.1%`), week IDs as `2026-W40`.

## 4. Layout and space

- Page: max width `--page-max` (72rem), side gutter `--gutter` (16 px on a phone, up to 40 px).
- **Margin column.** A `Section` puts its heading and a one-line lede in a left margin
  column (3 of 12 columns) on screens 64rem and wider, with the content in the other 9.
  The heading stays put while you scroll. Below 64rem it stacks. This is the report's
  signature layout; use `Section` for every top-level block.
- Sections are separated by a hairline (`--rule`) and `--space-12`.
- Spacing uses the token steps only (`--space-1` to `--space-16`, a 4 px base). Gaps
  inside a component use 4 to 16 px, gaps between components use 24 to 48 px.
- Left-align everything. Numbers right-align in tables.
- Check every view at 375 px wide: no horizontal scroll, and every control reachable by keyboard.

## 5. Colour roles

| Token | Role |
|---|---|
| `--paper` | Page background. The only surface. |
| `--ink` | Text, values, primary marks |
| `--muted` | Secondary text, labels, axis text (5.7:1 on paper) |
| `--faint` | Tertiary text, separators drawn as text |
| `--rule` | Hairlines, gridlines, axis lines |
| `--signal` | The one accent: leading stat rule, current selection, latest point, the kicker above `h1` |
| `--focus` | Keyboard focus ring only |
| `--field` | Subtle fills (input backgrounds, swatch borders) |

Dark mode is chosen, not inverted: every token has its own dark value in `tokens.css`,
and the data palettes were re-stepped for the dark surface and validated there.

## 6. Data palettes

All palettes were generated in OKLCH and checked with the dataviz palette validator
against `--paper` in each mode: lightness band, chroma floor, colour-vision-deficiency
separation (Machado 2009, protanopia and deuteranopia), normal-vision separation, and
contrast. Use the tokens, never new colours.

**Pick the palette by the job the colour does:**

| Job | Tokens | Rule |
|---|---|---|
| Identity (which region) | `--series-1` … `--series-4` | Fixed order, never cycled. Regions are ON, QC, WE, AT in that order. All four pass the validator with every pair compared, so any chart form (lines, bars, dots, small multiples) may use all four. A fifth series folds into "Other" or becomes small multiples. |
| Magnitude (how much) | `--seq-1` … `--seq-7` | One hue, signal gold, light to dark. Used for the choropleth. In dark mode the anchor flips: low values are dark and recede into the surface. For discrete ordered marks (tiers, bands) start at `--seq-3`. |
| Change (better or worse than last week) | `--worse-3` … `--diverging-mid` … `--better-3` | Blue is better, vermilion is worse, grey is no change. Judge "better" with the KPI's direction: a falling no-show rate is better. Never encode up or down with this; the arrow and sign do that. |
| Pipeline state | `--status-good`, `--status-warning`, `--status-critical`, `--status-neutral`, `--status-running` | Reserved for run and check status. Always a glyph plus a word (`StatusMark`). Never used for a data series. |

Rules:

- Colour follows the entity, never its rank. Ontario is `--series-1` on every chart, even
  when it is filtered to be the only line.
- Text wears text tokens. Values, labels and legends are `--ink` or `--muted`; the
  coloured mark beside them carries identity.
- Never put categorical and diverging colours in one chart (vermilion appears in both).
- When one series matters (the selected node), draw it in its colour and the rest in `--rule`.

## 7. Charts

Use `Chart` (ECharts with the Pulse theme) for line and bar charts, inside a `Figure`.
Use `Sparkline` (plain SVG) for word-sized trends in stats. Use deck.gl for the map (#38),
with the sequential tokens read through `token()`.

The map colours the shipped region or district polygons for the selected week and KPI.
Those polygons cover only FSAs with fictional branch locations, so unmapped land stays
blank; the adjacent list gives the same values and a keyboard path into each report.
The FSA coverage layer appears only when the export manifest enables FSA boundaries.
There are no basemap tiles; the Statistics Canada source is credited under the figure.

The theme (`web/src/theme/echarts.ts`) is built from `tokens.css` when a chart mounts, and
rebuilt when the colour scheme changes. It sets:

- Lines 2 px, no smoothing, markers (8 px) only on hover; no area gradients.
- Bars at most 24 px wide, 4 px rounded top, square at the baseline.
- Hairline horizontal gridlines in `--rule`, no tick marks, axis labels in `--muted` at 12 px.
- A tooltip on paper with a hairline border, no shadow, tabular figures.
- Categorical colours in token order.
- No animation under `prefers-reduced-motion`.

Rules for agents:

- **Always a `Figure`:** title (what it shows), an optional one-line reading (what it
  says), a source note with the week range, and `table` with the same numbers. The table
  is the accessible view and the fallback when colour fails.
- Every `Chart` needs a `label` describing the chart for screen readers.
- One y-axis per chart. Two measures with different units are two charts.
- Two or more series need a legend; with four or fewer, also label line ends directly
  (`endLabel`, and give the grid `right: 72` so labels are not clipped at 375 px).
- Start bar charts at zero. Line charts may start near the data range.
- Do not label every point. Label the latest value or the one the reading talks about.
- Rates are shown as percentages with one decimal; counts as integers.

## 8. Primitives

| Primitive | Use it for |
|---|---|
| `Section` | Every top-level block on a page: heading and lede in the margin column, content beside it |
| `Figure` | Every chart or map: title, reading, plot, note, table |
| `Chart` | Line and bar charts (ECharts, themed) |
| `StatGroup` / `Stat` | KPI values. One `Stat emphasis` per view, for the KPI the page leads with |
| `Delta` | Week-over-week change: arrow and sign for direction, colour and screen-reader text for better or worse. Pass `better="lower"` for no-show, late and quarantine rates, `better="neither"` for meeting minutes |
| `Sparkline` | A trend inside a `Stat`; give it a `label` that states the range, e.g. "last 8 weeks: from 10.6 to 11.5" |
| `Breadcrumb` | The drill path National → Region → District → Branch → Advisor. The last crumb is the current page |
| `StatusMark` | Run, stage and check status on the Pipeline and Data quality pages |
| `DataNotice` (`web/src/data`) | Any section whose data failed to load |

## 9. Motion

Motion answers a change of data or place. It is never decoration, and nothing moves on its own.

| Token | Value | Use |
|---|---|---|
| `--duration-quick` | 120 ms | Hover, press, focus, toggles |
| `--duration-standard` | 240 ms | Drill transitions, panels opening |
| `--duration-tween` | 600 ms | Number and chart tweens on week change |
| `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Things arriving or changing |
| `--ease-exit` | `cubic-bezier(0.4, 0, 1, 1)` | Things leaving |

- Week change: values tween to the new number, chart lines morph. The layout does not move.
- Drill down: the chosen node's row or region expands into the next page, so the reader
  keeps their place. Drill up reverses it.
- Pipeline replay (#42) steps through stages at 400 ms each, and can be paused.
- No entrance animations on scroll, no staggered fade-ins, no looping motion.
- `prefers-reduced-motion: reduce` sets every duration token to 0, and `Chart` turns off
  ECharts animation. Content must make sense with no motion at all.

## 10. Copy

- Plain, specific, sentence case. "Activities per advisor rose 14.6% week over week."
- Name things the way a branch manager would: "clients contacted", not "unique client IDs".
- Errors say what happened and what happens next: "We could not load this week's report
  just now. Last weekly run: Oct 5, 2026." No apologies, no exclamation marks.
- Always "weekly report", "last weekly run". Never "live" or "real-time".
- Every page footer states the data is synthetic and the bank is fictional.
