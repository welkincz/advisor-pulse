import { Delta } from '../../components/primitives'
import { KPI_LABELS, formatKpi } from '../../data'
import type { OrgWeekly } from '../../data/generated/org_weekly'
import type { KpiCode, WeeklyReport } from '../../data/generated/weekly_report'

interface Stage { label: string; count: number }
interface Step { code: KpiCode; value: number | null; usual: number | null; wow: number | null }

export interface FunnelData { stages: Stage[]; steps: Step[] }

const STEP_CODES: readonly KpiCode[] = ['CALL_TO_APPT', 'SHOW_RATE', 'APPT_CONV']

/** Calls, bookings, meetings held and conversions for one week, with the rate between each. */
export function funnelFor(org: OrgWeekly | undefined, report: readonly WeeklyReport[], week: string): FunnelData | null {
  if (!org) return null
  const rate = (code: KpiCode): Step => {
    const row = report.find((r) => r.kpi_code === code && r.iso_week_id === week)
    return { code, value: row?.value ?? null, usual: row?.trailing_13w_avg ?? null, wow: row?.wow_pct ?? null }
  }
  return {
    stages: [
      { label: 'Outbound calls', count: org.calls_out },
      { label: 'Appointments booked', count: org.appointments_booked },
      { label: 'Appointments held', count: org.appointments_held },
      { label: 'Conversions', count: org.conversions },
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
      return <li key={stage.label} className="funnel-stage">
        {step && <div className="funnel-step">
          <span className="funnel-step-rate figure-num">{formatKpi(step.code, step.value)}</span>
          <span className="funnel-step-label">{KPI_LABELS[step.code].toLowerCase()}</span>
          <Delta value={step.wow} />
          {step.usual != null && <span className="funnel-step-usual">usual {formatKpi(step.code, step.usual)}</span>}
        </div>}
        <div className="funnel-bar-row">
          <span className="funnel-label">{stage.label}</span>
          <span className="funnel-count figure-num">{stage.count.toLocaleString('en-CA')}</span>
          <span className="funnel-track" aria-hidden="true"><i style={{ inlineSize: `${Math.max(0.6, (stage.count / top) * 100)}%` }} /></span>
        </div>
      </li>
    })}
  </ol>
}
