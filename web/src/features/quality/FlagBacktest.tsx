import { Section } from '../../components/primitives'
import { FLAG_BACKTEST } from './backtestResults'

type Row = (typeof FLAG_BACKTEST.rows)[number]

const RULE_LABEL: Record<Row['rule'], string> = {
  ANOMALY: 'Anomaly, activity measures',
  PRTF_MOVE: 'Portfolio contacted, unusual move',
}

const percent = (value: number | null, digits = 0) => (value == null ? '–' : `${(value * 100).toFixed(digits)}%`)
const weeks = (value: number | null) => (value == null ? '–' : `${value} wk`)

/** The sentence a reviewer reads: the anomaly flag at branch level on the held-out seed. */
export function backtestSentence(rows: readonly Row[] = FLAG_BACKTEST.rows): string {
  const branch = rows.find((r) => r.rule === 'ANOMALY' && r.level === 'BRANCH')
  if (!branch) return ''
  return `On a seed held out from tuning, the anomaly flag caught ${branch.detected} of ${branch.stories} branches whose activity the generator changed, a median ${branch.medianLagWeeks} weeks after the change began, with ${branch.falsePer100} false alarms per 100 branch-weeks (before tuning it caught ${branch.detectedBefore} but raised ${branch.falsePer100Before}).`
}

export function FlagBacktest() {
  return <Section id="quality-flags" title="How well the flags work" lede={backtestSentence()}>
    <p className="quality-muted">Precision counts direct story matches among all flags; recall counts the larger injected stories. These synthetic histories do not establish accuracy at a real bank. Ordinary activity anomalies remain noisy.</p>
    <div className="quality-scroll" tabIndex={0} role="region" aria-label="Flag backtest results, scrollable">
      <table className="quality-table flag-backtest">
        <caption className="flag-backtest-caption">Benchmark histories: 2024-W41 to 2026-W42. Scored against the generator&rsquo;s ground truth. Thresholds tuned on seed {FLAG_BACKTEST.tunedSeed}, confirmed on seed {FLAG_BACKTEST.heldOutSeed}.</caption>
        <thead><tr>
          <th scope="col">Flag</th><th scope="col">Level</th>
          <th scope="col" className="num">Stories caught</th>
          <th scope="col" className="num">Median lag</th>
          <th scope="col" className="num">Precision</th>
          <th scope="col" className="num">False alarms per 100 node-weeks</th>
        </tr></thead>
        <tbody>{FLAG_BACKTEST.rows.map((r) => <tr key={`${r.rule}-${r.level}`}>
          <th scope="row">{RULE_LABEL[r.rule]}</th>
          <td>{r.level.toLowerCase()}</td>
          <td className="num">{r.detected} of {r.stories} ({percent(r.recall)}) <span className="quality-muted">(was {r.detectedBefore})</span></td>
          <td className="num">{weeks(r.medianLagWeeks)}</td>
          <td className="num">{percent(r.precision, 1)}</td>
          <td className="num">{r.falsePer100} <span className="quality-muted">(was {r.falsePer100Before})</span></td>
        </tr>)}</tbody>
      </table>
    </div>
  </Section>
}
