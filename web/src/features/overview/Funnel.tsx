import { Delta, Explain } from '../../components/primitives'
import { KPI_LABELS, KPI_PLAIN, formatKpi, happened } from '../../data'
import type { OrgWeekly } from '../../data/generated/org_weekly'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'

interface Stage { label: string; count: number; what: string }
interface Step { code: KpiCode; value: number | null; usual: number | null; wow: number | null }

export interface FunnelData { stages: Stage[]; steps: Step[] }

const STEP_CODES: readonly KpiCode[] = ['CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV']

/** Calls, bookings, meetings held and conversions for one week, with the rate between each. */
/** `settled` is false in the first 13 weeks, when there is no full trailing average to call usual. */
export function funnelFor(org: OrgWeekly | undefined, report: readonly WeeklyReport[], week: string, settled = true): FunnelData | null {
  if (!org) return null
  const rate = (code: KpiCode): Step => {
    const row = report.find((r) => r.kpi_code === code && r.iso_week_id === week)
    return { code, value: row?.value ?? null, usual: settled ? row?.trailing_13w_avg ?? null : null, wow: row?.wow_pct ?? null }
  }
  return {
    stages: [
      { label: 'Outbound calls', count: org.calls_out, what: KPI_PLAIN.CALLS_OUT },
      { label: 'Appointments booked', count: org.appointments_booked, what: KPI_PLAIN.APPT_BOOKED },
      { label: 'Appointments held', count: org.appointments_held, what: 'Meetings scheduled in the week that took place.' },
      { label: 'Conversions', count: org.conversions, what: 'Held meetings that ended in a plan or a new product.' },
    ],
    steps: STEP_CODES.map(rate),
  }
}

/**
 * The week as a funnel: each bar is a count on one zero-based scale, and between bars sits
 * the rate that links them, against its usual 13-week level. Bars grow to the new week.
 */
export function Funnel({ data }: { data: FunnelData }) {
  const top = Math.max(1, ...data.stages.map((s) => s.count))
  return <ol className="funnel">
    {data.stages.map((stage, i) => {
      const step = i > 0 ? data.steps[i - 1] : undefined
      const before = i > 0 ? data.stages[i - 1] : undefined
      // Held and converted count meetings scheduled this week, some booked earlier: a step can outgrow the one before.
      const answer = before && stage.count > before.count
        ? { q: `Why more than ${before.label.toLowerCase()}?`, a: 'This step counts meetings scheduled in the week, including ones booked in earlier weeks, so it can be larger than the step before.' }
        : undefined
      return <li key={stage.label} className="funnel-stage">
        {step && <Explain card={() => ({ title: KPI_LABELS[step.code], value: formatKpi(step.code, step.value), what: KPI_PLAIN[step.code],
          happened: happened({ code: step.code, value: step.value, wow: step.wow, usual: step.usual, better: 'higher' }) })}>
          {(described) => <div className="funnel-step" data-step={step.code} tabIndex={0} {...described}>
            <span className="funnel-step-rate figure-num">{formatKpi(step.code, step.value)}</span>
            <span className="funnel-step-label">{KPI_LABELS[step.code].toLowerCase()}</span>
            <Delta value={step.wow} />
            {step.usual != null && <span className="funnel-step-usual">usual {formatKpi(step.code, step.usual)}</span>}
          </div>}
        </Explain>}
        <Explain block card={{ title: stage.label, value: stage.count.toLocaleString('en-CA'), what: stage.what, answer }}>
          {(described) => <div className={`funnel-bar-row${answer ? ' has-answer' : ''}`} tabIndex={0} {...described}>
            <span className="funnel-label">{stage.label}</span>
            <span className="funnel-count figure-num">{stage.count.toLocaleString('en-CA')}{answer && <span className="funnel-ask" aria-hidden="true">?</span>}</span>
            <span className="funnel-track" aria-hidden="true"><i style={{ inlineSize: `${Math.max(0.6, (stage.count / top) * 100)}%` }} /></span>
          </div>}
        </Explain>
      </li>
    })}
  </ol>
}
