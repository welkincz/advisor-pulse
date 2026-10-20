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

Use `Chart` (ECharts with the Pulse theme) for line charts, inside a `Figure`; register any
other ECharts chart type in `primitives/echarts.ts` first.
Use `Sparkline` (plain SVG) for word-sized trends in stats. The map (#38, #169) is plain SVG
too (`features/map/CanadaMap.tsx`), filled with `var(--seq-N)` so it follows the scheme.

The map draws all of Canada in Statistics Canada's Lambert conformal conic projection
(standard parallels 49°N and 77°N), from a Natural Earth province layer
(`geo/build_provinces.py`, public domain). It has two levels:

- **Canada:** each province takes the colour of the Maplecrest region that serves it, so
  a region reads as one block; region borders are drawn in ink, province borders in paper.
  Territories have no branches and are hatched. Hollow circles show where each district's
  branches are, sized by activities completed.
- **A region:** choosing it flies the camera there (760 ms, geometric zoom). The other
  regions recede, and the district circles fill with their own value and get direct labels.
  Choosing a district opens its report.

Colours bin against every week in view, inside Tukey's fences, so a shade keeps its
meaning while the week player runs and warm-up weeks do not wash everything out.
The ranking beside the map is the keyboard path into every area; hovering a row and
hovering the map highlight each other. The FSA coverage layer appears only when the
export manifest enables FSA boundaries. Sources are credited under the map.

`WeekPlayer` (primitives) scrubs or plays through the weekly runs over a quiet trend strip.
It is a native range input, so drag, click and arrow keys all work.

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

### The overview (#171)

The overview is a weekly briefing, not a tile dashboard. In reading order:

1. **The week said in one sentence.** The page title is written from the numbers (`features/overview/headline.ts`): how activities per advisor moved, whether that is the lowest or highest for a while, then the biggest anomaly elsewhere. It is deterministic; the narrative model writes the region and district notes.
2. **One measure across every weekly run** (`TrendChart`), under a heavy ink rule. The weekly line runs through a soft ribbon: the trailing 13-week average, "usual". Anomalies get a signal ring. Click or arrow keys choose the report week; the axis fits the weeks after the 13-week warm-up.
3. **Every measure**, in three groups (reach, appointments, data quality). Each row is a toggle that plots that measure above, with a 26-week sparkline.
4. **The funnel**: calls, bookings, held and converted on one zero-based scale, with the linking rate and its usual level between bars.
5. **By region**: small multiples on a shared axis, region colour, the national line dashed beneath.
6. **Every week at a glance**: a heatmap of every region and district by week, coloured by distance from each area's own 13-week average (diverging, better follows the KPI's direction). Holidays show as vertical bands. The first 13 weeks have no usual level yet and stay neutral.
7. **Region notes** from the published narratives, labelled as written by Claude and checked against the figures.

`TrendChart` and the heatmap are hand-written SVG (`components/charts/`), so the overview no longer loads ECharts.

### Drill pages (#179)

Region, district and branch pages repeat the overview's grammar for one node: the computed
sentence, the chosen measure across every run with the **parent dashed beneath**, every
measure as toggles (batch-only rates hidden), and the children as small multiples, best
first, over the node's own dashed line. The advisor page plots one measure over 26 weeks
against the median of the branch's other advisors. The week and the measure travel with
every drill link.

## 8. Primitives

| Primitive | Use it for |
|---|---|
| `Section` | Every top-level block on a page: heading and lede in the margin column, content beside it |
| `Figure` | Every chart or map: title, reading, plot, note, table |
| `Chart` | Line and bar charts (ECharts, themed) |
| `StatGroup` / `Stat` | KPI values. One `Stat emphasis` per view, for the KPI the page leads with |
| `Delta` | Week-over-week change: arrow and sign for direction, colour and screen-reader text for better or worse. Pass `better="lower"` for no-show, late and quarantine rates, `better="neither"` for meeting minutes |
| `TrendChart` (`components/charts`) | A weekly line with a usual ribbon, anomaly rings, a week cursor, hover crosshair and keyboard week choice. `compact` for small multiples |
| `WeekPlayer` | Scrub or play through the weekly runs |
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
| `--duration-step` | 320 ms | Colour and size changes that must keep pace with the week player |
| `--ease-standard` | `cubic-bezier(0.2, 0, 0, 1)` | Things arriving or changing |
| `--ease-exit` | `cubic-bezier(0.4, 0, 1, 1)` | Things leaving |

- Week change: values tween to the new number, chart lines morph. The layout does not move.
- Drill down: the chosen node's row or region expands into the next page, so the reader
  keeps their place. Drill up reverses it.
- Pipeline replay (#42) steps through stages at 400 ms each, and can be paused.
- The week player steps a week every 360 ms only after the reader presses play, and stops at
  the latest week. Map colours and bars follow with `--duration-step`.
- The map flies to a chosen region and back out; on first paint its colours sweep west to
  east once, as the data arrives.
- Run history names each run type (weekly, manual, or backfill) beside its week and status.
- On the first report view, sections may fade in once in reading order, with opacity only.
  Never trigger an entrance on scroll or loop an animation.
- The overview's trend line draws itself once (1.1 s) when its data first arrives, then its
  anomaly rings appear. That is the page's one entrance.
- Choosing another measure morphs the line from the old values to the new (620 ms) while
  the axis labels cross-fade; the heatmap recolours left to right, 4 ms a column.
- The week cursor on every chart glides to the chosen week with `--duration-step`.
- `prefers-reduced-motion: reduce` sets every duration token to 0, and `Chart` turns off
  ECharts animation. Content must make sense with no motion at all.

## 10. Copy

- Plain, specific, sentence case. "Activities per advisor rose 14.6% week over week."
- Name things the way a branch manager would: "clients contacted", not "unique client IDs".
- Errors say what happened and what happens next: "We could not load this week's report
  just now. Last weekly run: Oct 5, 2026." No apologies, no exclamation marks.
- Always "weekly report", "last weekly run". Never "live" or "real-time".
- Every page footer states the data is synthetic and the bank is fictional.
